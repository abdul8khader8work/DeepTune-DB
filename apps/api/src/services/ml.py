"""Bridge between the Phase 3 engine report and the Phase 2 API contracts.

This module is intentionally torch-free and engine-import-free: it consumes the
duck-typed ``OptimizationReport`` returned by ``PlanOptimizer.optimize`` and maps
it onto :mod:`src.schemas.analysis`. That keeps it unit-testable with plain
fakes and guarantees the API never grows training logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from src.schemas.analysis import DAGEdge, DAGNode, IndexRecommendation
from src.schemas.connections import TableSchema

# PlanGraph numeric feature block: [est_rows, actual_rows, cost, bytes,
# selectivity, is_index_scan]. Only the tail is positional; the head is the
# operator one-hot, whose width is part of the checkpoint contract.
_NUMERIC_FEATURES = 6
_EST_ROWS_SLOT = 0
_ACTUAL_ROWS_SLOT = 1
_COST_SLOT = 2

_FALLBACK_ATTENTION_FLOOR = 0.25
#: Below this normalised spread the model's attention ranking carries no signal
#: (GATv2 can emit near-uniform weights for out-of-distribution plan shapes), so
#: the heatmap falls back to cost weighting instead of showing a flat wall.
_MIN_ATTENTION_SPREAD = 0.08


@dataclass(frozen=True)
class MlOutcome:
    recommendations: list[IndexRecommendation]
    original_nodes: list[DAGNode]
    optimized_nodes: list[DAGNode]
    edges: list[DAGEdge]
    baseline_ms: float
    predicted_ms: float
    speedup: float
    attention: tuple[Any, ...]
    attention_informative: bool
    symbolic_candidate_count: int
    rejected: tuple[Any, ...]
    tables: tuple[Any, ...]
    trace: tuple[str, ...]


def _expm1(value: float) -> float:
    return math.expm1(min(float(value), 50.0))


def _feature_offset(width: int) -> int:
    offset = width - _NUMERIC_FEATURES
    if offset <= 0:  # pragma: no cover - contract guard
        raise ValueError("PlanGraph node features are narrower than the numeric block")
    return offset


def to_catalog(tables: Iterable[TableSchema]) -> Any:
    """Build the engine's ``SchemaCatalog`` from the Phase 2 schema payload."""
    from parsers.schema import SchemaCatalog  # engine module, path set in lifespan

    return SchemaCatalog.from_api_tables([table.model_dump() for table in tables])


def _node_id(index: int) -> str:
    return f"node_{index + 1}"


def graph_to_nodes(graph: Any) -> list[DAGNode]:
    """Rebuild DAG nodes from the engine's PyG ``PlanGraph``.

    ``plan_to_graph`` and ``services.dag.build_dag`` both walk the EXPLAIN tree
    pre-order, so node ``i`` in the graph is ``node_{i+1}`` in the API contract.
    """
    data = graph.data
    matrix = data.x
    offset = _feature_offset(int(matrix.size(1)))
    nodes: list[DAGNode] = []
    for index, operator in enumerate(graph.operators):
        cost = _expm1(float(matrix[index, offset + _COST_SLOT]))
        rows = _expm1(float(matrix[index, offset + _ACTUAL_ROWS_SLOT]))
        relation = graph.relations[index]
        nodes.append(
            DAGNode(
                id=_node_id(index),
                operation_type=operator,
                relation_name=relation,
                estimated_cost=round(cost, 2),
                estimated_rows=max(0, int(round(rows))),
                actual_time_ms=None,
                gnn_attention_score=0.0,
            )
        )
    return nodes


def graph_to_edges(graph: Any) -> list[DAGEdge]:
    """``edge_index`` is child -> parent; the API contract is parent -> child."""
    edge_index = graph.data.edge_index
    nodes = graph_to_nodes(graph)
    edges: list[DAGEdge] = []
    for column in range(int(edge_index.size(1))):
        child = int(edge_index[0, column])
        parent = int(edge_index[1, column])
        edges.append(
            DAGEdge(
                id=f"edge_{_node_id(parent)}_{_node_id(child)}",
                source=_node_id(parent),
                target=_node_id(child),
                rows_transferred=nodes[child].estimated_rows,
            )
        )
    return edges


