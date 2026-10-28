"""Compatibility aliases kept from the master execution plan.

The canonical surface lives under `/api/v1`; these three routes exist so early
scripts written against `/api/connect`, `/api/analyze`, and `/api/apply_index`
keep working.
"""

from fastapi import APIRouter, Depends, Request

from src.api.deps import require_auth
from src.api.v1.databases import connect_database
from src.api.v1.queries import analyze_query
from src.api.v1.recommendations import apply_recommendation
from src.schemas.analysis import ApplyIndexResponse
from src.schemas.connections import ConnectionResponse
from src.schemas.system import LegacyApplyRequest

router = APIRouter(
    prefix="/api",
    tags=["legacy"],
    dependencies=[Depends(require_auth)],
    include_in_schema=False,
)

router.add_api_route(
    "/connect",
    connect_database,
    methods=["POST"],
    response_model=ConnectionResponse,
)
router.add_api_route(
    "/analyze",
    analyze_query,
    methods=["POST"],
    status_code=202,
)


@router.post("/apply_index", response_model=ApplyIndexResponse)
async def apply_index_legacy(
    payload: LegacyApplyRequest, request: Request
) -> ApplyIndexResponse:
    return await apply_recommendation(payload.recommendation_id, request)
