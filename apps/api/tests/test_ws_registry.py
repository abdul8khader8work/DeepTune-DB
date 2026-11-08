"""Patch 3, Task 1: the WebSocket registry must never leak a peer."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient

from src.core.config import Settings
from src.core.security import create_access_token
from src.schemas.analysis import AnalysisResult
from src.services.runs import Run
from src.services.ws_registry import (
    REPLACED,
    WebSocketRegistry,
    active_connection_total,
    copilot_registry,
    registry,
)

RESULT = AnalysisResult(
    run_id="ws-test",
    status="completed",
    engine="heuristic",
    original_metrics={"cost": 1.0, "time_ms": 1.0},
    optimized_metrics={"cost": 1.0, "time_ms": 1.0},
    original_dag=[],
    optimized_dag=[],
    edges=[],
    recommendations=[],
)


class FakeSocket:
    """Stands in for ``starlette.websockets.WebSocket`` in registry unit tests."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict] = []
        self.closed: list[tuple[int, str]] = []

    async def send_json(self, message: dict) -> None:
        if self.fail:
            raise RuntimeError("peer already closed")
        self.sent.append(message)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed.append((code, reason))


def _seed_run(client: TestClient, run_id: str) -> None:
    app: Any = client.app
    app.state.deeptune.runs._runs[run_id] = Run(  # noqa: SLF001 - test seam
        run_id=run_id,
        connection_id="conn-1",
        status="completed",
        progress=100,
        log="Analysis complete.",
        result=RESULT.model_copy(update={"run_id": run_id}),
    )


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


async def test_broadcast_to_dead_connection_returns_false() -> None:
    """Broadcasting to a run_id with no peer must return False, never raise."""
    assert await registry.broadcast("nonexistent-run-id", {"type": "test"}) is False


async def test_duplicate_run_id_replaces_old_connection() -> None:
    """Registering the same run_id twice closes the first peer and keeps one entry."""
    local = WebSocketRegistry()
    first = FakeSocket()
    second = FakeSocket()

    await local.register("dup", first)  # type: ignore[arg-type]
    await local.register("dup", second)  # type: ignore[arg-type]

    assert local.active_count == 1
    assert first.closed == [(REPLACED, "replaced")]
    assert await local.broadcast("dup", {"type": "progress"}) is True
    assert second.sent == [{"type": "progress"}]

    # A replaced peer's late cleanup must not evict its replacement.
    await local.unregister("dup", first)  # type: ignore[arg-type]
    assert local.active_count == 1
    await local.unregister("dup", second)  # type: ignore[arg-type]
    assert local.active_count == 0


async def test_broadcast_unregisters_a_failing_peer() -> None:
    local = WebSocketRegistry()
    await local.register("dead", FakeSocket(fail=True))  # type: ignore[arg-type]

    assert await local.broadcast("dead", {"type": "ping"}) is False
    assert local.active_count == 0


def test_rapid_connect_disconnect_no_leak(
    client: TestClient, settings: Settings
) -> None:
    """10 rapid connect/disconnect cycles must leave the registry at baseline."""
    token = create_access_token("pytest", settings)
    baseline = copilot_registry.active_count

    for index in range(10):
        run_id = f"stress-test-{index}"
        _seed_run(client, run_id)
        with client.websocket_connect(
            f"/api/v1/ws/copilot/{run_id}?token={token}"
        ) as socket:
            assert socket.receive_json()["type"] == "ready"
        # Abrupt close: the handler's finally block must drop the peer.
        assert _wait_for(lambda: copilot_registry.active_count == baseline), (
            f"cycle {index} leaked a peer"
        )

    assert copilot_registry.active_count == baseline


def test_live_socket_registers_and_unregisters(
    client: TestClient, settings: Settings
) -> None:
    token = create_access_token("pytest", settings)
    _seed_run(client, "live-test")
    baseline = copilot_registry.active_count

    with client.websocket_connect(
        f"/api/v1/ws/copilot/live-test?token={token}"
    ) as socket:
        assert socket.receive_json()["type"] == "ready"
        assert copilot_registry.active_count == baseline + 1

    assert _wait_for(lambda: copilot_registry.active_count == baseline)


def test_health_reports_active_connection_count(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["ws_active_connections"] == active_connection_total()