def apply_attention(
    nodes: Sequence[DAGNode], attention: Sequence[Any]
) -> tuple[list[DAGNode], bool]:
    """Overlay real GATv2 attention on the cost-normalised fallback.

    Returns ``(nodes, informative)``. ``summarize_attention`` returns only the
    hottest operators, so nodes outside that set keep a damped cost ratio to
    stay legible. When the whole distribution is near-uniform the weights are
    reported as uninformative and cost weighting is used instead.
    """
    if not attention:
        return list(nodes), False

    peak = max((float(item.weight) for item in attention), default=0.0)
    if peak <= 0:
        return list(nodes), False

    normalised = {
        _node_id(int(item.node_index)): float(item.weight) / peak for item in attention
    }
    spread = max(normalised.values()) - min(normalised.values())
    informative = spread >= _MIN_ATTENTION_SPREAD

    max_cost = max((node.estimated_cost for node in nodes), default=0.0)
    updated: list[DAGNode] = []
    for node in nodes:
        ratio = node.estimated_cost / max_cost if max_cost > 0 else 0.0
        real = normalised.get(node.id)
        if informative and real is not None:
            score = real
        else:
            score = ratio * (1.0 if not informative else _FALLBACK_ATTENTION_FLOOR)
        updated.append(
            node.model_copy(update={"gnn_attention_score": round(min(1.0, score), 4)})
        )
    return updated, informative


def to_recommendations(report: Any, run_id: str) -> list[IndexRecommendation]:
    """Map engine recommendations onto the API contract.

    The engine's candidate id is deterministic, so it is namespaced by run to
    keep ``/recommendations/{id}/apply`` unambiguous across concurrent runs.
    """
    mapped: list[IndexRecommendation] = []
    for item in report.recommendations:
        mapped.append(
            IndexRecommendation(
                id=f"{run_id}:{item.id}",
                sql_statement=item.sql_statement,
                target_table=item.target_table,
                target_columns=list(item.target_columns),
                predicted_speedup_factor=round(float(item.predicted_speedup_factor), 2),
                validated_speedup_factor=None,
                storage_overhead_bytes=int(item.storage_overhead_bytes),
                write_impact_percentage=round(float(item.write_impact_percentage), 1),
                confidence_score=round(float(item.confidence_score), 2),
                explanation=item.explanation,
            )
        )
    return mapped


def optimize(
    optimizer: Any,
    sql: str,
    explain_plan: dict,
    tables: Sequence[TableSchema],
    goal: str,
    original_nodes: Sequence[DAGNode],
    original_edges: Sequence[DAGEdge],
    original_ms: float,
    run_id: str,
) -> MlOutcome:
    """Run symbolic pruning + beam search and shape the result for the API."""
    catalog = to_catalog(tables)
    report = optimizer.optimize(sql=sql, plan=explain_plan, catalog=catalog, goal=goal)

    baseline_ms = float(report.baseline_latency_ms) or original_ms
    configurations = list(report.configurations)
    best = configurations[0] if configurations else None
    predicted_ms = (
        float(best.predicted_latency_ms) if best is not None else original_ms
    )
    speedup = (
        float(best.predicted_speedup)
        if best is not None and best.predicted_speedup > 0
        else (original_ms / predicted_ms if predicted_ms > 0 else 1.0)
    )

    trace = list(report.trace)
    graph = getattr(report, "plan_graph", None)
    if graph is not None:
        optimized_nodes = graph_to_nodes(graph)
        edges = graph_to_edges(graph)
        optimized_nodes, informative = apply_attention(optimized_nodes, report.attention)
    else:
        optimized_nodes = list(original_nodes)
        edges = list(original_edges)
        _, informative = apply_attention(list(original_nodes), report.attention)

    original, _ = apply_attention(list(original_nodes), report.attention)
    if report.attention and not informative:
        trace.append(
            "attention distribution was near-uniform; heatmap uses cost weighting"
        )

    return MlOutcome(
        recommendations=to_recommendations(report, run_id),
        original_nodes=original,
        optimized_nodes=optimized_nodes,
        edges=edges,
        baseline_ms=baseline_ms,
        predicted_ms=predicted_ms,
        speedup=speedup,
        attention=tuple(report.attention),
        attention_informative=informative,
        symbolic_candidate_count=int(report.symbolic_candidate_count),
        rejected=tuple(report.rejected),
        tables=tuple(report.tables),
        trace=tuple(trace),
    )


def scale_metrics(
    original_cost: float, original_ms: float, predicted_ms: float
) -> dict[str, float]:
    """Estimate the optimized cost by scaling it with the predicted latency."""
    if original_ms <= 0 or predicted_ms <= 0:
        return {"cost": round(original_cost, 2), "time_ms": round(original_ms, 3)}
    ratio = max(0.0, min(1.0, predicted_ms / original_ms))
    return {"cost": round(original_cost * ratio, 2), "time_ms": round(predicted_ms, 3)}
