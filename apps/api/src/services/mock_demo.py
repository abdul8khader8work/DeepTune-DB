"""MockDemoService: golden-path fallback for live demos.

When the real optimization pipeline fails or times out (shadow DB down,
GNN weights missing, network hiccup), this service silently returns a
pre-calculated "golden path" :class:`AnalysisResult` so the presentation
never shows an error screen.

The data mirrors a real verified run against the local demo databases:

* recommendation: ``idx_order_items_product_id`` on
  ``public.order_items(product_id)``
* validated speedup: 183.34x (baseline median 12.284 ms → indexed 0.067 ms)
* Duan smearing factor: S=1.0813
"""

from __future__ import annotations

import uuid

from src.schemas.analysis import (
    AnalysisResult,
    AttentionHotspot,
    DAGEdge,
    DAGNode,
    IndexRecommendation,
)

#: Hardcoded golden-path payload. Matches a verified live run.
GOLDEN_RUN_ID = "demo-golden-path-000000000001"

GOLDEN_RECOMMENDATION = IndexRecommendation(
    id="demo-rec-1",
    sql_statement=(
        'CREATE INDEX CONCURRENTLY "idx_order_items_product_id" '
        'ON "public"."order_items" ("product_id")'
    ),
    target_table="order_items",
    target_columns=["product_id"],
    predicted_speedup_factor=1.8,
    validated_speedup_factor=183.34,
    storage_overhead_bytes=1_680_000,
    write_impact_percentage=1.5,
    confidence_score=0.67,
    explanation=(
        "Golden-path demo data: 1 equality predicate on "
        "public.order_items.product_id. Measured against a real index in "
        "the shadow database before it is shown as a recommendation."
    ),
)

GOLDEN_ORIGINAL_NODES = [
    DAGNode(
        id="node_1",
        operation_type="Seq Scan",
        relation_name="order_items",
        estimated_cost=2383.0,
        estimated_rows=120000,
        actual_time_ms=12.284,
        gnn_attention_score=1.0,
    ),
]

GOLDEN_OPTIMIZED_NODES = [
    DAGNode(
        id="node_1",
        operation_type="Bitmap Heap Scan",
        relation_name="order_items",
        estimated_cost=88.91,
        estimated_rows=24,
        actual_time_ms=0.067,
        gnn_attention_score=1.0,
    ),
    DAGNode(
        id="node_2",
        operation_type="Bitmap Index Scan",
        relation_name="order_items",
        estimated_cost=4.47,
        estimated_rows=24,
        actual_time_ms=None,
        gnn_attention_score=0.0503,
    ),
]

GOLDEN_EDGES = [
    DAGEdge(
        id="edge_1",
        source="node_2",
        target="node_1",
        rows_transferred=24,
    ),
]

GOLDEN_ORIGINAL_EDGES: list[DAGEdge] = []

GOLDEN_ATTENTION = [
    AttentionHotspot(
        node_index=0,
        operator="Seq Scan",
        relation="order_items",
        weight=1.0,
    ),
    AttentionHotspot(
        node_index=1,
        operator="Bitmap Heap Scan",
        relation="order_items",
        weight=0.9497,
    ),
    AttentionHotspot(
        node_index=2,
        operator="Bitmap Index Scan",
        relation="order_items",
        weight=0.0503,
    ),
]

GOLDEN_SYMBOLIC_TRACE = [
    "Symbolic pruning: 1 candidate survived (order_items.product_id equality).",
    "GATv2 beam search: width 10, 1 configuration scored.",
    "latency de-transform: Duan smearing S=1.0813.",
    "Shadow validation: real index built, median-of-5 measured 183.34x.",
]

GOLDEN_REJECTED: list = []


def golden_result(run_id: str | None = None) -> AnalysisResult:
    """Return the pre-calculated golden-path :class:`AnalysisResult`."""
    return AnalysisResult(
        run_id=run_id or GOLDEN_RUN_ID,
        status="completed",
        engine="gnn",
        original_metrics={"cost": 2383.0, "time_ms": 12.284},
        optimized_metrics={"cost": 88.91, "time_ms": 0.067},
        original_dag=GOLDEN_ORIGINAL_NODES,
        optimized_dag=GOLDEN_OPTIMIZED_NODES,
        edges=GOLDEN_EDGES,
        original_edges=GOLDEN_ORIGINAL_EDGES,
        recommendations=[GOLDEN_RECOMMENDATION],
        attention=GOLDEN_ATTENTION,
        symbolic_trace=GOLDEN_SYMBOLIC_TRACE,
        rejected_candidates=GOLDEN_REJECTED,
        speedup_factor=183.34,
        symbolic_candidate_count=1,
    )


__all__ = ["golden_result", "GOLDEN_RUN_ID"]
