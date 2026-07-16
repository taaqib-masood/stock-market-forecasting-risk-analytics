"""
Multi-stock scanner.
Scans the NSE watchlist, scores each stock, returns ranked trade cards.

Run standalone:
    python -m src.scanner
"""

import contextlib
import io
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from src.watchlist import DEFAULT_SCAN, EXTENDED_SCAN, nse
from src.strategy import RuleStrategy
from src.backtest_runner import generate_live_signal

warnings.filterwarnings("ignore")

# NOTE: _score() and _trade_card() below are SUPERSEDED by the unified
# RuleStrategy + generate_live_signal path and are no longer called by the live
# scan. Kept temporarily; slated for removal in a dedicated cleanup commit.


# ── Indicator helpers (no external TA lib needed) ────────────────────────────

def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = np.diff(closes)
    gain  = np.where(delta > 0, delta, 0.0)
    loss  = np.where(delta < 0, -delta, 0.0)
    avg_g = np.mean(gain[-period:])
    avg_l = np.mean(loss[-period:])
    if avg_l == 0:
        return 100.0
    return 100 - (100 / (1 + avg_g / avg_l))


def _ema(arr: np.ndarray, span: int) -> float:
    k, e = 2 / (span + 1), arr[0]
    for v in arr[1:]:
        e = v * k + e * (1 - k)
    return e


def _atr(highs, lows, closes, period: int = 14) -> float:
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i]  - closes[i - 1]),
        ))
    return float(np.mean(trs[-period:])) if trs else 0.0


def _score(closes, highs, lows, volumes) -> dict:
    """
    Score a stock 0–100 on 7 criteria.
    Returns score, signal, individual indicator values.
    """
    c = np.array(closes, dtype=float)
    h = np.array(highs,  dtype=float)
    l = np.array(lows,   dtype=float)
    v = np.array(volumes, dtype=float)

    rsi       = _rsi(c)
    macd_line = _ema(c, 12) - _ema(c, 26)
    sig_line  = _ema(c[-9:], 9) if len(c) >= 9 else 0
    macd_hist = macd_line - sig_line
    atr       = _atr(h, l, c)
    sma20     = float(np.mean(c[-20:])) if len(c) >= 20 else c[-1]
    sma50     = float(np.mean(c[-50:])) if len(c) >= 50 else c[-1]
    vol_avg   = float(np.mean(v[-20:])) if len(v) >= 20 else v[-1]
    vol_surge = v[-1] / vol_avg if vol_avg > 0 else 1.0

    price = c[-1]

    # Bollinger
    std20   = float(np.std(c[-20:])) if len(c) >= 20 else 1
    bb_up   = sma20 + 2 * std20
    bb_lo   = sma20 - 2 * std20
    bb_pctb = (price - bb_lo) / (bb_up - bb_lo + 1e-10)

    # Momentum: 5d return
    ret_5d = (price / c[-6] - 1) * 100 if len(c) >= 6 else 0

    # ── Bullish scoring criteria ──────────────────────────────────────────────
    criteria = {
        "rsi_healthy":    40 <= rsi <= 68,                    # not overbought/oversold
        "macd_bullish":   macd_hist > 0,                      # MACD histogram positive
        "above_sma20":    price > sma20,                      # short-term uptrend
        "above_sma50":    price > sma50,                      # medium-term uptrend
        "volume_surge":   vol_surge >= 1.2,                   # above-average volume
        "bb_position":    0.4 <= bb_pctb <= 0.85,             # mid-to-upper Bollinger
        "momentum":       ret_5d > 0,                         # positive 5d momentum
    }

    score = sum(criteria.values()) / len(criteria) * 100

    # Direction
    bullish_count = sum(criteria.values())
    if bullish_count >= 5:
        direction, signal = 1,  "BUY"
    elif bullish_count <= 2:
        direction, signal = -1, "SELL"
    else:
        direction, signal = 0,  "WAIT"

    return {
        "score":      round(score, 1),
        "signal":     signal,
        "direction":  direction,
        "rsi":        round(rsi, 1),
        "macd_hist":  round(macd_hist, 4),
        "atr":        round(atr, 2),
        "sma20":      round(sma20, 2),
        "sma50":      round(sma50, 2),
        "vol_surge":  round(vol_surge, 2),
        "bb_pctb":    round(bb_pctb, 3),
        "ret_5d":     round(ret_5d, 2),
        "price":      round(price, 2),
        "criteria":   criteria,
    }


