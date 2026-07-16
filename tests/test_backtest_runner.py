"""
Tests for the unified backtest runner (add_features -> Strategy -> backtest_with_risk).

Pure functions (summarize_trades, passes_backtest) get golden values.
run_backtest is tested for wiring with a forced strategy (deterministic trade
count) and for end-to-end consistency with the real RuleStrategy.

Run: pytest tests/test_backtest_runner.py -v
"""

import numpy as np
import pandas as pd
import pytest

from src.strategy import Strategy, RuleStrategy
from src.backtest_runner import (
    summarize_trades, passes_backtest, run_backtest, generate_live_signal,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 380) -> pd.DataFrame:
    np.random.seed(7)
    close = 1000 + np.cumsum(np.random.randn(n) * 5)
    high = close + np.abs(np.random.randn(n) * 3)
    low = close - np.abs(np.random.randn(n) * 3)
    open_ = close + np.random.randn(n) * 2
    volume = np.random.randint(100_000, 5_000_000, n).astype(float)
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


class _ForcedBuyOnce(Strategy):
    """Test double: emit a single BUY at one positional row, flat elsewhere."""
    name = "forced_buy_once"

    def __init__(self, buy_at: int):
        self.buy_at = buy_at

    def generate_signals(self, features: pd.DataFrame) -> pd.DataFrame:
        sig = pd.Series(0, index=features.index, dtype=int)
        conf = pd.Series(0.0, index=features.index)
        if 0 <= self.buy_at < len(features):
            sig.iloc[self.buy_at] = 1
            conf.iloc[self.buy_at] = 1.0
        return pd.DataFrame({"score": conf * 100, "signal": sig, "confidence": conf})


# ── summarize_trades ──────────────────────────────────────────────────────────

def test_summarize_trades_golden():
    log = pd.DataFrame({
        "pnl":    [100.0, -50.0, 200.0],
        "won":    [True, False, True],
        "equity": [100100.0, 100050.0, 100250.0],
    })
    s = summarize_trades(log, capital=100_000)
    assert s["total_trades"] == 3
    assert s["wins"] == 2 and s["losses"] == 1
    assert s["win_rate"] == 66.7
    assert s["profit_factor"] == 6.0        # 300 / 50
    assert s["total_pnl"] == 250.0
    assert s["final_equity"] == 100250.0
    assert s["return_pct"] == 0.25


def test_summarize_trades_empty():
    s = summarize_trades(pd.DataFrame(), capital=50_000)
    assert s["total_trades"] == 0
    assert s["final_equity"] == 50_000.0
    assert s["profit_factor"] == 0.0


# ── passes_backtest gate ──────────────────────────────────────────────────────

def test_passes_backtest_too_few_trades():
    ok, reason = passes_backtest({"total_trades": 5, "win_rate": 90.0, "profit_factor": 3.0})
    assert ok is False and "only 5" in reason


def test_passes_backtest_low_win_rate():
    ok, reason = passes_backtest({"total_trades": 10, "win_rate": 40.0, "profit_factor": 2.0})
    assert ok is False and "win rate" in reason


def test_passes_backtest_low_pf():
    ok, reason = passes_backtest({"total_trades": 10, "win_rate": 60.0, "profit_factor": 1.0})
    assert ok is False and "PF" in reason


def test_passes_backtest_passes():
    ok, reason = passes_backtest({"total_trades": 10, "win_rate": 60.0, "profit_factor": 1.5})
    assert ok is True and reason == "passed"


# ── run_backtest wiring ───────────────────────────────────────────────────────

def test_run_backtest_forced_single_trade():
    df = _make_ohlcv(380)
    out = run_backtest(df, strategy=_ForcedBuyOnce(buy_at=50), fetch_context=False)
    # One BUY that flips back to flat next bar -> exactly one opened+closed trade.
    assert out["stats"]["total_trades"] == 1
    assert len(out["trade_log"]) == 1


def test_run_backtest_no_signals_empty():
    df = _make_ohlcv(380)
    out = run_backtest(df, strategy=_ForcedBuyOnce(buy_at=-1), fetch_context=False)
    assert out["trade_log"].empty
    assert out["stats"]["total_trades"] == 0


def test_run_backtest_rulestrategy_end_to_end_consistent():
    df = _make_ohlcv(380)
    out = run_backtest(df, strategy=RuleStrategy(), fetch_context=False)
    s = out["stats"]
    # No network, no crash, internally consistent accounting.
    assert set(out) >= {"trade_log", "stats", "features"}
    assert s["wins"] + s["losses"] == s["total_trades"]
    assert 0.0 <= s["win_rate"] <= 100.0


# ── generate_live_signal (unified live producer) ──────────────────────────────

class _AlwaysBuy(Strategy):
    name = "always_buy"

    def generate_signals(self, features: pd.DataFrame) -> pd.DataFrame:
        sig = pd.Series(1, index=features.index, dtype=int)
        conf = pd.Series(1.0, index=features.index)
        return pd.DataFrame({"score": conf * 100, "signal": sig, "confidence": conf})


class _NeverBuy(Strategy):
    name = "never_buy"

    def generate_signals(self, features: pd.DataFrame) -> pd.DataFrame:
        z = pd.Series(0, index=features.index, dtype=int)
        return pd.DataFrame({"score": z.astype(float), "signal": z, "confidence": z.astype(float)})


def test_generate_live_signal_buy_card():
    card = generate_live_signal(_make_ohlcv(380), strategy=_AlwaysBuy())
    assert card is not None
    assert card["signal"] == "BUY" and card["direction"] == 1
    assert card["shares"] > 0 and card["risk_rs"] > 0
    assert card["stop"] < card["entry"] < card["target"]
    assert card["reward_rs"] == round(card["risk_rs"] * card["rr"], 2)


def test_generate_live_signal_uses_riskmanager_rr_not_old_scanner():
    # Deliberate behavior change: R:R is now 2.0 (RiskManager), not 2.5 (old _trade_card).
    card = generate_live_signal(_make_ohlcv(380), strategy=_AlwaysBuy())
    assert card["rr"] == 2.0


def test_generate_live_signal_no_buy_returns_none():
    assert generate_live_signal(_make_ohlcv(380), strategy=_NeverBuy()) is None


def test_generate_live_signal_rulestrategy_runs():
    card = generate_live_signal(_make_ohlcv(380), strategy=RuleStrategy())
    assert card is None or (card["signal"] == "BUY" and len(card["criteria"]) == 7)


def test_cost_breakdown_gross_equals_net_plus_costs():
    from src.backtest_runner import cost_breakdown
    log = pd.DataFrame({
        "pnl": [100.0, -40.0], "commission": [0.5, 0.5], "slippage_cost": [2.0, 2.0],
    })
    cb = cost_breakdown(log, capital=100_000)
    assert cb["total_costs"] == 5.0      # (0.5+0.5) + (2+2)
    assert cb["net_pnl"] == 60.0         # 100 - 40
    assert cb["gross_pnl"] == 65.0       # net + costs
