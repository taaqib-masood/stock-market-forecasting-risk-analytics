"""
Unified backtest runner — the single path that backtests *exactly what we trade*.

    OHLCV  →  add_features (one feature pipeline)
           →  Strategy.generate_signals (one signal definition)
           →  backtest_with_risk (one tested risk/execution engine)
           →  summarize_trades

This collapses the old three-way divergence:
  - src.scanner._score        (live, 7-criteria, hand-coded)
  - src.backtest_filter        (validation, 5-criteria, drifted)
  - src.pipeline + ensemble    (research, 52-feature ML)
into one engine where the live signal and the backtest are the same code.

`passes_backtest` is the drop-in replacement for src.backtest_filter's gate, but
now driven by the real strategy through the real risk engine.
"""
from typing import Optional

import pandas as pd

from src.feature_engineering import add_features
from src.risk_manager import RiskManager, backtest_with_risk
from src.strategy import Strategy, RuleStrategy


def summarize_trades(trade_log: pd.DataFrame, capital: float) -> dict:
    """Win rate / profit factor / P&L summary from a backtest_with_risk trade log."""
    if trade_log.empty:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "total_pnl": 0.0, "final_equity": round(capital, 2), "return_pct": 0.0,
        }

    won = trade_log["won"].astype(bool)
    wins = trade_log[won]
    losses = trade_log[~won]
    gross_win = float(wins["pnl"].sum())
    gross_loss = abs(float(losses["pnl"].sum())) + 1e-10
    final_equity = float(trade_log["equity"].iloc[-1])

    return {
        "total_trades": int(len(trade_log)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate": round(len(wins) / len(trade_log) * 100, 1),
        "profit_factor": round(gross_win / gross_loss, 2),
        "total_pnl": round(float(trade_log["pnl"].sum()), 2),
        "final_equity": round(final_equity, 2),
        "return_pct": round((final_equity / capital - 1) * 100, 2),
    }


def run_backtest(
    df: pd.DataFrame,
    strategy: Optional[Strategy] = None,
    capital: float = 100_000,
    fetch_context: bool = False,
    add_sentiment: bool = False,
    add_macro: bool = False,
    ticker: str = "",
    **rm_kwargs,
) -> dict:
    """
    Backtest `strategy` on raw OHLCV `df` through the unified pipeline.

    Returns {"trade_log": DataFrame, "stats": dict, "features": DataFrame}.
    `rm_kwargs` are forwarded to backtest_with_risk / RiskManager.
    """
    strategy = strategy or RuleStrategy()

    feats = add_features(
        df, fetch_context=fetch_context,
        add_sentiment=add_sentiment, add_macro=add_macro, ticker=ticker,
    )
    sig = strategy.generate_signals(feats)

    vix = feats["vix_close"] if "vix_close" in feats.columns else None
    trade_log = backtest_with_risk(
        prices=feats["Close"],
        signals=sig["signal"],
        confidences=sig["confidence"],
        atrs=feats["atr_14"],
        vix=vix,
        capital=capital,
        **rm_kwargs,
    )
    return {
        "trade_log": trade_log,
        "stats": summarize_trades(trade_log, capital),
        "features": feats,
        "signals": sig,
    }


def cost_breakdown(trade_log: pd.DataFrame, capital: float) -> dict:
    """Gross-vs-net cost accounting from a backtest_with_risk trade log."""
    if trade_log.empty:
        return {"commission": 0.0, "slippage": 0.0, "total_costs": 0.0,
                "gross_pnl": 0.0, "net_pnl": 0.0, "cost_pct_of_gross": 0.0}
    commission = float(trade_log["commission"].sum())
    slippage = float(trade_log["slippage_cost"].sum())
    total_costs = commission + slippage
    net_pnl = float(trade_log["pnl"].sum())
    gross_pnl = net_pnl + total_costs
    return {
        "commission": round(commission, 2),
        "slippage": round(slippage, 2),
        "total_costs": round(total_costs, 2),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "cost_pct_of_gross": round(total_costs / abs(gross_pnl) * 100, 1) if gross_pnl else 0.0,
    }


def passes_backtest(
    stats: dict,
    min_win_rate: float = 52.0,
    min_pf: float = 1.2,
    min_trades: int = 8,
) -> tuple[bool, str]:
    """
    Historical-viability gate (replaces src.backtest_filter.passes_backtest).
    Operates on a `summarize_trades` stats dict from the UNIFIED engine.
    """
    if stats["total_trades"] < min_trades:
        return False, f"only {stats['total_trades']} historical trades (< {min_trades})"
    if stats["win_rate"] < min_win_rate:
        return False, f"historical win rate {stats['win_rate']}% < {min_win_rate}%"
    if stats["profit_factor"] < min_pf:
        return False, f"historical PF {stats['profit_factor']} < {min_pf}"
    return True, "passed"


def backtest_ticker(
    ticker: str,
    strategy: Optional[Strategy] = None,
    years: int = 2,
    capital: float = 100_000,
    **rm_kwargs,
) -> dict:
    """
    Fetch wrapper: load `years` of NSE daily data and run the unified backtest.
    Thin convenience over run_backtest; data loading still uses yfinance+.NS to
    match the current live path (the market-registry refactor unifies that later).
    """
    import contextlib
    import io
    import yfinance as yf
    from src.watchlist import nse

    with contextlib.redirect_stderr(io.StringIO()):
        df = yf.download(nse(ticker), period=f"{years}y", interval="1d",
                         progress=False, auto_adjust=True)
    if df.empty or len(df) < 60:
        return {"trade_log": pd.DataFrame(), "stats": summarize_trades(pd.DataFrame(), capital),
                "features": pd.DataFrame(), "error": "insufficient data"}
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return run_backtest(df, strategy=strategy, capital=capital, **rm_kwargs)


def generate_live_signal(
    df: pd.DataFrame,
    strategy: Optional[Strategy] = None,
    capital: float = 100_000,
    vix: float = 15.0,
    **rm_kwargs,
) -> Optional[dict]:
    """
    Latest-bar live BUY trade card, using the SAME Strategy + RiskManager as the
    backtest. This is the live analog of run_backtest — it guarantees the signal
    you trade is the signal you backtest.

    Returns a trade-card dict (caller adds 'ticker'), or None when there is no
    approved BUY on the most recent bar.

    NOTE: stop/target/sizing now come from RiskManager (R:R 2.0 + Kelly + VIX),
    replacing the old src.scanner._trade_card (R:R 2.5, fixed sizing). This is a
    deliberate behavior change so live == backtest.
    """
    strategy = strategy or RuleStrategy()
    feats = add_features(df, fetch_context=False)
    if feats.empty:
        return None

    sig = strategy.generate_signals(feats).iloc[-1]
    if int(sig["signal"]) != 1:
        return None

    last = feats.iloc[-1]
    entry = float(last["Close"])
    rm = RiskManager(capital=capital, **rm_kwargs)
    d = rm.evaluate(entry_price=entry, atr=float(last["atr_14"]),
                    confidence=float(sig["confidence"]), direction=1, vix=vix)
    if not d["approved"]:
        return None

    crit = {}
    if isinstance(strategy, RuleStrategy):
        crit = {k: bool(v) for k, v in strategy.criteria(feats).iloc[-1].items()}

    return {
        "signal": "BUY",
        "direction": 1,
        "score": float(sig["score"]),
        "confidence": float(sig["confidence"]),
        "price": round(entry, 2),
        "entry": round(entry, 2),
        "stop": d["stop_price"],
        "target": d["target_price"],
        "rr": d["rr_ratio"],
        "shares": d["shares"],
        "invest": round(d["shares"] * entry, 2),
        "risk_rs": d["risk_amount"],
        "reward_rs": round(d["risk_amount"] * d["rr_ratio"], 2),
        "rsi": round(float(last["rsi_14"]), 1),
        "vol_surge": round(float(last["volume_ratio"]), 2),
        "ret_5d": round(float(last["return_5d"]) * 100, 2),
        "atr": round(float(last["atr_14"]), 2),
        "criteria": crit,
    }


def filter_cards(
    cards: list,
    strategy: Optional[Strategy] = None,
    min_win_rate: float = 52.0,
    min_pf: float = 1.2,
    min_trades: int = 8,
    years: int = 2,
    capital: float = 100_000,
) -> tuple[list, list]:
    """
    Unified per-stock historical gate (drop-in for src.backtest_filter.filter_cards),
    but driven by the real strategy through the real risk engine.
    """
    passed, failed = [], []
    for card in cards:
        res = backtest_ticker(card["ticker"], strategy=strategy, years=years, capital=capital)
        stats = res["stats"]
        card["backtest"] = stats
        ok, reason = passes_backtest(stats, min_win_rate, min_pf, min_trades)
        if ok:
            passed.append(card)
        else:
            card["backtest_fail_reason"] = reason
            failed.append(card)
    return passed, failed
