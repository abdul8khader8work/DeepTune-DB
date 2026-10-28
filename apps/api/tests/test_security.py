"""Credential encryption, JWT handling, and DSN helpers."""

import pytest
from pydantic import SecretStr

from src.core.config import Settings
from src.core.errors import ApiError
from src.core.security import (
    build_dsn,
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    mask_dsn,
)


def test_encrypt_roundtrip(settings: Settings) -> None:
    token = encrypt_secret("postgresql://u:p@localhost/db", settings)
    assert "postgresql://" not in token
    assert decrypt_secret(token, settings) == "postgresql://u:p@localhost/db"


def test_decrypt_with_wrong_key_fails(settings: Settings) -> None:
    token = encrypt_secret("secret", settings)
    other = settings.model_copy(
        update={"credential_encryption_key": SecretStr("a-different-key")}
    )
    with pytest.raises(ValueError):
        decrypt_secret(token, other)


def test_jwt_roundtrip(settings: Settings) -> None:
    token = create_access_token("alice", settings)
    assert decode_access_token(token, settings) == "alice"


def test_jwt_wrong_secret_rejected(settings: Settings) -> None:
    token = create_access_token("alice", settings)
    other = settings.model_copy(
        update={"jwt_secret": SecretStr("wrong-secret-that-is-long-enough-for-hs256")}
    )
    with pytest.raises(ApiError) as excinfo:
        decode_access_token(token, other)
    assert excinfo.value.status_code == 401


def test_mask_dsn_hides_password() -> None:
    masked = mask_dsn("postgresql://alice:hunter2@db.local:5432/app")
    assert masked == "postgresql://alice:***@db.local:5432/app"
    assert "hunter2" not in masked


def test_build_dsn_escapes_credentials() -> None:
    dsn = build_dsn(
        host="localhost",
        port=5432,
        dbname="app db",
        user="user@corp",
        password="p@ss:word/with space",
    )
    assert "p%40ss%3Aword%2Fwith%20space" in dsn
    assert "user%40corp" in dsn
    assert "p@ss" not in dsn
