"""
Walk-forward evaluation, criteria-correlation, and marginal-lift gate.

This is the validation layer the live signals must earn their keep against. It
builds ON the unified engine (src.backtest_runner) — it does NOT reimplement
backtesting, cost accounting, or signal generation. Three things live here that
nothing else in the codebase does:

  1. walk_forward()        — split history into contiguous OUT-OF-SAMPLE windows
                             and report per-window + pooled stats NET OF COSTS,
                             plus an in-sample-vs-OOS gap (overfit "cliff" check).
  2. criteria_correlation()— pairwise correlation of RuleStrategy's 7 boolean
                             criteria across a universe, so you can see which of
                             your existing signals are redundant (e.g. RSI / %b /
                             Bollinger all measuring the same mean-reversion).
  3. compare_strategies()  — the GATE: does challenger beat base OOS, net of
                             costs? No new indicator ships live unless it clears
                             this. Returns a clear better/worse verdict.

IMPORTANT CAVEATS (printed on every CLI report — do not let a number lie to you):
  * RuleStrategy has FIXED thresholds (no fitted parameters), so walk-forward
    here measures REGIME STABILITY across time (plateau vs cliff), not anti-
    overfit-from-fitting. The moment you evaluate a *tuned* strategy or the ML
    ensemble (any Strategy exposing a `.fit(train_features)` method), this runner
    fits on the train slice and tests on the unseen window — then it is a true
    anti-overfit gate. The hook is already wired below.
  * Universe data is yfinance .NS as-is: SURVIVORSHIP-BIASED (delisted NSE names
    are silently absent), which inflates every backtest. The data loader is
    isolated in `_load` so a survivorship-free source can drop in later.

CLI:
    python -m src.walk_forward --ticker RELIANCE --years 5 --splits 4
    python -m src.walk_forward --universe --years 3      # criteria correlation
"""
from typing import Optional

import numpy as np
import pandas as pd

from src.backtest_runner import cost_breakdown, run_backtest, summarize_trades
from src.feature_engineering import add_features
from src.risk_manager import backtest_with_risk
from src.strategy import RuleStrategy, Strategy

# ── Cost presets ────────────────────────────────────────────────────────────────
# The engine charges `commission_per_share` (USD-style) + `slippage_pct` per fill.
# Indian delivery charges are %-of-turnover (Zerodha delivery brokerage = 0; STT
# ~0.1%/side dominates), so we fold all charges + slippage into slippage_pct and
# set per-share commission to 0. Conservative ~0.3% round-trip. Swap in exact
# numbers here when you have them — one place, one change.
COST_PRESETS = {
    "nse_delivery": {"slippage_pct": 0.0015, "commission_per_share": 0.0},
    "us_ibkr":      {"slippage_pct": 0.0010, "commission_per_share": 0.005},
    "frictionless": {"slippage_pct": 0.0,    "commission_per_share": 0.0},
}
SURVIVORSHIP_CAVEAT = (
    "⚠ yfinance .NS universe is survivorship-biased (delisted names absent) — "
    "treat absolute returns as optimistic; trust RELATIVE (OOS vs in-sample, "
    "challenger vs base) comparisons more than the raw numbers."
)


# ── Internal helpers ─────────────────────────────────────────────────────────────

def _costs(costs) -> dict:
    """Resolve a cost preset name (or pass a dict through)."""
    if isinstance(costs, dict):
        return costs
    if costs not in COST_PRESETS:
        raise ValueError(f"unknown cost preset {costs!r}; choose {list(COST_PRESETS)}")
    return COST_PRESETS[costs]


