"""
Passive halal core + regime overlay.

After the proof showed an active daily-signal strategy is dominated by simply
holding a screened halal basket, the project pivoted: the CORE is a passive,
periodically-rebalanced halal basket, and the system's value-add is an OVERLAY
(screening + a risk/drawdown guard + purification/Zakat).

This module tests the one place active management can genuinely help a long-only
halal investor: **cutting drawdowns**. A passive basket eats the full market
crash (2020 −38%, 2022 −18%); a regime overlay that sits in cash when the market
is below trend should reduce that. Because it's overlay-vs-no-overlay on the SAME
basket, the comparison is robust to the survivorship bias in the universe.

Regime signal: benchmark (Nifty) above/below its 200-day SMA — the classic trend
filter. Exposure is lagged one day to avoid look-ahead.
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np
import pandas as pd


# ── Pure math (unit-tested) ───────────────────────────────────────────────────

def basket_daily_returns(close_panel: pd.DataFrame, min_coverage: float = 0.5) -> pd.Series:
    """Equal-weight daily return of a basket (daily-rebalanced).

    `min_coverage` guards against corruption when fetched series have mismatched
    date ranges (e.g. a data provider intermittently returns out-of-window data):
    a day is included only if at least this fraction of the basket's stocks have a
    return that day. Without it, a single out-of-window series could masquerade as
    the whole basket on the days only it covers.
    """
    # fill_method=None: do NOT forward-fill missing prices (that would turn an
    # absent/delisted stock into fake 0% returns and defeat the coverage guard).
    rets = close_panel.pct_change(fill_method=None)
    coverage = rets.notna().mean(axis=1)
    rets = rets[coverage >= min_coverage]
    return rets.mean(axis=1, skipna=True).dropna()


def regime_exposure(benchmark_close: pd.Series, sma_window: int = 200, lag: int = 1) -> pd.Series:
    """1 when the benchmark is above its SMA (risk-on), else 0. Lagged to avoid
    look-ahead (today's exposure is set by yesterday's close vs SMA)."""
    sma = benchmark_close.rolling(sma_window).mean()
    raw = (benchmark_close > sma).astype(float)
    return raw.shift(lag).fillna(0.0)


def apply_overlay(returns: pd.Series, exposure: pd.Series) -> pd.Series:
    """Scale basket returns by exposure (aligned on the date index)."""
    exp = exposure.reindex(returns.index).ffill().fillna(1.0)
    return returns * exp


def drawdown_exposure(benchmark_close: pd.Series, dd_start: float = -0.08,
                      dd_full: float = -0.20, floor: float = 0.3, lag: int = 1) -> pd.Series:
    """
    Graded exposure based on the benchmark's drawdown from its trailing peak.

    Fixes the binary 200-SMA overlay's whipsaw: stay FULLY invested through ordinary
    dips (drawdown shallower than `dd_start`) so recoveries aren't missed, and scale
    exposure down toward `floor` only as a catastrophic drawdown deepens (reaching
    `floor` at `dd_full`) — keeping the crash insurance without the chop cost.
    Lagged to avoid look-ahead.
    """
    # Rolling (not all-time) peak: robust to a single spurious high price, and
    # measures drawdown from the recent high — the relevant crash signal.
    peak = benchmark_close.rolling(252, min_periods=1).max()
    dd = benchmark_close / peak - 1.0                       # <= 0
    frac = ((dd - dd_start) / (dd_full - dd_start)).clip(0, 1)
    exp = 1.0 - frac * (1.0 - floor)
    return exp.shift(lag).fillna(1.0)


def summarize_nav(returns: pd.Series, periods: int = 252) -> dict:
    """Total return, CAGR, max drawdown, Sharpe from a daily return series."""
    if len(returns) == 0:
        return {"total_return_pct": 0.0, "cagr_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0}
    nav = (1 + returns).cumprod()
    n_years = max(len(returns) / periods, 1e-9)
    cagr = (float(nav.iloc[-1]) ** (1 / n_years) - 1) * 100
    dd = ((nav - nav.cummax()) / nav.cummax()).min() * 100
    sharpe = (returns.mean() / returns.std() * np.sqrt(periods)) if returns.std() > 0 else 0.0
    return {
        "total_return_pct": round((float(nav.iloc[-1]) - 1) * 100, 1),
        "cagr_pct": round(cagr, 1),
        "max_drawdown_pct": round(float(dd), 1),
        "sharpe": round(float(sharpe), 2),
    }


# ── Data fetch + runner (network) ─────────────────────────────────────────────

def _fetch_close(ticker: str, years: int, start: Optional[str], end: Optional[str]) -> Optional[pd.Series]:
    import contextlib
    import io
    import yfinance as yf
    from src.watchlist import nse
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            if start:
                df = yf.download(nse(ticker), start=start, end=end, interval="1d",
                                 progress=False, auto_adjust=True)
            else:
                df = yf.download(nse(ticker), period=f"{years}y", interval="1d",
                                 progress=False, auto_adjust=True)
        if df.empty:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        out = df["Close"].rename(ticker)
        if start:
            out = out.loc[start:end]  # defensive clip: never trust the source to honor the window
        return out
    except Exception:
        return None


def _fetch_benchmark(symbol: str, years: int, start: Optional[str], end: Optional[str]) -> pd.Series:
    import contextlib
    import io
    import yfinance as yf
    with contextlib.redirect_stderr(io.StringIO()):
        if start:
            df = yf.download(symbol, start=start, end=end, interval="1d", progress=False, auto_adjust=True)
        else:
            df = yf.download(symbol, period=f"{years}y", interval="1d", progress=False, auto_adjust=True)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df["Close"]


def run_passive_overlay(
    tickers: Optional[list] = None,
    benchmark: str = "^NSEI",
    years: int = 7,
    start: Optional[str] = None,
    end: Optional[str] = None,
    sma_window: int = 200,
    workers: int = 8,
) -> dict:
    """
    Compare buy-and-hold of the halal basket vs the same basket with a regime
    (benchmark > 200-SMA) exposure overlay. Returns metrics for both + context.
    """
    from src.watchlist import DEFAULT_SCAN
    tickers = tickers or DEFAULT_SCAN

    series = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for s in pool.map(lambda t: _fetch_close(t, years, start, end), tickers):
            if s is not None and len(s) > sma_window:
                series.append(s)
    panel = pd.concat(series, axis=1).sort_index()
    basket_ret = basket_daily_returns(panel)

    # Fetch the benchmark to span the ACTUAL basket window + SMA lead-time. Deriving
    # it from basket dates (rather than a `period=Ny` call) guarantees full coverage
    # despite yfinance's non-deterministic period lengths — otherwise missing dates
    # would be filled and corrupt the exposure.
    b_start = (basket_ret.index.min() - pd.Timedelta(days=2 * sma_window)).strftime("%Y-%m-%d")
    b_end = (basket_ret.index.max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    bench = _fetch_benchmark(benchmark, years, b_start, b_end)
    exposure = regime_exposure(bench, sma_window=sma_window)

    bh = summarize_nav(basket_ret)
    ones = pd.Series(1.0, index=basket_ret.index)

    # Binary 200-SMA overlay
    overlay = summarize_nav(apply_overlay(basket_ret, exposure))
    invested = float(apply_overlay(ones, exposure).mean())

    # Graded drawdown overlay (refined — avoids whipsaw, keeps crash insurance)
    dd_exp = drawdown_exposure(bench)
    overlay_dd = summarize_nav(apply_overlay(basket_ret, dd_exp))
    dd_invested = float(apply_overlay(ones, dd_exp).mean())

    return {
        "n_stocks": panel.shape[1],
        "n_days": len(basket_ret),
        "pct_time_invested": round(invested * 100, 1),
        "pct_exposure_drawdown": round(dd_invested * 100, 1),
        "buy_and_hold": bh,
        "overlay": overlay,
        "overlay_drawdown": overlay_dd,
    }
