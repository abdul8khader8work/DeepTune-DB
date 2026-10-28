"""In-memory run registry and applied-hypopg-index tracking."""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

import asyncpg

from src.core.config import Settings
from src.db.run_archive import NullRunArchive, RunArchive, RunSnapshot
from src.schemas.analysis import (
    AnalysisResult,
    IndexRecommendation,
    RunState as RunStateLiteral,
)

logger = logging.getLogger(__name__)


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


class RunRegistry:
    def __init__(self, settings: Settings, archive: RunArchive | None = None) -> None:
        self._settings = settings
        self._archive: RunArchive = archive or NullRunArchive()
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
        except Exception:  # noqa: BLE001 - archival is not on the critical path
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
            snapshot = self._snapshot(run)
        await self._record(snapshot)

    async def fail(self, run_id: str, message: str) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            run.status = "failed"
            run.error = message
            run.log = message
            snapshot = self._snapshot(run)
        await self._record(snapshot)

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
