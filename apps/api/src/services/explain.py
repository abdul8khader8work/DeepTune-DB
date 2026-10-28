"""Transaction-wrapped EXPLAIN (ANALYZE, FORMAT JSON) with timeout + rollback."""

import json
from dataclasses import dataclass

import asyncpg


@dataclass(frozen=True)
class ExplainResult:
    plan: dict
    planning_time_ms: float
    execution_time_ms: float
    total_cost: float
    root_rows: int


def _decode_payload(raw: object) -> list[dict]:
    if isinstance(raw, str):
        payload = json.loads(raw)
    elif isinstance(raw, list):
        payload = raw
    else:
        raise ValueError("EXPLAIN did not return a JSON payload")
    if not isinstance(payload, list) or not payload:
        raise ValueError("EXPLAIN payload is empty")
    return payload


async def explain_analyze(
    conn: asyncpg.Connection, sql: str, timeout_ms: int
) -> ExplainResult:
    """Run EXPLAIN ANALYZE inside a transaction and always roll back.

    The SQL must already be validated as a single SELECT by sql_guard.
    """
    timeout = int(timeout_ms)
    transaction = conn.transaction()
    await transaction.start()
    try:
        await conn.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        row = await conn.fetchrow(f"EXPLAIN (ANALYZE, FORMAT JSON) {sql}")
    finally:
        await transaction.rollback()

    if row is None:
        raise ValueError("EXPLAIN returned no rows")
    payload = _decode_payload(row[0])
    top = payload[0]
    plan = top.get("Plan")
    if not isinstance(plan, dict):
        raise ValueError("EXPLAIN payload has no Plan object")

    return ExplainResult(
        plan=plan,
        planning_time_ms=float(top.get("Planning Time", 0.0)),
        execution_time_ms=float(top.get("Execution Time", 0.0)),
        total_cost=float(plan.get("Total Cost", 0.0)),
        root_rows=int(plan.get("Actual Rows", plan.get("Plan Rows", 0)) or 0),
    )
