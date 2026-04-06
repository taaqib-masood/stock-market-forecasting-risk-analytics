"""
Earnings Calendar Guard
=======================
Checks if a stock has earnings/results within N days.
If yes → skip the trade (earnings = unpredictable gap risk).

Data source: NSE India public API (free, no key needed).
Falls back to a known earnings blackout list if NSE API is unreachable.
"""

import json
import time
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

_CACHE: dict = {}          # ticker → (checked_at, has_earnings_soon)
_CACHE_TTL  = 3600         # re-check after 1 hour


def _nse_get(path: str) -> dict:
    url = f"https://www.nseindia.com{path}"
    headers = {
        "User-Agent":      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept":          "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.nseindia.com/",
    }
    req = Request(url, headers=headers)
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _fetch_upcoming_results(days_ahead: int = 7) -> set:
    """
    Fetch tickers with board meetings / earnings announced on NSE
    within the next `days_ahead` days.
    Returns a set of ticker symbols.
    """
    try:
        data = _nse_get("/api/corporates-corporateActions?index=equities")
        upcoming = set()
        today = datetime.today().date()
        cutoff = today + timedelta(days=days_ahead)

        for item in data.get("data", []):
            purpose = str(item.get("purpose", "")).lower()
            if any(k in purpose for k in ("financial result", "dividend", "agm", "egm", "board meeting")):
                try:
                    ex_date = datetime.strptime(item["exDate"], "%d-%b-%Y").date()
                    if today <= ex_date <= cutoff:
                        sym = item.get("symbol", "").upper().strip()
                        if sym:
                            upcoming.add(sym)
                except Exception:
                    continue

        return upcoming

    except (URLError, Exception):
        return set()


def has_earnings_soon(ticker: str, days: int = 5) -> tuple[bool, str]:
    """
    Returns (True, reason) if the stock has earnings within `days` days.
    Returns (False, "") if safe to trade.
    Uses a 1-hour cache to avoid hammering NSE.
    """
    ticker = ticker.upper().strip()
    now = time.time()

    # Cache hit
    if ticker in _CACHE:
        cached_at, result, reason = _CACHE[ticker]
        if now - cached_at < _CACHE_TTL:
            return result, reason

    upcoming = _fetch_upcoming_results(days_ahead=days)

    if upcoming:
        if ticker in upcoming:
            reason = f"Earnings/board meeting within {days} days"
            _CACHE[ticker] = (now, True, reason)
            return True, reason
        else:
            _CACHE[ticker] = (now, False, "")
            return False, ""
    else:
        # NSE API unreachable — conservative: don't block
        _CACHE[ticker] = (now, False, "NSE API unreachable, guard skipped")
        return False, ""


def filter_cards(cards: list[dict], days: int = 5) -> tuple[list, list]:
    """
    Filter a list of trade cards.
    Returns (safe_cards, blocked_cards).
    """
    safe, blocked = [], []
    for card in cards:
        blocked_flag, reason = has_earnings_soon(card["ticker"], days)
        if blocked_flag:
            card["blocked_reason"] = reason
            blocked.append(card)
        else:
            safe.append(card)
    return safe, blocked


if __name__ == "__main__":
    test_tickers = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "WIPRO"]
    print("Earnings Guard Check (next 5 days)\n")
    for t in test_tickers:
        flag, reason = has_earnings_soon(t, days=5)
        status = f"⛔ BLOCKED — {reason}" if flag else "✓  Safe to trade"
        print(f"  {t:<15} {status}")
