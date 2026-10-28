"""Convert PostgreSQL ``EXPLAIN (FORMAT JSON)`` payloads into PyG ``Data``.

The traversal is iterative (no deep recursion) and emits edges child -> parent,
so message passing flows bottom-up from scans to the root operator.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

import torch
from torch_geometric.data import Data

from config import (
    DEFAULT_ROW_WIDTH_BYTES,
    EDGE_FEATURE_DIM,
    INDEX_SCAN_OPERATORS,
    JOIN_INDEX,
    MAX_PLAN_NODES,
    NODE_FEATURE_DIM,
    OPERATOR_INDEX,
    OPERATOR_TYPES,
    UNKNOWN_OPERATOR_INDEX,
    log1p,
)
from parsers.schema import SchemaCatalog


class PlanParseError(ValueError):
    """Raised when an EXPLAIN payload is not a usable plan tree."""


@dataclass(frozen=True)
class PlanGraph:
    """A parsed plan plus the metadata the API needs for explainability."""

    data: Data
    operators: tuple[str, ...]
    relations: tuple[str | None, ...]
    execution_time_ms: float | None = None
    planning_time_ms: float | None = None

    @property
    def num_nodes(self) -> int:
        return int(self.data.num_nodes)

    @property
    def label_log(self) -> float | None:
        if getattr(self.data, "y", None) is None:
            return None
        return float(self.data.y.view(-1)[0].item())


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _decode_payload(payload: object) -> tuple[Mapping[str, Any], float | None, float | None]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PlanParseError("EXPLAIN payload is not valid JSON") from exc
    if isinstance(payload, list):
        if not payload:
            raise PlanParseError("EXPLAIN payload is empty")
        payload = payload[0]
    if not isinstance(payload, Mapping):
        raise PlanParseError("EXPLAIN payload must be an object or a one-element list")
    if "Plan" not in payload and "Node Type" not in payload:
        raise PlanParseError("EXPLAIN payload has no Plan object")

    planning = payload.get("Planning Time")
    execution = payload.get("Execution Time")
    plan = payload.get("Plan", payload)
    if not isinstance(plan, Mapping):
        raise PlanParseError("EXPLAIN payload has no Plan object")
    return (
        plan,
        _as_float(planning) if planning is not None else None,
        _as_float(execution) if execution is not None else None,
    )


def _one_hot(index: int, size: int) -> list[float]:
    vector = [0.0] * size
    vector[index] = 1.0
    return vector


def _operator_index(node_type: str) -> int:
    return OPERATOR_INDEX.get(node_type, UNKNOWN_OPERATOR_INDEX)


def _join_type(node: Mapping[str, Any]) -> str:
    raw = node.get("Join Type")
    if isinstance(raw, str):
        normalized = raw.upper()
        if normalized in JOIN_INDEX:
            return normalized
    node_type = str(node.get("Node Type", ""))
    if node_type in {"Hash Join", "Nested Loop", "Merge Join"}:
        return "INNER"
    return "NONE"


def _relation_name(node: Mapping[str, Any]) -> str | None:
    relation = node.get("Relation Name")
    return str(relation) if relation else None


def _relation_bytes(
    node: Mapping[str, Any], catalog: SchemaCatalog | None
) -> int:
    if catalog is None:
        return 0
    relation = _relation_name(node)
    if relation is None:
        return 0
    schema_name = str(node.get("Schema", "public"))
    table = catalog.table(schema_name, relation) or catalog.find(relation)
    if table is None:
        return 0
    return table.effective_bytes


def _selectivity(node: Mapping[str, Any]) -> float:
    planned = _as_float(node.get("Plan Rows"))
    actual = _as_float(node.get("Actual Rows"), planned)
    if planned <= 0:
        return 1.0
    return max(0.0, min(1.0, actual / planned))


def _node_features(node: Mapping[str, Any], catalog: SchemaCatalog | None) -> list[float]:
    node_type = str(node.get("Node Type", "Unknown"))
    features = _one_hot(_operator_index(node_type), len(OPERATOR_TYPES))
    features.extend(
        [
            log1p(_as_float(node.get("Plan Rows"))),
            log1p(_as_float(node.get("Actual Rows"), _as_float(node.get("Plan Rows")))),
            log1p(_as_float(node.get("Total Cost"))),
            log1p(_relation_bytes(node, catalog)),
            _selectivity(node),
            1.0 if node_type in INDEX_SCAN_OPERATORS else 0.0,
        ]
    )
    if len(features) != NODE_FEATURE_DIM:  # pragma: no cover - contract guard
        raise PlanParseError("Node feature vector has the wrong dimension")
    return features


def _edge_features(
    child: Mapping[str, Any],
    parent: Mapping[str, Any],
) -> list[float]:
    rows = _as_float(child.get("Actual Rows"), _as_float(child.get("Plan Rows")))
    width = _as_float(
        child.get("Plan Width"),
        _as_float(parent.get("Plan Width"), DEFAULT_ROW_WIDTH_BYTES),
    )
    cardinality = log1p(rows)
    data_size = log1p(rows * max(width, 1.0))
    join_type = _join_type(parent)
    features = [cardinality, data_size, *_one_hot(JOIN_INDEX[join_type], len(JOIN_INDEX))]
    if len(features) != EDGE_FEATURE_DIM:  # pragma: no cover - contract guard
        raise PlanParseError("Edge feature vector has the wrong dimension")
    return features


def plan_to_graph(
    payload: object,
    catalog: SchemaCatalog | None = None,
    execution_time_ms: float | None = None,
    max_nodes: int = MAX_PLAN_NODES,
) -> PlanGraph:
    """Parse an EXPLAIN payload into a bottom-up PyG graph.

    ``execution_time_ms`` overrides the payload's ``Execution Time``; when both
    are absent the graph is unlabelled and ``data.y`` is not set.
    """
    plan, planning_time, payload_execution = _decode_payload(payload)
    label_ms = execution_time_ms if execution_time_ms is not None else payload_execution

    node_features: list[list[float]] = []
    edge_index: list[tuple[int, int]] = []
    edge_features: list[list[float]] = []
    operators: list[str] = []
    relations: list[str | None] = []

    stack: list[tuple[Mapping[str, Any], int | None, Mapping[str, Any] | None]] = [
        (plan, None, None)
    ]
    while stack:
        node, parent_index, parent = stack.pop()
        if len(node_features) >= max_nodes:
            raise PlanParseError(f"Plan exceeds the {max_nodes} node limit")

        index = len(node_features)
        node_features.append(_node_features(node, catalog))
        operators.append(str(node.get("Node Type", "Unknown")))
        relations.append(_relation_name(node))

        if parent_index is not None and parent is not None:
            edge_index.append((index, parent_index))
            edge_features.append(_edge_features(node, parent))

        children = node.get("Plans") or []
        if not isinstance(children, list):
            children = []
        # Reversed push preserves left-to-right plan order in the node index.
        for child in reversed(children):
            if isinstance(child, Mapping):
                stack.append((child, index, node))

    x = torch.tensor(node_features, dtype=torch.float32)
    if edge_index:
        edge_index_tensor = torch.tensor(edge_index, dtype=torch.long).t().contiguous()
        edge_attr = torch.tensor(edge_features, dtype=torch.float32)
    else:
        edge_index_tensor = torch.zeros((2, 0), dtype=torch.long)
        edge_attr = torch.zeros((0, EDGE_FEATURE_DIM), dtype=torch.float32)

    data = Data(x=x, edge_index=edge_index_tensor, edge_attr=edge_attr)
    if label_ms is not None:
        data.y = torch.tensor([[log1p(label_ms)]], dtype=torch.float32)
    data.execution_time_ms = label_ms
    data.planning_time_ms = planning_time

    return PlanGraph(
        data=data,
        operators=tuple(operators),
        relations=tuple(relations),
        execution_time_ms=label_ms,
        planning_time_ms=planning_time,
    )


def graph_from_explain(
    payload: object,
    catalog: SchemaCatalog | None = None,
    execution_time_ms: float | None = None,
) -> PlanGraph:
    """Alias kept for readability at call sites."""
    return plan_to_graph(payload, catalog=catalog, execution_time_ms=execution_time_ms)
