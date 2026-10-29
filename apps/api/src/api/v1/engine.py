"""Engine capability probe. Public: the web shell needs it before login."""

from fastapi import APIRouter, Request

from src.api.deps import get_engine
from src.schemas.system import EngineStatusResponse

router = APIRouter(tags=["system"])


@router.get("/engine/status", response_model=EngineStatusResponse)
async def engine_status(request: Request) -> EngineStatusResponse:
    status = get_engine(request).status
    return EngineStatusResponse(
        enabled=status.enabled,
        available=status.available,
        backend=status.backend,
        label=status.label,
        device=status.device,
        runtime=status.runtime,
        checkpoint=status.checkpoint,
        model_version=status.model_version,
        parameters=status.parameters,
        hidden_dim=status.hidden_dim,
        layers=status.layers,
        heads=status.heads,
        error=status.error,
    )
