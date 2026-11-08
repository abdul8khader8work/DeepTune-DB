"""Streaming copilot WebSocket.

Protocol (all frames are JSON objects):

``client -> server``  ``{"type": "question", "text": "why the join?"}``
``server -> client``  ``{"type": "ready", "engine": "gnn"}``
``server -> client``  ``{"type": "thinking"}``
``server -> client``  ``{"type": "tool", "tool": "read_plan", "args": "...", "result": "...", "status": "done"}``
``server -> client``  ``{"type": "token", "text": "The "}``
``server -> client``  ``{"type": "done", "run_id": "..."}``

A ``thinking`` frame always precedes a ``tool`` frame by a short pause; the
client clears its indicator as soon as any other frame arrives.

Auth uses the same HS256 token as the REST surface, passed as a query
parameter because browsers cannot set headers on a WebSocket handshake.

Patch 3: every accepted socket is registered in ``copilot_registry`` and the
registration is removed in a ``finally`` block, so a crashed handler or an
abrupt tab close can never leave a zombie peer behind.
"""

import asyncio
import logging
from collections.abc import Sequence

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.v1.sockets import (
    WS_INTERNAL_ERROR,
    WS_NOT_FOUND,
    WS_UNAUTHORIZED,
    socket_authorised,
    socket_state,
)
from src.services import copilot as explainer
from src.services.ws_registry import copilot_registry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["copilot"])


async def _emit(
    websocket: WebSocket,
    sentences: Sequence[str],
    calls: Sequence[dict[str, str]],
    delay_ms: int,
    thinking_delay_ms: int,
) -> None:
    """Think, send tool-call chips, then stream the prose that they justify.

    Each tool call is preceded by a ``thinking`` frame and a pause, which is what
    makes the deterministic template read like an agent deciding what to look at
    next. The UI clears the indicator on the next frame of any other type.
    """
    thinking = max(0, thinking_delay_ms) / 1000
    for call in calls:
        await websocket.send_json({"type": "thinking"})
        if thinking:
            await asyncio.sleep(thinking)
        await websocket.send_json({"type": "tool", **call})
    async for token in explainer.stream(sentences, delay_ms):
        await websocket.send_json({"type": "token", "text": token})


@router.websocket("/ws/copilot/{run_id}")
async def copilot_socket(websocket: WebSocket, run_id: str) -> None:
    state = socket_state(websocket)
    if state is None:  # pragma: no cover - lifespan guard
        await websocket.close(code=WS_INTERNAL_ERROR)
        return

    if not socket_authorised(websocket, state):
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    run = await state.runs.get(run_id)
    if run is None or run.result is None:
        await websocket.close(code=WS_NOT_FOUND)
        return

    await websocket.accept()
    connection = await copilot_registry.register(run_id, websocket)
    result = run.result
    delay = state.settings.copilot_stream_delay_ms
    thinking = state.settings.copilot_thinking_delay_ms

    try:
        await websocket.send_json(
            {"type": "ready", "run_id": run_id, "engine": result.engine}
        )
        await _emit(
            websocket,
            explainer.summary(result),
            explainer.tool_calls(None, result),
            delay,
            thinking,
        )
        await websocket.send_json({"type": "done", "run_id": run_id})

        while True:
            frame = await websocket.receive_json()
            await copilot_registry.touch(run_id)
            question = str(frame.get("text", "")).strip() if isinstance(frame, dict) else ""
            if not question:
                continue
            await _emit(
                websocket,
                explainer.answer(question, result),
                explainer.tool_calls(question, result),
                delay,
                thinking,
            )
            await websocket.send_json({"type": "done", "run_id": run_id})
    except WebSocketDisconnect:
        logger.info("Copilot socket for run %s closed by the client", run_id)
    except Exception:
        logger.exception("Copilot stream failed for run %s", run_id)
        await websocket.close(code=1011)
    finally:
        # Non-negotiable: a crashed handler must not leak its peer. The identity
        # check keeps a replaced connection from evicting its replacement.
        await copilot_registry.unregister(run_id, connection.websocket)
