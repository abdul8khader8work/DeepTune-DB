"""Public inference facade for the DeepTune neuro-symbolic engine.

The FastAPI lifespan loads :class:`PlanOptimizer` once and calls ``optimize`` per
request. This module must never import FastAPI, uvicorn, SQLAlchemy, or database
drivers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import torch

from config import (
    BEAM_WIDTH,
    MAX_INDEXES,
    STORAGE_BUDGET_RATIO,
    TIE_MARGIN,
)
from models.checkpoint import ModelConfig, load_checkpoint
from models.gatv2 import summarize_attention
from parsers.explain import PlanGraph, plan_to_graph
from parsers.schema import SchemaCatalog
from search.beam import (
    BeamSearch,
    BeamSearchConfig,
    HeuristicPlanBuilder,
    ModelScorer,
)
from search.symbolic import generate_candidates
from search.types import (
    BeamResult,
    IndexCandidate,
    NodeAttention,
    OptimizationReport,
    RankedConfiguration,
    Recommendation,
)

CandidatePlanBuilder = Callable[[PlanGraph, Sequence[IndexCandidate]], PlanGraph]


class _CallablePlanBuilder:
    """Adapts a Phase 4 callable (hypopg) to the PlanBuilder protocol."""

    def __init__(self, build_fn: CandidatePlanBuilder) -> None:
        self._build_fn = build_fn

    def build(
        self, base: PlanGraph, configuration: Sequence[IndexCandidate]
    ) -> PlanGraph:
        return self._build_fn(base, configuration)


@dataclass(frozen=True)
class InferenceConfig:
    checkpoint_path: str
    device: str = "cpu"
    beam_width: int = BEAM_WIDTH
    max_indexes: int = MAX_INDEXES
    storage_budget_ratio: float = STORAGE_BUDGET_RATIO
    tie_margin: float = TIE_MARGIN


def _confidence(result: BeamResult) -> float:
    if not result.configurations:
        return 0.0
    best = result.configurations[0]
    if len(result.configurations) == 1:
        return 0.85
    runner_up = result.configurations[1]
    denominator = max(runner_up.predicted_latency_ms, 1e-6)
    gap = max(0.0, runner_up.predicted_latency_ms - best.predicted_latency_ms) / denominator
    return round(min(0.95, 0.6 + gap), 2)


class PlanOptimizer:
    """Loads the GATv2 checkpoint once, then scores beam configurations."""

    def __init__(self, config: InferenceConfig) -> None:
        self._config = config
        self._model, self._model_config, self._metadata = load_checkpoint(
            config.checkpoint_path, map_location=config.device
        )
        self._model.eval()
        self._scorer = ModelScorer(self._model, device=config.device)
        self._default_builder = HeuristicPlanBuilder()

    @property
    def model_config(self) -> ModelConfig:
        return self._model_config

    @property
    def metadata(self) -> dict[str, object]:
        return dict(self._metadata)

    def optimize(
        self,
        sql: str,
        plan: object,
        catalog: SchemaCatalog,
        goal: str = "balanced",
        candidate_plan_builder: CandidatePlanBuilder | None = None,
    ) -> OptimizationReport:
        """Run symbolic pruning, beam search, and explainability extraction."""
        base_graph = plan_to_graph(plan, catalog=catalog)
        symbolic = generate_candidates(sql, catalog, goal=goal)
        builder = (
            _CallablePlanBuilder(candidate_plan_builder)
            if candidate_plan_builder is not None
            else self._default_builder
        )
        search = BeamSearch(
            self._scorer,
            plan_builder=builder,
            config=BeamSearchConfig(
                width=self._config.beam_width,
                max_indexes=self._config.max_indexes,
                tie_margin=self._config.tie_margin,
                storage_budget_ratio=self._config.storage_budget_ratio,
            ),
        )
        result = search.search(base_graph, symbolic.candidates, catalog)
        best = result.configurations[0] if result.configurations else None

        if best is not None:
            explanation_graph = builder.build(base_graph, best.candidates)
        else:
            explanation_graph = base_graph
        attention = self._attention(explanation_graph)
        hotspot = (
            f"{attention[0].operator}"
            f"{' on ' + attention[0].relation if attention[0].relation else ''}"
            if attention
            else "the plan root"
        )

        confidence = _confidence(result)
        recommendations: list[Recommendation] = []
        if best is not None:
            for candidate in best.candidates:
                recommendations.append(
                    Recommendation(
                        id=candidate.id,
                        sql_statement=candidate.create_sql,
                        target_table=candidate.table.name,
                        target_columns=candidate.columns,
                        predicted_speedup_factor=best.predicted_speedup,
                        storage_overhead_bytes=candidate.storage_bytes,
                        write_impact_percentage=candidate.write_impact_percentage,
                        confidence_score=confidence,
                        explanation=(
                            f"Best beam configuration ({len(best.candidates)} index(es)) "
                            f"predicts {best.predicted_latency_ms:.2f} ms, "
                            f"{best.predicted_speedup:.2f}x faster than baseline. "
                            f"Attention hotspot: {hotspot}. {candidate.reason}."
                        ),
                    )
                )

        baseline_ms = (
            base_graph.execution_time_ms
            if base_graph.execution_time_ms is not None
            else result.baseline.predicted_latency_ms
        )
        return OptimizationReport(
            baseline_latency_ms=round(float(baseline_ms), 4),
            recommendations=tuple(recommendations),
            configurations=result.configurations,
            attention=attention,
            trace=result.trace,
            rejected=symbolic.rejected,
            tables=symbolic.tables,
            symbolic_candidate_count=len(symbolic.candidates),
            plan_graph=explanation_graph if best is not None else None,
        )

    def rank_configurations(
        self,
        sql: str,
        plan: object,
        catalog: SchemaCatalog,
        goal: str = "balanced",
        candidate_plan_builder: CandidatePlanBuilder | None = None,
    ) -> tuple[RankedConfiguration, ...]:
        """Expose the ranked configurations without building recommendations."""
        report = self.optimize(
            sql,
            plan,
            catalog,
            goal=goal,
            candidate_plan_builder=candidate_plan_builder,
        )
        return report.configurations

    def _attention(self, graph: PlanGraph) -> tuple[NodeAttention, ...]:
        data = graph.data.to(self._config.device)
        self._model.eval()
        with torch.no_grad():
            _, attentions = self._model(data, return_attention=True)
        if not attentions:
            return ()
        edge_index, alpha = attentions[-1]
        summary = summarize_attention(edge_index.cpu(), alpha.cpu(), graph.num_nodes)
        return tuple(
            NodeAttention(
                node_index=item.node_index,
                operator=graph.operators[item.node_index],
                relation=graph.relations[item.node_index],
                weight=round(item.weight, 6),
            )
            for item in summary[:10]
        )


def load_optimizer(config: InferenceConfig) -> PlanOptimizer:
    """Convenience constructor mirroring the API lifespan usage."""
    return PlanOptimizer(config)
