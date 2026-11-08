"""Ephemeral superuser statistics maintenance (Patch 2 Task 2).

The read-only ``query_optimizer`` role cannot run ``ANALYZE`` or ``VACUUM``
because it does not own the tables. Stale ``pg_statistic`` makes both the
planner and ``hypopg`` price indexes wrongly, so before every optimization run
the API opens a short-lived superuser connection, refreshes statistics, and
closes it again. The restricted role is never granted elevated rights, and the
superuser connection is never held while user SQL runs.

Design notes
------------
* Raw ``asyncpg`` only (no ORM), per the constitution.
* ``VACUUM (ANALYZE, SKIP_LOCKED)`` rather than a bare ``VACUUM``: ``SKIP_LOCKED``
  prevents the maintenance pass from queueing behind an `AccessExclusiveLock`
  and stalling the UI's own queries.
* The timeout is applied through the connection's ``statement_timeout`` server
  setting. ``SET LOCAL`` cannot be used here: it requires a transaction block,
  and PostgreSQL refuses to run ``VACUUM`` inside one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

import asyncpg

logger = logging.getLogger(__name__)

#: Hardcoded on purpose: the constitution mandates an explicit ANALYZE before
#: the optimization phase rather than trusting whatever statistics exist.
MAINTENANCE_SQL = "VACUUM (ANALYZE, SKIP_LOCKED)"


@dataclass(frozen=True)
class MaintenanceResult:
    """Outcome of the pre-flight statistics refresh (never raises to callers)."""

    applied: bool
    statement: str = MAINTENANCE_SQL
    skipped: bool = False
    error: str | None = None


def build_superuser_dsn(target_dsn: str, password: str, user: str = "postgres") -> str:
    """Swap the read-only credentials in ``target_dsn`` for the superuser ones.

    Only the userinfo is replaced; host, port, database, and query parameters
    (``sslmode`` et al.) are carried over unchanged.
    """
    parts = urlsplit(target_dsn)
    if not parts.hostname:
        raise ValueError("The target DSN has no host")
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{parts.hostname}"
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(
        (parts.scheme or "postgresql", netloc, parts.path, parts.query, parts.fragment)
    )


async def refresh_table_statistics(
    target_dsn: str,
    superuser_password: str,
    *,
    override_dsn: str = "",
    superuser_user: str = "postgres",
    timeout_ms: int = 10_000,
    connect_timeout_s: float = 5.0,
) -> MaintenanceResult:
    """Refresh planner statistics through a one-shot superuser connection.

    Returns a :class:`MaintenanceResult` instead of raising: a wrong password or
    a locked table must never abort an optimization run. ``skipped=True`` means
    no superuser credential was configured; ``error`` carries the database
    message when the command itself failed.
    """
    dsn = override_dsn or ""
    if not dsn:
        if not superuser_password:
            return MaintenanceResult(
                applied=False,
                skipped=True,
                error="TARGET_SUPERUSER_DSN / TARGET_SUPERUSER_PASSWORD not configured",
            )
        dsn = build_superuser_dsn(target_dsn, superuser_password, superuser_user)

    connection: asyncpg.Connection | None = None
    try:
        connection = await asyncpg.connect(
            dsn=dsn,
            timeout=connect_timeout_s,
            server_settings={
                "application_name": "deeptune-maintenance",
                "statement_timeout": str(max(1, int(timeout_ms))),
            },
        )
        await connection.execute(MAINTENANCE_SQL)
    except Exception as exc:  # noqa: BLE001 - maintenance is strictly best-effort
        logger.warning(
            "Statistics refresh failed (%s); proceeding with potentially stale statistics",
            exc.__class__.__name__,
        )
        return MaintenanceResult(
            applied=False,
            error=f"{exc.__class__.__name__}: {exc}",
        )
    finally:
        # Ephemeral by construction: the owner session is closed even if
        # VACUUM fails, and it is never held while user SQL runs.
        if connection is not None and not connection.is_closed():
            await connection.close()

    logger.info("Statistics refreshed as %s via an ephemeral connection", superuser_user)
    return MaintenanceResult(applied=True)


__all__ = [
    "MAINTENANCE_SQL",
    "MaintenanceResult",
    "build_superuser_dsn",
    "refresh_table_statistics",
]
