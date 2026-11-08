"""Registry of live WebSocket connections (Patch 3, Task 1).

FastAPI/Starlette exposes no ``ping_interval``/``ping_timeout`` on
``WebSocket``; those belong to uvicorn. The server-level heartbeat is configured
in ``Dockerfile``/``Makefile`` and evicts dead TCP peers, while this registry is
the application-level bookkeeping: one dictionary keyed by ``run_id``, guarded
by an ``asyncio.Lock`` so two coroutines cannot race a register/unregister.

Two independent instances exist because the copilot socket and the optimization
progress socket serve different lifecycles and must not close each other:

``copilot_registry``   ``WS /ws/copilot/{run_id}``   (question/answer stream)
``optimize_registry``  ``WS /ws/optimize/{run_id}``  (pipeline progress stream)
``registry``           backward-compatible alias of ``copilot_registry``
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

#: Close code used when a newer connection claims the same ``run_id``.
REPLACED = 4000


@dataclass(slots=True)
class ActiveConnection:
    """One live peer. ``slots=True`` keeps the per-connection footprint small."""

    run_id: str
    websocket: WebSocket
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: Serialises concurrent sends (pipeline broadcast + 30s heartbeat).
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class WebSocketRegistry:
    """Thread-safe (event-loop-safe) registry of active sockets by ``run_id``."""

    def __init__(self) -> None:
        self._connections: dict[str, ActiveConnection] = {}
        self._lock = asyncio.Lock()

    async def register(self, run_id: str, websocket: WebSocket) -> ActiveConnection:
        """Store ``websocket`` as the peer for ``run_id`` and evict the previous one.

        The close of the replaced peer happens *outside* the lock: closing is
        network I/O and must not block every other register/unregister.
        """
        async with self._lock:
            previous = self._connections.get(run_id)
            connection = ActiveConnection(run_id=run_id, websocket=websocket)
            self._connections[run_id] = connection
        if previous is not None:
            await self._safe_close(previous.websocket, REPLACED, "replaced")
        return connection

    async def unregister(
        self, run_id: str, websocket: WebSocket | None = None
    ) -> None:
        """Drop ``run_id``.

        When ``websocket`` is supplied, the entry is removed only if it still
        points at that exact peer. This prevents a replaced connection's late
        ``finally`` block from evicting the peer that replaced it.
        """
        async with self._lock:
            current = self._connections.get(run_id)
            if current is None:
                return
            if websocket is not None and current.websocket is not websocket:
                return
            self._connections.pop(run_id, None)

    async def touch(self, run_id: str) -> None:
        async with self._lock:
            connection = self._connections.get(run_id)
            if connection is not None:
                connection.last_activity = datetime.now(UTC)

    async def broadcast(self, run_id: str, message: dict[str, object]) -> bool:
        """Send ``message`` to ``run_id``; never raise for a dead peer."""
        async with self._lock:
            connection = self._connections.get(run_id)
        if connection is None:
            return False
        try:
            async with connection.send_lock:
                await connection.websocket.send_json(message)
        except Exception:
            await self.unregister(run_id, connection.websocket)
            return False
        await self.touch(run_id)
        return True

    @property
    def active_count(self) -> int:
        """Number of registered peers (sync read is atomic on the event loop)."""
        return len(self._connections)

    async def _safe_close(self, websocket: WebSocket, code: int, reason: str) -> None:
        try:
            await websocket.close(code=code, reason=reason)
        except Exception:
            logger.debug("Socket already closed (code=%d, reason=%s)", code, reason)


copilot_registry = WebSocketRegistry()
optimize_registry = WebSocketRegistry()

#: Patch 3's documented import path. The copilot socket owns this alias.
registry = copilot_registry


def active_connection_total() -> int:
    """Live peers across both sockets, for the health probe."""
    return copilot_registry.active_count + optimize_registry.active_count


__all__ = [
    "ActiveConnection",
    "WebSocketRegistry",
    "active_connection_total",
    "copilot_registry",
    "optimize_registry",
    "registry",
]
