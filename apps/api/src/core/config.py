from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value can be supplied as an env var."""

    model_config = SettingsConfigDict(
        env_file=(".env", "apps/api/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "DeepTune API"
    app_version: str = "0.2.0"
    app_env: Literal["dev", "test", "prod"] = "dev"
    api_v1_prefix: str = "/api/v1"

    cors_origins: str = "http://localhost:3000"

    auth_enabled: bool = True
    jwt_secret: SecretStr = SecretStr("dev-only-deeptune-jwt-secret-change-me")
    jwt_algorithm: str = "HS256"
    jwt_audience: str = "deeptune-web"
    jwt_ttl_minutes: int = 720

    credential_encryption_key: SecretStr = SecretStr(
        "dev-only-deeptune-encryption-key-change-me"
    )

    metadata_db_dsn: SecretStr = SecretStr("")
    shadow_db_dsn: SecretStr = SecretStr("")

    target_connect_timeout_s: float = 5.0
    explain_timeout_ms: int = 5000
    #: Patch 2 steady-state rule: run EXPLAIN this many times and keep the
    #: median, dropping the fastest and slowest samples (5 -> median of 3).
    explain_measurement_runs: int = Field(default=5, ge=1, le=15)
    max_sql_length: int = 10000
    analyze_rate_limit: str = "10/minute"
    #: Pre-flight ANALYZE switch. When enabled the API opens an ephemeral
    #: superuser connection (never the read-only role) and closes it again.
    target_allow_maintenance: bool = True
    #: Full DSN for the maintenance connection; wins over the password fields.
    target_superuser_dsn: SecretStr = SecretStr("")
    #: Password used to rebuild the target DSN with ``target_superuser_user``.
    target_superuser_password: SecretStr = SecretStr("")
    target_superuser_user: str = "postgres"
    #: ANALYZE must never hang the request path.
    maintenance_timeout_ms: int = Field(default=10_000, ge=500, le=60_000)
    shadow_validate: bool = True
    #: How many candidate configurations may be planned through hypopg per run.
    #: Depth-1 (single-index) plans are fetched first; the rest fall back to the
    #: offline plan builder instead of multiplying shadow-database round trips.
    hypopg_prefetch_limit: int = Field(default=48, ge=0, le=500)
    run_ttl_seconds: int = 1800

    # --- Patch 3: in-memory cache (no Redis, no external service) ------------
    cache_maxsize: int = Field(default=256, ge=1, le=100_000)
    cache_ttl_seconds: int = Field(default=300, ge=0, le=86_400)

    # --- Phase 4: neuro-symbolic engine wiring ------------------------------
    ml_enabled: bool = True
    # Empty means "resolve from the repository layout" (see services/engine.py).
    ml_engine_src: str = ""
    ml_checkpoint_path: str = ""
    ml_device: str = "cpu"
    ml_attention_nodes: int = 10
    copilot_stream_delay_ms: int = 20
    #: Pause before each tool call so the copilot reads as an agent, not a script.
    copilot_thinking_delay_ms: int = 500

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def encryption_key(self) -> str:
        return self.credential_encryption_key.get_secret_value()

    @property
    def metadata_dsn(self) -> str:
        return self.metadata_db_dsn.get_secret_value()

    @property
    def shadow_dsn(self) -> str:
        return self.shadow_db_dsn.get_secret_value()

    @property
    def superuser_dsn(self) -> str:
        return self.target_superuser_dsn.get_secret_value()

    @property
    def superuser_password(self) -> str:
        return self.target_superuser_password.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
