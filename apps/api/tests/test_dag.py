"""EXPLAIN plan tree → API DAG contract."""

from src.services.dag import build_dag

PLAN = {
    "Node Type": "Hash Join",
    "Total Cost": 120.0,
    "Plan Rows": 50,
    "Actual Rows": 40,
    "Actual Total Time": 2.0,
    "Plans": [
        {
            "Node Type": "Seq Scan",
            "Relation Name": "orders",
            "Total Cost": 80.0,
            "Plan Rows": 1000,
            "Actual Rows": 900,
            "Actual Total Time": 1.2,
            "Plans": [],
        },
        {
            "Node Type": "Index Scan",
            "Relation Name": "users",
            "Total Cost": 40.0,
            "Plan Rows": 100,
            "Actual Rows": 90,
            "Actual Total Time": 0.3,
            "Plans": [],
        },
    ],
}


def test_build_dag_nodes_and_edges() -> None:
    dag = build_dag(PLAN)
    assert len(dag.nodes) == 3
    assert len(dag.edges) == 2
    assert dag.nodes[0].operation_type == "Hash Join"
    assert dag.nodes[0].gnn_attention_score == 1.0
    assert dag.max_cost == 120.0
    assert {edge.source for edge in dag.edges} == {"node_1"}


def test_build_dag_marks_relation_names() -> None:
    dag = build_dag(PLAN)
    relations = {node.relation_name for node in dag.nodes if node.relation_name}
    assert relations == {"orders", "users"}
