"""
Tests for the passive core + regime overlay math (pure, no network).

Run: pytest tests/test_passive.py -v
"""

import numpy as np
import pandas as pd
import pytest

from src.passive import (
    basket_daily_returns, regime_exposure, apply_overlay, summarize_nav,
    drawdown_exposure,
)


def _idx(n):
    return pd.date_range("2024-01-01", periods=n, freq="B")


def test_basket_daily_returns_equal_weight():
    panel = pd.DataFrame({"A": [100, 110, 110], "B": [100, 100, 120]}, index=_idx(3))
    r = basket_daily_returns(panel)
    assert r.iloc[0] == pytest.approx(0.05)   # mean(+10%, 0%)
    assert r.iloc[1] == pytest.approx(0.10)   # mean(0%, +20%)


def test_regime_exposure_above_below_and_lagged():
    close = pd.Series([10, 11, 12, 13, 9, 8, 7], index=_idx(7))
    exp = regime_exposure(close, sma_window=3, lag=1)
    assert set(exp.unique()).issubset({0.0, 1.0})
    assert exp.sum() > 0          # on while above its rising SMA
    assert exp.iloc[-1] == 0.0    # risk-off after the collapse (and lagged)


def test_apply_overlay_zeroes_when_out():
    r = pd.Series([0.01, -0.02, 0.03], index=_idx(3))
    exp = pd.Series([1.0, 0.0, 1.0], index=_idx(3))
    assert list(apply_overlay(r, exp)) == [0.01, 0.0, 0.03]


def test_summarize_nav_drawdown_and_return():
    r = pd.Series([0.10, -0.50, 0.0], index=_idx(3))  # nav 1.1, 0.55, 0.55
    s = summarize_nav(r)
    assert s["max_drawdown_pct"] == pytest.approx(-50.0, abs=0.1)
    assert s["total_return_pct"] == pytest.approx(-45.0, abs=0.1)


def test_full_exposure_equals_buyhold():
    r = pd.Series([0.01, -0.02, 0.03, 0.01], index=_idx(4))
    full = pd.Series(1.0, index=_idx(4))
    assert summarize_nav(apply_overlay(r, full)) == summarize_nav(r)


def test_zero_exposure_is_flat():
    r = pd.Series([0.01, -0.02, 0.03], index=_idx(3))
    out = summarize_nav(apply_overlay(r, pd.Series(0.0, index=_idx(3))))
    assert out["total_return_pct"] == 0.0
    assert out["max_drawdown_pct"] == 0.0


def test_basket_ignores_sparse_out_of_window_days():
    # Reproduces the windowing corruption: one series with a wider date range than
    # the rest must NOT masquerade as the whole basket on the days only it covers.
    idx = _idx(8)
    panel = pd.DataFrame(index=idx, columns=["A", "B", "C", "ROGUE"], dtype=float)
    for col in ["A", "B", "C"]:
        panel.loc[idx[:5], col] = [100, 101, 102, 103, 104]   # present only days 0-4
    panel["ROGUE"] = [50, 60, 70, 80, 90, 100, 110, 120]       # present all 8 days
    r = basket_daily_returns(panel, min_coverage=0.5)
    # days 5-7 have only ROGUE (coverage 1/4 = 0.25 < 0.5) -> excluded
    assert r.index.max() <= idx[4]


def test_drawdown_exposure_grades_with_drawdown():
    # peak 100; drawdowns 0, 0, -8%, -14%, -20%, back to peak
    close = pd.Series([100, 100, 92, 86, 80, 100], index=_idx(6))
    exp = drawdown_exposure(close, dd_start=-0.08, dd_full=-0.20, floor=0.3, lag=0)
    assert exp.iloc[0] == pytest.approx(1.0)    # at peak -> fully invested
    assert exp.iloc[2] == pytest.approx(1.0)    # -8% (ordinary dip) -> still full
    assert exp.iloc[3] == pytest.approx(0.65)   # -14% -> 1 - 0.5*0.7
    assert exp.iloc[4] == pytest.approx(0.3)    # -20% (catastrophic) -> floor
    assert exp.iloc[5] == pytest.approx(1.0)    # recovered -> full


def test_drawdown_exposure_is_lagged_by_default():
    close = pd.Series([100, 90, 80, 100], index=_idx(4))
    exp = drawdown_exposure(close, lag=1)
    assert exp.iloc[0] == 1.0                    # no prior bar -> default fully invested