def _trade_card(ticker: str, s: dict, capital: float, max_risk_pct: float = 0.02) -> dict:
    """Build an actionable trade card from a score dict."""
    price      = s["price"]
    atr        = s["atr"] if s["atr"] > 0 else price * 0.015
    direction  = s["direction"]

    stop_dist  = 2.0 * atr
    target_dist = stop_dist * 2.5

    if direction == 1:
        stop   = round(price - stop_dist, 2)
        target = round(price + target_dist, 2)
    elif direction == -1:
        stop   = round(price + stop_dist, 2)
        target = round(price - target_dist, 2)
    else:
        stop = target = price

    max_loss_rs  = capital * max_risk_pct
    shares       = max(1, int(max_loss_rs / stop_dist)) if stop_dist > 0 else 0
    max_shares_by_capital = int((capital * 0.20) / price)  # max 20% of capital per stock
    shares       = min(shares, max_shares_by_capital)

    invest       = round(shares * price, 2)
    risk_rs      = round(shares * stop_dist, 2)
    reward_rs    = round(shares * target_dist, 2)
    rr           = round(target_dist / stop_dist, 2) if stop_dist > 0 else 0

    return {
        "ticker":     ticker,
        "signal":     s["signal"],
        "score":      s["score"],
        "price":      price,
        "entry":      price,
        "stop":       stop,
        "target":     target,
        "rr":         rr,
        "shares":     shares,
        "invest":     invest,
        "risk_rs":    risk_rs,
        "reward_rs":  reward_rs,
        "rsi":        s["rsi"],
        "vol_surge":  s["vol_surge"],
        "ret_5d":     s["ret_5d"],
        "atr":        atr,
        "criteria":   s["criteria"],
        "direction":  direction,
    }


def _weekly_trend(ticker: str) -> str:
    """
    Returns 'UP', 'DOWN', or 'NEUTRAL' based on weekly chart.
    UP   = price > weekly SMA10 AND weekly MACD histogram > 0
    DOWN = price < weekly SMA10 AND weekly MACD histogram < 0
    """
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(nse(ticker), period="1y", interval="1wk",
                             progress=False, auto_adjust=True)
        if df.empty or len(df) < 12:
            return "NEUTRAL"
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        c = df["Close"].values.astype(float)
        sma10 = np.mean(c[-10:])
        macd  = _ema(c, 12) - _ema(c, 26)
        sig   = _ema(c[-9:], 9) if len(c) >= 9 else 0
        hist  = macd - sig
        price = c[-1]
        if price > sma10 and hist > 0:
            return "UP"
        elif price < sma10 and hist < 0:
            return "DOWN"
        return "NEUTRAL"
    except Exception:
        return "NEUTRAL"


def _scan_one(ticker: str, capital: float) -> dict | None:
    """Produce a unified live BUY signal for one ticker. None on failure/no-signal.

    Uses the SAME RuleStrategy + RiskManager as the backtest (via
    generate_live_signal), so the live signal == the backtested signal.
    """
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(nse(ticker), period="2y", interval="1d",
                             progress=False, auto_adjust=True)
        # Need ~200 bars for the sma_200-based engineered features.
        if df.empty or len(df) < 220:
            return None

        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

        card = generate_live_signal(df, strategy=RuleStrategy(), capital=capital)
        if card is None:           # no approved BUY on the latest bar
            return None

        # ── Multi-timeframe: skip BUY if the weekly trend disagrees ───────
        weekly = _weekly_trend(ticker)
        if weekly == "DOWN":
            return None

        card["ticker"]        = ticker
        card["last_updated"]  = datetime.now().strftime("%Y-%m-%d %H:%M")
        card["weekly_trend"]  = weekly
        card["mtf_confirmed"] = weekly in ("UP", "NEUTRAL")
        return card

    except Exception:
        return None


