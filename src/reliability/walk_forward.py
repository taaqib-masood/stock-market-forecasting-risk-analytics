"""Leakage-resistant rolling windows and regime-level evidence."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.reliability.statistics import evaluate_outperformance


@dataclass(frozen=True)
class WalkForwardWindow:
    train: pd.Index
    test: pd.Index


def rolling_windows(
    index: pd.Index,
    train_size: int,
    test_size: int,
    step: int,
) -> list[WalkForwardWindow]:
    if min(train_size, test_size, step) <= 0:
        raise ValueError("train_size, test_size, and step must be positive")
    ordered = pd.Index(index)
    if not ordered.is_monotonic_increasing or ordered.has_duplicates:
        raise ValueError("index must be sorted and unique")
    windows = []
    for test_start in range(train_size, len(ordered) - test_size + 1, step):
        train_start = test_start - train_size
        windows.append(WalkForwardWindow(
            train=ordered[train_start:test_start],
            test=ordered[test_start:test_start + test_size],
        ))
    return windows


def evaluate_regimes(
    strategy: pd.Series,
    benchmark: pd.Series,
    regimes: pd.Series,
    *,
    policy: dict | None = None,
) -> dict:
    settings = dict(policy or {})
    required = settings.pop("required_regimes", sorted(pd.Series(regimes).dropna().unique()))
    frame = pd.concat(
        [strategy.rename("strategy"), benchmark.rename("benchmark"), regimes.rename("regime")],
        axis=1,
    ).dropna()
    results = {}
    for regime in required:
        subset = frame[frame["regime"] == regime]
        if subset.empty:
            results[regime] = {
                "passed": False, "failed_gates": ["missing_regime"],
                "metrics": {"observations": 0},
            }
            continue
        results[regime] = evaluate_outperformance(
            subset["strategy"], subset["benchmark"], policy=settings
        )
    return {
        "passed": bool(results) and all(result["passed"] for result in results.values()),
        "regimes": results,
    }
