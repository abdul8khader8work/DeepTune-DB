"""Patch 4 Task 3: shadow validation builds a real index, measures, and drops it.

hypopg only injects an index while *planning* an EXPLAIN without ANALYZE
(``hypopg_index.c``), so ``EXPLAIN (ANALYZE)`` used to execute the un-indexed
plan on both sides of the comparison. These tests pin the replacement: the
shadow index is real, the measurement is a median of N runs, and the index is
dropped even when the measurement fails.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.db import shadow
from src.services.explain import ExplainResult, SteadyStateResult
from src.services.hypothetical import HypotheticalPlanError

CREATE_SQL = (
    'CREATE INDEX CONCURRENTLY "idx_orders_status" '
    'ON "public"."orders" USING btree ("status")'
)


class FakeConnection:
    def __init__(self, *, oid: int = 4242) -> None:
        self.executed: list[str] = []
        self._oid = oid

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append(sql)
        return "OK"

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.executed.append(sql)
        return self._oid


def _steady(execution_ms: float, cost: float = 100.0) -> SteadyStateResult:
    return SteadyStateResult(
        result=ExplainResult(
            plan={"Node Type": "Index Scan", "Total Cost": cost},
            planning_time_ms=0.2,
            execution_time_ms=execution_ms,
            total_cost=cost,
            root_rows=10,
        ),
        samples_ms=(execution_ms,),
        kept_ms=(execution_ms,),
        discarded_ms=(),
    )


def test_shadow_index_sql_strips_concurrently_and_renames() -> None:
    statement = shadow.shadow_index_sql(CREATE_SQL, "deeptune_shadow_abc123")
    assert "CONCURRENTLY" not in statement.upper()
    assert statement == (
        'CREATE INDEX deeptune_shadow_abc123 ON "public"."orders" USING btree("status")'
    )


def test_shadow_index_sql_rejects_non_index_statements() -> None:
    with pytest.raises(HypotheticalPlanError):
        shadow.shadow_index_sql("DROP TABLE orders", "deeptune_shadow_x")


def test_shadow_index_name_is_short_and_unique() -> None:
    first = shadow._shadow_index_name()
    second = shadow._shadow_index_name()
    assert first != second
    assert first.startswith("deeptune_shadow_")
    assert len(first) <= 63


async def test_validate_index_builds_measures_and_drops(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([40.0, 4.0])

    async def fake_steady(*args: Any, **kwargs: Any) -> SteadyStateResult:
        return _steady(next(times))

    monkeypatch.setattr(shadow, "explain_steady_state", fake_steady)
    conn = FakeConnection()

    result = await shadow.validate_index(conn, "SELECT 1", CREATE_SQL, 5000, runs=5)

    assert result.baseline_execution_time_ms == pytest.approx(40.0)
    assert result.execution_time_ms == pytest.approx(4.0)
    assert result.shadow_index_oid == 4242
    assert conn.executed[0].startswith("DROP INDEX IF EXISTS")
    assert conn.executed[1].startswith("CREATE INDEX")
    assert "deeptune_shadow_" in conn.executed[1]
    assert conn.executed[-1] == f'DROP INDEX IF EXISTS "{result.index_name}"'


async def test_validate_index_drops_the_index_when_measurement_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_steady(*args: Any, **kwargs: Any) -> SteadyStateResult:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("EXPLAIN failed")
        return _steady(12.0)

    monkeypatch.setattr(shadow, "explain_steady_state", fake_steady)
    conn = FakeConnection()

    with pytest.raises(ValueError):
        await shadow.validate_index(conn, "SELECT 1", CREATE_SQL, 5000, runs=5)

    assert any(sql.startswith("CREATE INDEX") for sql in conn.executed)
    assert conn.executed[-1].startswith("DROP INDEX IF EXISTS")