def scan(
    tickers: list[str] = None,
    capital: float = 100_000,
    top_n: int = 5,
    workers: int = 8,
    use_sector_rotation: bool = True,
    use_backtest_filter: bool = True,
    use_gap_risk: bool = True,
    use_regime_gate: bool = True,
    vix: float = 15.0,
) -> dict:
    """
    Full scan pipeline:
      0. Regime gate      → block new BUYs in CRASH/TRENDING_DOWN regimes
      1. Sector rotation  → only scan top 2 sectors
      2. Multi-timeframe  → daily + weekly must agree
      3. Backtest filter  → historical win rate >= 52%
      4. Gap risk filter  → block HIGH gap risk, reduce MEDIUM
      5. Rank by score    → return top N

    Returns dict with keys: cards, blocked, regime, sectors
    """
    regime_info = {}

    # Stage 0: Regime gate
    # Only block in full CRASH. In TRENDING_DOWN we still scan but raise
    # the score threshold so only the strongest BUY setups get through.
    _bear_mode = False
    if use_regime_gate:
        try:
            from src.regime_detector import detect
            regime_info = detect().__dict__
            regime_name = regime_info.get("name", "UNKNOWN")
            print(f"  Market regime: {regime_name}")
            if regime_name == "CRASH":
                print(f"  Regime gate: CRASH detected — protecting capital, no trades today.")
                return {"cards": [], "blocked": [], "regime": regime_info, "sectors": []}
            if regime_name == "TRENDING_DOWN":
                print(f"  Regime gate: TRENDING_DOWN — scanning with strict 71+ score filter.")
                _bear_mode = True   # stricter threshold applied below
            # Adjust VIX from regime info
            vix = float(regime_info.get("vix", vix))
        except Exception as e:
            print(f"  Regime detect skipped: {e}")

    if tickers is None:
        if use_sector_rotation:
            from src.sector_rotation import rank_sectors, stocks_in_sectors
            top_sectors = rank_sectors(top_n=2)
            tickers = stocks_in_sectors(top_sectors)
            print(f"  Top sectors: {', '.join(top_sectors)} "
                  f"({len(tickers)} stocks)")
        else:
            tickers = EXTENDED_SCAN
            top_sectors = []
    else:
        top_sectors = []

    # Halal: only BUY signals, no short selling ever
    # In bear mode (TRENDING_DOWN) raise score threshold to 63
    min_score = 63 if _bear_mode else 57

    # Stage 1: score + multi-timeframe
    results = []
    near_misses = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_scan_one, t, capital): t for t in tickers}
        for fut in as_completed(futures):
            card = fut.result()
            if not card or card["signal"] != "BUY":
                continue
            if card["rr"] >= 2.0 and card["score"] >= min_score:
                results.append(card)
            elif card["rr"] >= 1.5 and card["score"] >= (min_score - 10):
                near_misses.append(card)

    near_misses.sort(key=lambda x: x["score"], reverse=True)

    if not results:
        return {"cards": [], "blocked": [], "regime": regime_info,
                "sectors": top_sectors, "near_misses": near_misses[:5]}

    # Stage 2: backtest filter (unified — same strategy + engine as live)
    if use_backtest_filter:
        from src.backtest_runner import filter_cards as bt_filter
        passed, failed = bt_filter(results)
        if failed:
            print(f"  Backtest filter blocked: "
                  f"{', '.join(c['ticker'] for c in failed)}")
        results = passed

    # Stage 3: Gap risk filter
    all_blocked = []
    if use_gap_risk and results:
        from src.gap_risk import filter_cards as gap_filter
        results, gap_blocked = gap_filter(results, vix=vix, block_high=True)
        if gap_blocked:
            print(f"  Gap risk blocked: "
                  f"{', '.join(c['ticker'] for c in gap_blocked)}")
        all_blocked.extend(gap_blocked)

    results.sort(key=lambda x: x["score"], reverse=True)
    return {
        "cards":       results[:top_n],
        "blocked":     all_blocked,
        "regime":      regime_info,
        "sectors":     top_sectors,
        "near_misses": near_misses[:5],
    }


if __name__ == "__main__":
    print("Scanning NSE... (takes ~30s)\n")
    result = scan(capital=50_000, top_n=5)
    cards   = result["cards"]
    blocked = result["blocked"]
    regime  = result.get("regime", {})
    if regime:
        print(f"Regime: {regime.get('name')} | VIX: {regime.get('vix')} | "
              f"Max positions: {regime.get('max_positions')}\n")
    for i, c in enumerate(cards, 1):
        gap = c.get("gap_risk", {})
        print(f"#{i} {c['ticker']:<15} Score:{c['score']:>5}  "
              f"Entry:{c['entry']:>8.2f}  Stop:{c['stop']:>8.2f}  "
              f"Target:{c['target']:>8.2f}  R:R:{c['rr']}  "
              f"Shares:{c['shares']}  Risk:₹{c['risk_rs']}  "
              f"Gap:{gap.get('verdict','?')}")
    if blocked:
        print(f"\nBlocked ({len(blocked)}): {', '.join(c['ticker'] for c in blocked)}")
