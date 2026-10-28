"""Training package: workload generation, datasets, metrics, and CLIs."""

from training.dataset import (
    PlanGraphDataset,
    apply_edge_dropout,
    concat_datasets,
    make_loader,
    split_dataset,
)
from training.evaluation import evaluate_model
from training.metrics import (
    geometric_mean_speedup,
    mae_ms,
    mape_percent,
    median_q_error,
    regression_metrics,
    rmse_ms,
    spearman_rho,
)
from training.workload import (
    SyntheticWorkload,
    WorkloadSample,
    build_demo_catalog,
    curriculum_tier,
    generate_workload,
)

__all__ = [
    "PlanGraphDataset",
    "SyntheticWorkload",
    "WorkloadSample",
    "apply_edge_dropout",
    "build_demo_catalog",
    "concat_datasets",
    "curriculum_tier",
    "evaluate_model",
    "generate_workload",
    "geometric_mean_speedup",
    "mae_ms",
    "make_loader",
    "mape_percent",
    "median_q_error",
    "regression_metrics",
    "rmse_ms",
    "spearman_rho",
    "split_dataset",
]
