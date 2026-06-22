"""
Tests for AAOIFI screening (classify) + Zakat/purification ledger. Pure logic, no network.

Run: pytest tests/test_halal_screen.py -v
"""

import datetime

from src.halal_screen import classify, screen_cached, GREEN, YELLOW, RED
from src.fundamentals import get_fundamentals
from src.zakat import zakat_due, purification_due, purification_for_portfolio, portfolio_zakat_report


# ── classify ──────────────────────────────────────────────────────────────────

def test_clean_company_is_green():
    r = classify(debt_to_assets=0.10, interest_income_ratio=0.02)
    assert r["tier"] == GREEN and r["tradeable"] is True
    assert r["purification_pct"] == 0.02


def test_narrow_fail_debt_is_yellow():
    assert classify(0.40, 0.02)["tier"] == YELLOW       # 33–45%


def test_high_debt_is_red():
    r = classify(0.50, 0.02)
    assert r["tier"] == RED and r["tradeable"] is False


def test_interest_income_tiers():
    assert classify(0.10, 0.07)["tier"] == YELLOW       # 5–10% -> purify
    assert classify(0.10, 0.12)["tier"] == RED          # >=10%


def test_worst_ratio_dominates():
    # green debt but red interest -> overall red
    assert classify(0.10, 0.12)["tier"] == RED
    # yellow debt + yellow interest -> yellow
    assert classify(0.40, 0.07)["tier"] == YELLOW


def test_vice_and_riba_are_red_and_not_tradeable():
    v = classify(0.05, 0.0, is_vice=True)
    assert v["tier"] == RED and v["tradeable"] is False
    b = classify(0.05, 0.0, is_riba_financial=True)
    assert b["tier"] == RED and b["tradeable"] is False


def test_unknown_ratios_are_yellow_caution():
    r = classify(None, None)
    assert r["tier"] == YELLOW
    assert r["purification_pct"] is None


def test_nan_ratios_treated_as_unknown_not_red():
    # yfinance returns NaN for some fields; NaN must be 'unknown' (🟡), not 🔴.
    r = classify(0.06, float("nan"))
    assert r["tier"] == YELLOW
    assert r["purification_pct"] is None


# ── zakat ─────────────────────────────────────────────────────────────────────

def test_zakat_full_method():
    z = zakat_due(100_000)                      # method 'full'
    assert z["below_nisab"] is False
    assert z["zakat_due"] == 2500.0             # 2.5% of 100k


def test_zakat_below_nisab_is_zero():
    z = zakat_due(40_000)                       # < 45k nisab
    assert z["below_nisab"] is True
    assert z["zakat_due"] == 0.0


def test_zakat_gains_method():
    z = zakat_due(100_000, method="gains", cost_basis=70_000)
    assert z["base"] == 30_000.0
    assert z["zakat_due"] == 750.0              # 2.5% of 30k gains


def test_zakat_hawl_not_complete_is_zero():
    z = zakat_due(100_000, hawl_complete=False)
    assert z["zakat_due"] == 0.0


# ── purification ──────────────────────────────────────────────────────────────

def test_purification_sums_impure_dividends():
    out = purification_due([
        {"ticker": "A", "dividends": 1000, "impure_pct": 0.03},   # 30
        {"ticker": "B", "dividends": 500, "impure_pct": 0.0},     # 0
        {"ticker": "C", "dividends": 2000, "impure_pct": 0.05},   # 100
    ])
    assert out["total_purification"] == 130.0
    assert out["by_holding"][0]["purification"] == 30.0


# ── cached fundamentals path (Tickertape cache → screen) ──────────────────────

def _today():
    return datetime.date.today().isoformat()


def test_screen_cached_green_from_cache():
    cache = {"TCS": {"fetched_at": _today(), "source": "tickertape", "periods": ["FY 2026"],
                     "latest": {"debt_to_assets": 0.06, "interest_income_ratio": 0.004}}}
    r = screen_cached("TCS", cache=cache)
    assert r["tier"] == GREEN and r["tradeable"] is True
    assert r["purification_pct"] == 0.004
    assert r["source"] == "tickertape" and r["as_of"] == _today()


def test_screen_cached_missing_ticker_is_yellow_no_data():
    r = screen_cached("NOSUCHTICKER", cache={})
    assert r["tier"] == YELLOW
    assert "no cached fundamentals" in r["reasons"][0]


def test_get_fundamentals_staleness_and_missing():
    fresh = {"X": {"fetched_at": _today(), "latest": {"debt_to_assets": 0.1, "interest_income_ratio": 0.02}}}
    assert get_fundamentals("X", cache=fresh)["stale"] is False
    old = {"X": {"fetched_at": "2020-01-01", "latest": {}}}
    assert get_fundamentals("X", cache=old)["stale"] is True
    assert get_fundamentals("Y", cache={}) is None


# ── auto-purification + portfolio zakat report ────────────────────────────────

def test_purification_for_portfolio_auto_looks_up_impure_ratio():
    cache = {
        "WIPRO": {"fetched_at": _today(), "latest": {"interest_income_ratio": 0.0159}},
        "TCS":   {"fetched_at": _today(), "latest": {"interest_income_ratio": 0.0045}},
    }
    out = purification_for_portfolio([
        {"ticker": "WIPRO", "dividends": 10000},   # 10000 * 0.0159 = 159.0
        {"ticker": "TCS",   "dividends": 5000},    # 5000 * 0.0045 = 22.5
        {"ticker": "MYSTERY", "dividends": 1000},  # not in cache -> 0, flagged
    ], cache=cache)
    assert out["total_purification"] == 181.5
    assert out["unknown_tickers"] == ["MYSTERY"]


def test_portfolio_zakat_report_combines_zakat_and_purification():
    cache = {"TCS": {"fetched_at": _today(), "latest": {"interest_income_ratio": 0.0045}}}
    rep = portfolio_zakat_report(
        [{"ticker": "TCS", "market_value": 100000, "dividends": 5000}], cache=cache)
    assert rep["portfolio_value"] == 100000.0
    assert rep["zakat"]["zakat_due"] == 2500.0            # 2.5% of 100k
    assert rep["purification"]["total_purification"] == 22.5
