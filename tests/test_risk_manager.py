"""
Golden-path regression tests for the risk manager + paper-P&L engine.

These are CHARACTERIZATION tests: every expected value is hand-computed from
the current implementation of src/risk_manager.py. They pin down what the code
*actually does today* so the upcoming refactors (unify scanner/backtest paths)
can't silently change risk behavior. If a refactor changes a number here, that
change must be deliberate — update the golden value on purpose, never to "make
the test pass".

Run: pytest tests/test_risk_manager.py -v
"""

import pandas as pd
import pytest

from src.risk_manager import RiskManager, backtest_with_risk


# ── Kelly position sizing (Rule 6) ────────────────────────────────────────────

def test_kelly_fraction_basic():
    rm = RiskManager()
    # b = 0.02/0.01 = 2 ; kelly = (2*0.55 - 0.45)/2 = 0.325 ; *0.25 = 0.08125
    assert rm.kelly_fraction(0.55, 0.02, 0.01) == pytest.approx(0.08125)


def test_kelly_fraction_zero_loss_returns_zero():
    rm = RiskManager()
    assert rm.kelly_fraction(0.55, 0.02, 0.0) == 0.0


def test_kelly_fraction_negative_edge_clamped_to_zero():
    rm = RiskManager()
    # win_rate 0.30, b=2 -> (0.6 - 0.7)/2 = -0.05 -> max(0, -0.0125) = 0
    assert rm.kelly_fraction(0.30, 0.02, 0.01) == 0.0


# ── evaluate(): approved golden path (Rules 1,2,3,6) ──────────────────────────

def test_evaluate_approved_long_golden():
    rm = RiskManager(capital=100_000)
    out = rm.evaluate(entry_price=100.0, atr=2.0, confidence=1.0, direction=1,
                      vix=15.0, win_rate=0.55, avg_win_pct=0.02, avg_loss_pct=0.01)
    # stop_distance = 2.0*2.0 = 4 ; long stop = 96, target = 100 + 4*2 = 108
    # size_fraction = min(0.08125, 0.05) = 0.05 -> max_pos = 5000 -> 50 shares
    # shares_by_risk = int(2000/4) = 500 ; shares = min(500, 50) = 50
    assert out["approved"] is True
    assert out["shares"] == 50
    assert out["stop_price"] == 96.0
    assert out["target_price"] == 108.0
    assert out["risk_amount"] == 200.0          # 50 * 4.0
    assert out["rr_ratio"] == 2.0
    assert out["vix_size_multiplier"] == 1.0


def test_evaluate_approved_short_golden():
    rm = RiskManager(capital=100_000)
    out = rm.evaluate(entry_price=100.0, atr=2.0, confidence=1.0, direction=-1, vix=15.0)
    # short: stop = 104, target = 92
    assert out["approved"] is True
    assert out["stop_price"] == 104.0
    assert out["target_price"] == 92.0
    assert out["shares"] == 50


# ── evaluate(): VIX regime gate (Rule 4) ──────────────────────────────────────

def test_evaluate_vix_crisis_rejected():
    rm = RiskManager()
    out = rm.evaluate(entry_price=100.0, atr=2.0, confidence=1.0, direction=1, vix=40.0)
    assert out["approved"] is False
    assert out["shares"] == 0
    assert "crisis" in out["reason"]


def test_evaluate_vix_elevated_halves_size():
    rm = RiskManager(capital=100_000)
    out = rm.evaluate(entry_price=100.0, atr=2.0, confidence=1.0, direction=1, vix=30.0)
    # vix_size_multiplier = 0.5 -> size_fraction = min(0.040625, 0.05) = 0.040625
    # max_pos = 4062.5 -> 40 shares (vs 50 at vix=15)
    assert out["approved"] is True
    assert out["vix_size_multiplier"] == 0.5
    assert out["shares"] == 40


# ── evaluate(): consecutive-loss halt (Rule 5) ────────────────────────────────

def test_evaluate_halts_after_consecutive_losses():
    rm = RiskManager(max_consecutive_losses=3)
    for _ in range(3):
        rm.record_outcome(won=False)
    out = rm.evaluate(entry_price=100.0, atr=2.0, confidence=1.0, direction=1, vix=15.0)
    assert out["approved"] is False
    assert "Halted" in out["reason"]


def test_reset_halt_reenables_trading():
    rm = RiskManager(max_consecutive_losses=3)
    for _ in range(3):
        rm.record_outcome(won=False)
    rm.reset_halt()
    out = rm.evaluate(entry_price=100.0, atr=2.0, confidence=1.0, direction=1, vix=15.0)
    assert out["approved"] is True


def test_record_outcome_counter_resets_on_win():
    rm = RiskManager()
    rm.record_outcome(won=False)
    rm.record_outcome(won=False)
    assert rm._consecutive_losses == 2
    rm.record_outcome(won=True)
    assert rm._consecutive_losses == 0


# ── evaluate(): zero-size rejection ───────────────────────────────────────────

def test_evaluate_zero_confidence_rounds_to_zero_shares():
    rm = RiskManager()
    # confidence 0.5 -> confidence_factor 0 -> size_fraction 0 -> 0 shares
    out = rm.evaluate(entry_price=100.0, atr=2.0, confidence=0.5, direction=1, vix=15.0)
    assert out["approved"] is False
    assert out["shares"] == 0
    assert "0 shares" in out["reason"]


def test_evaluate_rr_always_equals_min_rr():
    # CHARACTERIZATION + NOTE: target is defined as min_rr * stop_distance, so the
    # R:R "filter" can never reject — actual_rr is tautologically == min_rr.
    rm = RiskManager(min_rr=2.0)
    out = rm.evaluate(entry_price=100.0, atr=2.0, confidence=1.0, direction=1, vix=15.0)
    assert out["rr_ratio"] == 2.0


# ── backtest_with_risk(): paper-P&L engine ────────────────────────────────────

def _series(values):
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx)


def test_backtest_winning_long_hits_target():
    prices = _series([100, 100, 110, 110])
    signals = _series([0, 1, 0, 0])
    confs = _series([0, 1.0, 1.0, 1.0])
    atrs = _series([2, 2, 2, 2])
    log = backtest_with_risk(prices, signals, confs, atrs)
    # entry filled @100.1 (0.1% slip), 50 shares, target 108 hit at price 110
    # exit @109.89, commission 0.5, pnl = (109.89-100.1)*50 - 0.5 = 489.0
    assert len(log) == 1
    row = log.iloc[0]
    assert bool(row["won"]) is True
    assert row["exit_reason"] == "target"
    assert row["commission"] == 0.5
    assert row["pnl"] == 489.0
    assert row["equity"] == 100489.0


def test_backtest_losing_long_hits_stop():
    prices = _series([100, 100, 90, 90])
    signals = _series([0, 1, 0, 0])
    confs = _series([0, 1.0, 1.0, 1.0])
    atrs = _series([2, 2, 2, 2])
    log = backtest_with_risk(prices, signals, confs, atrs)
    row = log.iloc[0]
    assert bool(row["won"]) is False
    assert row["exit_reason"] == "stop"
    assert row["pnl"] == -510.0
    assert row["equity"] == 99490.0


def test_backtest_no_signals_returns_empty():
    prices = _series([100, 101, 102, 103])
    flat = _series([0, 0, 0, 0])
    atrs = _series([2, 2, 2, 2])
    log = backtest_with_risk(prices, flat, flat, atrs)
    assert log.empty
