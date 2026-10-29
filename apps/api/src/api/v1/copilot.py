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
"""

import asyncio
import logging
from collections.abc import Sequence

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.deps import AppState
from src.core.errors import ApiError
from src.core.security import decode_access_token
from src.services import copilot as explainer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["copilot"])

_WS_UNAUTHORIZED = 4401
_WS_NOT_FOUND = 4404


def _state(websocket: WebSocket) -> AppState | None:
    state = getattr(websocket.app.state, "deeptune", None)
    return state if isinstance(state, AppState) else None


def _authorised(websocket: WebSocket, state: AppState) -> bool:
    if not state.settings.auth_enabled:
        return True
    token = websocket.query_params.get("token")
    if not token:
        return False
    try:
        decode_access_token(token, state.settings)
    except ApiError:
        return False
    return True


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
    state = _state(websocket)
    if state is None:  # pragma: no cover - lifespan guard
        await websocket.close(code=1011)
        return

    if not _authorised(websocket, state):
        await websocket.close(code=_WS_UNAUTHORIZED)
        return

    run = await state.runs.get(run_id)
    if run is None or run.result is None:
        await websocket.close(code=_WS_NOT_FOUND)
        return

    await websocket.accept()
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
    except Exception:  # noqa: BLE001 - never leak a traceback into the socket
        logger.exception("Copilot stream failed for run %s", run_id)
        await websocket.close(code=1011)
