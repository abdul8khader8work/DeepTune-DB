"""Shadow DB helpers: hypothetical indexes via the hypopg extension."""

import asyncio
from dataclasses import dataclass

import asyncpg

from src.core.config import Settings
from src.services.explain import ExplainResult, explain_analyze, explain_steady_state


class ShadowUnavailable(RuntimeError):
    """Raised when the shadow database or hypopg is not usable."""


@dataclass(frozen=True)
class ValidationResult:
    hypopg_index_id: int
    index_name: str
    baseline_execution_time_ms: float
    execution_time_ms: float
    total_cost: float
    plan: dict


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
            f"Shadow database connection failed: {exc.__class__.__name__}"
        ) from exc

    try:
        installed = await conn.fetchval(
            "SELECT 1 FROM pg_extension WHERE extname = 'hypopg'"
        )
    except asyncpg.PostgresError as exc:
        await conn.close()
        raise ShadowUnavailable("Could not inspect shadow extensions") from exc

    if not installed:
        await conn.close()
        raise ShadowUnavailable("The hypopg extension is not installed")
    return conn


async def create_hypothetical_index(conn: asyncpg.Connection, create_sql: str) -> tuple[int, str]:
    row = await conn.fetchrow("SELECT * FROM hypopg_create_index($1)", create_sql)
    if row is None:
        raise ShadowUnavailable("hypopg_create_index returned no row")
    return int(row["indexrelid"]), str(row["indexname"])


async def drop_hypothetical_index(conn: asyncpg.Connection, index_id: int) -> None:
    await conn.execute("SELECT hypopg_drop_index($1)", index_id)


async def reset_hypothetical_indexes(conn: asyncpg.Connection) -> None:
    await conn.execute("SELECT hypopg_reset()")


async def validate_index(
    conn: asyncpg.Connection,
    sql_query: str,
    create_sql: str,
    timeout_ms: int,
    runs: int = 1,
) -> ValidationResult:
    """Create a hypothetical index, re-EXPLAIN, and always drop it.

    ``runs`` applies the median-of-5 rule to both sides of the comparison: with
    ``runs > 1`` the baseline and the indexed measurement are steady-state
    medians, so a cache-cold first execution cannot flatter or spoil the
    reported speedup. ``runs=1`` keeps the original single-shot behaviour.
    """
    baseline = await explain_steady_state(conn, sql_query, timeout_ms, runs)
    index_id, index_name = await create_hypothetical_index(conn, create_sql)
    try:
        after = await explain_steady_state(conn, sql_query, timeout_ms, runs)
    finally:
        await drop_hypothetical_index(conn, index_id)
    return ValidationResult(
        hypopg_index_id=index_id,
        index_name=index_name,
        baseline_execution_time_ms=baseline.result.execution_time_ms,
        execution_time_ms=after.result.execution_time_ms,
        total_cost=after.result.total_cost,
        plan=after.result.plan,
    )


async def apply_index(
    settings: Settings, sql_query: str, create_sql: str
) -> tuple[asyncpg.Connection, int, ExplainResult]:
    """Keep the shadow session open so /revert can drop the index later."""
    conn = await connect_shadow(settings)
    try:
        index_id, _ = await create_hypothetical_index(conn, create_sql)
        result = await explain_analyze(conn, sql_query, settings.explain_timeout_ms)
    except Exception:
        await conn.close()
        raise
    return conn, index_id, result
