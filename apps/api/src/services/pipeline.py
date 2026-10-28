"""Analysis pipeline: parse → EXPLAIN → DAG → candidates → hypopg validation."""

import logging
from dataclasses import dataclass

import asyncpg

from src.core.config import Settings
from src.core.errors import ApiError, not_found, unprocessable
from src.db.metadata import ConnectionStore
from src.db.shadow import ShadowUnavailable, connect_shadow, validate_index
from src.db.target import connect_target
from src.schemas.analysis import (
    AnalysisResult,
    IndexRecommendation,
    QueryAnalysisRequest,
)
from src.services.dag import build_dag
from src.services.explain import explain_analyze
from src.services.introspection import fetch_schema
from src.services.recommender import recommend_indexes
from src.services.runs import RecommendationState, RunRegistry
from src.services.sql_guard import SqlValidationError, validate_sql

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineDeps:
    settings: Settings
    store: ConnectionStore
    runs: RunRegistry


def _metrics(cost: float, time_ms: float) -> dict[str, float]:
    return {"cost": round(cost, 2), "time_ms": round(time_ms, 3)}


async def _refresh_stats(conn: asyncpg.Connection, settings: Settings) -> None:
    """Best-effort VACUUM ANALYZE.

    The target role is SELECT-only by design, so this only runs when the
    operator explicitly grants maintenance rights. The shadow DB is analyzed at
    init time instead.
    """
    if not settings.target_allow_maintenance:
        logger.info("Skipping VACUUM ANALYZE on the read-only target database")
        return
    try:
        await conn.execute("VACUUM ANALYZE")
    except asyncpg.PostgresError as exc:
        logger.warning("VACUUM ANALYZE failed: %s", exc.__class__.__name__)


async def execute(run_id: str, request: QueryAnalysisRequest, deps: PipelineDeps) -> None:
    try:
        await _execute(run_id, request, deps)
    except SqlValidationError as exc:
        await deps.runs.fail(run_id, str(exc))
    except ApiError as exc:
        await deps.runs.fail(run_id, exc.message)
    except Exception:  # pragma: no cover - defensive boundary
        logger.exception("Analysis run %s failed unexpectedly", run_id)
        await deps.runs.fail(
            run_id, "Analysis failed. Check the API logs for the error class."
        )


async def _execute(
    run_id: str, request: QueryAnalysisRequest, deps: PipelineDeps
) -> None:
    settings = deps.settings
    runs = deps.runs

    await runs.update(run_id, "parsing", 5, "Validating SQL with sqlglot…")
    validated = validate_sql(request.sql_query, settings.max_sql_length)

    stored = await deps.store.get(request.connection_id)
    if stored is None:
        raise not_found("CONNECTION_NOT_FOUND", "Unknown connection_id.")

    await runs.update(run_id, "parsing", 15, "Connecting to the target database…")
    conn = await connect_target(stored, settings)
    try:
        await _refresh_stats(conn, settings)
        await runs.update(
            run_id, "parsing", 30, "Capturing the baseline EXPLAIN (ANALYZE) plan…"
        )
        try:
            baseline = await explain_analyze(
                conn, validated.sql, settings.explain_timeout_ms
            )
            schema = await fetch_schema(conn)
        except asyncpg.PostgresError as exc:
            logger.warning("Target EXPLAIN failed: %s", exc.__class__.__name__)
            raise unprocessable(
                "QUERY_EXECUTION_FAILED",
                "The target database rejected the query plan.",
                "Check table names, column names, and SELECT privileges.",
            ) from exc
    finally:
        await conn.close()

    await runs.update(
        run_id,
        "gnn_inference",
        55,
        "Scoring plan structure (heuristic placeholder; GATv2 arrives in Phase 3)…",
    )
    original_dag = build_dag(baseline.plan)
    original_metrics = _metrics(baseline.total_cost, baseline.execution_time_ms)

    candidates = recommend_indexes(validated, schema, request.optimization_goal)

    optimized_nodes = original_dag.nodes
    optimized_metrics = original_metrics
    validated_recommendations = candidates

    if candidates and settings.shadow_dsn and settings.shadow_validate:
        await runs.update(
            run_id,
            "hypopg_validation",
            75,
            "Injecting hypothetical indexes into the shadow database…",
        )
        validated_recommendations, optimized_nodes, optimized_metrics = (
            await _validate_candidates(
                validated.sql,
                candidates,
                settings,
                original_dag.nodes,
                original_metrics,
            )
        )
    elif candidates:
        logger.info("Shadow validation disabled; returning heuristic candidates")

    result = AnalysisResult(
        run_id=run_id,
        status="completed",
        original_metrics=original_metrics,
        optimized_metrics=optimized_metrics,
        original_dag=original_dag.nodes,
        optimized_dag=optimized_nodes,
        edges=original_dag.edges,
        recommendations=validated_recommendations,
    )
    states = [
        RecommendationState(
            recommendation=recommendation,
            connection_id=request.connection_id,
            sql_query=validated.sql,
        )
        for recommendation in validated_recommendations
    ]
    await runs.complete(run_id, result, states)


async def _validate_candidates(
    sql_query: str,
    candidates: list[IndexRecommendation],
    settings: Settings,
    fallback_nodes: list,
    fallback_metrics: dict[str, float],
) -> tuple[list[IndexRecommendation], list, dict[str, float]]:
    try:
        conn = await connect_shadow(settings)
    except ShadowUnavailable as exc:
        logger.warning("Shadow validation skipped: %s", exc)
        return candidates, fallback_nodes, fallback_metrics

    validated: list[IndexRecommendation] = []
    best_plan = None
    best_time: float | None = None
    best_cost = 0.0

    try:
        for candidate in candidates:
            try:
                outcome = await validate_index(
                    conn, sql_query, candidate.sql_statement, settings.explain_timeout_ms
                )
            except (asyncpg.PostgresError, ValueError) as exc:
                logger.warning(
                    "hypopg validation failed for %s: %s",
                    candidate.target_table,
                    exc.__class__.__name__,
                )
                continue

            speedup = (
                outcome.baseline_execution_time_ms / outcome.execution_time_ms
                if outcome.execution_time_ms > 0
                else 1.0
            )
            validated.append(
                candidate.model_copy(
                    update={"validated_speedup_factor": round(speedup, 2)}
                )
            )
            if best_time is None or outcome.execution_time_ms < best_time:
                best_time = outcome.execution_time_ms
                best_cost = outcome.total_cost
                best_plan = outcome.plan
    finally:
        await conn.close()

    if not validated:
        return candidates, fallback_nodes, fallback_metrics

    if best_plan is None:
        return validated, fallback_nodes, fallback_metrics

    optimized = build_dag(best_plan)
    return validated, optimized.nodes, _metrics(best_cost, best_time or 0.0)
