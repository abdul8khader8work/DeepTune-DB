"""Liveness and capability probe. Public: no bearer token required."""

from fastapi import APIRouter, Request

from src.api.deps import get_state
from src.db.metadata import MemoryConnectionStore
from src.schemas.system import HealthResponse

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    state = get_state(request)
    return HealthResponse(
        status="ok",
        version=state.settings.app_version,
        environment=state.settings.app_env,
        auth_enabled=state.settings.auth_enabled,
        shadow_db_configured=bool(state.settings.shadow_dsn),
        metadata_store=(
            "memory"
            if isinstance(state.store, MemoryConnectionStore)
            else "postgres"
        ),
    )
