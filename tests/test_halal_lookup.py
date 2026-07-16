"""
Tests for the "is this stock halal?" lookup (cache-hit path; no network).

Run: pytest tests/test_halal_lookup.py -v
"""
import datetime

from src.halal_lookup import lookup, format_card


def _cache():
    return {"TCS": {"fetched_at": datetime.date.today().isoformat(), "source": "tickertape",
                    "latest": {"debt_to_assets": 0.06, "interest_income_ratio": 0.004}}}


def test_lookup_resolves_from_cache():
    r = lookup("TCS", cache=_cache())
    assert r["resolved_via"] == "cache"
    assert r["tier"] == "🟢"


def test_format_card_cites_standard_source_and_disclaimer():
    card = format_card(lookup("TCS", cache=_cache()))
    assert "HALAL" in card
    assert "AAOIFI" in card                       # standard cited
    assert "tickertape" in card                   # source cited
    assert "Purify" in card                       # purification surfaced
    assert "Not financial or religious advice" in card
