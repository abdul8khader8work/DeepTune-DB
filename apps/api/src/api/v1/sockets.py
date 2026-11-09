"""Shared state/auth helpers for the two WebSocket endpoints.

Browsers cannot set an ``Authorization`` header on a WebSocket handshake, so
both sockets take the same HS256 bearer token as a ``?token=`` query parameter.
The close codes are part of the wire contract: ``4401`` for a bad token and
``4404`` for an unknown run. ``1011`` is an unexpected server fault.
"""

from __future__ import annotations

from fastapi import WebSocket

from src.api.deps import AppState
from src.core.errors import ApiError
from src.core.security import decode_access_token

WS_UNAUTHORIZED = 4401
WS_NOT_FOUND = 4404
WS_INTERNAL_ERROR = 1011


def socket_state(websocket: WebSocket) -> AppState | None:
    state = getattr(websocket.app.state, "deeptune", None)
    return state if isinstance(state, AppState) else None


def socket_authorised(websocket: WebSocket, state: AppState) -> bool:
    if state.settings.demo_mode:
        return True
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


__all__ = [
    "WS_INTERNAL_ERROR",
    "WS_NOT_FOUND",
    "WS_UNAUTHORIZED",
    "socket_authorised",
    "socket_state",
]
