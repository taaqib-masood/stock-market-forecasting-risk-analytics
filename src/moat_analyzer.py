"""
FEATURE 5: Competitive Moat Analyzer
Compares a stock against its top competitors on key financial metrics.
Provides SWOT summary and best pick recommendation.
"""

import logging
import time
from datetime import datetime
import yfinance as yf
import numpy as np
from src.watchlist import nse

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_TTL = 3600

# Halal competitor maps (banks/insurance excluded)
COMPETITORS = {
    "TCS":        ["INFY", "WIPRO", "HCLTECH", "TECHM", "MPHASIS"],
    "INFY":       ["TCS", "WIPRO", "HCLTECH", "TECHM", "PERSISTENT"],
    "WIPRO":      ["TCS", "INFY", "HCLTECH", "TECHM", "MPHASIS"],
    "RELIANCE":   ["ONGC", "BPCL", "BHARTIARTL", "ADANIENT"],
    "SUNPHARMA":  ["DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"],
    "DRREDDY":    ["SUNPHARMA", "CIPLA", "LUPIN", "AUROPHARMA", "ALKEM"],
    "MARUTI":     ["M&M", "TVSMOTOR", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO"],
    "LT":         ["SIEMENS", "BEL", "ULTRACEMCO", "ADANIPORTS"],
    "BHARTIARTL": ["RELIANCE"],
    "HINDUNILVR": ["MARICO", "DABUR", "GODREJCP", "COLPAL", "BRITANNIA"],
    "ASIANPAINT": ["BERGEPAINT", "PIDILITIND", "KAJARIACER"],
    "TITAN":      ["TRENT", "DMART"],
    "NTPC":       ["POWERGRID", "TATAPOWER", "TORNTPOWER"],
    "TATASTEEL":  ["JSWSTEEL", "HINDALCO", "SAIL", "NMDC"],
}


def _get_info(ticker: str) -> dict:
    key = f"info_{ticker}"
    if key in _CACHE and time.time() - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    try:
        info = yf.Ticker(nse(ticker)).info or {}
        _CACHE[key] = (time.time(), info)
        return info
    except Exception:
        return {}


def _safe(info: dict, key: str, default=None):
    v = info.get(key)
    return v if v is not None else default


def _compare_peers(ticker: str) -> list:
    peers = COMPETITORS.get(ticker.upper(), [])[:4]
    all_tickers = [ticker] + peers
    rows = []
    for t in all_tickers:
        info = _get_info(t)
        time.sleep(0.2)
        rows.append({
            "ticker":          t,
            "market_cap_cr":   round(_safe(info, "marketCap", 0) / 1e7, 0),
            "pe_ratio":        _safe(info, "trailingPE"),
            "pb_ratio":        _safe(info, "priceToBook"),
            "roe_pct":         round(_safe(info, "returnOnEquity", 0) * 100, 1),
            "profit_margin_pct": round(_safe(info, "profitMargins", 0) * 100, 1),
            "de_ratio":        _safe(info, "debtToEquity"),
            "revenue_growth":  round(_safe(info, "revenueGrowth", 0) * 100, 1),
            "div_yield_pct":   round(_safe(info, "dividendYield", 0) * 100, 2),
        })
    return rows


def _moat_score(info: dict) -> tuple[int, str, list]:
    """Return (score 0-5, moat_type, reasons)."""
    roe  = _safe(info, "returnOnEquity", 0) * 100
    pm   = _safe(info, "profitMargins", 0) * 100
    de   = _safe(info, "debtToEquity", 99)
    rg   = _safe(info, "revenueGrowth", 0) * 100
    score = 0
    reasons = []

    if roe > 20:
        score += 2
        reasons.append(f"Exceptional ROE ({roe:.0f}%) — strong capital efficiency")
    elif roe > 12:
        score += 1
        reasons.append(f"Good ROE ({roe:.0f}%)")

    if pm > 15:
        score += 2
        reasons.append(f"High profit margin ({pm:.0f}%) — pricing power / cost advantage")
    elif pm > 8:
        score += 1

    if de < 0.3:
        score += 1
        reasons.append("Very low debt — financial fortress")

    moat_type = "Strong" if score >= 4 else "Moderate" if score >= 2 else "Weak"
    return score, moat_type, reasons


def _swot(ticker: str, info: dict, peers: list) -> dict:
    roe  = _safe(info, "returnOnEquity", 0) * 100
    pm   = _safe(info, "profitMargins", 0) * 100
    de   = _safe(info, "debtToEquity", 0) or 0
    rg   = _safe(info, "revenueGrowth", 0) * 100
    div  = _safe(info, "dividendYield", 0) * 100
    beta = _safe(info, "beta", 1) or 1

    strengths, weaknesses, opportunities, threats = [], [], [], []

    if roe > 15:   strengths.append(f"High ROE ({roe:.0f}%) — efficient capital use")
    if pm > 12:    strengths.append(f"Strong margins ({pm:.0f}%) — pricing power")
    if de < 0.5:   strengths.append("Low debt — strong balance sheet")
    if div > 2:    strengths.append(f"Solid dividend ({div:.1f}%) — income for investors")

    if roe < 8:    weaknesses.append(f"Low ROE ({roe:.0f}%) — capital not well deployed")
    if pm < 5:     weaknesses.append(f"Thin margins ({pm:.0f}%) — vulnerable to cost hikes")
    if de > 2:     weaknesses.append(f"High debt (D/E {de:.1f}) — financial risk")

    if rg > 10:    opportunities.append(f"Revenue growing {rg:.0f}% — expanding business")
    opportunities.append("Growing Indian consumer market")
    opportunities.append("Digital transformation tailwinds")

    if beta > 1.3: threats.append(f"High volatility (Beta {beta:.1f}) — sharp drops possible")
    threats.append("Global macro uncertainty / USD/INR volatility")
    if de > 1:     threats.append("Rising interest rates increase debt burden")

    return {
        "strengths":     strengths[:3],
        "weaknesses":    weaknesses[:3],
        "opportunities": opportunities[:3],
        "threats":       threats[:3],
    }


def analyze_moat(ticker: str) -> dict:
    """Full competitive moat analysis for a stock."""
    ticker = ticker.upper()
    info = _get_info(ticker)
    peers = _compare_peers(ticker)

    moat_score, moat_type, moat_reasons = _moat_score(info)
    swot = _swot(ticker, info, peers)

    # Best pick among peers
    scored_peers = []
    for p in peers:
        pi = _get_info(p["ticker"])
        s, _, _ = _moat_score(pi)
        scored_peers.append((p["ticker"], s))
    scored_peers.sort(key=lambda x: x[1], reverse=True)
    best_pick = scored_peers[0][0] if scored_peers else ticker

    return {
        "ticker":         ticker,
        "analysed_at":    datetime.utcnow().isoformat(),
        "moat_type":      moat_type,
        "moat_score":     f"{moat_score}/5",
        "moat_reasons":   moat_reasons,
        "swot":           swot,
        "peer_comparison": peers,
        "best_pick":      best_pick,
        "best_pick_reason": f"{best_pick} scores highest on ROE, margins, and debt metrics among peers.",
        "catalysts": [
            "Earnings beat in next quarter",
            "New product launches or market expansion",
            "FII/DII buying accumulation",
            "Sector tailwinds from government policy",
        ],
    }


if __name__ == "__main__":
    import sys, json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "TCS"
    result = analyze_moat(ticker)
    print(json.dumps(result, indent=2, default=str))
