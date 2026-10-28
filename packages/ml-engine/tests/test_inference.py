"""End-to-end inference facade with a temporary random checkpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from inference import InferenceConfig, PlanOptimizer, load_optimizer
from models.checkpoint import ModelConfig, build_model, save_checkpoint
from parsers.schema import SchemaCatalog


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


def test_optimize_returns_reviewable_report(
    optimizer: PlanOptimizer,
    join_sql: str,
    explain_payload: dict[str, Any],
    catalog: SchemaCatalog,
) -> None:
    report = optimizer.optimize(join_sql, explain_payload, catalog)

    assert report.baseline_latency_ms == pytest.approx(12.5)
    assert report.symbolic_candidate_count > 0
    assert report.recommendations
    assert report.configurations
    assert report.attention
    assert report.trace
    assert report.tables

    for recommendation in report.recommendations:
        assert recommendation.sql_statement.startswith("CREATE INDEX CONCURRENTLY")
        assert recommendation.target_table
        assert recommendation.target_columns
        assert recommendation.predicted_speedup_factor > 0.0
        assert 0.0 <= recommendation.confidence_score <= 1.0
        assert "Attention hotspot" in recommendation.explanation
        assert "DROP" not in recommendation.sql_statement.upper()


def test_rank_configurations_matches_report(
    optimizer: PlanOptimizer,
    join_sql: str,
    explain_payload: dict[str, Any],
    catalog: SchemaCatalog,
) -> None:
    report = optimizer.optimize(join_sql, explain_payload, catalog)
    configurations = optimizer.rank_configurations(join_sql, explain_payload, catalog)
    assert isinstance(configurations, tuple)
    assert len(configurations) == len(report.configurations)
    for configuration in configurations:
        assert configuration.predicted_latency_ms >= 0
        assert configuration.predicted_speedup > 0


def test_optimizer_exposes_checkpoint_metadata(optimizer: PlanOptimizer) -> None:
    assert optimizer.metadata["synthetic"] is True
    assert optimizer.model_config == ModelConfig()


def test_optimize_without_candidates_still_reports(
    optimizer: PlanOptimizer,
    explain_payload: dict[str, Any],
    catalog: SchemaCatalog,
) -> None:
    report = optimizer.optimize("SELECT id FROM orders", explain_payload, catalog)
    assert report.recommendations == ()
    assert report.rejected
    assert report.configurations == ()


def test_custom_plan_builder_is_used(
    optimizer: PlanOptimizer,
    join_sql: str,
    explain_payload: dict[str, Any],
    catalog: SchemaCatalog,
) -> None:
    calls: list[int] = []

    def builder(graph, configuration):
        calls.append(len(configuration))
        return graph

    report = optimizer.optimize(
        join_sql, explain_payload, catalog, candidate_plan_builder=builder
    )
    assert calls
    assert report.recommendations
