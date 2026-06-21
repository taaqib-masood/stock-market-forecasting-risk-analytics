"""
Tests for the look-ahead / leakage detector.

The detector is only trustworthy if it BOTH passes a clean strategy AND catches a
leaky one. We test both directions:
  - RuleStrategy (past-only features)  -> clean
  - a strategy that reads `target` (Close.shift(-1), the future) -> caught

Run: pytest tests/test_validation.py -v
"""

import numpy as np
import pandas as pd

from src.strategy import Strategy, RuleStrategy
from src.validation import detect_lookahead


def _make_ohlcv(n: int = 480) -> pd.DataFrame:
    np.random.seed(11)
    close = 1000 + np.cumsum(np.random.randn(n) * 5)
    high = close + np.abs(np.random.randn(n) * 3)
    low = close - np.abs(np.random.randn(n) * 3)
    open_ = close + np.random.randn(n) * 2
    volume = np.random.randint(100_000, 5_000_000, n).astype(float)
    idx = pd.date_range("2021-06-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


class _LeakyStrategy(Strategy):
    """Positive control: signals on `target` = (Close.shift(-1) > Close) = the FUTURE."""
    name = "leaky"

    def generate_signals(self, features: pd.DataFrame) -> pd.DataFrame:
        sig = features["target"].astype(int)
        return pd.DataFrame({
            "score": sig * 100.0, "signal": sig, "confidence": sig.astype(float),
        })


def test_rulestrategy_is_leak_free():
    report = detect_lookahead(_make_ohlcv(480), strategy=RuleStrategy())
    assert report["checks"] > 0
    assert report["clean"] is True, f"unexpected leakage: {report['mismatches']}"


def test_detector_catches_a_real_leak():
    report = detect_lookahead(_make_ohlcv(480), strategy=_LeakyStrategy())
    assert report["clean"] is False
    assert len(report["mismatches"]) > 0


def test_detector_runs_multiple_checks():
    report = detect_lookahead(_make_ohlcv(480), strategy=RuleStrategy(), n_checks=10, tail=4)
    assert report["checks"] >= 10
