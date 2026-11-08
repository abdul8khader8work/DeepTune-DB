"""Patch 2 Task 2: ephemeral superuser ANALYZE, and nothing that can abort a run."""

from __future__ import annotations

import pytest

from src.services import maintenance


class FakeConnection:
    """Minimal asyncpg connection: records SQL and supports ``close``.

    Deliberately not a context manager: ``asyncpg.Connection`` is not one either,
    and an earlier version of the service relied on that by mistake.
    """

    def __init__(self, error: Exception | None = None) -> None:
        self.sql: list[str] = []
        self.error = error
        self.closed = False

    async def execute(self, sql: str) -> None:
        self.sql.append(sql)
        if self.error is not None:
            raise self.error

    async def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


def test_build_superuser_dsn_swaps_only_the_credentials() -> None:
    dsn = maintenance.build_superuser_dsn(
        "postgresql://query_optimizer:ro@db.internal:5433/shop?sslmode=require",
        "s3cret/p@ss",
        "postgres",
    )
    assert dsn.startswith("postgresql://postgres:s3cret%2Fp%40ss@db.internal:5433/shop")
    assert "sslmode=require" in dsn
    assert "query_optimizer" not in dsn


async def test_missing_credentials_skip_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_connect(**kwargs: object) -> None:
        raise AssertionError("must not connect without a credential")

    monkeypatch.setattr(maintenance.asyncpg, "connect", fail_connect)

    result = await maintenance.refresh_table_statistics(
        "postgresql://query_optimizer:ro@localhost:5432/shop", ""
    )

    assert result.applied is False
    assert result.skipped is True
    assert "not configured" in (result.error or "")


async def test_analyze_runs_once_on_an_ephemeral_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    connection = FakeConnection()

    async def fake_connect(**kwargs: object) -> FakeConnection:
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(maintenance.asyncpg, "connect", fake_connect)

    result = await maintenance.refresh_table_statistics(
        "postgresql://query_optimizer:ro@localhost:5432/shop",
        "owner-secret",
        timeout_ms=7000,
    )

    assert result.applied is True
    assert connection.sql == [maintenance.MAINTENANCE_SQL]
    assert connection.closed is True
    # The DSN handed to asyncpg is the owner, never the read-only role.
    assert str(captured["dsn"]).startswith("postgresql://postgres:owner-secret@")
    server_settings = captured["server_settings"]
    assert isinstance(server_settings, dict)
    assert server_settings["statement_timeout"] == "7000"
    # No transaction block: VACUUM refuses to run inside one.
    assert connection.sql[0].startswith("VACUUM (ANALYZE, SKIP_LOCKED)")


async def test_database_error_is_returned_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection(error=RuntimeError("must be superuser"))

    async def fake_connect(**kwargs: object) -> FakeConnection:
        return connection

    monkeypatch.setattr(maintenance.asyncpg, "connect", fake_connect)

    result = await maintenance.refresh_table_statistics(
        "postgresql://query_optimizer:ro@localhost:5432/shop", "wrong"
    )

    assert result.applied is False
    assert result.skipped is False
    assert "must be superuser" in (result.error or "")
    assert connection.closed is True


async def test_override_dsn_wins_over_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    connection = FakeConnection()

    async def fake_connect(**kwargs: object) -> FakeConnection:
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(maintenance.asyncpg, "connect", fake_connect)

    await maintenance.refresh_table_statistics(
        "postgresql://query_optimizer:ro@localhost:5432/shop",
        "ignored-password",
        override_dsn="postgresql://admin:full@localhost:5432/shop",
    )

    assert captured["dsn"] == "postgresql://admin:full@localhost:5432/shop"
