"""Patch 2 Task 3: hypopg injection, one transaction, and guaranteed cleanup.

The patch's acceptance criterion is explicit: after a beam over N candidates,
``hypopg_drop_index`` must have been called exactly N times. These tests drive
the real functions in ``services/hypothetical.py`` against a fake asyncpg
connection and assert both the call counts and the ordering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import asyncpg
import pytest

from src.services import hypothetical
from src.services.hypothetical import (
    HypotheticalPlanError,
    get_hypothetical_qep,
    prefetch_configurations,
    to_hypopg_sql,
)

CREATE_INDEX_SQL = (
    'CREATE INDEX CONCURRENTLY "idx_orders_status" '
    'ON "public"."orders" USING btree ("status")'
)
QUERY = "SELECT id FROM public.orders WHERE status = 'paid'"

EXPLAIN_ROW = {
    "Plan": {
        "Node Type": "Index Scan",
        "Relation Name": "orders",
        "Total Cost": 8.5,
        "Actual Rows": 12,
        "Actual Total Time": 0.4,
    },
    "Planning Time": 0.2,
    "Execution Time": 0.5,
}


class FakeRecord:
    """Just enough of ``asyncpg.Record``: positional and named access."""

    def __init__(self, values: Sequence[Any], named: dict[str, Any] | None = None) -> None:
        self._values = list(values)
        self._named = dict(named or {})

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._named[key]


class FakeTransaction:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def start(self) -> None:
        self._log.append("begin")

    async def rollback(self) -> None:
        self._log.append("rollback")


class FakeConnection:
    """Records every statement; ``fail_on`` makes the first match raise."""

    def __init__(self, *, fail_on: str | None = None) -> None:
        self.log: list[str] = []
        self.sql: list[str] = []
        self.dropped: list[int] = []
        self._fail_on = fail_on
        self._next_index_id = 100

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self.log)

    async def execute(self, sql: str, *args: Any) -> str:
        self.sql.append(sql)
        if "hypopg_create_index" in sql:
            self.log.append("create")
        elif "hypopg_drop_index" in sql:
            self.log.append("drop")
            self.dropped.append(int(args[0]))
        return "SELECT 1"

    async def fetchrow(self, sql: str, *args: Any) -> FakeRecord:
        self.sql.append(sql)
        if self._fail_on and self._fail_on in sql:
            raise asyncpg.PostgresError("simulated planner failure")
        if "hypopg_create_index" in sql:
            self.log.append("create")
            self._next_index_id += 1
            return FakeRecord([self._next_index_id], {"indexrelid": self._next_index_id})
        if "hypopg_drop_index" in sql:
            self.log.append("drop")
            self.dropped.append(int(args[0]))
            return FakeRecord([True])
        self.log.append("explain")
        return FakeRecord([[EXPLAIN_ROW]])


@dataclass(frozen=True)
class Request:
    key: str
    create_sqls: tuple[str, ...]


def test_hypopg_sql_drops_concurrently() -> None:
    statement = to_hypopg_sql(CREATE_INDEX_SQL)
    assert "CONCURRENTLY" not in statement.upper()
    assert "idx_orders_status" in statement
    assert statement.upper().startswith("CREATE INDEX")


def test_hypopg_sql_rejects_non_index_statements() -> None:
    with pytest.raises(HypotheticalPlanError):
        to_hypopg_sql("DROP TABLE orders")
    with pytest.raises(HypotheticalPlanError):
        to_hypopg_sql("this is not sql")


async def test_single_index_runs_in_one_transaction_and_is_dropped() -> None:
    conn = FakeConnection()

    result = await get_hypothetical_qep(conn, CREATE_INDEX_SQL, QUERY, timeout_ms=2500)

    assert result.plan["Node Type"] == "Index Scan"
    assert result.execution_time_ms == pytest.approx(0.5)
    # Create -> explain -> drop all happen before the rollback.
    assert conn.log == ["begin", "create", "explain", "drop", "rollback"]
    assert conn.dropped == [101]
    assert "SET LOCAL statement_timeout = '2500'" in conn.sql


async def test_multi_index_configuration_injects_every_index() -> None:
    conn = FakeConnection()
    sqls = [
        CREATE_INDEX_SQL,
        CREATE_INDEX_SQL.replace("status", "customer_id"),
    ]

    await get_hypothetical_qep(conn, sqls, QUERY)

    assert conn.log == ["begin", "create", "create", "explain", "drop", "drop", "rollback"]
    assert len(conn.dropped) == 2


async def test_prefetch_drops_every_candidate_once() -> None:
    """The acceptance test from the patch: N candidates -> N drops."""
    requests = [
        Request(key=f"candidate-{index}", create_sqls=(CREATE_INDEX_SQL,))
        for index in range(3)
    ]
    conn = FakeConnection()

    plans = await prefetch_configurations(
        conn, QUERY, requests, timeout_ms=5000, limit=10
    )

    assert set(plans) == {"candidate-0", "candidate-1", "candidate-2"}
    assert len(conn.dropped) == 3
    assert conn.log.count("create") == 3
    assert conn.log.count("drop") == 3
    assert conn.log.count("explain") == 3
    assert conn.log.count("rollback") == 3
    # One connection serves every candidate: no reconnect per index.
    assert conn.log[0] == "begin"


async def test_prefetch_respects_the_limit() -> None:
    requests = [
        Request(key=f"candidate-{index}", create_sqls=(CREATE_INDEX_SQL,))
        for index in range(5)
    ]
    conn = FakeConnection()

    plans = await prefetch_configurations(
        conn, QUERY, requests, timeout_ms=5000, limit=2
    )

    assert list(plans) == ["candidate-0", "candidate-1"]
    assert len(conn.dropped) == 2


async def test_rejected_candidate_is_skipped_without_leaking() -> None:
    conn = FakeConnection(fail_on="hypopg_create_index")
    requests = [Request(key="bad", create_sqls=(CREATE_INDEX_SQL,))]

    plans = await prefetch_configurations(
        conn, QUERY, requests, timeout_ms=5000, limit=10
    )

    assert plans == {}
    assert conn.dropped == []
    # The failed statement still ends its transaction.
    assert conn.log.count("rollback") == 1


async def test_failed_explain_still_drops_the_index() -> None:
    conn = FakeConnection(fail_on="EXPLAIN")

    with pytest.raises(asyncpg.PostgresError):
        await get_hypothetical_qep(conn, CREATE_INDEX_SQL, QUERY)

    assert conn.log[0] == "begin"
    assert "create" in conn.log
    # Roll back first (the transaction is aborted), then drop.
    assert conn.log.index("rollback") < conn.log.index("drop")
    assert conn.dropped == [101]
