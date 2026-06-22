"""
Tests for the drawdown-guard "why I de-risked" explainer (pure, no network).

Run: pytest tests/test_drawdown_guard.py -v
"""
import pandas as pd
import pytest

from src.drawdown_guard import current_state, explain, format_card
from src.passive import drawdown_exposure


def _idx(n):
    return pd.date_range("2024-01-01", periods=n, freq="B")


def test_state_matches_passive_exposure_math():
    # The explainer must report the SAME exposure the backtest's overlay trades.
    close = pd.Series([100, 100, 92, 86, 80], index=_idx(5))
    state = current_state(close)
    # un-lagged exposure on the last bar = passive.drawdown_exposure(lag=0).iloc[-1]
    expected = float(drawdown_exposure(close, lag=0).iloc[-1]) * 100
    assert state["exposure_pct"] == pytest.approx(round(expected, 1))


def test_status_bands():
    peak = pd.Series([100, 100], index=_idx(2))
    assert current_state(peak)["status"] == "FULLY INVESTED"          # at peak
    mild = pd.Series([100, 86], index=_idx(2))                        # -14%
    assert current_state(mild)["status"] == "DE-RISKING"
    crash = pd.Series([100, 78], index=_idx(2))                       # -22%
    s = current_state(crash)
    assert s["status"] == "MAX DEFENSIVE"
    assert s["exposure_pct"] == pytest.approx(30.0)                   # floor
    assert s["cash_pct"] == pytest.approx(70.0)


def test_explain_text_is_grounded_in_the_drawdown():
    state = current_state(pd.Series([100, 86], index=_idx(2)))        # -14%
    txt = explain(state, "Nifty 50")
    assert "14" in txt and "Nifty 50" in txt
    assert "de-risk" in txt.lower()


def test_card_shows_rupee_split_and_disclaimer():
    state = current_state(pd.Series([100, 86], index=_idx(2)))        # -14% -> 65% invested
    card = format_card(state, capital=50000)
    assert "DE-RISKING" in card
    assert "₹32,500" in card                                         # 65% of 50k in basket
    assert "₹17,500" in card                                         # 35% in cash
    assert "not advice" in card.lower()
