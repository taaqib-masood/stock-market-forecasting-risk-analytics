"""
Tests for point-in-time halal screening (cache history; no network).

Run: pytest tests/test_halal_history.py -v
"""
from src.halal_history import (
    screen_as_of, tier_timeline, compliance_changes, _year,
)
from src.halal_screen import GREEN, RED


def _cache():
    # A name that was clean early, then crossed the debt line.
    return {"ACME": {"fetched_at": "2026-06-19", "source": "tickertape",
                     "latest": {"debt_to_assets": 0.50, "interest_income_ratio": 0.01},
                     "history": [
                         {"period": "FY 2021", "debt_to_assets": 0.10, "interest_income_ratio": 0.01},
                         {"period": "FY 2022", "debt_to_assets": 0.20, "interest_income_ratio": 0.02},
                         {"period": "FY 2023", "debt_to_assets": 0.50, "interest_income_ratio": 0.01},
                     ]}}


def test_year_extraction_handles_formats():
    assert _year("FY 2021") == 2021
    assert _year("FY2021") == 2021
    assert _year(2021) == 2021


def test_screen_as_of_uses_that_years_ratios():
    early = screen_as_of("ACME", 2021, cache=_cache())
    assert early["tier"] == GREEN                 # 10% debt back then
    late = screen_as_of("ACME", "FY 2023", cache=_cache())
    assert late["tier"] == RED                    # 50% debt now ✗
    assert late["period"] == "FY 2023"


def test_screen_as_of_missing_period():
    r = screen_as_of("ACME", 2019, cache=_cache())
    assert r["debt_to_assets"] is None
    assert "no cached fundamentals" in r["reasons"][0]


def test_timeline_is_chronological_and_flags_completeness():
    tl = tier_timeline("ACME", cache=_cache())
    assert [r["year"] for r in tl] == [2021, 2022, 2023]
    assert tl[0]["tier"] == GREEN and tl[-1]["tier"] == RED
    assert all(r["data_complete"] for r in tl)


def test_compliance_changes_detects_the_crossing():
    changes = compliance_changes(tier_timeline("ACME", cache=_cache()))
    assert len(changes) == 1
    assert changes[0]["to_period"] == "FY 2023"
    assert changes[0]["from"] == GREEN and changes[0]["to"] == RED
    assert changes[0]["worsened"] is True


def test_unknown_ticker_empty_timeline():
    assert tier_timeline("NOPE", cache=_cache()) == []
