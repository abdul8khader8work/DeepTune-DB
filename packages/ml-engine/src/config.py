"""Engine-wide feature vocabularies, model defaults, and safety limits."""

from __future__ import annotations

import math
import random

import numpy as np
import torch

# Physical operators emitted by PostgreSQL. The order is part of the model
# contract: changing it invalidates existing checkpoints.
OPERATOR_TYPES: tuple[str, ...] = (
    "Seq Scan",
    "Index Scan",
    "Index Only Scan",
    "Bitmap Heap Scan",
    "Bitmap Index Scan",
    "Hash Join",
    "Nested Loop",
    "Merge Join",
    "Hash",
    "Sort",
    "Incremental Sort",
    "Aggregate",
    "GroupAggregate",
    "HashAggregate",
    "Limit",
    "Result",
    "Materialize",
    "Memoize",
    "CTE Scan",
    "Subquery Scan",
    "Append",
    "Gather",
    "Gather Merge",
    "Unique",
    "WindowAgg",
    "SetOp",
    "Foreign Scan",
    "Function Scan",
    "Values Scan",
    "Tid Scan",
    "ProjectSet",
    "ModifyTable",
    "Unknown",
)

OPERATOR_INDEX: dict[str, int] = {name: i for i, name in enumerate(OPERATOR_TYPES)}
UNKNOWN_OPERATOR_INDEX: int = OPERATOR_INDEX["Unknown"]

JOIN_TYPES: tuple[str, ...] = (
    "INNER",
    "LEFT",
    "RIGHT",
    "FULL",
    "CROSS",
    "SEMI",
    "ANTI",
    "NONE",
)
JOIN_INDEX: dict[str, int] = {name: i for i, name in enumerate(JOIN_TYPES)}
NONE_JOIN_INDEX: int = JOIN_INDEX["NONE"]

INDEX_SCAN_OPERATORS = frozenset({"Index Scan", "Index Only Scan", "Bitmap Index Scan"})

# Node feature layout: [operator one-hot | 6 numeric features].
NODE_NUMERIC_FEATURES = 6
NODE_FEATURE_DIM = len(OPERATOR_TYPES) + NODE_NUMERIC_FEATURES
NODE_EST_ROWS_INDEX = len(OPERATOR_TYPES)
NODE_ACTUAL_ROWS_INDEX = NODE_EST_ROWS_INDEX + 1
NODE_COST_INDEX = NODE_EST_ROWS_INDEX + 2
NODE_RELATION_SIZE_INDEX = NODE_EST_ROWS_INDEX + 3
NODE_SELECTIVITY_INDEX = NODE_EST_ROWS_INDEX + 4
NODE_INDEX_SCAN_INDEX = NODE_EST_ROWS_INDEX + 5

# Edge feature layout: [log cardinality | log data size | join one-hot].
EDGE_NUMERIC_FEATURES = 2
EDGE_FEATURE_DIM = EDGE_NUMERIC_FEATURES + len(JOIN_TYPES)

MODEL_HIDDEN_DIM = 128
MODEL_HEADS = 4
MODEL_DROPOUT = 0.2
MODEL_LAYERS = 3

TARGET_LOG_BASE = math.e

BEAM_WIDTH = 5
MAX_INDEXES = 3
TIE_MARGIN = 0.05
STORAGE_BUDGET_RATIO = 0.15
MAX_INDEXES_PER_WRITE_TABLE = 3
MAX_CANDIDATES = 12
MAX_PLAN_NODES = 5_000

GOAL_MAX_COLUMNS: dict[str, int] = {
    "read_performance": 3,
    "balanced": 2,
    "minimal_storage": 1,
}

WRITE_HEAVY_IMPACT = 0.35
DEFAULT_ROW_WIDTH_BYTES = 16
INDEX_ROW_OVERHEAD_BYTES = 6


def log1p(value: float) -> float:
    """Numerically safe log(1 + x) for non-negative features."""
    return math.log1p(max(0.0, float(value)))


def expm1(value: float) -> float:
    """Inverse of :func:`log1p`, clamped to keep exp() finite."""
    return math.expm1(min(float(value), 50.0))


def set_seed(seed: int) -> None:
    """Make workload generation and training reproducible."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():  # pragma: no cover - CPU-first project
        torch.cuda.manual_seed_all(seed)
