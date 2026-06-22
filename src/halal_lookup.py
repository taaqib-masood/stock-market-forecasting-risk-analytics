"""
"Is this stock halal?" lookup — the shareable, single-ticker verdict.

Cache-first (Tickertape fundamentals, refreshed quarterly), live yfinance fallback for
tickers not yet cached. Emits a human-readable CARD with the actual ratios, the standard
CITED, the data source + date, and the not-advice disclaimer — the citation posture the
council said is the only survivable shape (cite an authority, never originate a ruling).

    python -m src.halal_lookup RELIANCE
"""
from typing import Optional

_VERDICT = {"🟢": "HALAL", "🟡": "DOUBTFUL — screen + purify", "🔴": "NOT HALAL"}


def lookup(ticker: str, cache: Optional[dict] = None) -> dict:
    """Unified halal verdict for `ticker`: cached fundamentals first, else live yfinance."""
    from src.halal_screen import screen_cached, screen_ticker
    cached = screen_cached(ticker, cache=cache)
    if cached.get("as_of") is not None:          # found in cache
        cached["resolved_via"] = "cache"
        return cached
    live = screen_ticker(ticker)                 # network fallback
    live["resolved_via"] = "live (yfinance)"
    live.setdefault("as_of", None)
    return live


def format_card(r: dict) -> str:
    tier = r["tier"]
    verdict = _VERDICT.get(tier, "UNKNOWN")
    suffix = "" if r.get("tradeable", True) else "  (not tradeable)"
    lines = [f"{tier} {r['ticker']} — {verdict}{suffix}"]
    for reason in r.get("reasons", []):
        lines.append(f"  • {reason}")
    src = r.get("source") or r.get("resolved_via", "")
    asof = f", as of {r['as_of']}" if r.get("as_of") else ""
    lines.append(f"  Standard: AAOIFI (debt < 33%, interest income < 5%)  |  Source: {src}{asof}")
    if r.get("purification_pct"):
        lines.append(f"  Purify {r['purification_pct'] * 100:.2f}% of dividends to charity.")
    lines.append("  ⚠️ Not financial or religious advice — verify with a qualified scholar.")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    print(format_card(lookup(tk)))
