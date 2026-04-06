"""
FEATURE 1: Technical Analysis System
Provides plain-English technical analysis across timeframes.
All results are beginner-friendly with clear explanations.
"""

import numpy as np
import pandas as pd
import yfinance as yf
import logging
from datetime import datetime
from functools import lru_cache
from src.watchlist import nse

logger = logging.getLogger(__name__)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _fetch(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    try:
        df = yf.download(nse(ticker), period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df
    except Exception as e:
        logger.warning("Fetch failed for %s: %s", ticker, e)
        return pd.DataFrame()


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = np.diff(closes)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_g = np.mean(gain[-period:])
    avg_l = np.mean(loss[-period:])
    if avg_l == 0:
        return 100.0
    return round(100 - (100 / (1 + avg_g / avg_l)), 1)


def _ema(arr: np.ndarray, span: int) -> float:
    k, e = 2 / (span + 1), arr[0]
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return float(e)


def _macd(closes: np.ndarray):
    if len(closes) < 26:
        return 0.0, 0.0, 0.0
    macd_line = _ema(closes, 12) - _ema(closes, 26)
    signal    = _ema(closes[-9:], 9) if len(closes) >= 9 else 0
    return round(macd_line, 4), round(signal, 4), round(macd_line - signal, 4)


def _bollinger(closes: np.ndarray, period: int = 20):
    if len(closes) < period:
        m = closes[-1]
        return m, m * 1.02, m * 0.98, 0.5
    window = closes[-period:]
    sma = np.mean(window)
    std = np.std(window)
    upper = sma + 2 * std
    lower = sma - 2 * std
    pct_b = (closes[-1] - lower) / (upper - lower + 1e-10)
    return round(sma, 2), round(upper, 2), round(lower, 2), round(pct_b, 3)


def _support_resistance(closes: np.ndarray, n: int = 10):
    """Find support and resistance using recent swing highs/lows."""
    if len(closes) < 20:
        return closes[-1] * 0.95, closes[-1] * 1.05
    # Rolling min/max over 10-bar windows
    supports  = [min(closes[max(0, i-n):i+1]) for i in range(n, len(closes))]
    resistances = [max(closes[max(0, i-n):i+1]) for i in range(n, len(closes))]
    support    = round(float(np.percentile(supports[-20:], 25)), 2)
    resistance = round(float(np.percentile(resistances[-20:], 75)), 2)
    return support, resistance


def _fibonacci_levels(high: float, low: float) -> dict:
    """Classic Fib retracement levels from recent swing."""
    diff = high - low
    return {
        "23.6%": round(high - 0.236 * diff, 2),
        "38.2%": round(high - 0.382 * diff, 2),
        "50.0%": round(high - 0.500 * diff, 2),
        "61.8%": round(high - 0.618 * diff, 2),
        "78.6%": round(high - 0.786 * diff, 2),
    }


def _detect_chart_pattern(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> str:
    """Simple pattern detection on last 30 bars."""
    if len(closes) < 30:
        return "Insufficient data"
    c = closes[-30:]
    h = highs[-30:]
    l = lows[-30:]

    # Double bottom: two lows within 3% of each other, separated by higher middle
    lo1, lo2 = np.min(l[:15]), np.min(l[15:])
    if abs(lo1 - lo2) / lo1 < 0.03 and np.min(l[10:20]) > max(lo1, lo2) * 1.01:
        return "Double Bottom (Bullish reversal pattern)"

    # Double top: two highs within 3%
    hi1, hi2 = np.max(h[:15]), np.max(h[15:])
    if abs(hi1 - hi2) / hi1 < 0.03 and np.max(h[10:20]) < min(hi1, hi2) * 0.99:
        return "Double Top (Bearish reversal pattern)"

    # Uptrend: each 10-bar block higher than previous
    if c[0] < c[10] < c[20] < c[-1]:
        return "Rising Channel (Bullish trend continuation)"

    # Downtrend
    if c[0] > c[10] > c[20] > c[-1]:
        return "Falling Channel (Bearish trend)"

    # Flag: sharp move then consolidation
    first_move = (c[10] - c[0]) / c[0]
    consolidation = np.std(c[10:]) / c[10]
    if first_move > 0.08 and consolidation < 0.02:
        return "Bull Flag (Continuation breakout setup)"

    return "No clear pattern (wait for confirmation)"


def _volume_trend(volumes: np.ndarray, closes: np.ndarray) -> dict:
    """Analyse whether buyers or sellers are in control."""
    if len(volumes) < 20:
        return {"trend": "Unknown", "interpretation": "Not enough data"}
    avg_vol   = np.mean(volumes[-20:])
    last_vol  = volumes[-1]
    up_days   = sum(1 for i in range(1, min(10, len(closes)))
                    if closes[-i] > closes[-(i+1)])
    vol_surge = round(last_vol / avg_vol, 2)

    if vol_surge > 1.5 and up_days >= 7:
        trend = "Strong Buying"
        interp = f"Volume is {vol_surge}x average on UP days — institutions are accumulating."
    elif vol_surge > 1.5 and up_days <= 3:
        trend = "Strong Selling"
        interp = f"Volume is {vol_surge}x average on DOWN days — heavy distribution."
    elif vol_surge < 0.7:
        trend = "Low Interest"
        interp = "Volume is well below average — weak conviction in current move."
    else:
        trend = "Neutral"
        interp = "Volume is near average — no strong conviction either way."

    return {
        "trend": trend,
        "vol_surge": vol_surge,
        "up_days_last_10": up_days,
        "interpretation": interp,
    }


def _confidence_rating(signals: dict) -> int:
    """Score 1–10 based on how many signals agree."""
    bullish = sum([
        signals.get("trend_daily") == "UPTREND",
        signals.get("rsi_signal") in ("Healthy", "Oversold - bounce likely"),
        signals.get("macd_signal") == "Bullish crossover",
        signals.get("price_vs_bb") == "Mid-zone (healthy)",
        signals.get("volume_trend") == "Strong Buying",
        signals.get("above_50ma"),
        signals.get("above_200ma"),
        signals.get("weekly_trend") == "UPTREND",
    ])
    return min(10, max(1, bullish + 1))


# ── Main analysis function ────────────────────────────────────────────────────

def analyze(ticker: str) -> dict:
    """
    Full technical analysis for a stock.

    Returns a report card with plain-English explanations.
    """
    df_daily  = _fetch(ticker, period="1y",  interval="1d")
    df_weekly = _fetch(ticker, period="3y",  interval="1wk")

    if df_daily.empty:
        return {"error": f"Could not fetch data for {ticker}"}

    c = df_daily["Close"].values.astype(float)
    h = df_daily["High"].values.astype(float)
    l = df_daily["Low"].values.astype(float)
    v = df_daily["Volume"].values.astype(float)
    price = round(float(c[-1]), 2)

    # ── Moving averages ──────────────────────────────────────────────────────
    ma50  = round(float(np.mean(c[-50:])),  2) if len(c) >= 50  else None
    ma100 = round(float(np.mean(c[-100:])), 2) if len(c) >= 100 else None
    ma200 = round(float(np.mean(c[-200:])), 2) if len(c) >= 200 else None

    # ── Trend ────────────────────────────────────────────────────────────────
    daily_trend  = "UPTREND"  if (ma50 and price > ma50)  else "DOWNTREND"
    weekly_trend = "UPTREND"
    if not df_weekly.empty:
        cw = df_weekly["Close"].values.astype(float)
        wma10 = np.mean(cw[-10:]) if len(cw) >= 10 else cw[-1]
        weekly_trend = "UPTREND" if cw[-1] > wma10 else "DOWNTREND"

    # ── RSI ──────────────────────────────────────────────────────────────────
    rsi = _rsi(c)
    if rsi < 30:
        rsi_signal = "Oversold - bounce likely"
        rsi_color  = "green"
    elif rsi < 40:
        rsi_signal = "Approaching oversold"
        rsi_color  = "yellow"
    elif rsi <= 60:
        rsi_signal = "Healthy"
        rsi_color  = "green"
    elif rsi <= 70:
        rsi_signal = "Approaching overbought"
        rsi_color  = "yellow"
    else:
        rsi_signal = "Overbought - risk of pullback"
        rsi_color  = "red"

    # ── MACD ─────────────────────────────────────────────────────────────────
    macd_line, macd_sig, macd_hist = _macd(c)
    if macd_hist > 0 and macd_line > macd_sig:
        macd_signal = "Bullish crossover"
    elif macd_hist < 0 and macd_line < macd_sig:
        macd_signal = "Bearish crossover"
    else:
        macd_signal = "Neutral"

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_mid, bb_up, bb_lo, bb_pctb = _bollinger(c)
    if bb_pctb < 0.2:
        bb_signal = "Near lower band (potential bounce zone)"
    elif bb_pctb > 0.8:
        bb_signal = "Near upper band (overbought caution)"
    else:
        bb_signal = "Mid-zone (healthy)"

    # ── Support / Resistance ─────────────────────────────────────────────────
    support, resistance = _support_resistance(c)

    # ── Fibonacci ─────────────────────────────────────────────────────────────
    period_high = round(float(np.max(h[-52:])), 2)
    period_low  = round(float(np.min(l[-52:])), 2)
    fib_levels  = _fibonacci_levels(period_high, period_low)

    # ── Volume ───────────────────────────────────────────────────────────────
    vol_analysis = _volume_trend(v, c)

    # ── Pattern ──────────────────────────────────────────────────────────────
    pattern = _detect_chart_pattern(c, h, l)

    # ── Entry / Stop / Target ─────────────────────────────────────────────────
    atr14 = float(np.mean([max(h[i] - l[i],
                               abs(h[i] - c[i-1]),
                               abs(l[i] - c[i-1]))
                            for i in range(1, min(15, len(c)))])) if len(c) > 1 else price * 0.02
    entry      = price
    stop_loss  = round(price - 2.0 * atr14, 2)
    take_profit = round(price + 4.0 * atr14, 2)
    rr_ratio   = round((take_profit - entry) / (entry - stop_loss), 2) if entry > stop_loss else 0

    # ── Confidence ───────────────────────────────────────────────────────────
    signal_dict = {
        "trend_daily": daily_trend,
        "rsi_signal": rsi_signal,
        "macd_signal": macd_signal,
        "price_vs_bb": bb_signal,
        "volume_trend": vol_analysis["trend"],
        "above_50ma": bool(ma50 and price > ma50),
        "above_200ma": bool(ma200 and price > ma200),
        "weekly_trend": weekly_trend,
    }
    confidence = _confidence_rating(signal_dict)

    # ── Overall verdict ──────────────────────────────────────────────────────
    if confidence >= 7:
        verdict = "STRONG BUY"
        verdict_emoji = "🟢"
    elif confidence >= 5:
        verdict = "BUY"
        verdict_emoji = "🟡"
    elif confidence >= 3:
        verdict = "WAIT"
        verdict_emoji = "🟠"
    else:
        verdict = "AVOID"
        verdict_emoji = "🔴"

    return {
        "ticker":          ticker.upper(),
        "price":           price,
        "analysed_at":     datetime.utcnow().isoformat(),
        "verdict":         verdict,
        "verdict_emoji":   verdict_emoji,
        "confidence":      f"{confidence}/10",

        "trend": {
            "daily":  daily_trend,
            "weekly": weekly_trend,
            "above_50ma":  ma50  and price > ma50,
            "above_100ma": ma100 and price > ma100,
            "above_200ma": ma200 and price > ma200,
            "ma_50":   ma50,
            "ma_100":  ma100,
            "ma_200":  ma200,
        },

        "momentum": {
            "rsi":        rsi,
            "rsi_signal": rsi_signal,
            "macd_line":  macd_line,
            "macd_hist":  macd_hist,
            "macd_signal": macd_signal,
        },

        "volatility": {
            "bb_upper":  bb_up,
            "bb_middle": bb_mid,
            "bb_lower":  bb_lo,
            "bb_pct_b":  bb_pctb,
            "bb_signal": bb_signal,
            "atr_14":    round(atr14, 2),
        },

        "levels": {
            "support":    support,
            "resistance": resistance,
            "52w_high":   period_high,
            "52w_low":    period_low,
            "fibonacci":  fib_levels,
        },

        "volume": vol_analysis,
        "pattern": pattern,

        "trade_plan": {
            "entry":       entry,
            "stop_loss":   stop_loss,
            "take_profit": take_profit,
            "rr_ratio":    rr_ratio,
            "plain_english": (
                f"Buy near ₹{entry:,.0f}. "
                f"If it falls to ₹{stop_loss:,.0f}, exit immediately (your loss is limited). "
                f"If it rises to ₹{take_profit:,.0f}, take profits. "
                f"For every ₹1 you risk, you could make ₹{rr_ratio}."
            ),
        },
    }


def print_report(ticker: str):
    """Print a beginner-friendly analysis report to console."""
    r = analyze(ticker)
    if "error" in r:
        print(r["error"])
        return

    t = r["trend"]
    m = r["momentum"]
    lv = r["levels"]
    tp = r["trade_plan"]

    print(f"\n{'='*60}")
    print(f"  {r['verdict_emoji']} TECHNICAL ANALYSIS — {r['ticker']}")
    print(f"  Price: ₹{r['price']:,.2f}  |  Confidence: {r['confidence']}  |  Verdict: {r['verdict']}")
    print(f"{'='*60}")
    print(f"\n  TREND")
    print(f"  Daily : {t['daily']}  |  Weekly: {t['weekly']}")
    print(f"  50-day MA: ₹{t['ma_50']:,.0f}  {'✅ above' if t['above_50ma'] else '❌ below'}")
    print(f"  200-day MA: ₹{t['ma_200']:,.0f}  {'✅ above' if t['above_200ma'] else '❌ below'}" if t['ma_200'] else "")
    print(f"\n  MOMENTUM")
    print(f"  RSI ({m['rsi']}): {m['rsi_signal']}")
    print(f"  MACD: {m['macd_signal']} (histogram: {m['macd_hist']})")
    print(f"\n  KEY LEVELS")
    print(f"  Support : ₹{lv['support']:,.2f}")
    print(f"  Resistance: ₹{lv['resistance']:,.2f}")
    print(f"  Fib 38.2%: ₹{lv['fibonacci']['38.2%']:,.2f}")
    print(f"  Fib 61.8%: ₹{lv['fibonacci']['61.8%']:,.2f}")
    print(f"\n  PATTERN: {r['pattern']}")
    print(f"  VOLUME: {r['volume']['trend']} — {r['volume']['interpretation']}")
    print(f"\n  TRADE PLAN")
    print(f"  {tp['plain_english']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE"
    print_report(ticker)
