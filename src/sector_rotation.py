"""
Sector Rotation Filter
======================
Scores NSE sectors by momentum. Returns top N sectors.
Scanner only processes stocks from top sectors — cleaner signals.

Sectors tracked via representative ETFs / index proxies on yfinance.
"""

import contextlib
import io
import numpy as np
import yfinance as yf

# Halal sectors — Banking removed (riba), ITC removed (tobacco), VEDL kept as metal
SECTORS = {
    "IT":      ["INFY.NS", "TCS.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS"],
    "Pharma":  ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS"],
    "Auto":    ["MARUTI.NS", "M&M.NS", "TVSMOTOR.NS", "BAJAJ-AUTO.NS", "HEROMOTOCO.NS"],
    "FMCG":    ["HINDUNILVR.NS", "NESTLEIND.NS", "BRITANNIA.NS", "DABUR.NS", "TATACONSUM.NS"],
    "Energy":  ["RELIANCE.NS", "ONGC.NS", "BPCL.NS", "NTPC.NS", "POWERGRID.NS"],
    "Metal":   ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "COALINDIA.NS", "NMDC.NS"],
    "Infra":   ["LT.NS", "ADANIPORTS.NS", "ULTRACEMCO.NS", "GRASIM.NS", "BEL.NS"],
    "Telecom": ["BHARTIARTL.NS", "RELIANCE.NS"],
}

# Map stock → sector for quick lookup
STOCK_SECTOR = {
    ticker.replace(".NS", ""): sector
    for sector, tickers in SECTORS.items()
    for ticker in tickers
}


def _sector_score(tickers: list[str]) -> float:
    """Score a sector 0–100 based on avg momentum of its stocks."""
    scores = []
    for t in tickers:
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                df = yf.download(t, period="3mo", interval="1d",
                                 progress=False, auto_adjust=True)
            if df.empty or len(df) < 20:
                continue
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            c = df["Close"].values.astype(float)
            sma20 = np.mean(c[-20:])
            sma50 = np.mean(c[-50:]) if len(c) >= 50 else sma20
            ret1m = (c[-1] / c[-22] - 1) * 100 if len(c) >= 22 else 0
            ret1w = (c[-1] / c[-6]  - 1) * 100 if len(c) >= 6  else 0
            score = sum([
                c[-1] > sma20,
                c[-1] > sma50,
                sma20  > sma50,
                ret1m  > 0,
                ret1w  > 0,
            ]) / 5 * 100
            scores.append(score)
        except Exception:
            continue
    return round(np.mean(scores), 1) if scores else 0.0


def rank_sectors(top_n: int = 2, verbose: bool = False) -> list[str]:
    """
    Score all sectors, return names of top N.
    E.g. ["Banking", "IT"]
    """
    results = {}
    for name, tickers in SECTORS.items():
        results[name] = _sector_score(tickers)
        if verbose:
            print(f"  {name:<10} {results[name]:.0f}/100")

    ranked = sorted(results.items(), key=lambda x: x[1], reverse=True)
    return [name for name, _ in ranked[:top_n]]


def stocks_in_sectors(sector_names: list[str]) -> list[str]:
    """Return list of stock tickers (without .NS) for given sectors."""
    tickers = []
    for s in sector_names:
        tickers += [t.replace(".NS", "") for t in SECTORS.get(s, [])]
    return tickers
