"""Analysis pipeline: parse → EXPLAIN → DAG → engine beam search → hypopg.

Phase 4 replaces the Phase 2 heuristic scorer with the neuro-symbolic engine.
The engine runs in a worker thread (``asyncio.to_thread``) so the event loop is
never blocked by PyTorch, and every engine fault degrades to the heuristic path
instead of failing the run.
"""

import asyncio
import logging
from dataclasses import dataclass, field

import asyncpg

from src.core.config import Settings
from src.core.errors import ApiError, not_found, unprocessable
from src.db.metadata import ConnectionStore
from src.db.shadow import ShadowUnavailable, connect_shadow, validate_index
from src.db.target import connect_target
from src.schemas.analysis import (
    AnalysisResult,
    AttentionHotspot,
    DAGEdge,
    DAGNode,
    IndexRecommendation,
    QueryAnalysisRequest,
    RejectedCandidate,
)
from src.services import ml
from src.services.dag import Dag, build_dag
from src.services.engine import EngineBundle
from src.services.explain import explain_steady_state
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
    engine: EngineBundle


@dataclass
class Stage:
    """Everything the engine (or its fallback) contributes to a run."""

    recommendations: list[IndexRecommendation] = field(default_factory=list)
    original_nodes: list[DAGNode] = field(default_factory=list)
    optimized_nodes: list[DAGNode] = field(default_factory=list)
    edges: list[DAGEdge] = field(default_factory=list)
    optimized_metrics: dict[str, float] = field(default_factory=dict)
    engine: str = "heuristic"
    attention: list[AttentionHotspot] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    rejected: list[RejectedCandidate] = field(default_factory=list)
    speedup: float = 1.0
    symbolic_count: int = 0


def _metrics(cost: float, time_ms: float) -> dict[str, float]:
    return {"cost": round(cost, 2), "time_ms": round(time_ms, 3)}


async def _refresh_stats(conn: asyncpg.Connection, settings: Settings) -> None:
    """Best-effort VACUUM ANALYZE before the baseline is measured.

    Patch 2 enables the attempt by default: stale planner statistics are the
    most common reason a correct query gets a bad plan, and the median-of-5
    baseline would faithfully measure that bad plan. ``VACUUM`` requires table
    ownership, and the target role is normally SELECT-only, so a refusal is
    logged and the run continues — the optimizer never depends on rights it is
    not supposed to have.
    """
    if not settings.target_allow_maintenance:
        logger.info("Skipping VACUUM ANALYZE on the read-only target database")
        return
    try:
        await conn.execute("VACUUM ANALYZE")
        logger.info("VACUUM ANALYZE refreshed target statistics")
    except (asyncpg.PostgresError, asyncio.TimeoutError, OSError) as exc:
        logger.info(
            "VACUUM ANALYZE not applied (%s); the target role needs table ownership",
            exc.__class__.__name__,
        )


def _heuristic_stage(
    validated,
    schema,
    request: QueryAnalysisRequest,
    dag: Dag,
    baseline_cost: float,
    baseline_ms: float,
) -> Stage:
    return Stage(
        recommendations=recommend_indexes(validated, schema, request.optimization_goal),
        original_nodes=dag.nodes,
        optimized_nodes=dag.nodes,
        edges=dag.edges,
        optimized_metrics=_metrics(baseline_cost, baseline_ms),
        engine="heuristic",
    )


def _attention_list(outcome: ml.MlOutcome) -> list[AttentionHotspot]:
    return [
        AttentionHotspot(
            node_index=int(item.node_index),
            operator=str(item.operator),
            relation=item.relation,
            weight=round(float(item.weight), 6),
        )
        for item in outcome.attention
    ]


