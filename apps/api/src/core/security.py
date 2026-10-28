"""Credential encryption, JWT handling, and log-safe masking."""

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit, urlunsplit

import jwt
from cryptography.fernet import Fernet, InvalidToken

from src.core.config import Settings
from src.core.errors import unauthorized


def _fernet(settings: Settings) -> Fernet:
    """Derive a stable 32-byte Fernet key from the configured secret."""
    digest = hashlib.sha256(settings.encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, settings: Settings) -> str:
    try:
        return _fernet(settings).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("Stored credential could not be decrypted") from exc


def create_access_token(subject: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
        )
    except jwt.PyJWTError as exc:
        raise unauthorized("Bearer token is invalid or expired.") from exc
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise unauthorized("Bearer token has no subject.")
    return subject


def build_dsn(
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
) -> str:
    """Build a DSN with correctly escaped credentials."""
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(dbname, safe='')}"
    )


def mask_dsn(dsn: str) -> str:
    """Return a DSN safe to print in logs."""
    try:
        parts = urlsplit(dsn)
    except ValueError:
        return "<unparseable-dsn>"
    if not parts.password:
        return dsn
    netloc = f"{parts.username}:***@{parts.hostname}"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
