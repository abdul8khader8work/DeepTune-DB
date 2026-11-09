"""Shadow DB helpers: measured candidate-index validation on a disposable clone.

Why the shadow index is *real* (Patch 4, Task 3)
------------------------------------------------
``hypopg`` only injects a hypothetical index while the planner is building an
``EXPLAIN`` **without** ``ANALYZE`` (``hypopg_index.c``: "hypothetical indexes
*ONLY* in an explain-no-analyze command"). ``EXPLAIN (ANALYZE)`` therefore runs
the *un-indexed* plan even while a hypothetical index exists, so comparing the
two execution times measures the same Seq Scan twice and always reports ~1.0x.

The shadow database is a disposable twin of the target (compose mounts its role
as the table owner) and the target database is never touched, so validation here
builds the candidate index for real, measures the median of ``runs``
``EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`` samples, and drops it again. The
hypothetical path stays in :mod:`src.services.hypothetical`, where it belongs:
scoring candidate plans during beam search.
"""

import asyncio
import uuid
from dataclasses import dataclass

import asyncpg
import sqlglot
from sqlglot import exp

from src.core.config import Settings
from src.services.explain import ExplainResult, explain_analyze, explain_steady_state
from src.services.hypothetical import to_hypopg_sql


class ShadowUnavailable(RuntimeError):
    """Raised when the shadow database or hypopg is not usable."""


@dataclass(frozen=True)
class ValidationResult:
    shadow_index_oid: int
    index_name: str
    baseline_execution_time_ms: float
    execution_time_ms: float
    total_cost: float
    plan: dict


#: Long enough to be unique inside the shadow DB, short enough for the 63-byte
#: PostgreSQL identifier limit.
_SHADOW_INDEX_PREFIX = "deeptune_shadow_"


async def connect_shadow(settings: Settings) -> asyncpg.Connection:
    if not settings.shadow_dsn:
        raise ShadowUnavailable("SHADOW_DB_DSN is not configured")
    try:
        conn = await asyncpg.connect(
            dsn=settings.shadow_dsn,
            timeout=settings.target_connect_timeout_s,
            command_timeout=settings.explain_timeout_ms / 1000 + 5,
            server_settings={"application_name": "deeptune-shadow"},
        )
    except (OSError, asyncio.TimeoutError, asyncpg.PostgresError) as exc:
        raise ShadowUnavailable(
            f"Shadow database is unreachable: {exc.__class__.__name__}"
        ) from exc

    try:
        await ensure_hypopg(conn)
    except asyncpg.PostgresError as exc:
        await conn.close()
        raise ShadowUnavailable("Could not inspect shadow extensions") from exc
    except ShadowUnavailable:
        await conn.close()
        raise
    return conn


async def ensure_hypopg(conn: asyncpg.Connection) -> None:
    """Fail fast when the shadow database cannot plan hypothetical indexes."""
    installed = await conn.fetchval(
        "SELECT 1 FROM pg_extension WHERE extname = 'hypopg'"
    )
    if not installed:
        raise ShadowUnavailable("The hypopg extension is not installed")


def _shadow_index_name() -> str:
    """Per-validation name so two concurrent runs can never collide."""
    return f"{_SHADOW_INDEX_PREFIX}{uuid.uuid4().hex[:12]}"


def shadow_index_sql(create_sql: str, name: str) -> str:
    """Re-emit the candidate DDL under a shadow-only index name.

    ``CONCURRENTLY`` is stripped (:func:`to_hypopg_sql` parses the statement with
    sqlglot and rejects anything that is not a ``CREATE INDEX``), because a
    concurrently built index cannot run inside the measurement transaction.
    """
    statement = sqlglot.parse_one(to_hypopg_sql(create_sql), read="postgres")
    statement.this.set("this", exp.to_identifier(name))
    return statement.sql(dialect="postgres")


async def drop_shadow_index(conn: asyncpg.Connection, name: str) -> None:
    """Drop a shadow index by name; a no-op when it was never created."""
    await conn.execute(f'DROP INDEX IF EXISTS "{name}"')


async def create_hypothetical_index(conn: asyncpg.Connection, create_sql: str) -> tuple[int, str]:
    row = await conn.fetchrow("SELECT * FROM hypopg_create_index($1)", create_sql)
    if row is None:
        raise ShadowUnavailable("hypopg_create_index returned no row")
    return int(row["indexrelid"]), str(row["indexname"])


async def drop_hypothetical_index(conn: asyncpg.Connection, index_id: int) -> None:
    await conn.execute("SELECT hypopg_drop_index($1)", index_id)


async def reset_hypothetical_indexes(conn: asyncpg.Connection) -> None:
    await conn.execute("SELECT hypopg_reset()")


async def _index_oid(conn: asyncpg.Connection, name: str) -> int:
    return int(await conn.fetchval("SELECT to_regclass($1)::oid", name) or 0)


async def validate_index(
    conn: asyncpg.Connection,
    sql_query: str,
    create_sql: str,
    timeout_ms: int,
    runs: int = 1,
) -> ValidationResult:
    """Build the candidate index for real, measure it, and always drop it.

    ``runs`` applies the median-of-5 rule to both sides: the baseline and the
    indexed measurement are steady-state medians, so a cache-cold first
    execution cannot flatter or spoil the reported speedup. ``runs=1`` keeps the
    single-shot behaviour for callers that cannot afford the extra samples.
    """
    baseline = await explain_steady_state(conn, sql_query, timeout_ms, runs)
    name = _shadow_index_name()
    # Drop first in case a previous process died mid-validation under this name.
    await drop_shadow_index(conn, name)
    try:
        await conn.execute(shadow_index_sql(create_sql, name))
        after = await explain_steady_state(conn, sql_query, timeout_ms, runs)
        oid = await _index_oid(conn, name)
    finally:
        await drop_shadow_index(conn, name)
    return ValidationResult(
        shadow_index_oid=oid,
        index_name=name,
        baseline_execution_time_ms=baseline.result.execution_time_ms,
        execution_time_ms=after.result.execution_time_ms,
        total_cost=after.result.total_cost,
        plan=after.result.plan,
    )


async def apply_index(
    settings: Settings, sql_query: str, create_sql: str
) -> tuple[asyncpg.Connection, str, ExplainResult]:
    """Keep a real shadow index alive so /revert can drop it later.

    Only the shadow database ever receives DDL; the target remains read-only and
    the user still reviews ``CREATE INDEX CONCURRENTLY`` before running it.
    """
    conn = await connect_shadow(settings)
    name = _shadow_index_name()
    try:
        await drop_shadow_index(conn, name)
        await conn.execute(shadow_index_sql(create_sql, name))
        result = await explain_analyze(conn, sql_query, settings.explain_timeout_ms)
    except Exception:
        await conn.close()
        raise
    return conn, name, result


__all__ = [
    "ShadowUnavailable",
    "ValidationResult",
    "apply_index",
    "connect_shadow",
    "create_hypothetical_index",
    "drop_hypothetical_index",
    "drop_shadow_index",
    "ensure_hypopg",
    "reset_hypothetical_indexes",
    "shadow_index_sql",
    "validate_index",
]
