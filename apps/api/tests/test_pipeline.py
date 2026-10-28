"""Pipeline fallback: a dead shadow DB must never wipe the baseline DAG."""

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

    recommendations, nodes, metrics = await pipeline._validate_candidates(
        "SELECT * FROM orders",
        [RECOMMENDATION],
        settings,
        NODES,
        METRICS,
    )

    assert recommendations == [RECOMMENDATION]
    assert nodes == NODES
    assert metrics == METRICS
