"""EXPLAIN sandbox: transaction, timeout, and unconditional rollback."""

import json
from typing import Any

import pytest

from src.services.explain import explain_analyze

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
