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
from src.db.target import StoredConnection, connect_target
from src.schemas.analysis import (
    AnalysisResult,
    AttentionHotspot,
    DAGEdge,
    DAGNode,
    IndexRecommendation,
    QueryAnalysisRequest,
    RejectedCandidate,
)
from src.schemas.connections import TableSchema
from src.services import ml
from src.services.dag import Dag, build_dag
from src.services.engine import EngineBundle
from src.services.explain import explain_steady_state
from src.services.hypothetical import HypotheticalPlanError, prefetch_configurations
from src.services.introspection import fetch_schema
from src.services.maintenance import refresh_table_statistics
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


async def _refresh_target_statistics(
    stored: StoredConnection, settings: Settings
) -> None:
    """Patch 2 Task 2: ANALYZE as the owner, never as ``query_optimizer``.

    A read-only target role cannot update ``pg_statistic``, and stale statistics
    make both the planner and hypopg mis-price indexes. The maintenance service
    opens an ephemeral superuser connection, runs ``VACUUM (ANALYZE,
    SKIP_LOCKED)``, and closes it before any user SQL is executed. Every failure
    degrades to a warning: a demo must still optimize without elevated rights.
    """
    if not settings.target_allow_maintenance:
        logger.info("Pre-flight ANALYZE is disabled (TARGET_ALLOW_MAINTENANCE=false)")
        return
    try:
        result = await refresh_table_statistics(
            stored.dsn,
            settings.superuser_password,
            override_dsn=settings.superuser_dsn,
            superuser_user=settings.target_superuser_user,
            timeout_ms=settings.maintenance_timeout_ms,
            connect_timeout_s=settings.target_connect_timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - maintenance must never abort a run
        logger.warning(
            "Failed to refresh stats, proceeding with potentially stale statistics: %s",
            exc.__class__.__name__,
        )
        return

    if result.skipped:
        logger.warning(
            "Statistics refresh skipped (%s); proceeding with potentially stale "
            "statistics",
            result.error,
        )
    elif result.error:
        logger.warning(
            "Failed to refresh stats, proceeding with potentially stale statistics: %s",
            result.error,
        )
    else:
        logger.info("ANALYZE refreshed target statistics via an ephemeral owner session")


def _without_attention(nodes: list[DAGNode]) -> list[DAGNode]:
    """Heuristic fallback: no GATv2 forward ran, so attention is ``None``.

    Patch 2 Task 1: the field became ``Optional`` so the UI can tell "no model
    scored this plan" apart from "the model scored this node at zero".
    """
    return [node.model_copy(update={"gnn_attention_score": None}) for node in nodes]


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
        original_nodes=_without_attention(dag.nodes),
        optimized_nodes=_without_attention(dag.nodes),
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


async def _prefetch_hypothetical_plans(
    run_id: str,
    sql_query: str,
    schema: list[TableSchema],
    goal: str,
    deps: PipelineDeps,
) -> dict[str, dict[str, object]]:
    """Task 3: hand the GNN the plan PostgreSQL would pick after the index.

    The engine enumerates every configuration it can reach; this fetches the
    matching QEPs through ``hypopg`` *before* the beam runs, so the beam scores
    post-index plans instead of the baseline with a heuristic discount. A
    missing shadow database yields an empty cache and the beam falls back to its
    offline plan builder.
    """
    settings = deps.settings
    if not settings.shadow_dsn or not settings.shadow_validate:
        return {}
    if settings.hypopg_prefetch_limit <= 0:
        return {}
    try:
        requests = await asyncio.to_thread(
            deps.engine.optimizer.plan_requests,
            sql_query,
            ml.to_catalog(schema),
            goal,
            settings.hypopg_prefetch_limit,
        )
    except Exception:  # noqa: BLE001 - prefetch is an optimisation, not a contract
        logger.exception("Could not enumerate hypothetical plans for run %s", run_id)
        return {}
    if not requests:
        return {}

    await deps.runs.update(
        run_id,
        "gnn_inference",
        55,
        f"Fetching {len(requests)} hypothetical plans via hypopg…",
    )
    try:
        conn = await connect_shadow(settings)
    except ShadowUnavailable as exc:
        logger.info("Hypothetical plans unavailable for run %s: %s", run_id, exc)
        return {}
    try:
        plans = await prefetch_configurations(
            conn,
            sql_query,
            requests,
            timeout_ms=settings.explain_timeout_ms,
            limit=settings.hypopg_prefetch_limit,
        )
    finally:
        await conn.close()
    logger.info(
        "Hypopg prefetch for run %s: %d/%d post-index plans cached",
        run_id,
        len(plans),
        len(requests),
    )
    return plans


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

    candidate_qeps = await _prefetch_hypothetical_plans(
        run_id, validated.sql, schema, request.optimization_goal, deps
    )

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
            candidate_qeps,
        )
    except Exception:  # noqa: BLE001 - a model fault must not kill the run
        logger.exception("Engine inference failed for run %s; using heuristics", run_id)
        return fallback

    return Stage(
        recommendations=outcome.recommendations or fallback.recommendations,
        original_nodes=outcome.original_nodes,
        optimized_nodes=outcome.optimized_nodes or dag.nodes,
        edges=outcome.edges or dag.edges,
        # Task 1: ``outcome.predicted_ms`` is already Duan-smearing-corrected
        # inside the engine's inverse log-transform (``search.beam``). Applying
        # the factor again here would double-correct the reported latency, so
        # the pipeline only scales cost by the corrected number.
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

    await runs.update(run_id, "parsing", 15, "Refreshing planner statistics…")
    await _refresh_target_statistics(stored, settings)

    conn = await connect_target(stored, settings)
    try:
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
            "Building candidate indexes in the shadow database…",
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
            except (asyncpg.PostgresError, HypotheticalPlanError, ValueError) as exc:
                logger.warning(
                    "shadow validation failed for %s: %s",
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
