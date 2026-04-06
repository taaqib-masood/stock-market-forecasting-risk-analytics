"""
Data provider — Alpaca Markets (free account, no download needed).

Why Alpaca instead of yfinance:
  - Real-time + historical data via REST API (free tier)
  - Same account used for paper/live trading
  - TradingView can send webhook alerts directly to Alpaca-connected systems
  - No CSV files, no local data, pulls fresh on every run

Setup (one-time, free):
  1. Sign up at https://alpaca.markets (free)
  2. Go to Paper Trading → API Keys → Generate
  3. Add to .env:
       ALPACA_API_KEY=PKxxxxxxxx
       ALPACA_SECRET_KEY=xxxxxxxx
       ALPACA_BASE_URL=https://paper-api.alpaca.markets   # paper
       # ALPACA_BASE_URL=https://api.alpaca.markets       # live

Fallback: if ALPACA_API_KEY is not set, falls back to yfinance silently.
"""

import os
import json
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError
import pandas as pd
import numpy as np


ALPACA_DATA_URL = "https://data.alpaca.markets/v2"


def _alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
        "Content-Type":        "application/json",
    }


def _alpaca_available() -> bool:
    return bool(os.environ.get("ALPACA_API_KEY"))


def _fetch_alpaca(ticker: str, start: str, end: str, timeframe: str = "1Day") -> pd.DataFrame:
    """
    Pull OHLCV bars from Alpaca Data API v2.
    timeframe: "1Day" | "1Hour" | "15Min" | "5Min" | "1Min"
    """
    url = (
        f"{ALPACA_DATA_URL}/stocks/{ticker}/bars"
        f"?timeframe={timeframe}&start={start}&end={end}&limit=10000&feed=iex"
    )
    headers = _alpaca_headers()
    rows = []
    next_token = None

    while True:
        page_url = url + (f"&page_token={next_token}" if next_token else "")
        req = Request(page_url, headers=headers)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        for bar in data.get("bars", []):
            rows.append({
                "Date":   bar["t"][:10],
                "Open":   bar["o"],
                "High":   bar["h"],
                "Low":    bar["l"],
                "Close":  bar["c"],
                "Volume": bar["v"],
            })

        next_token = data.get("next_page_token")
        if not next_token:
            break

    if not rows:
        raise ValueError(f"No Alpaca data returned for {ticker}")

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    df.sort_index(inplace=True)
    return df


def _fetch_yfinance(ticker: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No yfinance data for {ticker}")
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def load_bars(ticker: str, years: int = 5, timeframe: str = "1Day") -> pd.DataFrame:
    """
    Load OHLCV data for `ticker`.
    Uses Alpaca if credentials are present, else falls back to yfinance.

    Parameters
    ----------
    ticker    : e.g. "AAPL", "TSLA", "SPY"
    years     : how many years of history to pull
    timeframe : "1Day" | "1Hour" | "15Min" (Alpaca only; yfinance always daily)
    """
    end   = datetime.utcnow()
    start = end - timedelta(days=years * 365)
    start_str = start.strftime("%Y-%m-%d")
    end_str   = end.strftime("%Y-%m-%d")

    if _alpaca_available():
        print(f"  [Data] Alpaca → {ticker} ({timeframe}, {years}yr)")
        return _fetch_alpaca(ticker, start_str, end_str, timeframe)
    else:
        print(f"  [Data] yfinance fallback → {ticker} ({years}yr)  "
              f"[Set ALPACA_API_KEY for real-time data]")
        return _fetch_yfinance(ticker, start_str, end_str)


def load_market_context(years: int = 5) -> pd.DataFrame:
    """
    Load SPY (market trend) and VIX (volatility regime) as context features.
    Same provider logic — Alpaca if available, yfinance otherwise.
    """
    end_str   = datetime.utcnow().strftime("%Y-%m-%d")
    start_str = (datetime.utcnow() - timedelta(days=years * 365)).strftime("%Y-%m-%d")

    spy_df = (
        _fetch_alpaca("SPY",  start_str, end_str)
        if _alpaca_available()
        else _fetch_yfinance("SPY",  start_str, end_str)
    )
    try:
        vix_df = _fetch_yfinance("^VIX", start_str, end_str)  # VIX not on Alpaca free tier
    except Exception:
        vix_df = pd.DataFrame()

    ctx = pd.DataFrame(index=spy_df.index)
    ctx["spy_return"]      = spy_df["Close"].pct_change()
    ctx["spy_sma50"]       = spy_df["Close"].rolling(50).mean()
    ctx["spy_above_sma50"] = (spy_df["Close"] > ctx["spy_sma50"]).astype(int)

    if not vix_df.empty:
        ctx["vix_close"]  = vix_df["Close"].reindex(ctx.index, method="ffill")
        ctx["vix_regime"] = pd.cut(
            ctx["vix_close"],
            bins=[0, 15, 25, 40, 999],
            labels=[0, 1, 2, 3],
        ).astype(float)
    else:
        ctx["vix_close"]  = np.nan
        ctx["vix_regime"] = np.nan

    return ctx
