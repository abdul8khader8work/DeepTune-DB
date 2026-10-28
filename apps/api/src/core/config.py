from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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
    max_sql_length: int = 10000
    analyze_rate_limit: str = "10/minute"
    target_allow_maintenance: bool = False
    shadow_validate: bool = True
    run_ttl_seconds: int = 1800

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