def _pool_stats(logs: list, capital: float) -> dict:
    """
    Aggregate stats across several trade logs WITHOUT relying on the per-log
    `equity` column (which is per-window and not chainable). Win rate / profit
    factor / pnl are computed from pooled trades; return_pct is pnl over a single
    capital base (windows are independent, not compounded).
    """
    non_empty = [tl for tl in logs if not tl.empty]
    if not non_empty:
        return summarize_trades(pd.DataFrame(), capital)
    pooled = pd.concat(non_empty, ignore_index=True)
    won = pooled["won"].astype(bool)
    gross_win = float(pooled.loc[won, "pnl"].sum())
    gross_loss = abs(float(pooled.loc[~won, "pnl"].sum())) + 1e-10
    total_pnl = float(pooled["pnl"].sum())
    return {
        "total_trades": int(len(pooled)),
        "wins": int(won.sum()),
        "losses": int((~won).sum()),
        "win_rate": round(won.sum() / len(pooled) * 100, 1),
        "profit_factor": round(gross_win / gross_loss, 2),
        "total_pnl": round(total_pnl, 2),
        "final_equity": round(capital + total_pnl, 2),
        "return_pct": round(total_pnl / capital * 100, 2),
    }


def _window_backtest(feats: pd.DataFrame, sig: pd.DataFrame,
                     capital: float, cost_kwargs: dict, rm_kwargs: dict) -> pd.DataFrame:
    """Run the tested risk engine on one feature/signal slice."""
    vix = feats["vix_close"] if "vix_close" in feats.columns else None
    return backtest_with_risk(
        prices=feats["Close"], signals=sig["signal"], confidences=sig["confidence"],
        atrs=feats["atr_14"], vix=vix, capital=capital, **cost_kwargs, **rm_kwargs,
    )


# ── Walk-forward ─────────────────────────────────────────────────────────────────

def walk_forward(
    df: pd.DataFrame,
    strategy: Optional[Strategy] = None,
    capital: float = 100_000,
    n_splits: int = 4,
    min_window_bars: int = 90,
    costs="nse_delivery",
    **rm_kwargs,
) -> dict:
    """
    Evaluate `strategy` on `n_splits` contiguous out-of-sample windows of `df`.

    For a strategy exposing `.fit(train_features)`, each window is tested AFTER
    fitting on all bars before it (true walk-forward). For a fixed-rule strategy
    (no `.fit`), signals are generated once on the full leak-free feature history
    and sliced per window (regime-stability evaluation).

    Returns
    -------
    {
      "strategy": name, "costs": preset, "n_windows": int,
      "windows": [ {period, stats, costs} ... ],
      "oos": pooled OOS stats dict,
      "in_sample": full-history stats dict,
      "overfit_gap_pct": in_sample.win_rate - oos.win_rate,
      "stability": {"win_rate_mean", "win_rate_std", "win_rate_min", "cliff": bool},
      "caveat": SURVIVORSHIP_CAVEAT,
    }
    """
    strategy = strategy or RuleStrategy()
    cost_kwargs = _costs(costs)

    feats = add_features(df, fetch_context=False)
    if len(feats) < n_splits * min_window_bars:
        return {"error": f"need >= {n_splits * min_window_bars} feature bars, "
                         f"have {len(feats)}", "strategy": strategy.name}

    has_fit = hasattr(strategy, "fit")
    full_sig = None if has_fit else strategy.generate_signals(feats)

    n = len(feats)
    edges = np.linspace(0, n, n_splits + 1, dtype=int)
    windows = []
    logs = []
    for i in range(n_splits):
        s, e = int(edges[i]), int(edges[i + 1])
        if e - s < min_window_bars:
            continue
        fw = feats.iloc[s:e]
        if has_fit:
            if s > 0:
                strategy.fit(feats.iloc[:s])          # train on the past only
            sw = strategy.generate_signals(fw)
        else:
            sw = full_sig.iloc[s:e]

        tl = _window_backtest(fw, sw, capital, cost_kwargs, rm_kwargs)
        logs.append(tl)
        st = summarize_trades(tl, capital)
        windows.append({
            "period": f"{fw.index[0].date()} → {fw.index[-1].date()}",
            "stats": st,
            "costs": cost_breakdown(tl, capital),
        })

    oos = _pool_stats(logs, capital)
    non_empty = [tl for tl in logs if not tl.empty]
    oos_log = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()

    # In-sample reference: the same strategy over the whole history through the
    # unified engine (recomputes features — cheap, and keeps us honest).
    in_full = run_backtest(df, strategy=strategy, capital=capital, **cost_kwargs, **rm_kwargs)
    in_sample = in_full["stats"]

    wr = [w["stats"]["win_rate"] for w in windows if w["stats"]["total_trades"] > 0]
    wr_mean = round(float(np.mean(wr)), 1) if wr else 0.0
    wr_min = round(float(np.min(wr)), 1) if wr else 0.0
    stability = {
        "win_rate_mean": wr_mean,
        "win_rate_std": round(float(np.std(wr)), 1) if wr else 0.0,
        "win_rate_min": wr_min,
        # "cliff": a window collapses far below the mean → fragile across regimes.
        "cliff": bool(wr) and (wr_mean - wr_min) > 15.0,
    }

    return {
        "strategy": strategy.name,
        "costs": costs if isinstance(costs, str) else "custom",
        "n_windows": len(windows),
        "windows": windows,
        "oos": oos,
        "in_sample": in_sample,
        "overfit_gap_pct": round(in_sample["win_rate"] - oos["win_rate"], 1),
        "stability": stability,
        "oos_log": oos_log,
        "caveat": SURVIVORSHIP_CAVEAT,
    }


