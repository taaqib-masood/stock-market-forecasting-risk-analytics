"""
Gap Risk Protection
====================
Detects stocks with high overnight gap risk before recommending them.

Checks:
  1. Historical gap frequency  — how often does this stock gap >2%?
  2. Earnings proximity        — already handled by earnings_guard
  3. Beta                      — high-beta stocks gap more in volatile markets
  4. Recent gap history        — has the stock gapped in the last 5 days?
  5. VIX level                 — higher VIX = more gap risk across all stocks

Stocks with gap risk score > 60 are flagged (position size reduced) or
blocked (gap risk score > 80).
"""

import contextlib
import io
import numpy as np
import yfinance as yf
from src.watchlist import nse

_CACHE: dict = {}


def _gap_series(ticker: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns (gaps_pct, closes) where gaps_pct = overnight % gap array.
    Gap = (open[t] - close[t-1]) / close[t-1] * 100
    """
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(nse(ticker), period="1y", interval="1d",
                             progress=False, auto_adjust=True)
        if df.empty or len(df) < 20:
            return np.array([]), np.array([])
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        opens  = df["Open"].values.astype(float)
        closes = df["Close"].values.astype(float)
        gaps   = (opens[1:] - closes[:-1]) / closes[:-1] * 100
        return gaps, closes
    except Exception:
        return np.array([]), np.array([])


def analyse(ticker: str, vix: float = 15.0) -> dict:
    """
    Analyse gap risk for a ticker.
    Returns score (0–100), verdict, and details.
    """
    if ticker in _CACHE:
        return _CACHE[ticker]

    gaps, closes = _gap_series(ticker)
    if len(gaps) < 20:
        result = {"score": 30, "verdict": "LOW", "reason": "insufficient data"}
        _CACHE[ticker] = result
        return result

    abs_gaps = np.abs(gaps)

    # 1. Historical gap frequency (how often gap > 2%)
    freq_2pct   = float(np.mean(abs_gaps > 2.0) * 100)
    freq_3pct   = float(np.mean(abs_gaps > 3.0) * 100)

    # 2. Average gap size
    avg_gap = float(np.mean(abs_gaps))
    max_gap = float(np.max(abs_gaps))

    # 3. Recent gaps (last 5 days)
    recent_max_gap = float(np.max(abs_gaps[-5:])) if len(abs_gaps) >= 5 else 0

    # 4. Beta proxy (correlation + vol ratio vs Nifty)
    beta = _beta(closes)

    # 5. VIX multiplier
    vix_mul = 1.0 + max(0, (vix - 15) / 20)   # 1.0 at VIX=15, 2.0 at VIX=35

    # Score: weighted sum
    score = (
        freq_2pct  * 0.35 +
        freq_3pct  * 0.25 +
        avg_gap    * 8.0  +
        min(recent_max_gap * 5, 20) +
        min(beta   * 10,   15)
    ) * vix_mul

    score = min(100, round(score, 1))

    if score >= 80:
        verdict = "HIGH"
    elif score >= 55:
        verdict = "MEDIUM"
    else:
        verdict = "LOW"

    result = {
        "score":          score,
        "verdict":        verdict,
        "freq_2pct":      round(freq_2pct, 1),
        "avg_gap":        round(avg_gap, 2),
        "max_gap":        round(max_gap, 2),
        "recent_max_gap": round(recent_max_gap, 2),
        "beta":           round(beta, 2),
        "reason":         f"Gaps >2%: {freq_2pct:.0f}% of days  |  Avg gap: {avg_gap:.2f}%  |  Beta: {beta:.2f}",
    }
    _CACHE[ticker] = result
    return result


def _beta(closes: np.ndarray, period: int = 60) -> float:
    """Estimate beta vs Nifty over last `period` days."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            nifty = yf.download("^NSEI", period="3mo", interval="1d",
                                progress=False, auto_adjust=True)
        if nifty.empty:
            return 1.0
        nifty.columns = [c[0] if isinstance(c, tuple) else c for c in nifty.columns]
        nr = np.diff(nifty["Close"].values[-period:])
        sr = np.diff(closes[-period:])
        n  = min(len(nr), len(sr))
        if n < 10:
            return 1.0
        cov  = np.cov(sr[-n:], nr[-n:])[0][1]
        varn = np.var(nr[-n:])
        return float(cov / varn) if varn > 0 else 1.0
    except Exception:
        return 1.0


def position_size_multiplier(gap_verdict: str) -> float:
    """Return size adjustment based on gap risk."""
    return {"LOW": 1.0, "MEDIUM": 0.7, "HIGH": 0.4}.get(gap_verdict, 1.0)


def filter_cards(cards: list[dict], vix: float = 15.0,
                 block_high: bool = True) -> tuple[list, list]:
    """
    Filter trade cards by gap risk.
    HIGH gap risk → blocked (if block_high=True) or size reduced.
    Returns (safe_cards, blocked_cards).
    """
    safe, blocked = [], []
    for card in cards:
        risk = analyse(card["ticker"], vix=vix)
        card["gap_risk"] = risk
        if block_high and risk["verdict"] == "HIGH":
            card["gap_block_reason"] = risk["reason"]
            blocked.append(card)
        else:
            # Adjust shares by gap risk multiplier
            mul = position_size_multiplier(risk["verdict"])
            card["shares"] = max(1, int(card["shares"] * mul))
            card["invest"]    = round(card["shares"] * card["entry"], 2)
            card["risk_rs"]   = round(card["shares"] * abs(card["entry"] - card["stop"]), 2)
            card["reward_rs"] = round(card["shares"] * abs(card["target"] - card["entry"]), 2)
            safe.append(card)
    return safe, blocked
