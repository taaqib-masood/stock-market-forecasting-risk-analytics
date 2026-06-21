"""
Tests for the unified RuleStrategy — the single source of truth for the rule
signal. Inputs are engineered-feature rows; expected signal/score are derived by
hand from the 7-criteria definition.

Run: pytest tests/test_strategy.py -v
"""

import pandas as pd
import pytest

from src.strategy import RuleStrategy


def _row(rsi=50.0, macd=0.5, sma20=0.02, sma50=0.03,
         vol=1.5, bb=0.6, ret5=0.01):
    """One feature row where the defaults satisfy ALL 7 criteria."""
    return {
        "rsi_14": rsi, "macd_hist": macd,
        "price_vs_sma20": sma20, "price_vs_sma50": sma50,
        "volume_ratio": vol, "bb_pct_b": bb, "return_5d": ret5,
    }


def _df(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, index=idx)


def test_all_seven_pass_full_score_buy():
    out = RuleStrategy().generate_signals(_df([_row()]))
    r = out.iloc[0]
    assert r["score"] == 100.0
    assert r["signal"] == 1
    assert r["confidence"] == 1.0


def test_exactly_five_criteria_buys():
    # Fail RSI (>68) and BB (>0.85); other 5 pass -> count 5 -> BUY
    out = RuleStrategy().generate_signals(_df([_row(rsi=80.0, bb=0.95)]))
    r = out.iloc[0]
    assert r["signal"] == 1
    assert r["score"] == 71.4            # 5/7*100
    assert r["confidence"] == 0.7143


def test_four_criteria_no_trade():
    # Fail RSI, BB, and momentum -> count 4 -> below min_criteria=5 -> flat
    out = RuleStrategy().generate_signals(_df([_row(rsi=80.0, bb=0.95, ret5=-0.01)]))
    r = out.iloc[0]
    assert r["signal"] == 0
    assert r["score"] == 57.1            # 4/7*100


def test_no_short_by_default():
    # All criteria fail -> count 0, but shorts disabled -> signal stays 0
    bear = _row(rsi=80.0, macd=-1.0, sma20=-0.02, sma50=-0.02,
                vol=0.5, bb=0.1, ret5=-0.01)
    out = RuleStrategy().generate_signals(_df([bear]))
    assert out.iloc[0]["signal"] == 0


def test_short_when_enabled():
    bear = _row(rsi=80.0, macd=-1.0, sma20=-0.02, sma50=-0.02,
                vol=0.5, bb=0.1, ret5=-0.01)
    out = RuleStrategy(allow_short=True).generate_signals(_df([bear]))
    assert out.iloc[0]["signal"] == -1


def test_boundary_values_are_inclusive():
    # rsi exactly 40/68, bb exactly 0.4/0.85, volume exactly 1.2 all count
    edge = _row(rsi=40.0, bb=0.4, vol=1.2)
    assert RuleStrategy().generate_signals(_df([edge])).iloc[0]["score"] == 100.0
    edge2 = _row(rsi=68.0, bb=0.85, vol=1.2)
    assert RuleStrategy().generate_signals(_df([edge2])).iloc[0]["score"] == 100.0


def test_vectorized_multi_row():
    out = RuleStrategy().generate_signals(
        _df([_row(), _row(rsi=80.0, bb=0.95, ret5=-0.01)])  # buy, then flat
    )
    assert list(out["signal"]) == [1, 0]


def test_missing_column_raises():
    bad = _df([_row()]).drop(columns=["macd_hist"])
    with pytest.raises(KeyError):
        RuleStrategy().generate_signals(bad)
