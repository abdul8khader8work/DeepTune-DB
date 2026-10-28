"""Health, delete, and legacy compatibility contracts."""

from pydantic import Field

from src.schemas.connections import StrictModel


class HealthResponse(StrictModel):
    status: str
    version: str
    environment: str
    auth_enabled: bool
    shadow_db_configured: bool
    metadata_store: str


class DeleteResponse(StrictModel):
    status: str
    connection_id: str


class LegacyApplyRequest(StrictModel):
    recommendation_id: str = Field(min_length=1)


class EngineStatusResponse(StrictModel):
    """What the lifespan actually loaded. Public: no bearer token required."""

    enabled: bool
    available: bool
    backend: str
    label: str
    device: str
    checkpoint: str | None = None
    model_version: str | None = None
    parameters: int | None = None
    hidden_dim: int | None = None
    layers: int | None = None
    heads: int | None = None
    error: str | None = None
