"""Pipeline fallback: maintenance and shadow failures never wipe the run."""

import pytest

from src.core.config import Settings
from src.db.shadow import ShadowUnavailable
from src.schemas.analysis import DAGNode, IndexRecommendation
from src.services import pipeline

NODES = [
    DAGNode(
        id="node_1",
        operation_type="Seq Scan",
        relation_name="orders",
        estimated_cost=80.0,
        estimated_rows=1000,
        actual_time_ms=1.2,
        gnn_attention_score=1.0,
    )
]
METRICS = {"cost": 80.0, "time_ms": 1.2}
RECOMMENDATION = IndexRecommendation(
    id="rec-1",
    sql_statement='CREATE INDEX CONCURRENTLY "idx_orders_status" ON "public"."orders" ("status")',
    target_table="orders",
    target_columns=["status"],
    predicted_speedup_factor=1.8,
    validated_speedup_factor=None,
    storage_overhead_bytes=14_000,
    write_impact_percentage=1.5,
    confidence_score=0.67,
    explanation="test",
)


async def test_shadow_unavailable_falls_back_to_baseline(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_connect(_: Settings) -> None:
        raise ShadowUnavailable("shadow is down")

    monkeypatch.setattr(pipeline, "connect_shadow", fail_connect)

    recommendations, shadow_dag, metrics = await pipeline._validate_candidates(
        "SELECT * FROM orders",
        [RECOMMENDATION],
        settings,
        METRICS,
    )

    assert recommendations == [RECOMMENDATION]
    assert shadow_dag is None
    assert metrics == METRICS


async def test_heuristic_stage_reports_null_attention(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """Patch 2 Task 1: no GATv2 forward means no attention, not 0.0."""

    validated = pipeline.validate_sql("SELECT * FROM orders", 10000)
    dag = pipeline.build_dag(
        {
            "Node Type": "Seq Scan",
            "Relation Name": "orders",
            "Total Cost": 80.0,
            "Plan Rows": 1000,
        }
    )
    stage = pipeline._heuristic_stage(
        validated,
        [],
        pipeline.QueryAnalysisRequest(connection_id="c", sql_query="SELECT 1"),
        dag,
        80.0,
        1.2,
    )
    assert [node.gnn_attention_score for node in stage.original_nodes] == [None]
    assert [node.gnn_attention_score for node in stage.optimized_nodes] == [None]


async def test_maintenance_failure_never_aborts_the_run(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    async def explode(*args: object, **kwargs: object) -> None:
        raise OSError("superuser unreachable")

    monkeypatch.setattr(pipeline, "refresh_table_statistics", explode)
    stored = pipeline.StoredConnection(
        dsn="postgresql://query_optimizer:secret@localhost:5432/shop"
    )

    await pipeline._refresh_target_statistics(stored, settings)  # must not raise


async def test_maintenance_can_be_switched_off(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    calls: list[object] = []

    async def spy(*args: object, **kwargs: object) -> None:
        calls.append(args)

    monkeypatch.setattr(pipeline, "refresh_table_statistics", spy)
    disabled = settings.model_copy(update={"target_allow_maintenance": False})

    await pipeline._refresh_target_statistics(
        pipeline.StoredConnection(dsn="postgresql://u:p@localhost:5432/shop"),
        disabled,
    )
    assert calls == []
