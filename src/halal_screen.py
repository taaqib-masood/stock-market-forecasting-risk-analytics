"""
AAOIFI halal screening + tiering (🟢 / 🟡 / 🔴).

Encodes the locked policy:
  - 🟢 passes the AAOIFI ratios (debt/assets < 33%, interest income < 5%)
  - 🟡 narrow-fail / purifiable (debt 33–45%, interest 5–10%) — trade + purify
  - 🔴 core-haram: vice sectors (alcohol/gambling/tobacco/…) OFF; riba-financials
        (banks/insurance) gated opt-in. Both are NOT tradeable by default.

Also computes the **purification fraction** — the impure-income % to give to charity.

`classify()` is pure and fully tested. `screen_ticker()` is a best-effort yfinance
wrapper (current fundamentals only — yfinance has no deep NSE history; see PROOF_RESULT).
"""
import math
from typing import Optional

GREEN, YELLOW, RED = "🟢", "🟡", "🔴"
_ORDER = {GREEN: 0, YELLOW: 1, RED: 2}


def _clean_ratio(x) -> Optional[float]:
    """Coerce None/NaN/non-numeric to None (a missing ratio is 'unknown', not 0)."""
    if x is None:
        return None
    try:
        f = float(x)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None

VICE_KEYWORDS = (
    "alcohol", "brewer", "distill", "winer", "tobacco", "cigar", "casino",
    "gambl", "gaming", "adult", "weapon", "aerospace & defense", "defense", "defence",
)
RIBA_KEYWORDS = (
    "bank", "insurance", "capital markets", "consumer finance", "credit services",
    "mortgage", "asset management",
)

# AAOIFI thresholds
DEBT_GREEN, DEBT_RED = 0.33, 0.45
INC_GREEN, INC_RED = 0.05, 0.10


def _worst(*tiers: str) -> str:
    return max(tiers, key=lambda t: _ORDER[t])


def classify(
    debt_to_assets: Optional[float],
    interest_income_ratio: Optional[float],
    is_vice: bool = False,
    is_riba_financial: bool = False,
) -> dict:
    """Classify a company into 🟢/🟡/🔴 from its AAOIFI ratios + sector flags."""
    debt_to_assets = _clean_ratio(debt_to_assets)
    interest_income_ratio = _clean_ratio(interest_income_ratio)
    if is_vice:
        return {"tier": RED, "tradeable": False, "purification_pct": None,
                "reasons": ["vice sector (alcohol/gambling/tobacco/…) — excluded"]}
    if is_riba_financial:
        return {"tier": RED, "tradeable": False, "purification_pct": None,
                "reasons": ["riba-financial (core interest income) — opt-in only"]}

    tiers, reasons = [], []

    if debt_to_assets is None:
        tiers.append(YELLOW); reasons.append("debt/assets unknown → caution")
    elif debt_to_assets < DEBT_GREEN:
        tiers.append(GREEN); reasons.append(f"debt/assets {debt_to_assets:.0%} < 33% ✓")
    elif debt_to_assets < DEBT_RED:
        tiers.append(YELLOW); reasons.append(f"debt/assets {debt_to_assets:.0%} in 33–45% (narrow fail)")
    else:
        tiers.append(RED); reasons.append(f"debt/assets {debt_to_assets:.0%} ≥ 45% ✗")

    if interest_income_ratio is None:
        tiers.append(YELLOW); reasons.append("interest-income ratio unknown → caution")
    elif interest_income_ratio < INC_GREEN:
        tiers.append(GREEN); reasons.append(f"interest income {interest_income_ratio:.1%} < 5% ✓")
    elif interest_income_ratio < INC_RED:
        tiers.append(YELLOW); reasons.append(f"interest income {interest_income_ratio:.1%} in 5–10% (purify)")
    else:
        tiers.append(RED); reasons.append(f"interest income {interest_income_ratio:.1%} ≥ 10% ✗")

    tier = _worst(*tiers)
    purification_pct = (round(interest_income_ratio, 4)
                        if interest_income_ratio is not None else None)
    return {"tier": tier, "tradeable": tier in (GREEN, YELLOW),
            "purification_pct": purification_pct, "reasons": reasons}


def screen_ticker(ticker: str) -> dict:
    """Best-effort screen of a live ticker from yfinance current fundamentals."""
    import yfinance as yf
    from src.watchlist import nse

    t = yf.Ticker(nse(ticker))
    dta = iir = None
    is_vice = is_riba = False

    try:
        info = t.info or {}
        text = f"{info.get('sector', '')} {info.get('industry', '')}".lower()
        is_vice = any(k in text for k in VICE_KEYWORDS)
        is_riba = any(k in text for k in RIBA_KEYWORDS)
    except Exception:
        pass

    try:
        bs = t.quarterly_balance_sheet
        if bs is not None and not bs.empty:
            td = bs.loc["Total Debt"].iloc[0] if "Total Debt" in bs.index else None
            ta = bs.loc["Total Assets"].iloc[0] if "Total Assets" in bs.index else None
            if td is not None and ta:
                dta = float(td) / float(ta)
    except Exception:
        pass

    try:
        inc = t.quarterly_income_stmt
        if inc is not None and not inc.empty:
            ii = inc.loc["Interest Income"].iloc[0] if "Interest Income" in inc.index else None
            rev = inc.loc["Total Revenue"].iloc[0] if "Total Revenue" in inc.index else None
            if ii is not None and rev:
                iir = abs(float(ii)) / float(rev)
    except Exception:
        pass

    result = classify(dta, iir, is_vice, is_riba)
    result.update({"ticker": ticker, "debt_to_assets": dta, "interest_income_ratio": iir})
    return result


def screen_cached(ticker: str, cache: Optional[dict] = None) -> dict:
    """
    Screen from the local fundamentals cache (Tickertape data, refreshed quarterly) —
    the stable, decoupled path. Carries the data source + as-of date for the citation
    posture. Returns 🟡 'no data' if the ticker hasn't been refreshed yet.

    NOTE: the watchlist is pre-screened for vice/riba sectors, so this ratio-only path
    assumes a non-vice universe; use screen_ticker() for arbitrary tickers.
    """
    from src.fundamentals import get_fundamentals
    f = get_fundamentals(ticker, cache=cache)
    if f is None:
        return {"tier": YELLOW, "tradeable": True, "purification_pct": None, "ticker": ticker,
                "debt_to_assets": None, "interest_income_ratio": None, "as_of": None, "stale": True,
                "source": None, "reasons": ["no cached fundamentals — run scripts/refresh_fundamentals.py"]}
    r = classify(f["debt_to_assets"], f["interest_income_ratio"])
    r.update({
        "ticker": ticker,
        "debt_to_assets": f["debt_to_assets"],
        "interest_income_ratio": f["interest_income_ratio"],
        "as_of": f["as_of"], "stale": f["stale"], "source": f["source"],
    })
    if f["stale"]:
        r["reasons"] = r["reasons"] + [f"data is STALE (as of {f['as_of']}) — re-run the refresh"]
    return r
