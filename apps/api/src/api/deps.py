"""Shared FastAPI dependencies and application state."""

from dataclasses import dataclass

from fastapi import Header, Request

from src.core.config import Settings
from src.core.errors import unauthorized
from src.core.security import decode_access_token
from src.db.metadata import ConnectionStore
from src.services.runs import AppliedRegistry, RunRegistry


@dataclass
class AppState:
    """Long-lived objects created once in the lifespan hook."""

    settings: Settings
    store: ConnectionStore
    runs: RunRegistry
    applied: AppliedRegistry


def get_state(request: Request) -> AppState:
    state = getattr(request.app.state, "deeptune", None)
    if not isinstance(state, AppState):  # pragma: no cover - lifespan guard
        raise RuntimeError("Application state is not initialised")
    return state


async def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    """Verify the HS256 bearer token unless auth is disabled for local dev."""
    settings = get_state(request).settings
    if not settings.auth_enabled:
        return "auth-disabled"
    if not authorization:
        raise unauthorized()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    return decode_access_token(token.strip(), settings)