# ── The gate: does a challenger beat the base, OOS, net of costs? ─────────────────

def compare_strategies(
    df: pd.DataFrame,
    base: Strategy,
    challenger: Strategy,
    capital: float = 100_000,
    min_win_rate_lift: float = 2.0,
    **wf_kwargs,
) -> dict:
    """
    Run both strategies through identical walk-forward windows and report the
    challenger's MARGINAL lift. `challenger_wins` is the live-promotion gate:
    challenger must add >= `min_win_rate_lift` pp OOS win rate AND not lose money
    relative to base (higher net pnl). Tune the threshold to taste.
    """
    b = walk_forward(df, strategy=base, capital=capital, **wf_kwargs)
    c = walk_forward(df, strategy=challenger, capital=capital, **wf_kwargs)
    if "error" in b or "error" in c:
        return {"error": b.get("error") or c.get("error")}

    d_wr = round(c["oos"]["win_rate"] - b["oos"]["win_rate"], 1)
    d_pf = round(c["oos"]["profit_factor"] - b["oos"]["profit_factor"], 2)
    d_pnl = round(c["oos"]["total_pnl"] - b["oos"]["total_pnl"], 2)
    return {
        "base": {"name": base.name, "oos": b["oos"]},
        "challenger": {"name": challenger.name, "oos": c["oos"]},
        "delta": {"win_rate_pp": d_wr, "profit_factor": d_pf, "net_pnl": d_pnl},
        "challenger_wins": bool(d_wr >= min_win_rate_lift and d_pnl > 0),
        "caveat": SURVIVORSHIP_CAVEAT,
    }


# ── Criteria correlation: which of the 7 signals are redundant? ───────────────────

def criteria_correlation(feature_frames: list, strategy: Optional[RuleStrategy] = None) -> dict:
    """
    Pairwise correlation of the strategy's boolean criteria, pooled across every
    bar of every supplied (already feature-engineered) frame.

    Returns {"matrix": DataFrame, "redundant_pairs": [(a, b, corr)], "n_bars": int}.
    A high |corr| means two criteria fire together — they are not two independent
    bets, and counting both inflates your effective parameter count.
    """
    strategy = strategy or RuleStrategy()
    mats = []
    for f in feature_frames:
        if f is None or f.empty:
            continue
        mats.append(strategy.criteria(f).astype(float))
    if not mats:
        return {"matrix": pd.DataFrame(), "redundant_pairs": [], "n_bars": 0}

    pooled = pd.concat(mats, ignore_index=True)
    corr = pooled.corr().round(3)
    cols = list(corr.columns)
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            v = corr.loc[a, b]
            if pd.notna(v) and abs(v) >= 0.6:
                pairs.append((a, b, round(float(v), 3)))
    pairs.sort(key=lambda t: -abs(t[2]))
    return {"matrix": corr, "redundant_pairs": pairs, "n_bars": int(len(pooled))}


# ── Data loader (isolated so a survivorship-free source can replace it) ───────────

