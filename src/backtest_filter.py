"""
Per-Stock Backtest Filter
=========================
Before recommending a stock, backtest the scanner's signal logic
on that stock's last 2 years of daily data.

Only passes stocks where:
  - Historical win rate  >= min_win_rate  (default 52%)
  - Profit factor        >= min_pf        (default 1.2)
  - Sample trades        >= min_trades    (default 8)

This kills stocks where the model historically doesn't work,
even if today's signal looks strong.
"""

import contextlib
import io
import numpy as np
import yfinance as yf
from src.watchlist import nse

_CACHE: dict = {}   # ticker → result (cached per session)


def _backtest_ticker(ticker: str,
                     atr_multiplier: float = 2.0,
                     rr: float = 2.5) -> dict:
    """
    Simulate 2 years of daily signals on `ticker`.
    Entry: when score >= 70 (5/7 criteria met).
    Exit:  stop = entry - 2×ATR  |  target = entry + 2.5×stop_dist.
    Returns win_rate, profit_factor, total_trades.
    """
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(nse(ticker), period="2y", interval="1d",
                             progress=False, auto_adjust=True)
        if df.empty or len(df) < 60:
            return {"ok": False, "reason": "insufficient data"}

        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        closes  = df["Close"].values.astype(float)
        highs   = df["High"].values.astype(float)
        lows    = df["Low"].values.astype(float)
        volumes = df["Volume"].values.astype(float)

        trades = []
        i = 50   # warm-up period
        in_trade = None

        while i < len(closes) - 1:
            price = closes[i]

            # ── Close open trade ───────────────────────────────────────────
            if in_trade:
                next_price = closes[i + 1]
                hit_stop   = next_price <= in_trade["stop"]
                hit_target = next_price >= in_trade["target"]
                if hit_stop or hit_target:
                    pnl = (next_price - in_trade["entry"]) / in_trade["entry"]
                    trades.append({"pnl": pnl, "won": hit_target})
                    in_trade = None
                i += 1
                continue

            # ── Score current bar ─────────────────────────────────────────
            c_window = closes[max(0, i-49):i+1]
            v_window = volumes[max(0, i-19):i+1]
            h_window = highs[max(0, i-13):i+1]
            l_window = lows[max(0, i-13):i+1]

            sma20 = np.mean(c_window[-20:]) if len(c_window) >= 20 else price
            sma50 = np.mean(c_window[-50:]) if len(c_window) >= 50 else price
            vol_avg = np.mean(v_window[:-1]) if len(v_window) > 1 else volumes[i]

            # RSI
            delta = np.diff(c_window)
            gain  = np.where(delta > 0, delta, 0.0)
            loss  = np.where(delta < 0, -delta, 0.0)
            avg_g = np.mean(gain[-14:]) if len(gain) >= 14 else 0
            avg_l = np.mean(loss[-14:]) if len(loss) >= 14 else 1
            rsi   = 100 - (100 / (1 + avg_g / (avg_l + 1e-10)))

            # MACD histogram
            def ema(arr, span):
                k, e = 2 / (span + 1), arr[0]
                for v in arr[1:]:
                    e = v * k + e * (1 - k)
                return e
            macd_hist = (ema(c_window, 12) - ema(c_window, 26)) - \
                        ema(c_window[-9:], 9) if len(c_window) >= 26 else 0

            # ATR
            trs = [max(h_window[j] - l_window[j],
                       abs(h_window[j] - c_window[-(len(h_window)-j)]),
                       abs(l_window[j] - c_window[-(len(l_window)-j)]))
                   for j in range(1, len(h_window))]
            atr = np.mean(trs[-14:]) if len(trs) >= 14 else price * 0.015

            score = sum([
                40 <= rsi <= 68,
                macd_hist > 0,
                price > sma20,
                price > sma50,
                volumes[i] >= vol_avg * 1.2,
            ]) / 5

            # ── Open trade if score >= 70% ────────────────────────────────
            if score >= 0.7:
                stop_dist = atr_multiplier * atr
                in_trade  = {
                    "entry":  price,
                    "stop":   price - stop_dist,
                    "target": price + stop_dist * rr,
                }

            i += 1

        if len(trades) < 5:
            return {"ok": False, "reason": f"only {len(trades)} historical trades"}

        wins        = [t for t in trades if t["won"]]
        losses      = [t for t in trades if not t["won"]]
        win_rate    = len(wins) / len(trades) * 100
        gross_win   = sum(t["pnl"] for t in wins)
        gross_loss  = abs(sum(t["pnl"] for t in losses)) + 1e-10
        pf          = gross_win / gross_loss

        return {
            "ok":           True,
            "win_rate":     round(win_rate, 1),
            "profit_factor":round(pf, 2),
            "total_trades": len(trades),
            "wins":         len(wins),
            "losses":       len(losses),
        }

    except Exception as e:
        return {"ok": False, "reason": str(e)}


def passes_backtest(ticker: str,
                    min_win_rate: float = 52.0,
                    min_pf: float = 1.2,
                    min_trades: int = 8) -> tuple[bool, dict]:
    """
    Returns (True, stats) if stock passes historical backtest.
    Returns (False, stats) with reason if it fails.
    Cached per session so repeated calls don't re-fetch.
    """
    if ticker in _CACHE:
        return _CACHE[ticker]

    stats = _backtest_ticker(ticker)

    if not stats["ok"]:
        result = (False, stats)
    elif stats["total_trades"] < min_trades:
        stats["reason"] = f"only {stats['total_trades']} historical trades"
        result = (False, stats)
    elif stats["win_rate"] < min_win_rate:
        stats["reason"] = f"historical win rate {stats['win_rate']}% < {min_win_rate}%"
        result = (False, stats)
    elif stats["profit_factor"] < min_pf:
        stats["reason"] = f"historical PF {stats['profit_factor']} < {min_pf}"
        result = (False, stats)
    else:
        result = (True, stats)

    _CACHE[ticker] = result
    return result


def filter_cards(cards: list[dict],
                 min_win_rate: float = 52.0,
                 min_pf: float = 1.2) -> tuple[list, list]:
    """
    Filter trade cards by historical backtest.
    Returns (passed_cards, failed_cards).
    """
    passed, failed = [], []
    for card in cards:
        ok, stats = passes_backtest(card["ticker"], min_win_rate, min_pf)
        card["backtest"] = stats
        if ok:
            passed.append(card)
        else:
            card["backtest_fail_reason"] = stats.get("reason", "failed backtest")
            failed.append(card)
    return passed, failed
