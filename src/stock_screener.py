"""
FEATURE 3: Fundamental Stock Screener
Screens stocks on valuation, growth, debt, and quality metrics.
Beginner-friendly output with plain-English explanations.
Halal-compliant: excludes banks, insurance, alcohol, tobacco.
"""

import logging
import time
from datetime import datetime
from typing import Optional
import yfinance as yf
import numpy as np
from src.watchlist import nse, HALAL_NIFTY, HALAL_NEXT_50

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_CACHE_TTL = 3600  # 1 hour


def _cached(key: str):
    if key in _CACHE and time.time() - _CACHE[key][0] < _CACHE_TTL:
        return _CACHE[key][1]
    return None


def _set_cache(key: str, val):
    _CACHE[key] = (time.time(), val)


# ── Sector P/E benchmarks (halal sectors) ────────────────────────────────────
SECTOR_PE = {
    "IT":        28, "Pharma":   25, "Auto":      20,
    "FMCG":      45, "Energy":   12, "Metal":     10,
    "Infra":     18, "Telecom":  30, "Retail":    55,
    "Chemical":  30, "Logistics": 22,
}


def _fetch_fundamentals(ticker: str) -> dict:
    cached = _cached(f"fund_{ticker}")
    if cached:
        return cached

    try:
        t = yf.Ticker(nse(ticker))
        info = t.info or {}

        # Income statement
        try:
            fin = t.financials
            rev_list = fin.loc["Total Revenue"].dropna().values.tolist() if "Total Revenue" in fin.index else []
            net_list = fin.loc["Net Income"].dropna().values.tolist()     if "Net Income"    in fin.index else []
        except Exception:
            rev_list, net_list = [], []

        def _growth(series):
            if len(series) >= 2 and series[-1] and series[-1] != 0:
                return round((series[0] - series[-1]) / abs(series[-1]) * 100, 1)
            return None

        result = {
            "pe_ratio":     info.get("trailingPE"),
            "pb_ratio":     info.get("priceToBook"),
            "ps_ratio":     info.get("priceToSalesTrailing12Months"),
            "roe":          round(info.get("returnOnEquity", 0) * 100, 1) if info.get("returnOnEquity") else None,
            "roce":         None,   # not directly in yfinance info
            "de_ratio":     info.get("debtToEquity"),
            "div_yield":    round(info.get("dividendYield", 0) * 100, 2) if info.get("dividendYield") else 0.0,
            "payout_ratio": round(info.get("payoutRatio", 0) * 100, 1) if info.get("payoutRatio") else None,
            "market_cap":   info.get("marketCap"),
            "sector":       info.get("sector", "Unknown"),
            "rev_growth_1y": _growth(rev_list[:2]) if len(rev_list) >= 2 else None,
            "rev_growth_3y": _growth(rev_list[:4]) if len(rev_list) >= 4 else None,
            "profit_margin": round(info.get("profitMargins", 0) * 100, 1) if info.get("profitMargins") else None,
            "current_ratio": info.get("currentRatio"),
            "beta":          info.get("beta"),
            "52w_high":      info.get("fiftyTwoWeekHigh"),
            "52w_low":       info.get("fiftyTwoWeekLow"),
            "analyst_target": info.get("targetMeanPrice"),
        }
        _set_cache(f"fund_{ticker}", result)
        return result
    except Exception as e:
        logger.warning("Fundamentals fetch failed for %s: %s", ticker, e)
        return {}


def _moat_rating(f: dict) -> str:
    """Simple moat proxy based on margins and ROE."""
    roe   = f.get("roe") or 0
    pm    = f.get("profit_margin") or 0
    de    = f.get("de_ratio") or 99
    score = 0
    if roe > 20:  score += 2
    elif roe > 12: score += 1
    if pm > 15:   score += 2
    elif pm > 8:  score += 1
    if de < 0.5:  score += 1
    if score >= 4:  return "Strong"
    if score >= 2:  return "Moderate"
    return "Weak"


def _risk_rating(f: dict) -> int:
    """Risk score 1 (safe) – 10 (very risky)."""
    risk = 5
    de = f.get("de_ratio") or 0
    beta = f.get("beta") or 1
    cr = f.get("current_ratio") or 1
    if de > 2:    risk += 2
    elif de > 1:  risk += 1
    if beta > 1.5: risk += 2
    elif beta > 1: risk += 1
    if cr < 1:    risk += 1
    if de < 0.3:  risk -= 1
    if beta < 0.8: risk -= 1
    return max(1, min(10, risk))


