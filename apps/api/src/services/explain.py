"""Transaction-wrapped EXPLAIN (ANALYZE, FORMAT JSON) with timeout + rollback."""

import json
import logging
from dataclasses import dataclass
from typing import Sequence

import asyncpg

logger = logging.getLogger(__name__)

#: Patch 2: run the baseline five times, drop the fastest and slowest sample,
#: and report the median of the remaining three.
DEFAULT_MEASUREMENT_RUNS = 5


@dataclass(frozen=True)
class ExplainResult:
    plan: dict
    planning_time_ms: float
    execution_time_ms: float
    total_cost: float
    root_rows: int


@dataclass(frozen=True)
class SteadyStateResult:
    """The median run plus the samples that produced it (kept for the logs)."""

    result: ExplainResult
    samples_ms: tuple[float, ...]
    kept_ms: tuple[float, ...]
    discarded_ms: tuple[float, ...]


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


def _select_median(
    results: Sequence[ExplainResult],
) -> tuple[ExplainResult, list[ExplainResult], list[ExplainResult]]:
    """Drop the fastest and slowest run, then pick the median of the rest.

    Trimming needs three samples; with one or two runs the single sample (or the
    slower of the two) is the best estimate available.
    """
    ordered = sorted(results, key=lambda item: item.execution_time_ms)
    if len(ordered) >= 3:
        return ordered[len(ordered) // 2], ordered[1:-1], [ordered[0], ordered[-1]]
    return ordered[len(ordered) // 2], ordered, []


async def explain_steady_state(
    conn: asyncpg.Connection,
    sql: str,
    timeout_ms: int,
    runs: int = DEFAULT_MEASUREMENT_RUNS,
) -> SteadyStateResult:
    """Measure ``sql`` ``runs`` times and keep the median run.

    A single ``EXPLAIN (ANALYZE)`` is biased by Postgres caching: the first run
    pays for cold shared buffers, and an immediate repeat can be faster than the
    steady state because the plan and its pages are already resident. The
    "median of 5" rule discards the fastest and slowest samples and reports the
    middle one, so neither the cache-cold nor the cache-hot outlier decides the
    baseline.

    Every sample runs in its own rolled-back transaction (see
    :func:`explain_analyze`); the SQL must already be validated as a single
    SELECT by ``sql_guard``.
    """
    count = max(1, int(runs))
    results = [await explain_analyze(conn, sql, timeout_ms) for _ in range(count)]

    chosen, kept, discarded = _select_median(results)
    samples_ms = tuple(item.execution_time_ms for item in results)
    logger.info(
        "steady-state baseline: runs=%d samples=%s discarded=%s median=%.3f ms",
        count,
        [round(value, 3) for value in samples_ms],
        [round(item.execution_time_ms, 3) for item in discarded],
        chosen.execution_time_ms,
    )
    return SteadyStateResult(
        result=chosen,
        samples_ms=samples_ms,
        kept_ms=tuple(item.execution_time_ms for item in kept),
        discarded_ms=tuple(item.execution_time_ms for item in discarded),
    )
