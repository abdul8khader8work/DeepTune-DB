"""GNN-guided beam search over symbolically valid index configurations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol, Sequence

import torch
from torch_geometric.data import Data

from config import (
    BEAM_WIDTH,
    MAX_INDEXES,
    NODE_ACTUAL_ROWS_INDEX,
    NODE_COST_INDEX,
    NODE_INDEX_SCAN_INDEX,
    STORAGE_BUDGET_RATIO,
    TIE_MARGIN,
    expm1,
)
from parsers.explain import PlanGraph
from parsers.schema import SchemaCatalog
from search.types import (
    BeamResult,
    IndexCandidate,
    RankedConfiguration,
)


class PlanBuilder(Protocol):
    """Builds the QEP graph that results from a candidate configuration."""

    def build(
        self, base: PlanGraph, configuration: Sequence[IndexCandidate]
    ) -> PlanGraph: ...


class GraphScorer(Protocol):
    """Scores a QEP graph in log(1 + latency_ms) space."""

    def predict_log_latency(self, graph: PlanGraph) -> float: ...


@dataclass(frozen=True)
class BeamSearchConfig:
    width: int = BEAM_WIDTH
    max_indexes: int = MAX_INDEXES
    tie_margin: float = TIE_MARGIN
    storage_budget_ratio: float = STORAGE_BUDGET_RATIO


@dataclass(frozen=True)
class _State:
    candidates: tuple[IndexCandidate, ...]
    log_latency: float
    latency_ms: float
    write_penalty: float


class HeuristicPlanBuilder:
    """Deterministic stand-in for hypopg until Phase 4 injects real plans.

    It flips matching scan nodes to index scans and shrinks their cost/rows by a
    column-count factor. The API replaces this with the actual hypopg plan, but
    the interface is identical.
    """

    def build(
        self, base: PlanGraph, configuration: Sequence[IndexCandidate]
    ) -> PlanGraph:
        data = base.data.clone()
        factors: dict[str, float] = {}
        for candidate in configuration:
            factor = 1.0 / (1.0 + 0.3 * len(candidate.columns))
            key = candidate.table.name.lower()
            factors[key] = min(factors.get(key, 1.0), factor)

        if factors:
            mask_flags: list[bool] = []
            factor_values: list[float] = []
            for relation in base.relations:
                factor = factors.get(relation.lower()) if relation else None
                mask_flags.append(factor is not None)
                factor_values.append(factor if factor is not None else 1.0)

            mask = torch.tensor(mask_flags, dtype=torch.bool)
            if bool(mask.any()):
                x = data.x.clone()
                active_factors = torch.tensor(
                    [
                        value
                        for value, active in zip(factor_values, mask_flags)
                        if active
                    ],
                    dtype=torch.float32,
                )
                cost = torch.expm1(x[mask, NODE_COST_INDEX])
                rows = torch.expm1(x[mask, NODE_ACTUAL_ROWS_INDEX])
                x[mask, NODE_COST_INDEX] = torch.log1p(cost * active_factors)
                x[mask, NODE_ACTUAL_ROWS_INDEX] = torch.log1p(rows * active_factors)
                x[mask, NODE_INDEX_SCAN_INDEX] = 1.0
                data.x = x
                self._propagate_costs(data, base)

        return PlanGraph(
            data=data,
            operators=base.operators,
            relations=base.relations,
            execution_time_ms=None,
            planning_time_ms=base.planning_time_ms,
        )

    def _propagate_costs(self, data: Data, base: PlanGraph) -> None:
        """Roll child savings up the plan tree so the root cost reflects them."""
        edge_index = data.edge_index
        if edge_index is None or edge_index.size(1) == 0:
            return
        children: dict[int, list[int]] = defaultdict(list)
        for child, parent in zip(edge_index[0].tolist(), edge_index[1].tolist()):
            children[parent].append(child)

        x = data.x.clone()
        base_x = base.data.x
        for node in range(x.size(0) - 1, -1, -1):
            node_children = children.get(node)
            if not node_children:
                continue
            old_total = float(torch.expm1(base_x[node, NODE_COST_INDEX]).item())
            old_child_total = float(
                torch.expm1(base_x[node_children, NODE_COST_INDEX]).sum().item()
            )
            new_child_total = float(
                torch.expm1(x[node_children, NODE_COST_INDEX]).sum().item()
            )
            own_cost = max(old_total - old_child_total, 0.0)
            x[node, NODE_COST_INDEX] = torch.log1p(
                torch.tensor(own_cost + new_child_total, dtype=x.dtype)
            )
        data.x = x


class HeuristicScorer:
    """Cheap monotonic scorer used for tests and offline smoke runs."""

    def predict_log_latency(self, graph: PlanGraph) -> float:
        x = graph.data.x
        costs = torch.expm1(x[:, NODE_COST_INDEX]).sum()
        rows = torch.expm1(x[:, NODE_ACTUAL_ROWS_INDEX]).sum()
        return float(torch.log1p(costs * 0.05 + rows * 1e-4).item())


class BeamSearch:
    """Width-limited search ranked by predicted latency.

    The symbolic engine bounds the candidate set; the beam controls the
    combinatorial join of candidates. Configurations use at most one index per
    table and must stay inside the per-table storage budget.
    """

    def __init__(
        self,
        scorer: GraphScorer,
        plan_builder: PlanBuilder | None = None,
        config: BeamSearchConfig | None = None,
    ) -> None:
        self._scorer = scorer
        self._builder = plan_builder or HeuristicPlanBuilder()
        self._config = config or BeamSearchConfig()

    def search(
        self,
        base_graph: PlanGraph,
        candidates: Sequence[IndexCandidate],
        catalog: SchemaCatalog | None = None,
    ) -> BeamResult:
        baseline_log = self._scorer.predict_log_latency(base_graph)
        baseline_ms = max(expm1(baseline_log), 1e-6)
        # Prefer the measured baseline when EXPLAIN ANALYZE supplied one; the
        # model's own baseline is only a fallback for unlabelled plans.
        speedup_reference = (
            max(base_graph.execution_time_ms, 1e-6)
            if base_graph.execution_time_ms is not None
            else baseline_ms
        )
        baseline = RankedConfiguration(
            candidates=(),
            predicted_log_latency=baseline_log,
            predicted_latency_ms=round(baseline_ms, 4),
            predicted_speedup=1.0,
            write_penalty=0.0,
            is_baseline=True,
        )

        if not candidates:
            return BeamResult(
                baseline=baseline,
                configurations=(),
                trace=("no symbolic candidates survived pruning",),
            )

        states = [_State(candidates=(), log_latency=baseline_log, latency_ms=baseline_ms, write_penalty=0.0)]
        seen_states: dict[tuple[str, ...], _State] = {}
        trace: list[str] = []

        for depth in range(1, self._config.max_indexes + 1):
            expanded: dict[tuple[str, ...], _State] = {}
            for state in states:
                used_tables = {candidate.table.qualified_name for candidate in state.candidates}
                used_ids = {candidate.id for candidate in state.candidates}
                for candidate in candidates:
                    if candidate.id in used_ids:
                        continue
                    if candidate.table.qualified_name in used_tables:
                        continue
                    configuration = state.candidates + (candidate,)
                    if not self._within_budget(configuration, catalog):
                        continue
                    key = tuple(sorted(item.id for item in configuration))
                    if key in expanded:
                        continue
                    graph = self._builder.build(base_graph, configuration)
                    log_latency = self._scorer.predict_log_latency(graph)
                    latency_ms = max(expm1(log_latency), 1e-6)
                    write_penalty = sum(
                        item.write_impact_percentage for item in configuration
                    ) / 100.0
                    expanded[key] = _State(
                        candidates=configuration,
                        log_latency=log_latency,
                        latency_ms=latency_ms,
                        write_penalty=write_penalty,
                    )

            if not expanded:
                break
            seen_states.update(expanded)
            ordered = self._order(list(expanded.values()))
            states = ordered[: self._config.width]
            trace.append(
                f"depth {depth}: {len(expanded)} configurations -> keep "
                f"{len(states)} (best {states[0].latency_ms:.2f} ms)"
            )

        ranked = self._order(list(seen_states.values()))[: max(self._config.width, 10)]
        configurations = tuple(
            RankedConfiguration(
                candidates=state.candidates,
                predicted_log_latency=state.log_latency,
                predicted_latency_ms=round(state.latency_ms, 4),
                predicted_speedup=round(speedup_reference / state.latency_ms, 3),
                write_penalty=round(state.write_penalty, 3),
            )
            for state in ranked
        )
        return BeamResult(
            baseline=baseline,
            configurations=configurations,
            trace=tuple(trace),
        )

    def _within_budget(
        self,
        configuration: Sequence[IndexCandidate],
        catalog: SchemaCatalog | None,
    ) -> bool:
        if catalog is None:
            return True
        totals: dict[tuple[str, str], int] = defaultdict(int)
        for candidate in configuration:
            totals[(candidate.table.schema, candidate.table.name)] += candidate.storage_bytes
        for (schema_name, table_name), total in totals.items():
            table = catalog.table(schema_name, table_name)
            if table is None or table.effective_bytes <= 0:
                continue
            if total > table.effective_bytes * self._config.storage_budget_ratio:
                return False
        return True

    def _order(self, states: Sequence[_State]) -> list[_State]:
        ordered = sorted(states, key=lambda state: state.latency_ms)
        if not ordered:
            return []
        best = ordered[0].latency_ms
        threshold = best * (1.0 + self._config.tie_margin)
        near = [state for state in ordered if state.latency_ms <= threshold]
        far = [state for state in ordered if state.latency_ms > threshold]
        near.sort(key=lambda state: (state.write_penalty, len(state.candidates), state.latency_ms))
        return near + far


class ModelScorer:
    """GATv2-backed scorer; always runs under ``torch.no_grad()``."""

    def __init__(self, model: torch.nn.Module, device: str = "cpu") -> None:
        self._model = model
        self._device = torch.device(device)

    def predict_log_latency(self, graph: PlanGraph) -> float:
        data = graph.data.to(self._device)
        self._model.eval()
        with torch.no_grad():
            output = self._model(data)
        return float(output.view(-1)[0].item())
