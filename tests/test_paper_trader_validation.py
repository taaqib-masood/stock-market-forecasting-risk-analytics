import pytest

from src import paper_trader as pt


@pytest.fixture
def state(monkeypatch):
    monkeypatch.setattr(pt, "_save", lambda s: None)
    monkeypatch.setattr(pt, "live_price", lambda t: 100.0)
    return {"cash": 50_000.0, "positions": {}, "trades": []}


@pytest.mark.parametrize("shares", [0, -5, 1.5, True, "3"])
def test_buy_rejects_bad_shares(state, shares):
    r = pt.buy("RELIANCE", shares, 100.0, state=state)
    assert r["ok"] is False and state["cash"] == 50_000.0 and not state["positions"]


@pytest.mark.parametrize("price", [0, -1.0, float("nan"), float("inf"), float("-inf")])
def test_buy_rejects_bad_price(state, price):
    r = pt.buy("RELIANCE", 1, price, state=state)
    assert r["ok"] is False and state["cash"] == 50_000.0 and not state["positions"]


def test_buy_live_price_nan_is_rejected(state, monkeypatch):
    monkeypatch.setattr(pt, "live_price", lambda t: float("nan"))
    assert pt.buy("RELIANCE", 1, state=state)["ok"] is False
    assert state["cash"] == 50_000.0


@pytest.mark.parametrize("shares,price", [(-1, 100.0), (0, 100.0), (1, float("nan")),
                                          (1, float("inf")), (1, -5.0)])
def test_sell_rejects_bad_input(state, shares, price):
    assert pt.buy("RELIANCE", 2, 100.0, state=state)["ok"] is True
    cash, pos = state["cash"], dict(state["positions"]["RELIANCE"])
    r = pt.sell("RELIANCE", shares, price, state=state)
    assert r["ok"] is False and state["cash"] == cash
    assert state["positions"]["RELIANCE"] == pos and not state["trades"]


def test_valid_buy_and_sell_still_work(state):
    assert pt.buy("RELIANCE", 2, 100.0, state=state)["ok"] is True
    assert pt.sell("RELIANCE", 1, 110.0, state=state)["ok"] is True
    assert pt.sell("RELIANCE", price=None, state=state)["ok"] is True
    assert not state["positions"] and len(state["trades"]) == 2
