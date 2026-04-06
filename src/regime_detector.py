"""
Advanced Market Regime Detector
================================
Detects 5 market regimes with confidence scores:

  TRENDING_UP   — strong uptrend, high momentum, low VIX
  TRENDING_DOWN — strong downtrend, falling prices
  RANGING       — sideways, mean-reverting, low momentum
  BREAKOUT      — volatility expansion, potential trend start
  CRASH         — VIX spike, breadth collapse, avoid all longs

Each regime maps to different strategy parameters.
"""

import contextlib
import io
import numpy as np
import yfinance as yf
from dataclasses import dataclass
from datetime import datetime

_CACHE = {"regime": None, "at": None}
_CACHE_TTL = 1800  # 30 min


@dataclass
class Regime:
    name:        str
    confidence:  float    # 0–100
    vix:         float
    nifty_price: float
    nifty_ret1w: float
    nifty_ret1m: float
    adv_decline: float    # advance/decline proxy
    description: str

    # Strategy params for this regime
    max_positions:    int
    position_size_mul: float   # multiply normal size by this
    min_score:        int      # minimum signal score to trade
    use_trailing_stop: bool


REGIME_PARAMS = {
    "TRENDING_UP": Regime(
        name="TRENDING_UP", confidence=0, vix=0,
        nifty_price=0, nifty_ret1w=0, nifty_ret1m=0, adv_decline=0,
        description="Strong uptrend. Trend-following works best.",
        max_positions=3, position_size_mul=1.0,
        min_score=65, use_trailing_stop=True,
    ),
    "TRENDING_DOWN": Regime(
        name="TRENDING_DOWN", confidence=0, vix=0,
        nifty_price=0, nifty_ret1w=0, nifty_ret1m=0, adv_decline=0,
        description="Downtrend. Avoid longs. Wait for reversal.",
        max_positions=0, position_size_mul=0.0,
        min_score=85, use_trailing_stop=False,
    ),
    "RANGING": Regime(
        name="RANGING", confidence=0, vix=0,
        nifty_price=0, nifty_ret1w=0, nifty_ret1m=0, adv_decline=0,
        description="Sideways market. Mean-reversion setups only.",
        max_positions=2, position_size_mul=0.7,
        min_score=72, use_trailing_stop=False,
    ),
    "BREAKOUT": Regime(
        name="BREAKOUT", confidence=0, vix=0,
        nifty_price=0, nifty_ret1w=0, nifty_ret1m=0, adv_decline=0,
        description="Volatility expanding. Early trend. High reward.",
        max_positions=2, position_size_mul=0.8,
        min_score=70, use_trailing_stop=True,
    ),
    "CRASH": Regime(
        name="CRASH", confidence=0, vix=0,
        nifty_price=0, nifty_ret1w=0, nifty_ret1m=0, adv_decline=0,
        description="Market crash / panic. All longs forbidden.",
        max_positions=0, position_size_mul=0.0,
        min_score=99, use_trailing_stop=False,
    ),
}


