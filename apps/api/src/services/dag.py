"""Convert a PostgreSQL EXPLAIN plan tree into the API DAG contract."""

from dataclasses import dataclass

from src.schemas.analysis import DAGEdge, DAGNode


@dataclass(frozen=True)
class Dag:
    nodes: list[DAGNode]
    edges: list[DAGEdge]
    max_cost: float


def _flatten(plan: dict) -> list[dict]:
    flat = [plan]
    for child in plan.get("Plans", []) or []:
        flat.extend(_flatten(child))
    return flat


def build_dag(plan: dict) -> Dag:
    flat = _flatten(plan)
    max_cost = max((float(node.get("Total Cost", 0.0) or 0.0) for node in flat), default=0.0)

    nodes: list[DAGNode] = []
    edges: list[DAGEdge] = []
    counter = 0

    def visit(node: dict, parent_id: str | None) -> None:
        nonlocal counter
        counter += 1
        node_id = f"node_{counter}"
        cost = float(node.get("Total Cost", 0.0) or 0.0)
        rows = int(node.get("Actual Rows", node.get("Plan Rows", 0)) or 0)
        actual = node.get("Actual Total Time")
        nodes.append(
            DAGNode(
                id=node_id,
                operation_type=str(node.get("Node Type", "Unknown")),
                relation_name=(
                    str(node["Relation Name"]) if node.get("Relation Name") else None
                ),
                estimated_cost=cost,
                estimated_rows=rows,
                actual_time_ms=float(actual) if actual is not None else None,
                gnn_attention_score=round(cost / max_cost, 4) if max_cost > 0 else 0.0,
            )
        )
        if parent_id is not None:
            edges.append(
                DAGEdge(
                    id=f"edge_{parent_id}_{node_id}",
                    source=parent_id,
                    target=node_id,
                    rows_transferred=rows,
                )
            )
        for child in node.get("Plans", []) or []:
            visit(child, node_id)

    visit(plan, None)
    return Dag(nodes=nodes, edges=edges, max_cost=max_cost)
