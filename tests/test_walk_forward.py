"""
Tests for the walk-forward + criteria-correlation harness.

Network-free: synthetic OHLCV (same pattern as test_backtest_runner) run through
the real add_features + RuleStrategy offline. We assert wiring and invariants,
not golden P&L numbers (those depend on the random walk).

Run: pytest tests/test_walk_forward.py -v
"""
import numpy as np
import pandas as pd
import pytest

from src.feature_engineering import add_features
from src.strategy import RuleStrategy
from src.walk_forward import (
    COST_PRESETS,
    buy_and_hold_return,
    compare_strategies,
    criteria_correlation,
    walk_forward,
    _pool_stats,
)


def _make_ohlcv(n: int = 900) -> pd.DataFrame:
    np.random.seed(7)
    close = 1000 + np.cumsum(np.random.randn(n) * 5)
    high = close + np.abs(np.random.randn(n) * 3)
    low = close - np.abs(np.random.randn(n) * 3)
    open_ = close + np.random.randn(n) * 2
    volume = np.random.randint(100_000, 5_000_000, n).astype(float)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


# ── walk_forward ────────────────────────────────────────────────────────────────

def test_walk_forward_shape():
    df = _make_ohlcv()
    r = walk_forward(df, n_splits=3, min_window_bars=50, costs="nse_delivery")
    assert "error" not in r, r
    assert r["strategy"] == "rule_7criteria"
    assert r["n_windows"] >= 1
    assert len(r["windows"]) == r["n_windows"]
    for w in r["windows"]:
        assert {"period", "stats", "costs"} <= set(w)
        assert w["stats"]["win_rate"] >= 0
    # aggregate + overfit blocks exist
    assert "oos" in r and "in_sample" in r
    assert isinstance(r["overfit_gap_pct"], float)
    assert {"win_rate_mean", "win_rate_std", "win_rate_min", "cliff"} <= set(r["stability"])
    assert "survivorship" in r["caveat"].lower()


def test_walk_forward_too_little_data_errors():
    df = _make_ohlcv(120)
    r = walk_forward(df, n_splits=4, min_window_bars=90)
    assert "error" in r


def test_costs_change_results_not_crash():
    df = _make_ohlcv()
    frictionless = walk_forward(df, n_splits=3, min_window_bars=50, costs="frictionless")
    nse = walk_forward(df, n_splits=3, min_window_bars=50, costs="nse_delivery")
    assert "error" not in frictionless and "error" not in nse
    # frictionless can only be >= net P&L of the costed run (costs subtract)
    assert frictionless["oos"]["total_pnl"] >= nse["oos"]["total_pnl"] - 1e-6


# ── criteria_correlation ─────────────────────────────────────────────────────────

def test_criteria_correlation_is_7x7():
    feats = add_features(_make_ohlcv(), fetch_context=False)
    res = criteria_correlation([feats])
    assert res["n_bars"] > 0
    m = res["matrix"]
    assert m.shape == (7, 7)
    # diagonal is self-correlation = 1
    for c in m.columns:
        assert m.loc[c, c] == pytest.approx(1.0, abs=1e-9)
    # redundant_pairs entries are (name, name, corr) with |corr| >= 0.6
    for a, b, v in res["redundant_pairs"]:
        assert a in m.columns and b in m.columns and abs(v) >= 0.6


def test_criteria_correlation_empty():
    res = criteria_correlation([])
    assert res["n_bars"] == 0
    assert res["redundant_pairs"] == []


# ── compare_strategies (the gate) ────────────────────────────────────────────────

def test_compare_strategies_returns_verdict():
    df = _make_ohlcv()
    base = RuleStrategy(min_criteria=5)
    challenger = RuleStrategy(min_criteria=4)   # looser → different trade set
    res = compare_strategies(
        df, base, challenger, n_splits=3, min_window_bars=50, costs="frictionless",
    )
    assert "error" not in res, res
    assert {"win_rate_pp", "profit_factor", "net_pnl"} <= set(res["delta"])
    assert isinstance(res["challenger_wins"], bool)


# ── _pool_stats ──────────────────────────────────────────────────────────────────

def test_pool_stats_empty():
    s = _pool_stats([pd.DataFrame(), pd.DataFrame()], capital=100_000)
    assert s["total_trades"] == 0
    assert s["final_equity"] == 100_000


def test_cost_presets_exist():
    assert {"nse_delivery", "us_ibkr", "frictionless"} <= set(COST_PRESETS)


# ── portfolio / benchmark ────────────────────────────────────────────────────────

def test_buy_and_hold_return():
    s = pd.Series([100.0, 110.0, 120.0])
    assert buy_and_hold_return(s) == pytest.approx(20.0)
    assert buy_and_hold_return(pd.Series([100.0])) == 0.0   # too short
    assert buy_and_hold_return(pd.Series(dtype=float)) == 0.0


def test_track_a_features_present_and_bounded():
    feats = add_features(_make_ohlcv(), fetch_context=False)
    for col in ["adx_14", "donchian_pos_20", "donchian_break_20",
                "bb_squeeze_pct", "volume_zscore"]:
        assert col in feats.columns, col
    assert feats["adx_14"].between(0, 100).all()
    assert feats["donchian_pos_20"].between(-0.01, 1.01).all()
    assert set(feats["donchian_break_20"].unique()) <= {0, 1}
    assert feats["bb_squeeze_pct"].between(0, 1).all()


def test_rule_v2_buy_only_and_gated():
    from src.strategy import RuleStrategyV2
    feats = add_features(_make_ohlcv(), fetch_context=False)
    sig = RuleStrategyV2().generate_signals(feats)
    assert {"score", "signal", "confidence"} <= set(sig.columns)
    assert set(sig["signal"].unique()) <= {0, 1}          # halal BUY-only
    # ADX gate: no BUY may fire on a bar below the gate threshold
    buys = sig["signal"] == 1
    assert (feats.loc[buys, "adx_14"] >= 20.0).all()


def test_walk_forward_exposes_oos_log():
    df = _make_ohlcv()
    r = walk_forward(df, n_splits=3, min_window_bars=50, costs="frictionless")
    assert "oos_log" in r
    assert isinstance(r["oos_log"], pd.DataFrame)
    # pooled OOS trade count must match the aggregate stats
    assert len(r["oos_log"]) == r["oos"]["total_trades"]
