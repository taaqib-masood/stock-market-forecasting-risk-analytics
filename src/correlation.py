"""
Correlation & Portfolio Risk
=============================
Computes a correlation matrix for open positions + candidates.
Blocks new trades that are too correlated with existing positions.

Rule: if new stock has correlation > 0.75 with any open position → skip.
This ensures you're not doubling up on the same sector bet.
"""

import contextlib
import io
import numpy as np
import pandas as pd
import yfinance as yf
from src.watchlist import nse

CORR_THRESHOLD = 0.75   # block if correlation > this


def _returns(ticker: str, period: str = "6mo") -> pd.Series:
    """Daily returns series for a ticker."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(nse(ticker), period=period, interval="1d",
                             progress=False, auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df["Close"].pct_change().dropna()
    except Exception:
        return pd.Series(dtype=float)


def correlation_matrix(tickers: list[str]) -> pd.DataFrame:
    """
    Compute pairwise correlation matrix for a list of tickers.
    Returns a DataFrame with tickers as both index and columns.
    """
    series = {}
    for t in tickers:
        r = _returns(t)
        if not r.empty:
            series[t] = r

    if len(series) < 2:
        return pd.DataFrame()

    df   = pd.DataFrame(series)
    corr = df.corr(method="pearson")
    return corr.round(3)


def is_too_correlated(
    candidate: str,
    open_positions: list[str],
    threshold: float = CORR_THRESHOLD,
) -> tuple[bool, str, float]:
    """
    Check if `candidate` is too correlated with any open position.
    Returns (blocked, reason, max_corr).
    """
    if not open_positions:
        return False, "", 0.0

    all_tickers = open_positions + [candidate]
    corr        = correlation_matrix(all_tickers)

    if corr.empty or candidate not in corr.columns:
        return False, "", 0.0

    max_corr  = 0.0
    max_peer  = ""
    for peer in open_positions:
        if peer in corr.index:
            c = float(corr.loc[candidate, peer])
            if abs(c) > max_corr:
                max_corr = abs(c)
                max_peer = peer

    if max_corr >= threshold:
        return (True,
                f"Corr {max_corr:.2f} with open position {max_peer} (>{threshold})",
                max_corr)
    return False, "", max_corr


def portfolio_correlation_risk(open_positions: list[str]) -> dict:
    """
    Evaluate the correlation risk of the current portfolio.
    Returns avg_corr, max_corr, highly_correlated_pairs.
    """
    if len(open_positions) < 2:
        return {"avg_corr": 0.0, "max_corr": 0.0, "pairs": []}

    corr = correlation_matrix(open_positions)
    if corr.empty:
        return {"avg_corr": 0.0, "max_corr": 0.0, "pairs": []}

    pairs = []
    vals  = []
    n     = len(open_positions)
    for i in range(n):
        for j in range(i + 1, n):
            t1, t2 = open_positions[i], open_positions[j]
            if t1 in corr.index and t2 in corr.columns:
                c = float(corr.loc[t1, t2])
                vals.append(abs(c))
                if abs(c) >= 0.6:
                    pairs.append({"a": t1, "b": t2, "corr": round(c, 3)})

    return {
        "avg_corr": round(float(np.mean(vals)), 3) if vals else 0.0,
        "max_corr": round(float(np.max(vals)),  3) if vals else 0.0,
        "pairs":    sorted(pairs, key=lambda x: abs(x["corr"]), reverse=True),
        "matrix":   corr.to_dict() if not corr.empty else {},
    }
