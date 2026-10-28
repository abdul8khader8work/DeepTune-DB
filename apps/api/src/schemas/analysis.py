"""Query analysis, DAG, and recommendation contracts."""

from typing import Literal

from pydantic import Field

from src.schemas.connections import StrictModel

OptimizationGoal = Literal["read_performance", "balanced", "minimal_storage"]
RunState = Literal[
    "queued",
    "parsing",
    "gnn_inference",
    "hypopg_validation",
    "completed",
    "failed",
]


class QueryAnalysisRequest(StrictModel):
    connection_id: str = Field(min_length=1)
    sql_query: str = Field(min_length=1, max_length=10000)
    optimization_goal: OptimizationGoal = "balanced"


class AnalyzeAccepted(StrictModel):
    run_id: str
    status: str
    message: str


class RunStatus(StrictModel):
    run_id: str
    status: RunState
    progress_percentage: int = Field(ge=0, le=100)
    current_step_log: str


class DAGNode(StrictModel):
    id: str
    operation_type: str
    relation_name: str | None = None
    estimated_cost: float
    estimated_rows: int
    actual_time_ms: float | None = None
    gnn_attention_score: float


class DAGEdge(StrictModel):
    id: str
    source: str
    target: str
    rows_transferred: int


class IndexRecommendation(StrictModel):
    id: str
    sql_statement: str
    target_table: str
    target_columns: list[str]
    predicted_speedup_factor: float
    validated_speedup_factor: float | None = None
    storage_overhead_bytes: int
    write_impact_percentage: float
    confidence_score: float
    explanation: str


class AttentionHotspot(StrictModel):
    """One GATv2 attention record, used by the explainability panel."""

    node_index: int
    operator: str
    relation: str | None = None
    weight: float


class RejectedCandidate(StrictModel):
    """A symbolic candidate that was pruned before beam search."""

    description: str
    reason: str


EngineBackend = Literal["gnn", "heuristic"]


class AnalysisResult(StrictModel):
    run_id: str
    status: Literal["completed", "failed"]
    engine: EngineBackend = "heuristic"
    original_metrics: dict[str, float]
    optimized_metrics: dict[str, float]
    original_dag: list[DAGNode]
    optimized_dag: list[DAGNode]
    edges: list[DAGEdge]
    original_edges: list[DAGEdge] = []
    recommendations: list[IndexRecommendation]
    attention: list[AttentionHotspot] = []
    symbolic_trace: list[str] = []
    rejected_candidates: list[RejectedCandidate] = []
    speedup_factor: float = 1.0
    symbolic_candidate_count: int = 0


class ApplyIndexResponse(StrictModel):
    hypopg_index_id: int
    status: str
    validated_execution_time_ms: float
    message: str


class RevertResponse(StrictModel):
    status: str
