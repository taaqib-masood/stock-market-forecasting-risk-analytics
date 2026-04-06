"""
FEATURE 2: Pattern Finder
Finds seasonal patterns, day-of-week tendencies, earnings behaviour,
and sector rotation signals using free data sources.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional
import numpy as np
import pandas as pd
import yfinance as yf
from src.watchlist import nse

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_TTL = 3600


def _cache_get(k):
    if k in _CACHE and time.time() - _CACHE[k][0] < _TTL:
        return _CACHE[k][1]
    return None


def _cache_set(k, v):
    _CACHE[k] = (time.time(), v)


def _fetch_daily(ticker: str, years: int = 5) -> pd.DataFrame:
    cached = _cache_get(f"daily_{ticker}_{years}")
    if cached is not None:
        return cached
    try:
        df = yf.download(nse(ticker), period=f"{years}y", interval="1d",
                         progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        _cache_set(f"daily_{ticker}_{years}", df)
        return df
    except Exception as e:
        logger.warning("Fetch failed: %s", e)
        return pd.DataFrame()


# ── Seasonal patterns ──────────────────────────────────────────────────────────

def seasonal_patterns(ticker: str) -> dict:
    """Best and worst months historically."""
    df = _fetch_daily(ticker)
    if df.empty:
        return {}

    df["month"]  = df.index.month
    df["return"] = df["Close"].pct_change()

    monthly = df.groupby("month")["return"].mean() * 100
    monthly.index = [datetime(2000, m, 1).strftime("%B") for m in monthly.index]

    best_month  = monthly.idxmax()
    worst_month = monthly.idxmin()

    return {
        "best_month":  {"month": best_month,  "avg_return": round(monthly[best_month], 2)},
        "worst_month": {"month": worst_month, "avg_return": round(monthly[worst_month], 2)},
        "monthly_avg_returns": {k: round(v, 2) for k, v in monthly.items()},
        "interpretation": (
            f"{ticker} historically performs best in {best_month} "
            f"(avg +{monthly[best_month]:.1f}%) and worst in {worst_month} "
            f"(avg {monthly[worst_month]:.1f}%)."
        ),
    }


# ── Day-of-week patterns ───────────────────────────────────────────────────────

def day_of_week_patterns(ticker: str) -> dict:
    df = _fetch_daily(ticker)
    if df.empty:
        return {}

    df["dow"]    = df.index.dayofweek
    df["return"] = df["Close"].pct_change()

    days = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}
    dow_avg = df.groupby("dow")["return"].mean() * 100
    dow_avg.index = [days[d] for d in dow_avg.index]

    best_day  = dow_avg.idxmax()
    worst_day = dow_avg.idxmin()

    return {
        "best_day":  {"day": best_day,  "avg_return": round(dow_avg[best_day], 3)},
        "worst_day": {"day": worst_day, "avg_return": round(dow_avg[worst_day], 3)},
        "daily_avg_returns": {k: round(v, 3) for k, v in dow_avg.items()},
        "interpretation": (
            f"Historically, {ticker} is strongest on {best_day} "
            f"and weakest on {worst_day}."
        ),
    }


# ── Earnings behaviour ─────────────────────────────────────────────────────────

def earnings_behaviour(ticker: str) -> dict:
    """Analyse pre-earnings run and post-earnings gap."""
    df = _fetch_daily(ticker, years=3)
    if df.empty:
        return {"interpretation": "No data available"}

    try:
        t = yf.Ticker(nse(ticker))
        cal = t.calendar
        next_earnings = None
        if cal is not None and not (isinstance(cal, pd.DataFrame) and cal.empty):
            if isinstance(cal, dict) and "Earnings Date" in cal:
                dates = cal["Earnings Date"]
                next_earnings = str(dates[0]) if dates else None
    except Exception:
        next_earnings = None

    # Simulate pre-earnings run: 5-day return before estimated earnings months
    # Use Q1/Q2/Q3/Q4 typical months for Indian stocks (Apr, Jul, Oct, Jan)
    earnings_months = [1, 4, 7, 10]
    pre_runs, post_gaps = [], []

    df["month"]  = df.index.month
    df["return"] = df["Close"].pct_change()

    for m in earnings_months:
        month_data = df[df["month"] == m]
        if len(month_data) >= 10:
            pre_run  = month_data["return"].iloc[:5].sum() * 100
            post_gap = month_data["return"].iloc[5:10].sum() * 100
            pre_runs.append(pre_run)
            post_gaps.append(post_gap)

    avg_pre  = round(np.mean(pre_runs), 2)  if pre_runs  else 0
    avg_post = round(np.mean(post_gaps), 2) if post_gaps else 0

    return {
        "next_earnings":      next_earnings or "Not available",
        "avg_pre_earnings_run":  avg_pre,
        "avg_post_earnings_gap": avg_post,
        "interpretation": (
            f"On average, {ticker} moves {'+' if avg_pre >= 0 else ''}{avg_pre:.1f}% "
            f"in the 5 days BEFORE earnings and "
            f"{'+' if avg_post >= 0 else ''}{avg_post:.1f}% in the 5 days AFTER."
        ),
    }


# ── Sector rotation signals ────────────────────────────────────────────────────

def sector_rotation_signal(ticker: str) -> dict:
    """Relative strength of this stock vs its sector and Nifty."""
    df_stock = _fetch_daily(ticker, years=1)
    df_nifty = _cache_get("nifty_1y")
    if df_nifty is None:
        try:
            df_nifty = yf.download("^NSEI", period="1y", progress=False, auto_adjust=True)
            df_nifty.columns = [c[0] if isinstance(c, tuple) else c for c in df_nifty.columns]
            _cache_set("nifty_1y", df_nifty)
        except Exception:
            df_nifty = pd.DataFrame()

    if df_stock.empty or df_nifty.empty:
        return {"interpretation": "Data unavailable"}

    stock_ret = (df_stock["Close"].iloc[-1] / df_stock["Close"].iloc[0] - 1) * 100
    nifty_ret = (df_nifty["Close"].iloc[-1] / df_nifty["Close"].iloc[0] - 1) * 100
    rel_str   = round(stock_ret - nifty_ret, 2)

    # 1-month
    stock_1m = (df_stock["Close"].iloc[-1] / df_stock["Close"].iloc[-22] - 1) * 100 if len(df_stock) >= 22 else 0
    nifty_1m = (df_nifty["Close"].iloc[-1] / df_nifty["Close"].iloc[-22] - 1) * 100 if len(df_nifty) >= 22 else 0
    rel_1m   = round(stock_1m - nifty_1m, 2)

    return {
        "stock_return_1y":  round(float(stock_ret), 2),
        "nifty_return_1y":  round(float(nifty_ret), 2),
        "relative_strength_1y": rel_str,
        "relative_strength_1m": rel_1m,
        "interpretation": (
            f"{ticker} {'outperformed' if rel_str > 0 else 'underperformed'} Nifty 50 "
            f"by {abs(rel_str):.1f}% over the last year. "
            f"{'This is a market leader — favour it in portfolios.' if rel_str > 5 else 'Monitor for rotation into stronger stocks.'}"
        ),
    }


# ── Statistical edge ───────────────────────────────────────────────────────────

def statistical_edge(ticker: str) -> dict:
    """Win rate, avg win, avg loss, expectancy over 5 years."""
    df = _fetch_daily(ticker, years=5)
    if df.empty:
        return {}

    returns = df["Close"].pct_change().dropna() * 100
    wins    = returns[returns > 0]
    losses  = returns[returns < 0]

    win_rate   = round(len(wins) / len(returns) * 100, 1)
    avg_win    = round(float(wins.mean()), 3)
    avg_loss   = round(float(losses.mean()), 3)
    expectancy = round(win_rate / 100 * avg_win + (1 - win_rate / 100) * avg_loss, 3)

    return {
        "win_rate_daily":   win_rate,
        "avg_win_pct":      avg_win,
        "avg_loss_pct":     avg_loss,
        "expectancy_pct":   expectancy,
        "profit_factor":    round(abs(wins.sum() / losses.sum()), 2) if losses.sum() != 0 else 99,
        "interpretation": (
            f"On any given day, {ticker} goes up {win_rate}% of the time. "
            f"Average up day: +{avg_win:.2f}%, average down day: {avg_loss:.2f}%. "
            f"Expected daily move: {'+' if expectancy >= 0 else ''}{expectancy:.3f}%."
        ),
    }


# ── Full report ────────────────────────────────────────────────────────────────

def full_pattern_report(ticker: str) -> dict:
    return {
        "ticker":             ticker.upper(),
        "generated_at":       datetime.utcnow().isoformat(),
        "seasonal_patterns":  seasonal_patterns(ticker),
        "day_of_week":        day_of_week_patterns(ticker),
        "earnings_behaviour": earnings_behaviour(ticker),
        "sector_rotation":    sector_rotation_signal(ticker),
        "statistical_edge":   statistical_edge(ticker),
    }


if __name__ == "__main__":
    import sys, json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    report = full_pattern_report(ticker)
    print(json.dumps(report, indent=2, default=str))