def _load(ticker: str, years: int) -> pd.DataFrame:
    """Load `years` of NSE daily OHLCV, matching the live path (yfinance + .NS)."""
    import contextlib
    import io

    import yfinance as yf

    from src.watchlist import nse

    with contextlib.redirect_stderr(io.StringIO()):
        df = yf.download(nse(ticker), period=f"{years}y", interval="1d",
                         progress=False, auto_adjust=True)
    if df.empty:
        return df
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def criteria_correlation_universe(tickers: list, years: int = 3,
                                  strategy: Optional[RuleStrategy] = None) -> dict:
    """Network helper: fetch each ticker, feature-engineer, pool criteria correlation."""
    frames = []
    for t in tickers:
        df = _load(t, years)
        if df.empty or len(df) < 60:
            continue
        frames.append(add_features(df, fetch_context=False))
    return criteria_correlation(frames, strategy=strategy)


# ── CLI ──────────────────────────────────────────────────────────────────────────

# ── Portfolio (universe-aggregate) walk-forward vs buy-and-hold NIFTY ─────────────

def buy_and_hold_return(close: pd.Series) -> float:
    """Buy-at-start, hold-to-end percentage return of a price series."""
    s = close.dropna()
    if len(s) < 2:
        return 0.0
    return round(float(s.iloc[-1] / s.iloc[0] - 1.0) * 100, 2)


def _fetch_nifty(years: int) -> pd.Series:
    """Benchmark close series (^NSEI), reusing passive's fetcher; empty on failure."""
    try:
        from src.passive import _fetch_benchmark
        return _fetch_benchmark("^NSEI", years, None, None).dropna()
    except Exception:
        return pd.Series(dtype=float)


def walk_forward_universe(
    tickers: list,
    years: int = 3,
    n_splits: int = 4,
    capital: float = 100_000,
    costs="nse_delivery",
    strategy: Optional[Strategy] = None,
    **rm_kwargs,
) -> dict:
    """
    Run walk_forward on every ticker, POOL all out-of-sample trades across the
    universe, and report one portfolio-level OOS aggregate, edge breadth, and a
    buy-and-hold NIFTY context line.

    HONESTY NOTE: the aggregate pools independent per-signal trades — it answers
    "do these signals have edge net of costs across the universe" (win rate /
    profit factor / expectancy). It is NOT a compounded portfolio equity curve;
    that needs a concurrent-position portfolio simulator (shared capital across
    overlapping holds), deliberately out of scope here. Compare PF to 1.0 and
    expectancy to 0; read the NIFTY return as period CONTEXT, not a capital-
    matched benchmark.
    """
    per_ticker = []
    logs = []
    skipped = 0
    for t in tickers:
        df = _load(t, years)
        if df.empty or len(df) < n_splits * 90:
            skipped += 1
            continue
        r = walk_forward(df, strategy=strategy, n_splits=n_splits, capital=capital,
                         costs=costs, **rm_kwargs)
        if "error" in r:
            skipped += 1
            continue
        per_ticker.append({
            "ticker": t,
            "trades": r["oos"]["total_trades"],
            "win_rate": r["oos"]["win_rate"],
            "profit_factor": r["oos"]["profit_factor"],
            "net_pnl": r["oos"]["total_pnl"],
            "cliff": r["stability"]["cliff"],
        })
        if not r["oos_log"].empty:
            logs.append(r["oos_log"])

    agg = _pool_stats(logs, capital)
    traded = [p for p in per_ticker if p["trades"] > 0]
    n_profitable = sum(1 for p in traded if p["profit_factor"] >= 1.0)
    n_cliff = sum(1 for p in per_ticker if p["cliff"])
    expectancy = round(agg["total_pnl"] / agg["total_trades"], 2) if agg["total_trades"] else 0.0

    nifty = _fetch_nifty(years)
    bh = buy_and_hold_return(nifty) if not nifty.empty else None

    return {
        "n_names": len(tickers),
        "n_evaluated": len(per_ticker),
        "n_skipped": skipped,
        "n_traded": len(traded),
        "n_profitable": n_profitable,
        "edge_breadth_pct": round(n_profitable / len(traded) * 100, 1) if traded else 0.0,
        "n_cliff": n_cliff,
        "portfolio_oos": agg,
        "expectancy_per_trade": expectancy,
        "nifty_buy_hold_pct": bh,
        "per_ticker": per_ticker,
        "caveat": SURVIVORSHIP_CAVEAT,
    }