def _fetch(ticker, period, interval):
    with contextlib.redirect_stderr(io.StringIO()):
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
    if not df.empty:
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def detect() -> Regime:
    """Detect current market regime. Cached for 30 minutes."""
    import time
    now = time.time()
    if _CACHE["regime"] and _CACHE["at"] and (now - _CACHE["at"]) < _CACHE_TTL:
        return _CACHE["regime"]

    try:
        nifty = _fetch("^NSEI",  "6mo", "1d")
        vix   = _fetch("^INDIAVIX", "3mo", "1d")

        c = nifty["Close"].values.astype(float) if not nifty.empty else np.array([])
        if len(c) < 20:
            return _default_regime()

        price  = float(c[-1])
        sma20  = float(np.mean(c[-20:]))
        sma50  = float(np.mean(c[-50:])) if len(c) >= 50 else sma20
        sma200 = float(np.mean(c[-200:])) if len(c) >= 200 else sma50
        ret1w  = float((price / c[-6]  - 1) * 100) if len(c) >= 6  else 0
        ret1m  = float((price / c[-22] - 1) * 100) if len(c) >= 22 else 0
        ret3m  = float((price / c[-66] - 1) * 100) if len(c) >= 66 else 0

        # Volatility: 20-day realised vol (annualised)
        rets    = np.diff(np.log(c[-21:]))
        vol20   = float(np.std(rets) * np.sqrt(252) * 100) if len(rets) > 0 else 15.0
        vol_avg = float(np.std(np.diff(np.log(c[-61:-21]))) * np.sqrt(252) * 100) \
                  if len(c) >= 61 else vol20

        # VIX
        vix_val = 15.0
        if not vix.empty:
            vix_val = float(vix["Close"].iloc[-1])

        # ADX proxy (trend strength via directional movement)
        adx = _adx(nifty["High"].values, nifty["Low"].values, c)

        # ── Regime classification ─────────────────────────────────────────
        if vix_val >= 30 and ret1w <= -3:
            name = "CRASH"
            conf = min(100, 60 + (vix_val - 30) * 2 + abs(ret1w) * 3)

        elif price > sma20 > sma50 and ret1m > 2 and adx > 25:
            name = "TRENDING_UP"
            conf = min(100, 50 + adx + ret1m * 2)

        elif price < sma20 < sma50 and ret1m < -2 and adx > 20:
            name = "TRENDING_DOWN"
            conf = min(100, 50 + adx + abs(ret1m) * 2)

        elif vol20 > vol_avg * 1.4 and abs(ret1w) > 2:
            name = "BREAKOUT"
            conf = min(100, 50 + (vol20 / vol_avg - 1) * 40)

        else:
            name = "RANGING"
            conf = min(100, 80 - adx)

        r = Regime(
            name=name,
            confidence=round(conf, 1),
            vix=round(vix_val, 2),
            nifty_price=round(price, 2),
            nifty_ret1w=round(ret1w, 2),
            nifty_ret1m=round(ret1m, 2),
            adv_decline=0.0,
            description=REGIME_PARAMS[name].description,
            max_positions=REGIME_PARAMS[name].max_positions,
            position_size_mul=REGIME_PARAMS[name].position_size_mul,
            min_score=REGIME_PARAMS[name].min_score,
            use_trailing_stop=REGIME_PARAMS[name].use_trailing_stop,
        )
        _CACHE["regime"] = r
        _CACHE["at"]     = now
        return r

    except Exception:
        return _default_regime()


def _adx(highs, lows, closes, period=14):
    """Simplified ADX (trend strength 0-100)."""
    try:
        h, l, c = highs[-period*2:], lows[-period*2:], closes[-period*2:]
        dm_plus, dm_minus, tr = [], [], []
        for i in range(1, len(c)):
            up   = h[i] - h[i-1]
            down = l[i-1] - l[i]
            dm_plus.append(up   if up > down and up > 0   else 0)
            dm_minus.append(down if down > up and down > 0 else 0)
            tr.append(max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])))
        atr  = np.mean(tr[-period:])
        if atr == 0:
            return 0
        di_plus  = np.mean(dm_plus[-period:])  / atr * 100
        di_minus = np.mean(dm_minus[-period:]) / atr * 100
        dx = abs(di_plus - di_minus) / (di_plus + di_minus + 1e-10) * 100
        return round(float(dx), 1)
    except Exception:
        return 20.0


def _default_regime() -> Regime:
    return Regime(
        name="RANGING", confidence=50.0, vix=15.0,
        nifty_price=0, nifty_ret1w=0, nifty_ret1m=0, adv_decline=0,
        description="Could not detect regime. Defaulting to cautious.",
        max_positions=2, position_size_mul=0.7,
        min_score=72, use_trailing_stop=False,
    )


def regime_emoji(name: str) -> str:
    return {"TRENDING_UP": "🟢", "TRENDING_DOWN": "🔴",
            "RANGING": "🟡", "BREAKOUT": "🔵", "CRASH": "💀"}.get(name, "❓")


if __name__ == "__main__":
    r = detect()
    print(f"\nMarket Regime: {regime_emoji(r.name)} {r.name}  ({r.confidence:.0f}% confidence)")
    print(f"Description  : {r.description}")
    print(f"VIX          : {r.vix}")
    print(f"Nifty        : ₹{r.nifty_price:,.0f}  (1W: {r.nifty_ret1w:+.2f}%  1M: {r.nifty_ret1m:+.2f}%)")
    print(f"Max positions: {r.max_positions}")
    print(f"Size factor  : {r.position_size_mul}x")
    print(f"Min score    : {r.min_score}")
    print(f"Trailing stop: {r.use_trailing_stop}")
