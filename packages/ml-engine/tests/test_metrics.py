"""Regression metrics: MAE, RMSE, Spearman, Q-error, MAPE, speedup."""

from __future__ import annotations

import math

import pytest

from config import inverse_log_latency
from training.metrics import (
    duan_smearing_factor,
    geometric_mean_speedup,
    mae_ms,
    mape_percent,
    median_q_error,
    regression_metrics,
    rmse_ms,
    spearman_rho,
)


def test_perfect_predictions() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert mae_ms(values, values) == 0.0
    assert rmse_ms(values, values) == 0.0
    assert spearman_rho(values, values) == pytest.approx(1.0)
    assert median_q_error(values, values) == pytest.approx(1.0)
    assert mape_percent(values, values) == 0.0


def test_known_error_values() -> None:
    assert mae_ms([1.0, 2.0], [2.0, 4.0]) == pytest.approx(1.5)
    assert rmse_ms([1.0, 2.0], [2.0, 4.0]) == pytest.approx(math.sqrt(2.5))
    assert mape_percent([10.0, 20.0], [12.0, 18.0]) == pytest.approx(15.0)


def test_spearman_detects_monotonic_and_inverse_rankings() -> None:
    true = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert spearman_rho(true, [10.0, 20.0, 30.0, 40.0, 50.0]) == pytest.approx(1.0)
    assert spearman_rho(true, [50.0, 40.0, 30.0, 20.0, 10.0]) == pytest.approx(-1.0)
    assert spearman_rho(true, [1.0, 1.0, 1.0, 1.0, 1.0]) == 0.0


def test_median_q_error_is_symmetric() -> None:
    assert median_q_error([10.0], [20.0]) == pytest.approx(2.0)
    assert median_q_error([20.0], [10.0]) == pytest.approx(2.0)


def test_geometric_mean_speedup() -> None:
    assert geometric_mean_speedup([100.0, 400.0], [50.0, 200.0]) == pytest.approx(2.0)


def test_regression_bundle_uses_regression_terms_only() -> None:
    report = regression_metrics([1.0, 2.0, 3.0], [1.1, 1.9, 3.4])
    assert set(report) == {
        "mae_ms",
        "rmse_ms",
        "spearman_rho",
        "median_q_error",
        "mape_percent",
    }
    assert "accuracy" not in report
    assert report["mae_ms"] > 0


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError):
        mae_ms([1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        mae_ms([], [])


def test_duan_smearing_factor_recovers_the_mean() -> None:
    # Residuals +log(2), 0, -log(2): mean(exp(residual)) = (2 + 1 + 0.5) / 3.
    true_log = [math.log(2.0), 0.0, -math.log(2.0)]
    pred_log = [0.0, 0.0, 0.0]
    factor = duan_smearing_factor(true_log, pred_log)
    assert factor == pytest.approx((2.0 + 1.0 + 0.5) / 3.0)


def test_duan_smearing_factor_is_one_for_perfect_predictions() -> None:
    values = [0.0, 1.0, 2.0, 3.0]
    assert duan_smearing_factor(values, values) == pytest.approx(1.0)


def test_inverse_log_latency_matches_expm1_without_calibration() -> None:
    assert inverse_log_latency(2.5) == pytest.approx(math.expm1(2.5))
    assert inverse_log_latency(2.5, 1.0) == pytest.approx(math.expm1(2.5))


def test_inverse_log_latency_applies_the_multiplicative_factor() -> None:
    # E[y|x] = exp(z_hat) * S - 1, not expm1(z_hat) * S.
    assert inverse_log_latency(2.5, 1.4) == pytest.approx(
        math.exp(2.5) * 1.4 - 1.0
    )


def test_inverse_log_latency_rejects_a_poisoned_factor() -> None:
    assert inverse_log_latency(1.0, 0.0) == pytest.approx(math.expm1(1.0))
    assert inverse_log_latency(1.0, -3.0) == pytest.approx(math.expm1(1.0))
