import numpy as np
import pandas as pd

from src.reliability.statistics import (
    bootstrap_excess_ci,
    deflated_sharpe_probability,
    evaluate_outperformance,
)
from src.reliability.walk_forward import evaluate_regimes, rolling_windows


def _returns(days=504, edge=0.0, seed=7):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2020-01-01", periods=days)
    benchmark = pd.Series(rng.normal(0.0003, 0.01, days), index=index)
    strategy = benchmark + edge + rng.normal(0, 0.001, days)
    return strategy, benchmark


def test_bootstrap_excess_ci_distinguishes_durable_edge():
    strategy, benchmark = _returns(edge=0.001)

    result = bootstrap_excess_ci(
        strategy, benchmark, n_boot=500, block_size=20, seed=11
    )

    assert result["lower"] > 0
    assert result["probability_positive"] >= 0.99


def test_release_gate_rejects_indistinguishable_returns():
    strategy, benchmark = _returns(edge=0.0)

    result = evaluate_outperformance(
        strategy,
        benchmark,
        policy={"min_observations": 252, "bootstrap_samples": 500, "seed": 2},
    )

    assert result["passed"] is False
    assert "excess_return_ci" in result["failed_gates"]


def test_release_gate_rejects_benchmark_underperformance():
    strategy, benchmark = _returns(edge=-0.0008)

    result = evaluate_outperformance(
        strategy,
        benchmark,
        policy={"min_observations": 252, "bootstrap_samples": 500, "seed": 3},
    )

    assert result["metrics"]["annualized_excess_return"] < 0
    assert result["passed"] is False


def test_deflated_sharpe_penalizes_multiple_trials():
    strategy, _ = _returns(edge=0.0005)

    one_trial = deflated_sharpe_probability(strategy, n_trials=1)
    many_trials = deflated_sharpe_probability(strategy, n_trials=100)

    assert many_trials < one_trial


def test_rolling_windows_are_ordered_and_non_overlapping():
    index = pd.bdate_range("2020-01-01", periods=30)

    windows = rolling_windows(index, train_size=10, test_size=5, step=5)

    assert len(windows) == 4
    assert windows[0].train[-1] < windows[0].test[0]
    assert windows[-1].test[-1] == index[-1]


def test_regime_gate_requires_every_required_regime_to_pass():
    strategy, benchmark = _returns(days=180, edge=0.001)
    regimes = pd.Series(
        ["BULL"] * 60 + ["BEAR"] * 60 + ["SIDEWAYS"] * 60,
        index=strategy.index,
    )
    strategy.loc[regimes == "BEAR"] = benchmark.loc[regimes == "BEAR"] - 0.002

    result = evaluate_regimes(
        strategy,
        benchmark,
        regimes,
        policy={
            "required_regimes": ["BULL", "BEAR", "SIDEWAYS"],
            "min_observations": 40,
            "bootstrap_samples": 300,
            "seed": 5,
        },
    )

    assert result["passed"] is False
    assert result["regimes"]["BEAR"]["passed"] is False
