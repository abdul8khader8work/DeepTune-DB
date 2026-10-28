"""Test bootstrap: environment is set before the app and settings are imported."""

import os

os.environ.update(
    {
        "APP_ENV": "test",
        "APP_VERSION": "0.2.0",
        "AUTH_ENABLED": "true",
        "JWT_SECRET": "pytest-jwt-secret-not-for-production",
        "JWT_AUDIENCE": "deeptune-web",
        "CREDENTIAL_ENCRYPTION_KEY": "pytest-encryption-key-not-for-production",
        "METADATA_DB_DSN": "",
        "SHADOW_DB_DSN": "",
        "ANALYZE_RATE_LIMIT": "1000/minute",
        "CORS_ORIGINS": "http://localhost:3000",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.core.config import Settings, get_settings  # noqa: E402
from src.core.security import create_access_token  # noqa: E402
from src.main import app  # noqa: E402


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def auth_headers(settings: Settings) -> dict[str, str]:
    token = create_access_token("pytest", settings)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
