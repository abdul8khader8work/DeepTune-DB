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
    #: VACUUM ANALYZE is attempted by default; a read-only target role simply
    #: fails the attempt and the run continues (see services/pipeline.py).
    target_allow_maintenance: bool = True
    shadow_validate: bool = True
    run_ttl_seconds: int = 1800

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
