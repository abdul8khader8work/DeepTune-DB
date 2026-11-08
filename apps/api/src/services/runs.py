"""In-memory run registry and applied-hypopg-index tracking."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import asyncpg

from src.core.config import Settings
from src.db.run_archive import NullRunArchive, RunArchive, RunSnapshot
from src.schemas.analysis import (
    AnalysisResult,
    IndexRecommendation,
    RunState as RunStateLiteral,
)

logger = logging.getLogger(__name__)

#: ``(run_id, frame) -> delivered``; returns False when no peer is listening.
Broadcaster = Callable[[str, dict[str, object]], Awaitable[bool]]

_STEP_FOR: dict[str, str] = {
    "queued": "parsing",
    "parsing": "parsing",
    "gnn_inference": "gnn",
    "hypopg_validation": "hypopg",
    "completed": "done",
    "failed": "error",
}


def _iso_now() -> str:
    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )



@dataclass
class RecommendationState:
    recommendation: IndexRecommendation
    connection_id: str
    sql_query: str


@dataclass
class Run:
    run_id: str
    connection_id: str
    status: RunStateLiteral = "queued"
    progress: int = 0
    log: str = "Analysis queued."
    result: AnalysisResult | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    recommendations: dict[str, RecommendationState] = field(default_factory=dict)
    #: Monotonic frame sequence: a late snapshot can never overwrite newer
    #: progress on the client.
    seq: int = 0


class RunRegistry:
    def __init__(
        self,
        settings: Settings,
        archive: RunArchive | None = None,
        broadcaster: Broadcaster | None = None,
    ) -> None:
        self._settings = settings
        self._archive: RunArchive = archive or NullRunArchive()
        self._broadcaster = broadcaster
        self._runs: dict[str, Run] = {}
        self._lock = asyncio.Lock()

    def _expired(self, run: Run) -> bool:
        return (time.monotonic() - run.created_at) > self._settings.run_ttl_seconds

    @staticmethod
    def _snapshot(run: Run) -> RunSnapshot:
        return RunSnapshot(
            run_id=run.run_id,
            connection_id=run.connection_id,
            status=run.status,
            progress=run.progress,
            engine=run.result.engine if run.result is not None else None,
            error=run.error,
            result=run.result,
        )

    async def _record(self, snapshot: RunSnapshot) -> None:
        """Archive best-effort: a metadata DB fault must never fail a run."""
        try:
            await self._archive.record(snapshot)
        except Exception:
            logger.warning("Could not archive run %s", snapshot.run_id, exc_info=True)

    async def create(self, connection_id: str) -> Run:
        run = Run(run_id=str(uuid.uuid4()), connection_id=connection_id)
        async with self._lock:
            self._runs[run.run_id] = run
            self._sweep_locked()
            snapshot = self._snapshot(run)
        await self._record(snapshot)
        return run

    async def get(self, run_id: str) -> Run | None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is not None and self._expired(run):
                self._runs.pop(run_id, None)
                return None
            return run

    async def update(
        self, run_id: str, status: RunStateLiteral, progress: int, log: str
    ) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = status
            run.progress = max(0, min(100, progress))
            run.log = log
            run.seq += 1
            frames = self._state_frames(run)
        await self._publish(run_id, frames)

    async def complete(
        self,
        run_id: str,
        result: AnalysisResult,
        recommendations: list[RecommendationState],
    ) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = "completed"
            run.progress = 100
            run.log = "Analysis complete."
            run.result = result
            run.recommendations = {
                item.recommendation.id: item for item in recommendations
            }
            run.seq += 1
            snapshot = self._snapshot(run)
            frames = [*self._state_frames(run), self._complete_frame(run)]
        await self._record(snapshot)
        await self._publish(run_id, frames)

    async def fail(self, run_id: str, message: str) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = "failed"
            run.error = message
            run.log = message
            run.seq += 1
            snapshot = self._snapshot(run)
            frames = [*self._state_frames(run), self._error_frame(run)]
        await self._record(snapshot)
        await self._publish(run_id, frames)

    def snapshot_frames(self, run: Run) -> list[dict[str, object]]:
        """Frames that bring a freshly connected client up to the current state."""
        frames = self._state_frames(run)
        if run.status == "completed" and run.result is not None:
            frames.append(self._complete_frame(run))
        elif run.status == "failed":
            frames.append(self._error_frame(run))
        return frames

    def _state_frames(self, run: Run) -> list[dict[str, object]]:
        return [
            {
                "type": "progress",
                "seq": run.seq,
                "payload": {
                    "percentage": run.progress,
                    "step": _STEP_FOR.get(run.status, "parsing"),
                    "status": run.status,
                    "message": run.log,
                },
            },
            {
                "type": "log_update",
                "seq": run.seq,
                "payload": {
                    "ts": _iso_now(),
                    "level": (
                        "err"
                        if run.status == "failed"
                        else "ok"
                        if run.status == "completed"
                        else "info"
                    ),
                    "text": run.log,
                },
            },
        ]

    def _complete_frame(self, run: Run) -> dict[str, object]:
        payload = run.result.model_dump(mode="json") if run.result is not None else {}
        return {"type": "complete", "seq": run.seq, "payload": payload}

    def _error_frame(self, run: Run) -> dict[str, object]:
        return {
            "type": "error",
            "seq": run.seq,
            "payload": {
                "code": "ANALYSIS_FAILED",
                "message": run.error or run.log,
            },
        }

    async def _publish(self, run_id: str, frames: list[dict[str, object]]) -> None:
        if self._broadcaster is None:
            return
        for frame in frames:
            try:
                await self._broadcaster(run_id, frame)
            except Exception:
                logger.debug("Progress broadcast failed for run %s", run_id)

    async def find_recommendation(
        self, recommendation_id: str
    ) -> RecommendationState | None:
        async with self._lock:
            for run in self._runs.values():
                if self._expired(run):
                    continue
                item = run.recommendations.get(recommendation_id)
                if item is not None:
                    return item
        return None

    def _sweep_locked(self) -> None:
        expired = [key for key, run in self._runs.items() if self._expired(run)]
        for key in expired:
            self._runs.pop(key, None)


@dataclass
class AppliedIndex:
    conn: asyncpg.Connection
    hypopg_index_id: int
    validated_execution_time_ms: float


class AppliedRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AppliedIndex] = {}
        self._lock = asyncio.Lock()

    async def add(self, recommendation_id: str, applied: AppliedIndex) -> None:
        async with self._lock:
            self._items[recommendation_id] = applied

    async def pop(self, recommendation_id: str) -> AppliedIndex | None:
        async with self._lock:
            return self._items.pop(recommendation_id, None)

    async def exists(self, recommendation_id: str) -> bool:
        async with self._lock:
            return recommendation_id in self._items

    async def close_all(self) -> None:
        async with self._lock:
            items = list(self._items.values())
            self._items.clear()
        for item in items:
            await item.conn.close()
