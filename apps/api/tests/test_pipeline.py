"""Pipeline fallback: a dead shadow DB must never wipe the baseline DAG."""

import asyncpg
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


class FakeTargetConnection:
    def __init__(self, error: Exception | None = None) -> None:
        self.sql: list[str] = []
        self.error = error

    async def execute(self, sql: str) -> None:
        self.sql.append(sql)
        if self.error is not None:
            raise self.error


async def test_vacuum_analyze_is_attempted_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TARGET_ALLOW_MAINTENANCE", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    conn = FakeTargetConnection()

    assert settings.target_allow_maintenance is True
    await pipeline._refresh_stats(conn, settings)  # type: ignore[arg-type]
    assert conn.sql == ["VACUUM ANALYZE"]


async def test_vacuum_analyze_privilege_error_is_not_fatal(
    settings: Settings,
) -> None:
    conn = FakeTargetConnection(asyncpg.PostgresError("must be owner of table"))

    # A read-only target role must degrade, not fail the analysis run.
    await pipeline._refresh_stats(conn, settings)  # type: ignore[arg-type]
    assert conn.sql == ["VACUUM ANALYZE"]


async def test_vacuum_analyze_timeout_is_not_fatal(settings: Settings) -> None:
    conn = FakeTargetConnection(TimeoutError("command timeout"))

    await pipeline._refresh_stats(conn, settings)  # type: ignore[arg-type]
    assert conn.sql == ["VACUUM ANALYZE"]


async def test_maintenance_can_be_switched_off(settings: Settings) -> None:
    conn = FakeTargetConnection()
    disabled = settings.model_copy(update={"target_allow_maintenance": False})

    await pipeline._refresh_stats(conn, disabled)  # type: ignore[arg-type]
    assert conn.sql == []
