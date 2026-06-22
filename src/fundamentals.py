"""
Reader for the fundamentals cache produced by scripts/refresh_fundamentals.py.

The refresh job (run in the isolated Bharat-sm-data venv) writes data/fundamentals_cache.json
with multi-year debt/assets + interest-income ratios from Tickertape. The trading/screening
code reads that stable cache here — so scraper fragility and heavy deps never touch the live
path. Returns staleness info so the screen can show "as of <date>".
"""
import datetime
import json
from pathlib import Path
from typing import Optional

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "fundamentals_cache.json"
STALE_DAYS = 120  # fundamentals refresh quarterly


def _load(path: Path = CACHE_PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _is_stale(fetched_at: Optional[str]) -> bool:
    if not fetched_at:
        return True
    try:
        age = (datetime.date.today() - datetime.date.fromisoformat(fetched_at)).days
        return age > STALE_DAYS
    except Exception:
        return True


def get_fundamentals(ticker: str, cache: Optional[dict] = None) -> Optional[dict]:
    """Latest cached AAOIFI ratios for `ticker`, or None if not cached.
    Pass `cache` (a pre-loaded dict) for testing; otherwise reads the cache file."""
    data = cache if cache is not None else _load()
    rec = data.get(ticker.upper())
    if not rec:
        return None
    latest = rec.get("latest", {})
    return {
        "ticker": ticker.upper(),
        "debt_to_assets": latest.get("debt_to_assets"),
        "interest_income_ratio": latest.get("interest_income_ratio"),
        "as_of": rec.get("fetched_at"),
        "stale": _is_stale(rec.get("fetched_at")),
        "source": rec.get("source"),
        "periods": rec.get("periods", []),
        "history": rec.get("history", []),
    }
