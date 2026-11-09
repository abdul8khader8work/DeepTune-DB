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
    #: Patch File Final: true when DEMO_MODE is active (auth bypassed,
    # # auto-connect, no connection modal).
    demo_mode: bool = False
    #: Connection id of the auto-connected demo database (demo mode only).
    demo_connection_id: str | None = None
    #: Patch 3: copilot + optimize peers currently registered. Must return to 0
    #: within one server heartbeat (30s + 10s timeout) after every tab closes.
    ws_active_connections: int = 0


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
    runtime: str = "torch"
    checkpoint: str | None = None
    model_version: str | None = None
    parameters: int | None = None
    hidden_dim: int | None = None
    layers: int | None = None
    heads: int | None = None
    error: str | None = None
