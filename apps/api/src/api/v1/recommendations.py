"""Apply and revert real candidate indexes inside the shadow database."""

import asyncpg
from fastapi import APIRouter, Depends, Request

from src.api.deps import get_state, require_auth
from src.core.errors import bad_gateway, conflict, not_found
from src.db.shadow import ShadowUnavailable, apply_index, drop_shadow_index
from src.schemas.analysis import ApplyIndexResponse, RevertResponse
from src.services.runs import AppliedIndex

router = APIRouter(
    prefix="/recommendations",
    tags=["recommendations"],
    dependencies=[Depends(require_auth)],
)


@router.post("/{recommendation_id}/apply", response_model=ApplyIndexResponse)
async def apply_recommendation(
    recommendation_id: str, request: Request
) -> ApplyIndexResponse:
    state = get_state(request)
    item = await state.runs.find_recommendation(recommendation_id)
    if item is None:
        raise not_found(
            "RECOMMENDATION_NOT_FOUND",
            "That recommendation is unknown or its run has expired.",
        )
    if await state.applied.exists(recommendation_id):
        raise conflict(
            "INDEX_ALREADY_APPLIED",
            "That shadow index is already applied.",
            "Revert it before applying again.",
        )

    try:
        connection, index_name, result = await apply_index(
            state.settings,
            item.sql_query,
            item.recommendation.sql_statement,
        )
    except ShadowUnavailable as exc:
        raise bad_gateway(str(exc)) from exc

    await state.applied.add(
        recommendation_id,
        AppliedIndex(
            conn=connection,
            shadow_index_name=index_name,
            validated_execution_time_ms=result.execution_time_ms,
        ),
    )
    return ApplyIndexResponse(
        shadow_index_name=index_name,
        status="applied",
        validated_execution_time_ms=round(result.execution_time_ms, 3),
        message=(
            "Index built in the disposable shadow database only and measured "
            "with EXPLAIN (ANALYZE). Review the CREATE INDEX CONCURRENTLY "
            "script before running it on the target database."
        ),
    )


@router.post("/{recommendation_id}/revert", response_model=RevertResponse)
async def revert_recommendation(
    recommendation_id: str, request: Request
) -> RevertResponse:
    state = get_state(request)
    applied = await state.applied.pop(recommendation_id)
    if applied is None:
        raise not_found(
            "INDEX_NOT_APPLIED",
            "No applied shadow index matches that recommendation_id.",
        )
    try:
        await drop_shadow_index(applied.conn, applied.shadow_index_name)
    except asyncpg.PostgresError as exc:
        raise bad_gateway("Could not drop the shadow index.") from exc
    finally:
        await applied.conn.close()
    return RevertResponse(status="reverted")
