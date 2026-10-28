"""Regression metrics for the cost model.

The GNN is a regressor: classification accuracy is never a valid metric here.
We report MAE, RMSE, Spearman rank correlation, median Q-error, and MAPE.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

_EPSILON = 1e-9


def _as_arrays(
    y_true: Iterable[float], y_pred: Iterable[float]
) -> tuple[np.ndarray, np.ndarray]:
    true = np.asarray(list(y_true), dtype=np.float64).reshape(-1)
    pred = np.asarray(list(y_pred), dtype=np.float64).reshape(-1)
    if true.shape != pred.shape:
        raise ValueError("y_true and y_pred must have the same length")
    if true.size == 0:
        raise ValueError("Metrics require at least one sample")
    return true, pred


def mae_ms(y_true: Iterable[float], y_pred: Iterable[float]) -> float:
    true, pred = _as_arrays(y_true, y_pred)
    return float(np.mean(np.abs(pred - true)))


def rmse_ms(y_true: Iterable[float], y_pred: Iterable[float]) -> float:
    true, pred = _as_arrays(y_true, y_pred)
    return float(np.sqrt(np.mean((pred - true) ** 2)))


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=np.float64)
    ranks[order] = np.arange(1, values.size + 1, dtype=np.float64)
    # Average tied ranks so Spearman is correct with repeated predictions.
    sorted_values = values[order]
    start = 0
    while start < sorted_values.size:
        end = start + 1
        while end < sorted_values.size and sorted_values[end] == sorted_values[start]:
            end += 1
        if end - start > 1:
            average = (start + 1 + end) / 2.0
            ranks[order[start:end]] = average
        start = end
    return ranks


def spearman_rho(y_true: Iterable[float], y_pred: Iterable[float]) -> float:
    true, pred = _as_arrays(y_true, y_pred)
    true_ranks = _average_ranks(true)
    pred_ranks = _average_ranks(pred)
    if np.std(true_ranks) < _EPSILON or np.std(pred_ranks) < _EPSILON:
        return 0.0
    return float(np.corrcoef(true_ranks, pred_ranks)[0, 1])


def median_q_error(y_true: Iterable[float], y_pred: Iterable[float]) -> float:
    true, pred = _as_arrays(y_true, y_pred)
    safe_true = np.maximum(true, _EPSILON)
    safe_pred = np.maximum(pred, _EPSILON)
    ratios = np.maximum(safe_pred / safe_true, safe_true / safe_pred)
    return float(np.median(ratios))


def mape_percent(y_true: Iterable[float], y_pred: Iterable[float]) -> float:
    true, pred = _as_arrays(y_true, y_pred)
    mask = true > _EPSILON
    if not bool(mask.any()):
        return 0.0
    return float(np.mean(np.abs(pred[mask] - true[mask]) / true[mask]) * 100.0)


def geometric_mean_speedup(
    baseline_ms: Iterable[float], optimized_ms: Iterable[float]
) -> float:
    baseline, optimized = _as_arrays(baseline_ms, optimized_ms)
    ratios = np.maximum(baseline, _EPSILON) / np.maximum(optimized, _EPSILON)
    return float(np.exp(np.mean(np.log(ratios))))


def regression_metrics(
    y_true_ms: Iterable[float], y_pred_ms: Iterable[float]
) -> dict[str, float]:
    """Full metric bundle on the original (millisecond) scale."""
    true, pred = _as_arrays(y_true_ms, y_pred_ms)
    pred = np.maximum(pred, 0.0)
    return {
        "mae_ms": round(mae_ms(true, pred), 4),
        "rmse_ms": round(rmse_ms(true, pred), 4),
        "spearman_rho": round(spearman_rho(true, pred), 4),
        "median_q_error": round(median_q_error(true, pred), 4),
        "mape_percent": round(mape_percent(true, pred), 4),
    }