def _valuation_verdict(pe: Optional[float], sector: str) -> str:
    if pe is None:
        return "P/E not available"
    benchmark = SECTOR_PE.get(sector, 25)
    if pe < benchmark * 0.7:
        return f"Undervalued (P/E {pe:.0f} vs sector avg {benchmark})"
    elif pe < benchmark * 1.2:
        return f"Fairly valued (P/E {pe:.0f} vs sector avg {benchmark})"
    else:
        return f"Expensive (P/E {pe:.0f} vs sector avg {benchmark})"


def screen_stock(ticker: str) -> dict:
    """
    Screen a single halal stock on fundamentals.
    Returns a beginner-friendly report.
    """
    f = _fetch_fundamentals(ticker)
    if not f:
        return {"ticker": ticker, "error": "Data unavailable — try again later"}

    pe      = f.get("pe_ratio")
    roe     = f.get("roe")
    de      = f.get("de_ratio")
    div     = f.get("div_yield", 0)
    rev_g   = f.get("rev_growth_1y")
    pm      = f.get("profit_margin")
    moat    = _moat_rating(f)
    risk    = _risk_rating(f)
    val     = _valuation_verdict(pe, f.get("sector", ""))

    # Bull/bear targets (rough analyst target or ±20%)
    target  = f.get("analyst_target")
    h52     = f.get("52w_high")
    l52     = f.get("52w_low")

    # Entry zone: near 52w low or Fib 38.2% support
    if h52 and l52:
        entry_zone  = round(l52 + 0.382 * (h52 - l52), 2)
        bull_target = round(h52 * 1.10, 2)
        bear_target = round(l52 * 0.90, 2)
    else:
        entry_zone = bull_target = bear_target = None

    # Plain-English quality summary
    quality_notes = []
    if roe and roe > 15: quality_notes.append(f"Good ROE ({roe}%) — company uses capital well")
    if de is not None and de < 0.5: quality_notes.append("Low debt — financially strong")
    elif de and de > 2: quality_notes.append("High debt — watch carefully")
    if rev_g and rev_g > 10: quality_notes.append(f"Strong revenue growth ({rev_g}% YoY)")
    if pm and pm > 15: quality_notes.append(f"High profit margin ({pm}%) — pricing power")
    if div > 2: quality_notes.append(f"Good dividend yield ({div}%)")

    overall_score = sum([
        bool(roe and roe > 12),
        bool(de is not None and de < 1),
        bool(rev_g and rev_g > 8),
        bool(pm and pm > 10),
        moat in ("Strong", "Moderate"),
        risk <= 5,
    ])

    if overall_score >= 5:
        verdict = "Strong Buy (Fundamental)"
    elif overall_score >= 3:
        verdict = "Buy (Fundamental)"
    elif overall_score >= 2:
        verdict = "Hold / Watch"
    else:
        verdict = "Avoid"

    return {
        "ticker": ticker,
        "screened_at": datetime.utcnow().isoformat(),
        "verdict": verdict,
        "overall_score": f"{overall_score}/6",
        "valuation": {
            "pe_ratio": pe,
            "pb_ratio": f.get("pb_ratio"),
            "verdict":  val,
        },
        "growth": {
            "revenue_growth_1y": rev_g,
            "revenue_growth_3y": f.get("rev_growth_3y"),
            "profit_margin":     pm,
        },
        "financial_health": {
            "debt_to_equity": de,
            "current_ratio":  f.get("current_ratio"),
            "roe":            roe,
            "dividend_yield": div,
            "payout_ratio":   f.get("payout_ratio"),
        },
        "quality": {
            "moat":       moat,
            "risk_rating": f"{risk}/10",
            "beta":        f.get("beta"),
            "notes":       quality_notes,
        },
        "price_targets": {
            "entry_zone":   entry_zone,
            "bull_target":  bull_target,
            "bear_target":  bear_target,
            "analyst_target": target,
        },
        "halal_compliant": True,
    }


def screen_all(tickers: list = None, top_n: int = 10) -> list:
    """Screen multiple stocks and return top picks ranked by overall score."""
    if tickers is None:
        tickers = HALAL_NIFTY + HALAL_NEXT_50[:20]

    results = []
    for ticker in tickers:
        try:
            r = screen_stock(ticker)
            if "error" not in r:
                results.append(r)
            time.sleep(0.3)  # be gentle with yfinance
        except Exception as e:
            logger.warning("Screen failed for %s: %s", ticker, e)

    # Sort by overall_score descending
    results.sort(key=lambda x: int(x["overall_score"].split("/")[0]), reverse=True)
    return results[:top_n]


if __name__ == "__main__":
    import sys, json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "TCS"
    result = screen_stock(ticker)
    print(json.dumps(result, indent=2, default=str))
