"""Beam search: scoring, tie-breaks, storage budgets, and width limits."""

from __future__ import annotations

from typing import Any

import pytest

from config import NODE_COST_INDEX, NODE_INDEX_SCAN_INDEX
from parsers.explain import PlanGraph, plan_to_graph
from parsers.schema import ColumnStats, SchemaCatalog, TableStats
from search.beam import (
    BeamSearch,
    BeamSearchConfig,
    HeuristicPlanBuilder,
    HeuristicScorer,
)
from search.types import IndexCandidate, TableRef


def _candidate(
    table: str,
    column: str,
    write_impact: float = 1.5,
    storage: int = 1_000,
    columns: tuple[str, ...] | None = None,
) -> IndexCandidate:
    selected = columns or (column,)
    return IndexCandidate(
        id=f"{table}-{column}",
        table=TableRef(schema="public", name=table),
        columns=selected,
        method="btree",
        create_sql=(
            f'CREATE INDEX CONCURRENTLY idx_{table}_{column} ON public."{table}" '
            f"USING btree ({', '.join(selected)})"
        ),
        storage_bytes=storage,
        write_impact_percentage=write_impact,
        priority=1.0,
        reason="test candidate",
    )


class ConstantScorer:
    def predict_log_latency(self, graph: PlanGraph) -> float:
        return 1.0


def test_heuristic_builder_reduces_scan_cost(explain_payload: dict[str, Any]) -> None:
    base = plan_to_graph(explain_payload)
    builder = HeuristicPlanBuilder()
    candidate = _candidate("orders", "customer_id")
    optimized = builder.build(base, [candidate])

    scan_index = base.operators.index("Seq Scan")
    assert optimized.data.x[scan_index, NODE_COST_INDEX] < base.data.x[scan_index, NODE_COST_INDEX]
    assert optimized.data.x[scan_index, NODE_INDEX_SCAN_INDEX].item() == 1.0
    assert optimized.execution_time_ms is None


def test_beam_tie_break_prefers_lowest_write_impact(explain_payload: dict[str, Any]) -> None:
    base = plan_to_graph(explain_payload)
    candidates = [
        _candidate("orders", "a", write_impact=9.0),
        _candidate("orders", "b", write_impact=1.0),
        _candidate("orders", "c", write_impact=5.0),
    ]
    result = BeamSearch(
        ConstantScorer(),
        config=BeamSearchConfig(width=5, max_indexes=1),
    ).search(base, candidates)

    assert result.configurations
    assert result.configurations[0].candidates[0].columns == ("b",)
    assert result.configurations[0].write_penalty == pytest.approx(0.01)


def test_beam_width_is_enforced(explain_payload: dict[str, Any]) -> None:
    base = plan_to_graph(explain_payload)
    candidates = [_candidate(f"t{index}", "id") for index in range(6)]
    result = BeamSearch(
        ConstantScorer(),
        config=BeamSearchConfig(width=2, max_indexes=1),
    ).search(base, candidates)
    assert "keep 2" in result.trace[0]


def test_storage_budget_blocks_configurations(explain_payload: dict[str, Any]) -> None:
    base = plan_to_graph(explain_payload)
    catalog = SchemaCatalog(
        tables=(
            TableStats(
                name="orders",
                row_count=100,
                total_bytes=1_000,
                columns=(ColumnStats("id", "bigint", n_distinct=100),),
            ),
        )
    )
    result = BeamSearch(
        ConstantScorer(),
        config=BeamSearchConfig(width=5, max_indexes=1, storage_budget_ratio=0.15),
    ).search(base, [_candidate("orders", "id", storage=10_000)], catalog)
    assert result.configurations == ()


def test_no_candidates_returns_baseline_only(explain_payload: dict[str, Any]) -> None:
    base = plan_to_graph(explain_payload)
    result = BeamSearch(HeuristicScorer()).search(base, [])
    assert result.baseline.is_baseline
    assert result.configurations == ()
    assert "no symbolic candidates" in result.trace[0]


def test_configuration_never_reuses_a_table(explain_payload: dict[str, Any]) -> None:
    base = plan_to_graph(explain_payload)
    candidates = [
        _candidate("orders", "a"),
        _candidate("orders", "b"),
        _candidate("customers", "id"),
    ]
    result = BeamSearch(
        HeuristicScorer(), config=BeamSearchConfig(width=5, max_indexes=2)
    ).search(base, candidates)
    for configuration in result.configurations:
        tables = [candidate.table.qualified_name for candidate in configuration.candidates]
        assert len(tables) == len(set(tables))
