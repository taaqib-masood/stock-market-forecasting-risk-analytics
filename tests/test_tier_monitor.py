"""
Tests for the halal tier-change monitor. Pure logic, no network.

Run: pytest tests/test_tier_monitor.py -v
"""
import datetime

from src.tier_monitor import current_tiers, diff_tiers, format_changes
from src.halal_screen import GREEN, YELLOW, RED


def _today():
    return datetime.date.today().isoformat()


def test_current_tiers_screens_all_cached():
    cache = {
        "TCS":    {"fetched_at": _today(), "latest": {"debt_to_assets": 0.06, "interest_income_ratio": 0.004}},
        "HIDEBT": {"fetched_at": _today(), "latest": {"debt_to_assets": 0.50, "interest_income_ratio": 0.004}},
    }
    out = current_tiers(cache=cache)
    assert out["TCS"]["tier"] == GREEN
    assert out["HIDEBT"]["tier"] == RED          # debt ≥ 45%


def test_diff_tiers_detects_transitions_worsened_first():
    old = {"A": {"tier": GREEN}, "B": {"tier": GREEN}, "C": {"tier": YELLOW}}
    new = {"A": {"tier": RED},   "B": {"tier": GREEN}, "C": {"tier": GREEN}}
    changes = diff_tiers(old, new)
    by = {c["ticker"]: c for c in changes}
    assert set(by) == {"A", "C"}                 # B unchanged, excluded
    assert by["A"]["worsened"] is True
    assert by["C"]["worsened"] is False
    assert changes[0]["ticker"] == "A"           # worsened sorted first


def test_diff_tiers_ignores_newly_added_tickers():
    old = {"A": {"tier": GREEN}}
    new = {"A": {"tier": GREEN}, "NEW": {"tier": RED}}
    assert diff_tiers(old, new) == []


def test_format_changes_empty_and_nonempty():
    assert "No halal tier changes" in format_changes([])
    msg = format_changes([{"ticker": "X", "from": GREEN, "to": RED, "worsened": True}])
    assert "X" in msg and "NON-TRADEABLE" in msg
