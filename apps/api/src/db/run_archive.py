"""Durable archive for analysis runs (the ``analysis_runs`` table).

Runs live in memory for the life of the process; this archive makes them
survivable and queryable. It is optional: with no ``METADATA_DB_DSN`` the API
uses :class:`NullRunArchive` and behaves exactly as it did in Phase 2.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

import asyncpg

from src.schemas.analysis import AnalysisResult

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id UUID PRIMARY KEY,
    connection_id UUID NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS engine TEXT;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS error TEXT;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS result JSONB;
ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
"""


@dataclass(frozen=True)
class RunSnapshot:
    run_id: str
    connection_id: str
    status: str
    progress: int
    engine: str | None = None
    error: str | None = None
    result: AnalysisResult | None = None


class RunArchive(Protocol):
    async def record(self, snapshot: RunSnapshot) -> None: ...

    async def close(self) -> None: ...


class NullRunArchive:
    """No-op archive used when the metadata DB is not configured."""

    async def record(self, snapshot: RunSnapshot) -> None:
        return None

    async def close(self) -> None:
        return None


class PostgresRunArchive:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._lock = asyncio.Lock()

    @classmethod
    async def create(cls, dsn: str) -> "PostgresRunArchive":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, timeout=5)
        async with pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)
        return cls(pool)

    async def record(self, snapshot: RunSnapshot) -> None:
        try:
            key = uuid.UUID(snapshot.run_id)
            connection_key = uuid.UUID(snapshot.connection_id)
        except ValueError:
            logger.warning("Skipping archive for non-UUID run %s", snapshot.run_id)
            return

        payload = snapshot.result.model_dump_json() if snapshot.result else None
        async with self._lock:
            await self._pool.execute(
                """
                INSERT INTO analysis_runs
                    (run_id, connection_id, status, progress, engine, error, result)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                ON CONFLICT (run_id) DO UPDATE
                SET status = EXCLUDED.status,
                    progress = EXCLUDED.progress,
                    engine = EXCLUDED.engine,
                    error = EXCLUDED.error,
                    result = EXCLUDED.result,
                    updated_at = now()
                """,
                key,
                connection_key,
                snapshot.status,
                snapshot.progress,
                snapshot.engine,
                snapshot.error,
                payload,
            )

    async def close(self) -> None:
        await self._pool.close()


async def create_run_archive(dsn: str) -> RunArchive:
    """Build the Postgres archive, or degrade to the no-op one."""
    if not dsn:
        return NullRunArchive()
    try:
        archive = await PostgresRunArchive.create(dsn)
    except (OSError, asyncio.TimeoutError, asyncpg.PostgresError) as exc:
        logger.warning(
            "Run archive unavailable (%s); analysis runs stay in memory",
            exc.__class__.__name__,
        )
        return NullRunArchive()
    logger.info("Analysis run archive ready")
    return archive
