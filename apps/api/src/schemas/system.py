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
