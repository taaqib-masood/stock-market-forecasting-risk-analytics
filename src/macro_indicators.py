"""
UPGRADE 2: Macroeconomic Indicators

Fetches key macro indicators from Yahoo Finance (yfinance) and FRED API.
Results are cached for 1 day (configurable).
"""

import time
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_CACHE: dict = {}
_CACHE_TTL_SECONDS = 86400  # 1 day

_CACHE_KEY = "macro_indicators"


def _from_cache() -> Optional[dict]:
    if _CACHE_KEY in _CACHE:
        ts, result = _CACHE[_CACHE_KEY]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return result
    return None


def _to_cache(result: dict):
    _CACHE[_CACHE_KEY] = (time.time(), result)


# ---------------------------------------------------------------------------
# Yahoo Finance fetchers
# ---------------------------------------------------------------------------

def _yf_latest(symbol: str) -> Optional[float]:
    """Return the most recent closing price for a Yahoo Finance symbol."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        if hist.empty:
            return None
        return round(float(hist["Close"].iloc[-1]), 4)
    except Exception as e:
        logger.warning("yfinance fetch failed for %s: %s", symbol, e)
        return None


def _fetch_vix() -> Optional[float]:
    return _yf_latest("^VIX")


def _fetch_dxy() -> Optional[float]:
    return _yf_latest("DX-Y.NYB")


def _fetch_gold() -> Optional[float]:
    return _yf_latest("GC=F")


def _fetch_nifty50() -> Optional[float]:
    return _yf_latest("^NSEI")


def _fetch_nifty_bank() -> Optional[float]:
    return _yf_latest("^NSEBANK")


# ---------------------------------------------------------------------------
# FRED API fetchers
# ---------------------------------------------------------------------------

def _fred_latest(series_id: str, api_key: str) -> Optional[float]:
    """
    Fetch the latest observation for a FRED series.
    Free API key from: https://fred.stlouisfed.org/docs/api/api_key.html
    """
    try:
        import requests
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&api_key={api_key}&file_type=json"
            f"&sort_order=desc&limit=5"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        observations = data.get("observations", [])
        for obs in observations:
            if obs["value"] != ".":
                return round(float(obs["value"]), 4)
        return None
    except Exception as e:
        logger.warning("FRED fetch failed for %s: %s", series_id, e)
        return None


def _fetch_yield_spread(api_key: str) -> Optional[float]:
    """10Y - 2Y Treasury spread (yield curve)."""
    t10 = _fred_latest("DGS10", api_key)
    t2 = _fred_latest("DGS2", api_key)
    if t10 is not None and t2 is not None:
        return round(t10 - t2, 4)
    return None


def _fetch_fed_funds_rate(api_key: str) -> Optional[float]:
    return _fred_latest("FEDFUNDS", api_key)


# ---------------------------------------------------------------------------
# NSE Advance/Decline ratio
# ---------------------------------------------------------------------------

def _fetch_advance_decline_ratio() -> Optional[float]:
    """
    Approximate A/D ratio using Nifty 500 constituents from yfinance.
    Returns advances / (advances + declines).
    """
    try:
        # Nifty 500 is large; use Nifty 50 as a quick proxy
        nifty50_tickers = [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
            "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
            "LT.NS", "BAJFINANCE.NS", "HCLTECH.NS", "ASIANPAINT.NS", "AXISBANK.NS",
            "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "WIPRO.NS",
        ]
        data = yf.download(
            nifty50_tickers, period="2d", progress=False, group_by="ticker"
        )
        advances = 0
        declines = 0
        for t in nifty50_tickers:
            try:
                closes = data[t]["Close"]
                if len(closes) >= 2 and closes.iloc[-1] > closes.iloc[-2]:
                    advances += 1
                else:
                    declines += 1
            except Exception:
                pass
        total = advances + declines
        if total == 0:
            return None
        return round(advances / total, 4)
    except Exception as e:
        logger.warning("A/D ratio fetch failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Market regime classification
# ---------------------------------------------------------------------------

def _classify_vix(vix: Optional[float]) -> str:
    if vix is None:
        return "unknown"
    if vix < 15:
        return "low_fear"
    if vix < 25:
        return "moderate"
    if vix < 35:
        return "elevated"
    return "extreme_fear"


def _classify_yield_curve(spread: Optional[float]) -> str:
    if spread is None:
        return "unknown"
    if spread < 0:
        return "inverted"
    if spread < 0.5:
        return "flat"
    return "normal"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_macro_indicators(fred_api_key: Optional[str] = None) -> dict:
    """
    Fetch all macro indicators.

    Parameters
    ----------
    fred_api_key : FRED API key. Falls back to env var FRED_API_KEY.
                   If not provided, FRED indicators will be None.

    Returns
    -------
    {
        "vix"              : float | None,
        "dxy"              : float | None,
        "gold"             : float | None,
        "yield_spread"     : float | None,  # 10Y-2Y
        "fed_funds_rate"   : float | None,
        "nifty50"          : float | None,
        "nifty_bank"       : float | None,
        "advance_decline"  : float | None,  # 0-1
        "vix_regime"       : str,
        "yield_curve_regime": str,
        "cached"           : bool,
        "fetched_at"       : str,
    }
    """
    cached = _from_cache()
    if cached:
        cached["cached"] = True
        return cached

    key = fred_api_key or os.environ.get("FRED_API_KEY")

    vix = _fetch_vix()
    dxy = _fetch_dxy()
    gold = _fetch_gold()
    nifty50 = _fetch_nifty50()
    nifty_bank = _fetch_nifty_bank()
    advance_decline = _fetch_advance_decline_ratio()

    yield_spread = _fetch_yield_spread(key) if key else None
    fed_funds_rate = _fetch_fed_funds_rate(key) if key else None

    result = {
        "vix": vix,
        "dxy": dxy,
        "gold": gold,
        "yield_spread": yield_spread,
        "fed_funds_rate": fed_funds_rate,
        "nifty50": nifty50,
        "nifty_bank": nifty_bank,
        "advance_decline": advance_decline,
        "vix_regime": _classify_vix(vix),
        "yield_curve_regime": _classify_yield_curve(yield_spread),
        "cached": False,
        "fetched_at": datetime.utcnow().isoformat(),
    }

    _to_cache(result)
    return result


def get_macro_features(fred_api_key: Optional[str] = None) -> dict:
    """
    Returns flat feature dict for ML model ingestion.

    Features:
        vix_level         : raw VIX (0 if unavailable)
        dxy_level         : raw DXY
        yield_curve_spread: 10Y-2Y spread
        market_breadth    : advance/decline ratio (0-1)
    """
    data = get_macro_indicators(fred_api_key)
    return {
        "vix_level": data["vix"] or 0.0,
        "dxy_level": data["dxy"] or 0.0,
        "yield_curve_spread": data["yield_spread"] or 0.0,
        "market_breadth": data["advance_decline"] or 0.5,
    }


if __name__ == "__main__":
    import json
    result = get_macro_indicators()
    print(json.dumps(result, indent=2))
