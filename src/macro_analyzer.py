"""
FEATURE 6: Macro Impact Assessment
Fetches macro data and explains how it impacts your portfolio.
Uses FRED API + yfinance. Falls back to defaults if unavailable.
"""

import logging
import os
import time
from datetime import datetime
from typing import Optional
import urllib.request
import json
import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_TTL = 3600


def _cache_get(k):
    if k in _CACHE and time.time() - _CACHE[k][0] < _TTL:
        return _CACHE[k][1]
    return None


def _cache_set(k, v):
    _CACHE[k] = (time.time(), v)


# ── FRED fetch ────────────────────────────────────────────────────────────────

def _fred(series_id: str, label: str) -> dict:
    cached = _cache_get(f"fred_{series_id}")
    if cached:
        return cached
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        return {"value": None, "date": None, "label": label, "source": "FRED (key missing)"}
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={series_id}&api_key={key}&file_type=json"
               f"&sort_order=desc&limit=5")
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for obs in data.get("observations", []):
            if obs["value"] != ".":
                result = {"value": float(obs["value"]), "date": obs["date"],
                          "label": label, "source": "FRED"}
                _cache_set(f"fred_{series_id}", result)
                return result
    except Exception as e:
        logger.warning("FRED %s failed: %s", series_id, e)
    return {"value": None, "date": None, "label": label, "source": "FRED (unavailable)"}


def _yf_price(symbol: str, label: str, default: float = 0.0) -> dict:
    cached = _cache_get(f"yf_{symbol}")
    if cached:
        return cached
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if not hist.empty:
            result = {"value": round(float(hist["Close"].iloc[-1]), 2),
                      "label": label, "source": "yfinance"}
            _cache_set(f"yf_{symbol}", result)
            return result
    except Exception as e:
        logger.warning("yfinance %s failed: %s", symbol, e)
    return {"value": default, "label": label, "source": "yfinance (unavailable)"}


# ── Economic cycle classifier ─────────────────────────────────────────────────

def _classify_cycle(gdp_growth: Optional[float], inflation: Optional[float],
                    rate: Optional[float]) -> dict:
    g = gdp_growth or 6.5   # India avg default
    i = inflation  or 4.5
    r = rate       or 6.5

    if g > 6 and i < 5 and r < 7:
        phase = "Expansion"
        desc  = "Economy is growing healthily. Good time to hold quality stocks."
        favour  = ["IT", "Auto", "Retail", "FMCG"]
        avoid   = ["Defensives only"]
    elif g > 4 and i > 6:
        phase = "Stagflation Risk"
        desc  = "Growth slowing but prices rising. Be selective — favour commodity exporters."
        favour  = ["Energy", "Metal", "Pharma"]
        avoid   = ["High-debt companies", "Rate-sensitive sectors"]
    elif g < 4:
        phase = "Slowdown"
        desc  = "Economy slowing down. Rotate to defensive, dividend-paying halal stocks."
        favour  = ["Pharma", "FMCG", "Energy"]
        avoid   = ["Auto", "Infrastructure", "Capital goods"]
    elif r > 7.5:
        phase = "Rate Tightening"
        desc  = "RBI raising rates. Avoid high-debt companies. Cash and quality are king."
        favour  = ["IT (dollar earners)", "Pharma", "FMCG"]
        avoid   = ["High-debt infra", "Real estate"]
    else:
        phase = "Stable"
        desc  = "Macro environment is balanced. Stick to your strategy."
        favour  = ["IT", "FMCG", "Pharma", "Auto"]
        avoid   = ["Highly leveraged companies"]

    return {"phase": phase, "description": desc,
            "favour_sectors": favour, "avoid_sectors": avoid}


# ── Main ──────────────────────────────────────────────────────────────────────

def full_macro_analysis() -> dict:
    """Fetch all macro indicators and produce a portfolio impact report."""
    # Market indicators
    vix    = _yf_price("^VIX",     "VIX (Fear Index)", 18)
    nifty  = _yf_price("^NSEI",    "Nifty 50", 22000)
    dxy    = _yf_price("DX-Y.NYB", "US Dollar Index", 104)
    gold   = _yf_price("GC=F",     "Gold (USD/oz)", 2300)
    usdinr = _yf_price("INR=X",    "USD/INR", 84)

    # FRED indicators
    fed_rate   = _fred("FEDFUNDS",   "Fed Funds Rate (%)")
    us_cpi     = _fred("CPIAUCSL",   "US CPI (Inflation Index)")
    t10y       = _fred("DGS10",      "US 10Y Treasury Yield (%)")
    t2y        = _fred("DGS2",       "US 2Y Treasury Yield (%)")
    yield_spread = None
    if t10y["value"] and t2y["value"]:
        yield_spread = round(t10y["value"] - t2y["value"], 3)

    # Economic cycle
    cycle = _classify_cycle(
        gdp_growth=6.5,                   # India FY25 estimate
        inflation=us_cpi["value"],
        rate=fed_rate["value"],
    )

    # Portfolio impact rules
    impacts = []
    if vix["value"] and vix["value"] > 25:
        impacts.append("⚠️ VIX > 25: Reduce position sizes by 30-50%")
    if vix["value"] and vix["value"] > 35:
        impacts.append("🛑 VIX > 35: Move to cash, wait for stabilisation")
    if dxy["value"] and dxy["value"] > 106:
        impacts.append("💵 Strong USD: Hurts FII flows — favour IT exporters (TCS, INFY)")
    if dxy["value"] and dxy["value"] < 100:
        impacts.append("💵 Weak USD: Good for FII inflows — broader market rally likely")
    if yield_spread is not None and yield_spread < 0:
        impacts.append("📉 Inverted yield curve: Recession signal — be defensive")
    if gold["value"] and gold["value"] > 2400:
        impacts.append("🥇 Gold rising: Risk-off sentiment — reduce equity exposure")
    if usdinr["value"] and usdinr["value"] > 86:
        impacts.append("📉 INR weak: Import costs rise — avoid commodity importers")

    if not impacts:
        impacts.append("✅ No major macro red flags — normal market conditions")

    # Rebalancing suggestions
    rebalancing = []
    for sector in cycle["favour_sectors"]:
        rebalancing.append(f"Increase weight in {sector}")
    for sector in cycle["avoid_sectors"]:
        rebalancing.append(f"Reduce weight in {sector}")

    return {
        "analysed_at": datetime.utcnow().isoformat(),
        "market_indicators": {
            "vix":      vix,
            "nifty_50": nifty,
            "dxy":      dxy,
            "gold":     gold,
            "usd_inr":  usdinr,
        },
        "interest_rates": {
            "fed_funds_rate":  fed_rate,
            "us_10y_yield":    t10y,
            "us_2y_yield":     t2y,
            "yield_spread_10y_2y": yield_spread,
            "yield_curve_status": ("Inverted ⚠️" if yield_spread and yield_spread < 0
                                   else "Normal ✅" if yield_spread else "Unknown"),
        },
        "economic_cycle": cycle,
        "portfolio_impact": impacts,
        "rebalancing_suggestions": rebalancing,
        "plain_english": (
            f"The economy is in a {cycle['phase']} phase. "
            f"{cycle['description']} "
            f"Focus on: {', '.join(cycle['favour_sectors'])}."
        ),
    }


if __name__ == "__main__":
    import json
    result = full_macro_analysis()
    print(json.dumps(result, indent=2, default=str))
