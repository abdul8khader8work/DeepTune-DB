"""Patch 2 Task 3: the beam scores the *post-hypopg* plan, not the baseline.

These tests stand in for the shadow database: configuration keys are enumerated
by the engine, a hypothetical EXPLAIN payload is fabricated for each key, and
the GNN must then score that payload. The API-side half of the loop (real
``hypopg_create_index`` / ``hypopg_drop_index`` calls) is covered by
``apps/api/tests/test_hypothetical.py``.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from inference import InferenceConfig, PlanOptimizer, load_optimizer
from models.checkpoint import ModelConfig, build_model, save_checkpoint
from parsers.explain import PlanGraph, plan_to_graph
from parsers.schema import SchemaCatalog
from search.beam import (
    HeuristicPlanBuilder,
    configuration_key,
    enumerate_configurations,
)
from search.symbolic import generate_candidates


@pytest.fixture()
def checkpoint(tmp_path: Path) -> Path:
    config = ModelConfig()
    model = build_model(config)
    path = tmp_path / "random.pt"
    save_checkpoint(path, model, config, metadata={"epoch": 1, "synthetic": True})
    return path


@pytest.fixture()
def optimizer(checkpoint: Path) -> PlanOptimizer:
    return load_optimizer(InferenceConfig(checkpoint_path=str(checkpoint)))


def _indexed_payload(explain_payload: dict[str, Any]) -> dict[str, Any]:
    """Turn every Seq Scan into an Index Scan and drop the execution time."""

    payload = copy.deepcopy(explain_payload)

    def visit(node: dict[str, Any]) -> None:
        if node.get("Node Type") == "Seq Scan":
            node["Node Type"] = "Index Scan"
            node["Index Name"] = "idx_hypothetical"
        node["Total Cost"] = round(float(node.get("Total Cost", 1.0)) / 10.0, 2)
        for child in node.get("Plans", []) or []:
            visit(child)

    visit(payload["Plan"])
    payload["Execution Time"] = 3.0
    return payload


def test_configuration_key_is_order_insensitive(
    join_sql: str, catalog: SchemaCatalog
) -> None:
    candidates = generate_candidates(join_sql, catalog).candidates
    assert len(candidates) >= 2
    first, second = candidates[0], candidates[1]
    assert configuration_key((first, second)) == configuration_key((second, first))


def test_enumerate_configurations_is_breadth_first_and_budgeted(
    join_sql: str, catalog: SchemaCatalog
) -> None:
    candidates = generate_candidates(join_sql, catalog).candidates
    configurations = enumerate_configurations(candidates, catalog, max_indexes=3)

    assert configurations
    depths = [len(configuration) for configuration in configurations]
    assert depths == sorted(depths), "single indexes must be enumerated first"
    # At most one index per table, so no configuration repeats a table.
    for configuration in configurations:
        tables = [candidate.table.qualified_name for candidate in configuration]
        assert len(tables) == len(set(tables))

    limited = enumerate_configurations(candidates, catalog, limit=2)
    assert len(limited) == 2
    assert enumerate_configurations(candidates, catalog, limit=0) == []


def test_builder_prefers_the_hypothetical_plan(
    join_sql: str,
    catalog: SchemaCatalog,
    explain_payload: dict[str, Any],
) -> None:
    candidates = generate_candidates(join_sql, catalog).candidates
    base = plan_to_graph(explain_payload, catalog=catalog)
    hypothetical = plan_to_graph(_indexed_payload(explain_payload), catalog=catalog)
    key = configuration_key((candidates[0],))

    from inference import _HypotheticalPlanBuilder  # noqa: PLC0415 - private by design

    builder = _HypotheticalPlanBuilder({key: hypothetical}, HeuristicPlanBuilder())
    graph = builder.build(base, (candidates[0],))

    assert isinstance(graph, PlanGraph)
    assert "Index Scan" in graph.operators
    assert graph.execution_time_ms == pytest.approx(3.0)
    assert builder.scored == {key}
    assert builder.misses == set()

    # An unknown configuration must degrade, not raise.
    missing = builder.build(base, candidates[1:2])
    assert "Index Scan" not in missing.operators
    assert builder.misses == {configuration_key(candidates[1:2])}


def test_optimize_scores_every_prefetched_configuration(
    optimizer: PlanOptimizer,
    join_sql: str,
    catalog: SchemaCatalog,
    explain_payload: dict[str, Any],
) -> None:
    requests = optimizer.plan_requests(join_sql, catalog)
    assert requests
    assert all(request.create_sqls for request in requests)

    payload = _indexed_payload(explain_payload)
    qeps = {request.key: payload for request in requests}

    baseline = optimizer.optimize(join_sql, explain_payload, catalog)
    report = optimizer.optimize(
        join_sql, explain_payload, catalog, candidate_qeps=qeps
    )

    summary = [line for line in report.trace if line.startswith("hypopg:")]
    assert summary, report.trace
    assert "fell back to the offline builder" in summary[0]
    assert f"{len(requests)} hypothetical plan(s)" in summary[0]
    assert "0 configuration(s) fell back" in summary[0]

    # The winning configuration is explained with the post-index plan.
    assert report.plan_graph is not None
    assert "Index Scan" in report.plan_graph.operators
    assert baseline.plan_graph is not None
    assert "Index Scan" not in baseline.plan_graph.operators


def test_partial_prefetch_is_disclosed_in_the_trace(
    optimizer: PlanOptimizer,
    join_sql: str,
    catalog: SchemaCatalog,
    explain_payload: dict[str, Any],
) -> None:
    requests = optimizer.plan_requests(join_sql, catalog, limit=1)
    assert len(requests) == 1
    assert requests[0].depth == 1

    report = optimizer.optimize(
        join_sql,
        explain_payload,
        catalog,
        candidate_qeps={requests[0].key: _indexed_payload(explain_payload)},
    )
    summary = next(line for line in report.trace if line.startswith("hypopg:"))
    assert "1 hypothetical plan(s)" in summary
    assert "0 configuration(s) fell back" not in summary


def test_plan_requests_respects_the_prefetch_limit(
    optimizer: PlanOptimizer, join_sql: str, catalog: SchemaCatalog
) -> None:
    requests = optimizer.plan_requests(join_sql, catalog, limit=3)
    assert len(requests) == 3
    assert all(request.depth == 1 for request in requests)
