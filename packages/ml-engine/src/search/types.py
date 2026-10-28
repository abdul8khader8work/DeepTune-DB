"""Shared dataclasses for symbolic pruning, beam search, and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

PredicateKind = Literal["equality", "range", "join", "grouping", "ordering"]
IndexMethod = Literal["btree", "hash", "gin"]


@dataclass(frozen=True)
class TableRef:
    schema: str
    name: str

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"


@dataclass(frozen=True)
class ColumnRef:
    table: TableRef
    name: str

    @property
    def qualified_name(self) -> str:
        return f"{self.table.qualified_name}.{self.name}"


@dataclass(frozen=True)
class Predicate:
    column: ColumnRef
    kind: PredicateKind
    operator: str


@dataclass(frozen=True)
class IndexCandidate:
    id: str
    table: TableRef
    columns: tuple[str, ...]
    method: IndexMethod
    create_sql: str
    storage_bytes: int
    write_impact_percentage: float
    priority: float
    reason: str


@dataclass(frozen=True)
class PruningRejection:
    description: str
    reason: str


@dataclass(frozen=True)
class SymbolicResult:
    candidates: tuple[IndexCandidate, ...] = field(default_factory=tuple)
    rejected: tuple[PruningRejection, ...] = field(default_factory=tuple)
    tables: tuple[TableRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RankedConfiguration:
    candidates: tuple[IndexCandidate, ...]
    predicted_log_latency: float
    predicted_latency_ms: float
    predicted_speedup: float
    write_penalty: float
    is_baseline: bool = False


@dataclass(frozen=True)
class BeamResult:
    baseline: RankedConfiguration
    configurations: tuple[RankedConfiguration, ...] = field(default_factory=tuple)
    trace: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class NodeAttention:
    node_index: int
    operator: str
    relation: str | None
    weight: float


@dataclass(frozen=True)
class Recommendation:
    id: str
    sql_statement: str
    target_table: str
    target_columns: tuple[str, ...]
    predicted_speedup_factor: float
    storage_overhead_bytes: int
    write_impact_percentage: float
    confidence_score: float
    explanation: str


@dataclass(frozen=True)
class OptimizationReport:
    baseline_latency_ms: float
    recommendations: tuple[Recommendation, ...]
    configurations: tuple[RankedConfiguration, ...]
    attention: tuple[NodeAttention, ...]
    trace: tuple[str, ...]
    rejected: tuple[PruningRejection, ...]
    tables: tuple[TableRef, ...]
    symbolic_candidate_count: int = 0
