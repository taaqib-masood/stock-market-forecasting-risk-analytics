"""
Engine seam tests (Phase 2) — the Lean-style role separation. Network-free:
AlphaModel.score is pure NumPy; the rest is exercised via monkeypatch so nothing
hits yfinance or real portfolio state.
"""
import numpy as np
import pytest

from src.engine import AlphaModel, PortfolioModel, RiskModel, ExecutionModel, TradingEngine


def test_engine_wires_four_roles():
    eng = TradingEngine(capital=50_000)
    assert isinstance(eng.alpha, AlphaModel)
    assert isinstance(eng.portfolio, PortfolioModel)
    assert isinstance(eng.risk, RiskModel)
    assert isinstance(eng.execution, ExecutionModel)
    assert eng.capital == 50_000


def test_alpha_score_is_pure():
    np.random.seed(7)
    n = 60
    c = 1000 + np.cumsum(np.random.randn(n))
    h = c + 3; l = c - 3; v = np.random.randint(1e5, 5e6, n).astype(float)
    s = AlphaModel().score(c, h, l, v)
    assert "score" in s and "signal" in s and "criteria" in s
    assert 0 <= s["score"] <= 100
    assert s["signal"] in {"BUY", "SELL", "WAIT"}


def test_risk_model_uses_active_preset(monkeypatch, tmp_path):
    from src import strategy_presets as sp
    monkeypatch.setattr(sp, "CONFIG_FILE", tmp_path / "cfg.json")
    sp.set_active("intra_month")
    rm = RiskModel().manager(capital=100_000)
    assert rm.atr_multiplier == sp.PRESETS["intra_month"]["atr_multiplier"]
    assert rm.min_rr == sp.PRESETS["intra_month"]["min_rr"]
    assert RiskModel().max_hold_days() == sp.PRESETS["intra_month"]["max_hold_days"]


def test_portfolio_regime_ok_logic():
    from src.regime_detector import REGIME_PARAMS
    pm = PortfolioModel()
    assert pm.regime_ok(REGIME_PARAMS["TRENDING_UP"]) is True
    assert pm.regime_ok(REGIME_PARAMS["CRASH"]) is False        # longs forbidden
    assert pm.regime_ok(REGIME_PARAMS["TRENDING_DOWN"]) is False
    assert pm.max_positions(REGIME_PARAMS["TRENDING_UP"]) == 3


@pytest.mark.parametrize("ticker,shares,frag", [
    ("REL!", 5, "alphanumeric"),
    ("RELIANCE", 0, "positive integer"),
])
def test_execution_buy_guards(ticker, shares, frag):
    r = ExecutionModel().buy(ticker, shares, price=100)
    assert r["ok"] is False and frag in r["reason"]


def test_execution_close_refuses_unheld(monkeypatch):
    import src.paper_trader as pt
    monkeypatch.setattr(pt, "_load", lambda: {"positions": {}})
    r = ExecutionModel().close("RELIANCE")
    assert r["ok"] is False and "refusing to short" in r["reason"]
