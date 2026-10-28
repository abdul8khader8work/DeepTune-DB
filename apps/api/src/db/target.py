"""Read-only Target DB connections."""

import asyncio
from dataclasses import dataclass

import asyncpg

from src.core.config import Settings
from src.core.errors import gateway_timeout, unauthorized
from src.schemas.connections import SSLMode


@dataclass(frozen=True)
class StoredConnection:
    dsn: str
    ssl_mode: SSLMode = "prefer"


def _ssl_argument(mode: SSLMode) -> bool | None:
    if mode == "disable":
        return False
    if mode == "require":
        return True
    # "prefer" and "allow" both let asyncpg negotiate.
    return None


async def connect_target(connection: StoredConnection, settings: Settings) -> asyncpg.Connection:
    try:
        return await asyncpg.connect(
            dsn=connection.dsn,
            timeout=settings.target_connect_timeout_s,
            command_timeout=settings.explain_timeout_ms / 1000 + 5,
            ssl=_ssl_argument(connection.ssl_mode),
            server_settings={"application_name": "deeptune-optimizer"},
        )
    except (
        asyncpg.InvalidPasswordError,
        asyncpg.InvalidAuthorizationSpecificationError,
    ) as exc:
        raise unauthorized("Target database rejected the credentials.") from exc
    except (OSError, asyncio.TimeoutError, asyncpg.CannotConnectNowError) as exc:
        raise gateway_timeout(
            f"Could not reach the target database within "
            f"{settings.target_connect_timeout_s:.0f}s."
        ) from exc
    except asyncpg.PostgresError as exc:
        raise gateway_timeout(
            f"Target database connection failed: {exc.__class__.__name__}"
        ) from exc
