"""Shared evaluation loop for training and the evaluation CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import torch
from torch import nn
from torch_geometric.loader import DataLoader

from training.metrics import duan_smearing_factor, regression_metrics


@dataclass(frozen=True)
class EvaluationReport:
    """Millisecond metrics plus the calibration Duan's estimator needs."""

    metrics: dict[str, float]
    smearing_factor: float


def _log_predictions(
    model: nn.Module,
    loader: DataLoader,
    device: str = "cpu",
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(log1p(target), log1p(prediction))`` arrays in model space."""
    model.eval()
    predictions: list[float] = []
    targets: list[float] = []
    with torch.no_grad():
        for batch in loader:
            batch = batch.to(device)
            output = model(batch)
            predictions.extend(output.view(-1).detach().cpu().tolist())
            targets.extend(batch.y.view(-1).detach().cpu().tolist())

    if not targets:
        raise ValueError("Evaluation loader produced no samples")

    return (
        np.asarray(targets, dtype=np.float64),
        np.asarray(predictions, dtype=np.float64),
    )


def evaluate_model_report(
    model: nn.Module,
    loader: DataLoader,
    device: str = "cpu",
) -> EvaluationReport:
    """Run the model once and return metrics plus the Duan smearing factor."""
    log_targets, log_predictions = _log_predictions(model, loader, device=device)
    y_true = np.expm1(log_targets)
    y_pred = np.expm1(log_predictions)
    return EvaluationReport(
        metrics=regression_metrics(y_true, y_pred),
        smearing_factor=duan_smearing_factor(log_targets, log_predictions),
    )


def evaluate_model(
    model: nn.Module,
    loader: DataLoader,
    device: str = "cpu",
) -> dict[str, float]:
    """Run the model in eval mode and compute millisecond-scale metrics."""
    return evaluate_model_report(model, loader, device=device).metrics


def evaluate_predictions(
    y_true_ms: Iterable[float], y_pred_ms: Iterable[float]
) -> dict[str, float]:
    return regression_metrics(y_true_ms, y_pred_ms)
