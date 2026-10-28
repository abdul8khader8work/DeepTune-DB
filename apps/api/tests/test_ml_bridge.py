"""Phase 4 bridge: engine report -> API contracts, with no torch in the way."""

import math
from dataclasses import dataclass

from src.schemas.analysis import DAGEdge, DAGNode
from src.services import ml

_OPERATOR_WIDTH = 33  # len(config.OPERATOR_TYPES); only the tail is positional
_WIDTH = _OPERATOR_WIDTH + 6


@dataclass
class FakeAttention:
    node_index: int
    operator: str
    relation: str | None
    weight: float


@dataclass
class FakeRecommendation:
    id: str
    sql_statement: str
    target_table: str
    target_columns: tuple[str, ...]
    predicted_speedup_factor: float
    storage_overhead_bytes: int
    write_impact_percentage: float
    confidence_score: float
    explanation: str


@dataclass
class FakeMatrix:
    rows: list[list[float]]

    def size(self, dim: int) -> int:
        return len(self.rows) if dim == 0 else len(self.rows[0])

    def __getitem__(self, key: tuple[int, int]) -> float:
        return self.rows[key[0]][key[1]]


@dataclass
class FakeEdgeIndex:
    pairs: list[tuple[int, int]]

    def size(self, dim: int) -> int:
        return len(self.pairs) if dim == 1 else 2

    def __getitem__(self, key: tuple[int, int]) -> int:
        return self.pairs[key[1]][key[0]]


@dataclass
class FakeData:
    x: FakeMatrix
    edge_index: FakeEdgeIndex


@dataclass
class FakeGraph:
    data: FakeData
    operators: tuple[str, ...]
    relations: tuple[str | None, ...]


def _row(cost: float, rows: float) -> list[float]:
    values = [0.0] * _WIDTH
    values[_OPERATOR_WIDTH] = math.log1p(rows)
    values[_OPERATOR_WIDTH + 1] = math.log1p(rows)
    values[_OPERATOR_WIDTH + 2] = math.log1p(cost)
    return values


def _graph() -> FakeGraph:
    return FakeGraph(
        data=FakeData(
            x=FakeMatrix([_row(100.0, 10.0), _row(40.0, 5.0)]),
            edge_index=FakeEdgeIndex([(1, 0)]),
        ),
        operators=("Hash Join", "Seq Scan"),
        relations=(None, "orders"),
    )


def _nodes() -> list[DAGNode]:
    return [
        DAGNode(
            id="node_1",
            operation_type="Hash Join",
            estimated_cost=100.0,
            estimated_rows=10,
            gnn_attention_score=0.0,
        ),
        DAGNode(
            id="node_2",
            operation_type="Seq Scan",
            relation_name="orders",
            estimated_cost=40.0,
            estimated_rows=5,
            gnn_attention_score=0.0,
        ),
    ]


def test_graph_to_nodes_round_trips_costs_and_rows() -> None:
    nodes = ml.graph_to_nodes(_graph())
    assert [node.id for node in nodes] == ["node_1", "node_2"]
    assert nodes[0].operation_type == "Hash Join"
    assert nodes[0].estimated_cost == 100.0
    assert nodes[1].estimated_rows == 5
    assert nodes[1].relation_name == "orders"


def test_graph_to_edges_flips_child_to_parent() -> None:
    edges = ml.graph_to_edges(_graph())
    assert edges == [
        DAGEdge(
            id="edge_node_1_node_2",
            source="node_1",
            target="node_2",
            rows_transferred=5,
        )
    ]


def test_apply_attention_uses_real_weights_when_informative() -> None:
    attention = [
        FakeAttention(0, "Hash Join", None, 1.0),
        FakeAttention(1, "Seq Scan", "orders", 0.2),
    ]
    nodes, informative = ml.apply_attention(_nodes(), attention)
    assert informative is True
    assert nodes[0].gnn_attention_score == 1.0
    assert nodes[1].gnn_attention_score == 0.2


def test_apply_attention_falls_back_to_cost_when_uniform() -> None:
    attention = [
        FakeAttention(0, "Hash Join", None, 0.5),
        FakeAttention(1, "Seq Scan", "orders", 0.5),
    ]
    nodes, informative = ml.apply_attention(_nodes(), attention)
    assert informative is False
    # cost ratio: 100 / 100 -> 1.0, 40 / 100 -> 0.4
    assert nodes[0].gnn_attention_score == 1.0
    assert nodes[1].gnn_attention_score == 0.4


def test_apply_attention_without_records_is_a_noop() -> None:
    original = _nodes()
    nodes, informative = ml.apply_attention(original, [])
    assert informative is False
    assert nodes == original


def test_to_recommendations_namespaces_ids_by_run() -> None:
    @dataclass
    class Report:
        recommendations: tuple[FakeRecommendation, ...]

    report = Report(
        recommendations=(
            FakeRecommendation(
                id="candidate-1",
                sql_statement="CREATE INDEX CONCURRENTLY x ON public.orders (a)",
                target_table="orders",
                target_columns=("a", "b"),
                predicted_speedup_factor=2.345,
                storage_overhead_bytes=1024,
                write_impact_percentage=1.234,
                confidence_score=0.876,
                explanation="because",
            ),
        )
    )
    mapped = ml.to_recommendations(report, "run-9")
    assert mapped[0].id == "run-9:candidate-1"
    assert mapped[0].target_columns == ["a", "b"]
    assert mapped[0].predicted_speedup_factor == 2.35
    assert mapped[0].write_impact_percentage == 1.2
    assert mapped[0].validated_speedup_factor is None


def test_scale_metrics_shrinks_cost_with_latency() -> None:
    scaled = ml.scale_metrics(original_cost=1000.0, original_ms=400.0, predicted_ms=100.0)
    assert scaled == {"cost": 250.0, "time_ms": 100.0}


def test_scale_metrics_guards_against_zero_latency() -> None:
    scaled = ml.scale_metrics(original_cost=1000.0, original_ms=0.0, predicted_ms=0.0)
    assert scaled == {"cost": 1000.0, "time_ms": 0.0}