# ── Multi-strategy gate over the universe (load each name once) ───────────────────

def _oos_log_for(feats, strategy, capital, cost_kwargs, rm_kwargs, n_splits, min_window_bars):
    """Pooled OOS trade log for one strategy on one already-engineered feature frame."""
    has_fit = hasattr(strategy, "fit")
    full_sig = None if has_fit else strategy.generate_signals(feats)
    n = len(feats)
    edges = np.linspace(0, n, n_splits + 1, dtype=int)
    logs = []
    for i in range(n_splits):
        s, e = int(edges[i]), int(edges[i + 1])
        if e - s < min_window_bars:
            continue
        fw = feats.iloc[s:e]
        if has_fit:
            if s > 0:
                strategy.fit(feats.iloc[:s])
            sw = strategy.generate_signals(fw)
        else:
            sw = full_sig.iloc[s:e]
        logs.append(_window_backtest(fw, sw, capital, cost_kwargs, rm_kwargs))
    ne = [l for l in logs if not l.empty]
    return pd.concat(ne, ignore_index=True) if ne else pd.DataFrame()


def compare_strategies_universe(
    tickers: list,
    strategies: dict,
    years: int = 3,
    n_splits: int = 4,
    min_window_bars: int = 90,
    capital: float = 100_000,
    costs="nse_delivery",
    **rm_kwargs,
) -> dict:
    """
    Evaluate several strategies on the SAME universe in one pass (each ticker
    fetched + feature-engineered once), pooling OOS trades per strategy. This is
    the Track-A gate: it answers "which candidate beats base net-of-cost OOS"
    without N× the network cost of calling compare_strategies repeatedly.

    `strategies`: {label: Strategy}. Returns {"results": {label: pooled_stats}, ...}.
    """
    cost_kwargs = _costs(costs)
    pooled = {name: [] for name in strategies}
    n_eval = 0
    for t in tickers:
        df = _load(t, years)
        if df.empty or len(df) < n_splits * min_window_bars:
            continue
        feats = add_features(df, fetch_context=False)
        if len(feats) < n_splits * min_window_bars:
            continue
        n_eval += 1
        for name, strat in strategies.items():
            log = _oos_log_for(feats, strat, capital, cost_kwargs, rm_kwargs,
                               n_splits, min_window_bars)
            if not log.empty:
                pooled[name].append(log)
    return {
        "n_evaluated": n_eval,
        "results": {name: _pool_stats(logs, capital) for name, logs in pooled.items()},
        "caveat": SURVIVORSHIP_CAVEAT,
    }


# ── Selection-aware walk-forward (live gates: regime + RS-vs-Nifty) ───────────────

def _oos_log_from_signals(feats, full_sig, capital, cost_kwargs, rm_kwargs,
                          n_splits, min_window_bars):
    """Pooled OOS trade log from a PRE-COMPUTED signal frame (for masked signals)."""
    n = len(feats)
    edges = np.linspace(0, n, n_splits + 1, dtype=int)
    logs = []
    for i in range(n_splits):
        s, e = int(edges[i]), int(edges[i + 1])
        if e - s < min_window_bars:
            continue
        logs.append(_window_backtest(feats.iloc[s:e], full_sig.iloc[s:e],
                                     capital, cost_kwargs, rm_kwargs))
    ne = [l for l in logs if not l.empty]
    return pd.concat(ne, ignore_index=True) if ne else pd.DataFrame()


