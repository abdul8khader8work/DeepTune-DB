"""EXPLAIN sandbox: transaction, timeout, unconditional rollback, median of 5."""

import json
from typing import Any

import pytest

from src.services.explain import explain_analyze, explain_steady_state

PLAN = {
    "Plan": {
        "Node Type": "Seq Scan",
        "Relation Name": "users",
        "Total Cost": 42.5,
        "Plan Rows": 100,
        "Actual Rows": 90,
        "Actual Total Time": 0.75,
        "Plans": [],
    },
    "Planning Time": 0.2,
    "Execution Time": 1.25,
}


def payload(execution_ms: float) -> str:
    return json.dumps([{**PLAN, "Execution Time": execution_ms}])


class FakeTransaction:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def start(self) -> None:
        self.log.append("BEGIN")

    async def rollback(self) -> None:
        self.log.append("ROLLBACK")


class FakeConnection:
    def __init__(self, payload: str, fail: bool = False) -> None:
        self.log: list[str] = []
        self.payload = payload
        self.fail = fail

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self.log)

    async def execute(self, sql: str) -> None:
        self.log.append(sql)

    async def fetchrow(self, sql: str) -> Any:
        self.log.append(sql)
        if self.fail:
            raise RuntimeError("boom")
        return (self.payload,)


async def test_explain_uses_transaction_timeout_and_rollback() -> None:
    conn = FakeConnection(json.dumps([PLAN]))
    result = await explain_analyze(conn, "SELECT * FROM users", 5000)  # type: ignore[arg-type]

    assert result.execution_time_ms == 1.25
    assert result.total_cost == 42.5
    assert result.root_rows == 90
    assert conn.log[0] == "BEGIN"
    assert any("statement_timeout" in item and "5000" in item for item in conn.log)
    assert conn.log[-1] == "ROLLBACK"


async def test_explain_rolls_back_on_failure() -> None:
    conn = FakeConnection("[]", fail=True)
    with pytest.raises(RuntimeError):
        await explain_analyze(conn, "SELECT * FROM users", 5000)  # type: ignore[arg-type]
    assert conn.log[-1] == "ROLLBACK"


class TimedConnection:
    """Returns one execution time per ``fetchrow`` call, in the order given."""

    def __init__(self, times: list[float]) -> None:
        self.times = list(times)
        self.calls = 0
        self.log: list[str] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self.log)

    async def execute(self, sql: str) -> None:
        self.log.append(sql)

    async def fetchrow(self, sql: str) -> Any:
        self.log.append(sql)
        execution = self.times[self.calls]
        self.calls += 1
        return (payload(execution),)


async def test_steady_state_discards_extremes_and_returns_median() -> None:
    conn = TimedConnection([50.0, 2.0, 9.0, 8.0, 10.0])
    outcome = await explain_steady_state(  # type: ignore[arg-type]
        conn, "SELECT * FROM users", 5000, 5
    )

    assert outcome.result.execution_time_ms == 9.0
    assert outcome.samples_ms == (50.0, 2.0, 9.0, 8.0, 10.0)
    assert outcome.kept_ms == (8.0, 9.0, 10.0)
    assert outcome.discarded_ms == (2.0, 50.0)
    assert conn.log.count("BEGIN") == 5
    assert conn.log.count("ROLLBACK") == 5


async def test_steady_state_single_run_keeps_the_only_sample() -> None:
    conn = TimedConnection([7.5])
    outcome = await explain_steady_state(  # type: ignore[arg-type]
        conn, "SELECT * FROM users", 5000, 1
    )

    assert outcome.result.execution_time_ms == 7.5
    assert outcome.kept_ms == (7.5,)
    assert outcome.discarded_ms == ()


async def test_steady_state_handles_identical_samples() -> None:
    conn = TimedConnection([4.0, 4.0, 4.0, 4.0, 4.0])
    outcome = await explain_steady_state(  # type: ignore[arg-type]
        conn, "SELECT * FROM users", 5000, 5
    )

    assert outcome.result.execution_time_ms == 4.0
    assert outcome.kept_ms == (4.0, 4.0, 4.0)
    assert outcome.discarded_ms == (4.0, 4.0)
