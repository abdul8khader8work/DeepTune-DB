"""Asynchronous query analysis: accept, poll, and fetch results."""

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from src.api.deps import get_state, require_auth
from src.core.errors import conflict, not_found, unprocessable
from src.core.ratelimit import analyze_limit, limiter
from src.schemas.analysis import (
    AnalysisResult,
    AnalyzeAccepted,
    QueryAnalysisRequest,
    RunStatus,
)
from src.services import pipeline
from src.services.pipeline import PipelineDeps
from src.services.sql_guard import SqlValidationError, validate_sql

router = APIRouter(
    prefix="/queries",
    tags=["queries"],
    dependencies=[Depends(require_auth)],
)


@router.post("/analyze", response_model=AnalyzeAccepted, status_code=202)
@limiter.limit(analyze_limit)
async def analyze_query(
    request: Request,
    payload: QueryAnalysisRequest,
    background: BackgroundTasks,
) -> AnalyzeAccepted:
    state = get_state(request)
    try:
        validate_sql(payload.sql_query, state.settings.max_sql_length)
    except SqlValidationError as exc:
        raise unprocessable(
            "INVALID_SQL",
            str(exc),
            "Send exactly one read-only SELECT statement.",
        ) from exc

    run = await state.runs.create(payload.connection_id)
    background.add_task(
        pipeline.execute,
        run.run_id,
        payload,
        PipelineDeps(
            settings=state.settings,
            store=state.store,
            runs=state.runs,
        ),
    )
    return AnalyzeAccepted(
        run_id=run.run_id,
        status="queued",
        message="Analysis accepted. Poll the status endpoint for progress.",
    )


@router.get("/{run_id}/status", response_model=RunStatus)
async def get_run_status(run_id: str, request: Request) -> RunStatus:
    state = get_state(request)
    run = await state.runs.get(run_id)
    if run is None:
        raise not_found(
            "RUN_NOT_FOUND",
            "That run_id is unknown or has expired (runs live in memory).",
        )
    log = run.log if run.error is None else f"{run.log} ({run.error})"
    return RunStatus(
        run_id=run.run_id,
        status=run.status,
        progress_percentage=run.progress,
        current_step_log=log,
    )


@router.get("/{run_id}/results", response_model=AnalysisResult)
async def get_run_results(run_id: str, request: Request) -> AnalysisResult:
    state = get_state(request)
    run = await state.runs.get(run_id)
    if run is None:
        raise not_found(
            "RUN_NOT_FOUND",
            "That run_id is unknown or has expired (runs live in memory).",
        )
    if run.status == "failed":
        raise conflict(
            "RUN_FAILED",
            run.error or "The analysis failed.",
            "Inspect the status endpoint log, fix the query, and submit it again.",
        )
    if run.result is None or run.status != "completed":
        raise conflict(
            "RUN_NOT_READY",
            f"Run is still {run.status}.",
            "Poll the status endpoint until progress_percentage reaches 100.",
        )
    return run.result