def compare_selection_universe(
    tickers: list,
    strategy: Optional[Strategy] = None,
    years: int = 3,
    n_splits: int = 4,
    min_window_bars: int = 90,
    capital: float = 100_000,
    costs="nse_delivery",
    rs_lookback: int = 20,
    **rm_kwargs,
) -> dict:
    """
    The SELECTION-aware gate: take the base strategy's signals and test what
    happens when entries are restricted by the live-style selection gates —
      • regime : only enter when Nifty is risk-on (close > 200-SMA, lagged 1d)
      • RS     : only enter when the stock's `rs_lookback`-day return beats Nifty's
    Pools OOS trades across the universe for base / +regime / +rs / +regime+rs so
    you can see whether SELECTION (not more indicators) is the edge lever.

    NOTE: sector-rotation and gap-risk gates are NOT historicized here (hard to
    reconstruct point-in-time); the LIVE scan already applies them, so this is a
    lower bound on the selection benefit. Benchmark = ^NSEI.
    """
    strategy = strategy or RuleStrategy()
    cost_kwargs = _costs(costs)
    nifty = _fetch_nifty(years)
    if nifty.empty:
        return {"error": "benchmark (^NSEI) fetch failed"}

    nifty_regime = (nifty > nifty.rolling(200).mean()).shift(1)   # risk-on, leak-safe
    nifty_ret = nifty.pct_change(rs_lookback)

    configs = ["base", "+regime", "+rs", "+regime+rs"]
    pooled = {c: [] for c in configs}
    n_eval = 0
    for t in tickers:
        df = _load(t, years)
        if df.empty or len(df) < n_splits * min_window_bars:
            continue
        feats = add_features(df, fetch_context=False)
        if len(feats) < n_splits * min_window_bars:
            continue
        reg = nifty_regime.reindex(feats.index, method="ffill").fillna(False).astype(bool)
        nret = nifty_ret.reindex(feats.index, method="ffill")
        stock_ret = feats["Close"].pct_change(rs_lookback)
        rs_ok = (stock_ret > nret).fillna(False)

        base_sig = strategy.generate_signals(feats)
        masks = {
            "base": pd.Series(True, index=feats.index),
            "+regime": reg,
            "+rs": rs_ok,
            "+regime+rs": reg & rs_ok,
        }
        n_eval += 1
        for c in configs:
            sig = base_sig.copy()
            sig.loc[~masks[c].values, "signal"] = 0
            log = _oos_log_from_signals(feats, sig, capital, cost_kwargs, rm_kwargs,
                                        n_splits, min_window_bars)
            if not log.empty:
                pooled[c].append(log)

    nifty_bh = buy_and_hold_return(nifty)
    return {
        "n_evaluated": n_eval,
        "results": {c: _pool_stats(pooled[c], capital) for c in configs},
        "nifty_buy_hold_pct": nifty_bh,
        "caveat": SURVIVORSHIP_CAVEAT,
    }


# ── CLI printers ─────────────────────────────────────────────────────────────────

def _print_portfolio(r: dict) -> None:
    o = r["portfolio_oos"]
    print(f"\n  Universe: {r['n_names']} names  →  evaluated {r['n_evaluated']}, "
          f"skipped {r['n_skipped']} (insufficient data)")
    print("  ── pooled OOS across the universe (net of costs) ──")
    print(f"    trades        : {o['total_trades']}")
    print(f"    win rate      : {o['win_rate']}%")
    print(f"    profit factor : {o['profit_factor']}   (>1.0 = edge; <1.0 = losing)")
    print(f"    net P&L       : {o['total_pnl']}")
    print(f"    expectancy/tr : {r['expectancy_per_trade']}   (avg P&L per trade)")
    print("  ── edge breadth ──")
    print(f"    names with PF >= 1.0 : {r['n_profitable']}/{r['n_traded']} "
          f"({r['edge_breadth_pct']}%)")
    print(f"    names flagged CLIFF  : {r['n_cliff']}/{r['n_evaluated']}")
    bh = r["nifty_buy_hold_pct"]
    print("  ── context ──")
    print(f"    NIFTY buy & hold over period : "
          f"{bh if bh is not None else 'n/a'}%  (period context, NOT capital-matched)")
    # Worst offenders by net P&L — where the bleeding is.
    worst = sorted([p for p in r["per_ticker"] if p["trades"] > 0],
                   key=lambda p: p["net_pnl"])[:5]
    if worst:
        print("  ── 5 worst names by net P&L ──")
        for p in worst:
            print(f"    {p['ticker']:<14} trades={p['trades']:>3}  win={p['win_rate']:>5}%  "
                  f"PF={p['profit_factor']:>5}  net={p['net_pnl']:>10}")
    print(f"  {r['caveat']}")


