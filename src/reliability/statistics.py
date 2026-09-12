"""Benchmark-relative statistical evidence for strategy promotion."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew


def _aligned(strategy: pd.Series, benchmark: pd.Series) -> tuple[pd.Series, pd.Series]:
    frame = pd.concat(
        [pd.Series(strategy, name="strategy"), pd.Series(benchmark, name="benchmark")],
        axis=1,
    ).dropna()
    if frame.empty:
        raise ValueError("strategy and benchmark have no aligned observations")
    if not frame.index.is_monotonic_increasing:
        frame = frame.sort_index()
    return frame["strategy"].astype(float), frame["benchmark"].astype(float)


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return abs(float(drawdown.min()))


def _block_sample(values: np.ndarray, block_size: int, rng: np.random.Generator) -> np.ndarray:
    n = len(values)
    blocks = math.ceil(n / block_size)
    starts = rng.integers(0, n, size=blocks)
    indices = np.concatenate([(np.arange(block_size) + start) % n for start in starts])[:n]
    return values[indices]


def bootstrap_excess_ci(
    strategy: pd.Series,
    benchmark: pd.Series,
    *,
    n_boot: int = 2000,
    block_size: int = 20,
    confidence: float = 0.95,
    periods: int = 252,
    seed: int = 0,
) -> dict[str, float]:
    """Block-bootstrap annualized mean excess return and its confidence interval."""
    strategy, benchmark = _aligned(strategy, benchmark)
    excess = (strategy - benchmark).to_numpy()
    if n_boot < 100:
        raise ValueError("n_boot must be at least 100")
    if block_size < 1:
        raise ValueError("block_size must be positive")
    rng = np.random.default_rng(seed)
    samples = np.array([
        _block_sample(excess, block_size, rng).mean() * periods for _ in range(n_boot)
    ])
    alpha = (1.0 - confidence) / 2.0
    return {
        "mean": float(excess.mean() * periods),
        "lower": float(np.quantile(samples, alpha)),
        "upper": float(np.quantile(samples, 1.0 - alpha)),
        "probability_positive": float(np.mean(samples > 0.0)),
    }


def deflated_sharpe_probability(
    returns: pd.Series,
    *,
    n_trials: int = 1,
    periods: int = 252,
) -> float:
    """Probability that Sharpe exceeds the expected best result from repeated trials."""
    values = pd.Series(returns).dropna().astype(float).to_numpy()
    sample_std = float(np.std(values, ddof=1))
    if len(values) < 3:
        return 0.0
    if sample_std < 1e-12:
        return 1.0 if float(np.mean(values)) > 0 else 0.0
    n_trials = max(1, int(n_trials))
    daily_sharpe = float(np.mean(values) / sample_std)
    quantile = (n_trials - 0.375) / (n_trials + 0.25)
    expected_best = float(norm.ppf(quantile) / math.sqrt(max(len(values) - 1, 1)))
    sample_skew = float(skew(values, bias=False))
    sample_kurtosis = float(kurtosis(values, fisher=False, bias=False))
    variance = (
        1.0 - sample_skew * daily_sharpe
        + ((sample_kurtosis - 1.0) / 4.0) * daily_sharpe**2
    ) / max(len(values) - 1, 1)
    standard_error = math.sqrt(max(variance, 1e-12))
    probability = norm.cdf((daily_sharpe - expected_best) / standard_error)
    return float(np.clip(probability, 0.0, 1.0))


def evaluate_outperformance(
    strategy: pd.Series,
    benchmark: pd.Series,
    *,
    policy: dict | None = None,
) -> dict:
    """Evaluate strategy evidence against explicit benchmark-relative release gates."""
    settings = {
        "min_observations": 252,
        "bootstrap_samples": 2000,
        "block_size": 20,
        "confidence": 0.95,
        "min_probability_positive": 0.95,
        "min_deflated_sharpe_probability": 0.95,
        "max_drawdown": 0.20,
        "n_trials": 1,
        "seed": 0,
    }
    settings.update(policy or {})
    strategy, benchmark = _aligned(strategy, benchmark)
    ci = bootstrap_excess_ci(
        strategy,
        benchmark,
        n_boot=int(settings["bootstrap_samples"]),
        block_size=int(settings["block_size"]),
        confidence=float(settings["confidence"]),
        seed=int(settings["seed"]),
    )
    dsr = deflated_sharpe_probability(
        strategy - benchmark, n_trials=int(settings["n_trials"])
    )
    drawdown = _max_drawdown(strategy)
    failed = []
    if len(strategy) < int(settings["min_observations"]):
        failed.append("minimum_observations")
    if ci["lower"] <= 0 or ci["probability_positive"] < float(settings["min_probability_positive"]):
        failed.append("excess_return_ci")
    if dsr < float(settings["min_deflated_sharpe_probability"]):
        failed.append("deflated_sharpe")
    if drawdown > float(settings["max_drawdown"]):
        failed.append("max_drawdown")
    return {
        "passed": not failed,
        "failed_gates": failed,
        "metrics": {
            "observations": len(strategy),
            "annualized_excess_return": ci["mean"],
            "excess_return_ci_lower": ci["lower"],
            "excess_return_ci_upper": ci["upper"],
            "probability_outperformance": ci["probability_positive"],
            "deflated_sharpe_probability": dsr,
            "max_drawdown": drawdown,
        },
    }
