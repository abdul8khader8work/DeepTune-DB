"""Hypothetical query plans via ``hypopg`` (Patch 2 Task 3).

The GNN must score the plan PostgreSQL *would* choose with a candidate index
set, not the baseline plan with a hand-made discount. The engine is torch-only
and may not import a database driver (AGENTS.md §1), so the API fetches the
post-index plans here and hands them to the engine as plain EXPLAIN JSON.

Every configuration runs inside one transaction on one connection::

    BEGIN;
    SET LOCAL statement_timeout = '<n>';
    SELECT * FROM hypopg_create_index(...);      -- one per index in the set
    EXPLAIN (ANALYZE, FORMAT JSON) <query>;
    SELECT hypopg_drop_index(...);               -- same transaction
    ROLLBACK;

``hypopg`` indexes live in backend memory rather than in the catalog, so a
leaked id survives the rollback and accumulates for the lifetime of the
connection. The drop therefore sits in a ``finally`` and a failed drop falls
back to ``hypopg_reset()``: the shadow session must never OOM mid-search.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from typing import Protocol

import asyncpg
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from src.core.cache import cached
from src.services.explain import ExplainResult, result_from_payload

logger = logging.getLogger(__name__)

_HYPOPG_CREATE = "SELECT * FROM hypopg_create_index($1)"
_HYPOPG_DROP = "SELECT hypopg_drop_index($1)"
_HYPOPG_RESET = "SELECT hypopg_reset()"


class HypotheticalPlanError(RuntimeError):
    """Raised when hypopg or the planner rejects a candidate configuration."""


class PlanRequestLike(Protocol):
    """The engine's ``PlanRequest`` as seen from the API (duck-typed)."""

    @property
    def key(self) -> str: ...

    @property
    def create_sqls(self) -> Sequence[str]: ...


@cached(namespace="hypopg_sql")
def to_hypopg_sql(create_sql: str) -> str:
    """Strip ``CONCURRENTLY``: hypopg cannot plan a concurrently built index.

    The statement is parsed with sqlglot (never regex-edited) and re-emitted for
    PostgreSQL, so a malformed or non-``CREATE INDEX`` string is rejected before
    it reaches the shadow database.

    Patch 3: the pure string-to-string translation is cached, because beam
    prefetch and apply/revert re-plan the same candidate SQL many times per run.
    """
    try:
        statement = sqlglot.parse_one(create_sql, read="postgres")
    except ParseError as exc:
        raise HypotheticalPlanError("candidate SQL is not parseable") from exc
    if not isinstance(statement, exp.Create) or (statement.kind or "").upper() != "INDEX":
        raise HypotheticalPlanError("candidate SQL is not a CREATE INDEX statement")
    statement.set("concurrently", False)
    return statement.sql(dialect="postgres")


async def get_hypothetical_qep(
    conn: asyncpg.Connection,
    candidate_index_sql: str | Sequence[str],
    target_query: str,
    timeout_ms: int = 5000,
) -> ExplainResult:
    """Inject the index set, EXPLAIN the query, and always drop the indexes.

    The plan is a plain ``EXPLAIN`` (no ``ANALYZE``) on purpose: hypopg only
    injects a hypothetical index while the planner is building an explain-only
    statement (``hypopg_index.c``: "hypothetical indexes *ONLY* in an
    explain-no-analyze command"). Adding ``ANALYZE`` makes the planner ignore
    the index and silently returns the un-indexed plan for every configuration.

    A single index is passed as a string; a multi-index beam configuration is
    passed as a sequence, so one EXPLAIN sees the whole candidate set at once.
    """
    create_sqls = (
        [candidate_index_sql]
        if isinstance(candidate_index_sql, str)
        else list(candidate_index_sql)
    )
    if not create_sqls:
        raise HypotheticalPlanError("no candidate index SQL was supplied")
    statements = [to_hypopg_sql(sql) for sql in create_sqls]
    timeout = max(1, int(timeout_ms))

    index_ids: list[int] = []
    transaction = conn.transaction()
    await transaction.start()
    try:
        await conn.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        for statement in statements:
            row = await conn.fetchrow(_HYPOPG_CREATE, statement)
            if row is None:
                raise HypotheticalPlanError("hypopg_create_index returned no row")
            index_ids.append(int(row["indexrelid"]))
        row = await conn.fetchrow(f"EXPLAIN (FORMAT JSON) {target_query}")
        if row is None:
            raise HypotheticalPlanError("EXPLAIN returned no rows")
        result = result_from_payload(row[0])
        # Drop before the rollback so the hypothetical index never outlives the
        # plan it produced. ``index_ids`` is cleared so the finally block does
        # not drop twice.
        for index_id in index_ids:
            await conn.execute(_HYPOPG_DROP, index_id)
        index_ids = []
        return result
    finally:
        # Rolls back first on purpose: after a planner error the transaction is
        # aborted and even ``hypopg_drop_index`` is refused until it ends.
        await transaction.rollback()
        for index_id in index_ids:
            try:
                await conn.execute(_HYPOPG_DROP, index_id)
            except asyncpg.PostgresError:
                logger.warning(
                    "hypopg_drop_index(%s) failed; resetting every hypothetical index",
                    index_id,
                )
                await conn.execute(_HYPOPG_RESET)
                break


async def prefetch_configurations(
    conn: asyncpg.Connection,
    sql_query: str,
    requests: Sequence[PlanRequestLike],
    *,
    timeout_ms: int,
    limit: int,
) -> dict[str, dict[str, object]]:
    """Fetch a post-index QEP for each requested configuration.

    One connection serves every candidate: opening a connection per index would
    cost a TCP + auth round trip per beam entry. A rejected candidate is logged
    and skipped; the engine then scores that entry with its offline builder, so
    a single bad index never aborts the run.
    """
    budget = max(0, int(limit))
    plans: dict[str, dict[str, object]] = {}
    for request in list(requests)[:budget]:
        try:
            result = await get_hypothetical_qep(
                conn, request.create_sqls, sql_query, timeout_ms
            )
        except (
            HypotheticalPlanError,
            asyncpg.PostgresError,
            asyncio.TimeoutError,
            OSError,
        ) as exc:
            logger.info(
                "hypopg could not plan %s (%s); the offline builder will score it",
                request.key,
                exc.__class__.__name__,
            )
            continue
        plans[request.key] = {
            "Plan": result.plan,
            "Planning Time": result.planning_time_ms,
            # No "Execution Time": the candidate plan is a planner estimate, not
            # a measurement. The engine labels it accordingly instead of reading
            # a fabricated 0 ms.
        }
    return plans


__all__ = [
    "HypotheticalPlanError",
    "PlanRequestLike",
    "get_hypothetical_qep",
    "prefetch_configurations",
    "to_hypopg_sql",
]
