"""
The V-1.0 proof: does an India, 🟢-halal-only, rule strategy show an edge that
survives realistic costs — on the ONE unified code path, leakage-checked?

Pools per-ticker unified backtests across the halal universe and reports the
gross-vs-net trade statistics + Rank IC, so costs and predictiveness are explicit.

CAVEAT (point-in-time halal): the halal universe is applied as it stands TODAY
across history. Halal status is time-varying, so this carries survivorship bias
until the universe is reconstructed point-in-time (OpenBB fundamentals). Treat a
positive result as encouraging, not yet bankable. A clearly-negative result is
still informative — costs/structure don't get better with point-in-time data.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.metrics import summarise
from src.backtest_runner import run_backtest
from src.strategy import RuleStrategy


def aggregate_proof(results: list, capital: float) -> dict:
    """
    Pool per-ticker run_backtest() results into one verdict.

    Trade returns are pooled per-trade (scale-free), so win rate / profit factor /
    Sharpe / avg-return are valid across the universe. Both NET (after slippage +
    commission) and GROSS (costs added back) are reported to show the cost drag.
    Rank IC = Spearman corr of signal confidence vs next-day return.
    """
    net, gross = [], []
    conf_all, fwd_all = [], []
    sig_fwd, base_fwd = [], []
    n_traded = 0

    for r in results:
        tl = r["trade_log"]
        if not tl.empty:
            net.extend((tl["pnl"] / capital).tolist())
            gross.extend(((tl["pnl"] + tl["commission"] + tl["slippage_cost"]) / capital).tolist())
            n_traded += 1

        feats, sig = r.get("features"), r.get("signals")
        if feats is not None and sig is not None and not feats.empty:
            fwd = feats["Close"].pct_change().shift(-1)
            v = fwd.notna()
            conf_all.extend(sig.loc[v, "confidence"].tolist())
            fwd_all.extend(fwd[v].tolist())
            buys = (sig["signal"] == 1) & v
            sig_fwd.extend(fwd[buys].tolist())
            base_fwd.extend(fwd[v].tolist())

    net_s, gross_s = pd.Series(net), pd.Series(gross)
    rank_ic = (round(float(spearmanr(conf_all, fwd_all).correlation), 4)
               if len(conf_all) > 10 else None)
    signal_edge_bps = (round((float(np.mean(sig_fwd)) - float(np.mean(base_fwd))) * 10000, 1)
                       if sig_fwd and base_fwd else None)

    return {
        "tickers_total": len(results),
        "tickers_traded": n_traded,
        "total_trades": len(net),
        "net": summarise(net_s, "net of costs") if len(net) else {},
        "gross": summarise(gross_s, "gross") if len(gross) else {},
        "rank_ic": rank_ic,
        "signal_edge_bps": signal_edge_bps,
    }


def _one(ticker: str, years: int, capital: float, strategy,
         start: Optional[str] = None, end: Optional[str] = None) -> Optional[dict]:
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
        if df.empty or len(df) < 230:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return run_backtest(df, strategy, capital=capital)
    except Exception:
        return None


def run_india_halal_proof(
    tickers: Optional[list] = None,
    years: int = 3,
    capital: float = 100_000,
    workers: int = 8,
    strategy: Optional[object] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """Fetch + backtest the halal universe in parallel, then aggregate the verdict.

    Pass `start`/`end` (YYYY-MM-DD) to test a specific regime window instead of
    the trailing `years`. NOTE: the first ~200 bars of any window are consumed by
    feature warmup, so choose a window that begins ~1y before the regime of interest.
    """
    from src.watchlist import DEFAULT_SCAN
    tickers = tickers or DEFAULT_SCAN
    strategy = strategy or RuleStrategy()

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_one, t, years, capital, strategy, start, end): t for t in tickers}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(r)

    report = aggregate_proof(results, capital)
    report["tickers_total"] = len(tickers)
    report["tickers_with_data"] = len(results)
    return report


def buy_and_hold_benchmark(
    tickers: Optional[list] = None,
    years: int = 3,
    start: Optional[str] = None,
    end: Optional[str] = None,
    workers: int = 8,
) -> dict:
    """
    Equal-weight buy-and-hold return of the universe over the window = the pure
    survivorship beta. If the strategy can't be explained by this (and a random
    control on the same names can't either), the edge isn't just survivorship.
    """
    import contextlib
    import io
    import yfinance as yf
    from src.watchlist import DEFAULT_SCAN, nse
    tickers = tickers or DEFAULT_SCAN

    def _bh(t):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                if start:
                    df = yf.download(nse(t), start=start, end=end, interval="1d",
                                     progress=False, auto_adjust=True)
                else:
                    df = yf.download(nse(t), period=f"{years}y", interval="1d",
                                     progress=False, auto_adjust=True)
            if df.empty or len(df) < 30:
                return None
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            c = df["Close"].dropna()
            return float(c.iloc[-1] / c.iloc[0] - 1) * 100
        except Exception:
            return None

    rets = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(_bh, tickers):
            if r is not None:
                rets.append(r)

    arr = np.array(rets)
    return {
        "n": len(arr),
        "avg_return_pct": round(float(arr.mean()), 1) if len(arr) else 0.0,
        "median_return_pct": round(float(np.median(arr)), 1) if len(arr) else 0.0,
        "pct_positive": round(float((arr > 0).mean() * 100), 1) if len(arr) else 0.0,
    }
