"""PostgreSQL access for the App Metadata DB (encrypted DSNs)."""

import asyncio
import logging
import uuid
from typing import Protocol

import asyncpg

from src.core.config import Settings
from src.core.security import decrypt_secret, encrypt_secret
from src.db.target import StoredConnection
from src.schemas.connections import SSLMode

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS target_databases (
    connection_id UUID PRIMARY KEY,
    encrypted_dsn TEXT NOT NULL,
    ssl_mode TEXT NOT NULL DEFAULT 'prefer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id UUID PRIMARY KEY,
    connection_id UUID NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class ConnectionStore(Protocol):
    async def save(
        self, connection_id: str, dsn: str, ssl_mode: SSLMode
    ) -> None: ...

    async def get(self, connection_id: str) -> StoredConnection | None: ...

    async def delete(self, connection_id: str) -> bool: ...

    async def close(self) -> None: ...


class MemoryConnectionStore:
    """Fallback used when the metadata DB is unavailable (local demos/tests)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._items: dict[str, tuple[str, SSLMode]] = {}
        self._lock = asyncio.Lock()

    async def save(self, connection_id: str, dsn: str, ssl_mode: SSLMode) -> None:
        async with self._lock:
            self._items[connection_id] = (
                encrypt_secret(dsn, self._settings),
                ssl_mode,
            )

    async def get(self, connection_id: str) -> StoredConnection | None:
        async with self._lock:
            item = self._items.get(connection_id)
        if item is None:
            return None
        token, ssl_mode = item
        return StoredConnection(dsn=decrypt_secret(token, self._settings), ssl_mode=ssl_mode)

    async def delete(self, connection_id: str) -> bool:
        async with self._lock:
            return self._items.pop(connection_id, None) is not None

    async def close(self) -> None:
        self._items.clear()


class PostgresConnectionStore:
    def __init__(self, pool: asyncpg.Pool, settings: Settings) -> None:
        self._pool = pool
        self._settings = settings

    @classmethod
    async def create(cls, dsn: str, settings: Settings) -> "PostgresConnectionStore":
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5, timeout=5)
        async with pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)
        return cls(pool, settings)

    async def save(self, connection_id: str, dsn: str, ssl_mode: SSLMode) -> None:
        await self._pool.execute(
            """
            INSERT INTO target_databases (connection_id, encrypted_dsn, ssl_mode)
            VALUES ($1, $2, $3)
            ON CONFLICT (connection_id) DO UPDATE
            SET encrypted_dsn = EXCLUDED.encrypted_dsn,
                ssl_mode = EXCLUDED.ssl_mode
            """,
            uuid.UUID(connection_id),
            encrypt_secret(dsn, self._settings),
            ssl_mode,
        )

    async def get(self, connection_id: str) -> StoredConnection | None:
        try:
            key = uuid.UUID(connection_id)
        except ValueError:
            return None
        row = await self._pool.fetchrow(
            "SELECT encrypted_dsn, ssl_mode FROM target_databases WHERE connection_id = $1",
            key,
        )
        if row is None:
            return None
        return StoredConnection(
            dsn=decrypt_secret(row["encrypted_dsn"], self._settings),
            ssl_mode=row["ssl_mode"],
        )

    async def delete(self, connection_id: str) -> bool:
        try:
            key = uuid.UUID(connection_id)
        except ValueError:
            return False
        result = await self._pool.execute(
            "DELETE FROM target_databases WHERE connection_id = $1", key
        )
        return result.endswith("1")

    async def close(self) -> None:
        await self._pool.close()


async def create_connection_store(settings: Settings) -> ConnectionStore:
    if not settings.metadata_dsn:
        logger.info("Metadata DSN not set; using in-memory connection store")
        return MemoryConnectionStore(settings)
    try:
        store = await PostgresConnectionStore.create(settings.metadata_dsn, settings)
        logger.info("Metadata connection store ready")
        return store
    except (OSError, asyncio.TimeoutError, asyncpg.PostgresError) as exc:
        logger.warning(
            "Metadata DB unavailable (%s); falling back to in-memory store",
            exc.__class__.__name__,
        )
        return MemoryConnectionStore(settings)
