"""Realtime optimization progress over WebSocket (Patch 3, Task 5).

The HTTP surface still accepts the analysis (``POST /queries/analyze``) and
returns the run id, but progress is streamed here rather than polled:

``server -> client``  ``{"type": "progress", "seq": 3, "payload": {...}}``
``server -> client``  ``{"type": "log_update", "seq": 3, "payload": {...}}``
``server -> client``  ``{"type": "complete", "seq": 9, "payload": <AnalysisResult>}``
``server -> client``  ``{"type": "error", "seq": 9, "payload": {...}}``
``server -> client``  ``{"type": "ping"}`` every 30 s

``seq`` is monotonic per run. A client that connects mid-run receives a
snapshot, and the sequence number lets it discard a stale snapshot that raced a
live broadcast. The endpoint is registry-backed, so a browser that closes
mid-optimization cannot leave a zombie sender behind.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.v1.sockets import (
    WS_INTERNAL_ERROR,
    WS_NOT_FOUND,
    WS_UNAUTHORIZED,
    socket_authorised,
    socket_state,
)
from src.services.ws_registry import optimize_registry

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 30.0

router = APIRouter(tags=["queries"])


async def _heartbeat(run_id: str) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        if not await optimize_registry.broadcast(run_id, {"type": "ping"}):
            return


@router.websocket("/ws/optimize/{run_id}")
async def optimize_stream(websocket: WebSocket, run_id: str) -> None:
    state = socket_state(websocket)
    if state is None:  # pragma: no cover - lifespan guard
        await websocket.close(code=WS_INTERNAL_ERROR)
        return
    if not socket_authorised(websocket, state):
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    run = await state.runs.get(run_id)
    if run is None:
        await websocket.close(code=WS_NOT_FOUND)
        return

    await websocket.accept()
    connection = await optimize_registry.register(run_id, websocket)
    heartbeat = asyncio.create_task(_heartbeat(run_id))

    try:
        for frame in state.runs.snapshot_frames(run):
            await optimize_registry.broadcast(run_id, frame)
        while True:
            client_frame = await websocket.receive_json()
            await optimize_registry.touch(run_id)
            if isinstance(client_frame, dict) and client_frame.get("type") == "close":
                break
    except WebSocketDisconnect:
        logger.info("Client disconnected from optimize stream %s", run_id)
    except Exception:
        logger.exception("Optimize stream failed for run %s", run_id)
        try:
            await websocket.close(code=WS_INTERNAL_ERROR)
        except Exception:
            logger.debug("Optimize socket already closed for run %s", run_id)
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Heartbeat task ended for run %s", run_id)
        await optimize_registry.unregister(run_id, connection.websocket)