async def _engine_stage(
    run_id: str,
    request: QueryAnalysisRequest,
    validated,
    baseline,
    schema,
    dag: Dag,
    deps: PipelineDeps,
) -> Stage:
    fallback = _heuristic_stage(
        validated,
        schema,
        request,
        dag,
        baseline.total_cost,
        baseline.execution_time_ms,
    )
    if not deps.engine.available:
        return fallback

    await deps.runs.update(
        run_id,
        "gnn_inference",
        60,
        "Symbolic pruning + GATv2 beam search over candidate index sets…",
    )
    try:
        outcome = await asyncio.to_thread(
            ml.optimize,
            deps.engine.optimizer,
            validated.sql,
            baseline.plan,
            schema,
            request.optimization_goal,
            dag.nodes,
            dag.edges,
            baseline.execution_time_ms,
            run_id,
        )
    except Exception:  # noqa: BLE001 - a model fault must not kill the run
        logger.exception("Engine inference failed for run %s; using heuristics", run_id)
        return fallback

    return Stage(
        recommendations=outcome.recommendations or fallback.recommendations,
        original_nodes=outcome.original_nodes,
        optimized_nodes=outcome.optimized_nodes or dag.nodes,
        edges=outcome.edges or dag.edges,
        optimized_metrics=ml.scale_metrics(
            baseline.total_cost,
            baseline.execution_time_ms,
            outcome.predicted_ms,
        ),
        engine="gnn",
        attention=_attention_list(outcome),
        trace=list(outcome.trace),
        rejected=[
            RejectedCandidate(description=str(item.description), reason=str(item.reason))
            for item in outcome.rejected
        ],
        speedup=round(outcome.speedup, 2),
        symbolic_count=outcome.symbolic_candidate_count,
    )


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
            run_id,
            "parsing",
            30,
            "Capturing the baseline EXPLAIN (ANALYZE) plan "
            f"(median of {settings.explain_measurement_runs} runs)…",
        )
        try:
            baseline = (
                await explain_steady_state(
                    conn,
                    validated.sql,
                    settings.explain_timeout_ms,
                    settings.explain_measurement_runs,
                )
            ).result
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

    original_dag = build_dag(baseline.plan)
    stage = await _engine_stage(
        run_id, request, validated, baseline, schema, original_dag, deps
    )

    optimized_nodes = stage.optimized_nodes
    optimized_metrics = stage.optimized_metrics
    validated_recommendations = stage.recommendations
    edges = stage.edges

    if stage.recommendations and settings.shadow_dsn and settings.shadow_validate:
        await runs.update(
            run_id,
            "hypopg_validation",
            80,
            "Injecting hypothetical indexes into the shadow database…",
        )
        validated_recommendations, shadow_dag, shadow_metrics = (
            await _validate_candidates(
                validated.sql,
                stage.recommendations,
                settings,
                stage.optimized_metrics,
            )
        )
        if shadow_dag is not None:
            optimized_nodes = shadow_dag.nodes
            edges = shadow_dag.edges
            optimized_metrics = shadow_metrics
    elif stage.recommendations:
        logger.info("Shadow validation disabled; returning unvalidated candidates")

    await runs.update(
        run_id, "gnn_inference", 95, "Assembling explainability and recommendations…"
    )
    result = AnalysisResult(
        run_id=run_id,
        status="completed",
        engine=stage.engine,
        original_metrics=_metrics(baseline.total_cost, baseline.execution_time_ms),
        optimized_metrics=optimized_metrics,
        original_dag=stage.original_nodes or original_dag.nodes,
        optimized_dag=optimized_nodes,
        edges=edges,
        original_edges=original_dag.edges,
        recommendations=validated_recommendations,
        attention=stage.attention,
        symbolic_trace=stage.trace,
        rejected_candidates=stage.rejected,
        speedup_factor=stage.speedup,
        symbolic_candidate_count=stage.symbolic_count,
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
    fallback_metrics: dict[str, float],
) -> tuple[list[IndexRecommendation], Dag | None, dict[str, float]]:
    try:
        conn = await connect_shadow(settings)
    except ShadowUnavailable as exc:
        logger.warning("Shadow validation skipped: %s", exc)
        return candidates, None, fallback_metrics

    validated: list[IndexRecommendation] = []
    best_plan = None
    best_time: float | None = None
    best_cost = 0.0

    try:
        for candidate in candidates:
            try:
                outcome = await validate_index(
                    conn,
                    sql_query,
                    candidate.sql_statement,
                    settings.explain_timeout_ms,
                    settings.explain_measurement_runs,
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
        return candidates, None, fallback_metrics

    if best_plan is None:
        return validated, None, fallback_metrics

    return validated, build_dag(best_plan), _metrics(best_cost, best_time or 0.0)
