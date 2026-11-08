"""Patch 3, Task 5: optimization progress streams over WebSocket, never polling."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.core.config import Settings
from src.core.security import create_access_token
from src.schemas.analysis import AnalysisResult
from src.services.runs import Run, RunRegistry
from src.services.ws_registry import optimize_registry

RESULT = AnalysisResult(
    run_id="optimize-test",
    status="completed",
    engine="heuristic",
    original_metrics={"cost": 100.0, "time_ms": 10.0},
    optimized_metrics={"cost": 50.0, "time_ms": 5.0},
    original_dag=[],
    optimized_dag=[],
    edges=[],
    recommendations=[],
)


def _seed(client: TestClient, run_id: str, status: str = "completed") -> None:
    app: Any = client.app
    app.state.deeptune.runs._runs[run_id] = Run(  # noqa: SLF001 - test seam
        run_id=run_id,
        connection_id="conn-1",
        status=status,  # type: ignore[arg-type]
        progress=100 if status == "completed" else 30,
        log="Analysis complete." if status == "completed" else "Capturing the baseline…",
        result=RESULT.model_copy(update={"run_id": run_id})
        if status == "completed"
        else None,
        error="boom" if status == "failed" else None,
    )


def test_missing_token_is_rejected(client: TestClient) -> None:
    _seed(client, "optimize-test")
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/v1/ws/optimize/optimize-test"):
            pass
    assert excinfo.value.code == 4401


def test_unknown_run_is_rejected(client: TestClient, settings: Settings) -> None:
    token = create_access_token("pytest", settings)
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect(
            f"/api/v1/ws/optimize/does-not-exist?token={token}"
        ):
            pass
    assert excinfo.value.code == 4404


def test_completed_run_streams_a_snapshot_then_complete(
    client: TestClient, settings: Settings
) -> None:
    token = create_access_token("pytest", settings)
    _seed(client, "optimize-test")

    frames: list[dict] = []
    with client.websocket_connect(
        f"/api/v1/ws/optimize/optimize-test?token={token}"
    ) as socket:
        while True:
            frame = socket.receive_json()
            frames.append(frame)
            if frame["type"] == "complete":
                break

    types = [frame["type"] for frame in frames]
    assert "progress" in types
    assert "log_update" in types
    assert frames[-1]["type"] == "complete"
    assert frames[-1]["payload"]["run_id"] == "optimize-test"
    assert all(frame.get("seq", 0) >= 0 for frame in frames)


def test_failed_run_streams_an_error_frame(
    client: TestClient, settings: Settings
) -> None:
    token = create_access_token("pytest", settings)
    _seed(client, "optimize-failed", status="failed")

    with client.websocket_connect(
        f"/api/v1/ws/optimize/optimize-failed?token={token}"
    ) as socket:
        frame = socket.receive_json()
        while frame["type"] != "error":
            frame = socket.receive_json()

    assert frame["payload"]["message"] == "boom"


async def test_registry_broadcasts_sequenced_pipeline_frames(settings: Settings) -> None:
    sent: list[tuple[str, dict]] = []

    async def capture(run_id: str, frame: dict) -> bool:
        sent.append((run_id, frame))
        return True

    registry = RunRegistry(settings, broadcaster=capture)
    run = await registry.create("conn-1")

    await registry.update(run.run_id, "parsing", 30, "Capturing the baseline…")
    await registry.update(run.run_id, "gnn_inference", 60, "Beam search…")
    await registry.complete(
        run.run_id, RESULT.model_copy(update={"run_id": run.run_id}), []
    )

    progress = [frame for _, frame in sent if frame["type"] == "progress"]
    assert [frame["payload"]["percentage"] for frame in progress] == [30, 60, 100]
    assert [frame["seq"] for frame in progress] == sorted(
        frame["seq"] for frame in progress
    )
    assert sent[-1][1]["type"] == "complete"
    assert sent[-1][1]["payload"]["run_id"] == run.run_id


async def test_registry_broadcasts_an_error_frame(settings: Settings) -> None:
    sent: list[dict] = []

    async def capture(_run_id: str, frame: dict) -> bool:
        sent.append(frame)
        return True

    registry = RunRegistry(settings, broadcaster=capture)
    run = await registry.create("conn-1")
    await registry.fail(run.run_id, "query rejected")

    assert sent[-1]["type"] == "error"
    assert sent[-1]["payload"]["message"] == "query rejected"


def test_optimize_registry_returns_to_baseline(
    client: TestClient, settings: Settings
) -> None:
    token = create_access_token("pytest", settings)
    _seed(client, "optimize-test")
    baseline = optimize_registry.active_count

    with client.websocket_connect(
        f"/api/v1/ws/optimize/optimize-test?token={token}"
    ) as socket:
        while socket.receive_json()["type"] != "complete":
            continue
        assert optimize_registry.active_count == baseline + 1

    for _ in range(100):
        if optimize_registry.active_count == baseline:
            break
        time.sleep(0.01)
    assert optimize_registry.active_count == baseline
