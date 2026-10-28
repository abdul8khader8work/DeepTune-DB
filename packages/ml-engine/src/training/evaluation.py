"""Shared evaluation loop for training and the evaluation CLI."""

from __future__ import annotations

from typing import Iterable

import numpy as np
import torch
from torch import nn
from torch_geometric.loader import DataLoader

from training.metrics import regression_metrics


def evaluate_model(
    model: nn.Module,
    loader: DataLoader,
    device: str = "cpu",
) -> dict[str, float]:
    """Run the model in eval mode and compute millisecond-scale metrics."""
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

    y_true = np.expm1(np.asarray(targets, dtype=np.float64))
    y_pred = np.expm1(np.asarray(predictions, dtype=np.float64))
    return regression_metrics(y_true, y_pred)


def evaluate_predictions(
    y_true_ms: Iterable[float], y_pred_ms: Iterable[float]
) -> dict[str, float]:
    return regression_metrics(y_true_ms, y_pred_ms)
