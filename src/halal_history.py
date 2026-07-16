"""
Point-in-time halal screening — "was this stock compliant back THEN?"

The quarterly refresh caches 8 fiscal years of debt/assets + interest-income ratios per
ticker (`history` in the fundamentals cache). This module runs the SAME `classify()`
engine over each historical period, so you can answer:

  - what tier was BHARTIARTL in FY 2021?            → screen_as_of()
  - show me its 🟢/🟡/🔴 timeline across 8 years     → tier_timeline()
  - which year did it cross the AAOIFI line?         → compliance_changes()

Why it matters: a backtest that only buys names that were halal AT THE TIME avoids
"look-ahead halal bias" — screening history with today's compliance and pretending you
knew it then. Same single-source thresholds as the live screen (no drift).

    python -m src.halal_history BHARTIARTL
"""
import re
from typing import Optional

from src.halal_screen import classify, GREEN, YELLOW, RED
from src.fundamentals import get_fundamentals


def _year(period) -> Optional[int]:
    """Extract the 4-digit year from 'FY 2021' / 'FY2021' / '2021' / 2021."""
    m = re.search(r"(\d{4})", str(period))
    return int(m.group(1)) if m else None


def _history(ticker: str, cache: Optional[dict]) -> list:
    f = get_fundamentals(ticker, cache=cache)
    return f["history"] if f else []


def screen_as_of(ticker: str, period, cache: Optional[dict] = None) -> dict:
    """Classify `ticker` using the fundamentals it reported for `period` (a fiscal year).

    `period` may be 'FY 2021', '2021', or 2021. Returns the same shape as
    `classify()` plus the matched period + ratios; tier 🟡 'no data' if not found.
    """
    want = _year(period)
    for row in _history(ticker, cache):
        if _year(row.get("period")) == want:
            r = classify(row.get("debt_to_assets"), row.get("interest_income_ratio"))
            r.update({"ticker": ticker.upper(), "period": row.get("period"),
                      "debt_to_assets": row.get("debt_to_assets"),
                      "interest_income_ratio": row.get("interest_income_ratio")})
            return r
    return {"tier": YELLOW, "tradeable": True, "purification_pct": None, "ticker": ticker.upper(),
            "period": str(period), "debt_to_assets": None, "interest_income_ratio": None,
            "reasons": [f"no cached fundamentals for {period}"]}


def tier_timeline(ticker: str, cache: Optional[dict] = None) -> list:
    """Per-fiscal-year tier across all cached history (oldest → newest)."""
    out = []
    for row in _history(ticker, cache):
        r = classify(row.get("debt_to_assets"), row.get("interest_income_ratio"))
        complete = (row.get("debt_to_assets") is not None
                    and row.get("interest_income_ratio") is not None)
        out.append({"period": row.get("period"), "year": _year(row.get("period")),
                    "tier": r["tier"], "tradeable": r["tradeable"],
                    "debt_to_assets": row.get("debt_to_assets"),
                    "interest_income_ratio": row.get("interest_income_ratio"),
                    "data_complete": complete})
    out.sort(key=lambda d: (d["year"] is None, d["year"]))
    return out


def compliance_changes(timeline: list) -> list:
    """Year-over-year tier transitions in a timeline (only the periods that changed)."""
    changes = []
    prev = None
    for row in timeline:
        if prev is not None and row["tier"] != prev["tier"]:
            changes.append({"from_period": prev["period"], "to_period": row["period"],
                            "from": prev["tier"], "to": row["tier"],
                            "worsened": _SEV[row["tier"]] > _SEV[prev["tier"]]})
        prev = row
    return changes


_SEV = {GREEN: 0, YELLOW: 1, RED: 2}


def format_timeline(ticker: str, timeline: list) -> str:
    if not timeline:
        return f"No cached history for {ticker}."
    lines = [f"{ticker.upper()} — halal tier by fiscal year:"]
    for r in timeline:
        d = f"{r['debt_to_assets']*100:.0f}%" if r["debt_to_assets"] is not None else "—"
        i = f"{r['interest_income_ratio']*100:.1f}%" if r["interest_income_ratio"] is not None else "—"
        flag = "" if r["data_complete"] else "  (partial data)"
        lines.append(f"  {r['period']}: {r['tier']}  debt {d} · interest {i}{flag}")
    changes = compliance_changes(timeline)
    if changes:
        lines.append("Transitions:")
        for c in changes:
            arrow = "↓ worsened" if c["worsened"] else "↑ improved"
            lines.append(f"  {c['to_period']}: {c['from']}→{c['to']}  ({arrow})")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else "BHARTIARTL"
    print(format_timeline(tk, tier_timeline(tk)))
