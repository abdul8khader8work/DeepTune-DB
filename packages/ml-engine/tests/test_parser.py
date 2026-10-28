"""Parser contract: EXPLAIN JSON -> bottom-up PyG graph."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from config import (
    EDGE_FEATURE_DIM,
    NODE_ACTUAL_ROWS_INDEX,
    NODE_FEATURE_DIM,
    NODE_INDEX_SCAN_INDEX,
    NODE_SELECTIVITY_INDEX,
)
from parsers.explain import PlanParseError, plan_to_graph
from parsers.schema import SchemaCatalog


def test_plan_is_parsed_into_expected_graph(
    explain_payload: dict[str, Any], catalog: SchemaCatalog
) -> None:
    graph = plan_to_graph(explain_payload, catalog=catalog)

    assert graph.num_nodes == 3
    assert graph.operators == ("Limit", "Sort", "Seq Scan")
    assert graph.relations == (None, None, "orders")
    assert graph.data.x.shape == (3, NODE_FEATURE_DIM)
    assert graph.data.edge_attr.shape == (2, EDGE_FEATURE_DIM)
    assert graph.data.edge_index.tolist() == [[1, 2], [0, 1]]


def test_label_uses_log1p_of_execution_time(explain_payload: dict[str, Any]) -> None:
    graph = plan_to_graph(explain_payload)
    assert graph.label_log == pytest.approx(math.log1p(12.5))
    assert graph.execution_time_ms == pytest.approx(12.5)
    assert graph.planning_time_ms == pytest.approx(0.4)
    assert graph.data.y.shape == (1, 1)


def test_accepts_json_string_payload(explain_payload: dict[str, Any]) -> None:
    graph = plan_to_graph(json.dumps(explain_payload))
    assert graph.num_nodes == 3


def test_index_scan_and_selectivity_features() -> None:
    payload = {
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "orders",
            "Plan Rows": 100,
            "Actual Rows": 50,
            "Total Cost": 12.0,
        }
    }
    graph = plan_to_graph(payload)
    features = graph.data.x[0]
    assert features[NODE_INDEX_SCAN_INDEX].item() == 1.0
    assert features[NODE_SELECTIVITY_INDEX].item() == pytest.approx(0.5)
    assert features[NODE_ACTUAL_ROWS_INDEX].item() == pytest.approx(math.log1p(50))


def test_unlabelled_plan_has_no_target() -> None:
    graph = plan_to_graph({"Plan": {"Node Type": "Result"}})
    assert getattr(graph.data, "y", None) is None
    assert graph.label_log is None


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        [],
        {"Plan": "nope"},
        {"nothing": True},
    ],
)
def test_invalid_payloads_raise(payload: object) -> None:
    with pytest.raises(PlanParseError):
        plan_to_graph(payload)


def test_node_limit_is_enforced(explain_payload: dict[str, Any]) -> None:
    with pytest.raises(PlanParseError):
        plan_to_graph(explain_payload, max_nodes=2)


def test_deep_plan_parses_iteratively() -> None:
    node: dict[str, Any] = {"Node Type": "Result", "Plan Rows": 1, "Total Cost": 1.0}
    for _ in range(400):
        node = {
            "Node Type": "Limit",
            "Plan Rows": 1,
            "Actual Rows": 1,
            "Total Cost": 2.0,
            "Plans": [node],
        }
    graph = plan_to_graph({"Plan": node}, max_nodes=1_000)
    assert graph.num_nodes == 401
    assert graph.data.edge_index.shape == (2, 400)
