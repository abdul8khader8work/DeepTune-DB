"""Pydantic v2 request/response contracts (mirrors the API specification)."""

from src.schemas.analysis import (
    AnalysisResult,
    AnalyzeAccepted,
    DAGEdge,
    DAGNode,
    IndexRecommendation,
    QueryAnalysisRequest,
    RunStatus,
    ApplyIndexResponse,
    RevertResponse,
)
from src.schemas.connections import (
    ColumnSchema,
    ConnectionResponse,
    DBConnectionRequest,
    SchemaResponse,
    TableSchema,
)
from src.schemas.system import DeleteResponse, HealthResponse, LegacyApplyRequest

__all__ = [
    "AnalysisResult",
    "AnalyzeAccepted",
    "ApplyIndexResponse",
    "ColumnSchema",
    "ConnectionResponse",
    "DAGEdge",
    "DAGNode",
    "DBConnectionRequest",
    "DeleteResponse",
    "HealthResponse",
    "IndexRecommendation",
    "LegacyApplyRequest",
    "QueryAnalysisRequest",
    "RevertResponse",
    "RunStatus",
    "SchemaResponse",
    "TableSchema",
]