def _print_walk_forward(r: dict) -> None:
    if "error" in r:
        print(f"  ✗ {r['error']}")
        return
    print(f"\n  Strategy: {r['strategy']}   costs: {r['costs']}   windows: {r['n_windows']}")
    print("  ── per-window OOS ──")
    for w in r["windows"]:
        s = w["stats"]
        print(f"    {w['period']}  trades={s['total_trades']:>3}  "
              f"win={s['win_rate']:>5}%  PF={s['profit_factor']:>5}  "
              f"ret={s['return_pct']:>7}%  costs={w['costs']['cost_pct_of_gross']:>5}% of gross")
    o, ins = r["oos"], r["in_sample"]
    print("  ── aggregate ──")
    print(f"    OOS pooled : trades={o['total_trades']}  win={o['win_rate']}%  "
          f"PF={o['profit_factor']}  net_pnl={o['total_pnl']}")
    print(f"    In-sample  : trades={ins['total_trades']}  win={ins['win_rate']}%  "
          f"PF={ins['profit_factor']}")
    print(f"    Overfit gap: {r['overfit_gap_pct']} pp (in-sample minus OOS win rate)")
    st = r["stability"]
    flag = "⚠ CLIFF" if st["cliff"] else "plateau"
    print(f"    Stability  : win mean={st['win_rate_mean']}%  std={st['win_rate_std']}  "
          f"min={st['win_rate_min']}%  → {flag}")
    print(f"  {r['caveat']}")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Walk-forward + criteria-correlation harness")
    p.add_argument("--ticker", default="RELIANCE")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--splits", type=int, default=4)
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--costs", default="nse_delivery", choices=list(COST_PRESETS))
    p.add_argument("--universe", action="store_true",
                   help="criteria-correlation across the DEFAULT_SCAN watchlist")
    p.add_argument("--portfolio", action="store_true",
                   help="universe-aggregate walk-forward (pooled OOS vs NIFTY)")
    args = p.parse_args()

    if args.portfolio:
        from src.watchlist import DEFAULT_SCAN
        print(f"Portfolio walk-forward across {len(DEFAULT_SCAN)} names "
              f"({args.years}y, {args.splits} splits)…")
        _print_portfolio(walk_forward_universe(
            DEFAULT_SCAN, years=args.years, n_splits=args.splits,
            capital=args.capital, costs=args.costs,
        ))
        return

    if args.universe:
        from src.watchlist import DEFAULT_SCAN
        print(f"Criteria correlation across {len(DEFAULT_SCAN)} names "
              f"({args.years}y daily)…")
        res = criteria_correlation_universe(DEFAULT_SCAN, years=args.years)
        if res["n_bars"] == 0:
            print("  ✗ no data")
            return
        print(f"\n  pooled bars: {res['n_bars']}\n")
        print(res["matrix"].to_string())
        print("\n  Redundant pairs (|corr| >= 0.6) — candidates to merge/drop:")
        if res["redundant_pairs"]:
            for a, b, v in res["redundant_pairs"]:
                print(f"    {a:<14} ~ {b:<14} {v:+.3f}")
        else:
            print("    none — your 7 criteria look reasonably independent.")
        print(f"\n  {SURVIVORSHIP_CAVEAT}")
        return

    print(f"Walk-forward: {args.ticker}  {args.years}y  {args.splits} splits")
    df = _load(args.ticker, args.years)
    if df.empty or len(df) < 60:
        print("  ✗ insufficient data")
        return
    _print_walk_forward(
        walk_forward(df, n_splits=args.splits, capital=args.capital, costs=args.costs)
    )


if __name__ == "__main__":
    main()
