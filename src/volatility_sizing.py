"""
Volatility-Adjusted Position Sizing
=====================================
Normalises position size to a target volatility of 15% annualised.
In high-volatility markets (VIX>25), sizes down automatically.
In low-volatility markets, sizes up slightly (capped at 1x).

Formula:
  raw_shares = (capital × risk_pct) / stop_distance
  vol_factor = target_vol / realised_vol   (capped 0.3 – 1.0)
  adj_shares = raw_shares × vol_factor × regime_multiplier
"""

import contextlib
import io
import numpy as np
import yfinance as yf
from src.watchlist import nse

TARGET_VOL  = 0.15    # 15% annualised target volatility
VIX_NORMAL  = 15.0    # baseline VIX
VIX_HIGH    = 25.0    # reduce size above this
VIX_CRISIS  = 35.0    # block all new trades above this


def _realised_vol(ticker: str, period: int = 20) -> float:
    """20-day annualised realised volatility for a stock."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download(nse(ticker), period="3mo", interval="1d",
                             progress=False, auto_adjust=True)
        if df.empty or len(df) < period + 1:
            return TARGET_VOL
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        rets = np.diff(np.log(df["Close"].values[-period:]))
        return float(np.std(rets) * np.sqrt(252))
    except Exception:
        return TARGET_VOL


def _vix_multiplier(vix: float) -> float:
    """Return a size multiplier based on current VIX level."""
    if vix >= VIX_CRISIS:
        return 0.0
    elif vix >= VIX_HIGH:
        # Linear scale from 0.5x at VIX=25 to 0.3x at VIX=35
        return round(1.0 - (vix - VIX_NORMAL) / (VIX_CRISIS - VIX_NORMAL) * 0.7, 2)
    else:
        return 1.0


def adjusted_shares(
    ticker: str,
    entry_price: float,
    stop_price: float,
    capital: float,
    risk_pct: float   = 0.02,
    vix: float        = 15.0,
    regime_mul: float = 1.0,
    max_pos_pct: float= 0.20,
) -> dict:
    """
    Calculate volatility-adjusted position size.

    Returns dict with:
      shares, invest, risk_rs, vol_factor, vix_factor, final_factor
    """
    stop_dist = abs(entry_price - stop_price)
    if stop_dist <= 0:
        return {"shares": 0, "reason": "invalid stop distance"}

    # Base size from risk
    base_shares = int((capital * risk_pct) / stop_dist)

    # Vol adjustment
    rv         = _realised_vol(ticker)
    vol_factor = min(1.0, max(0.3, TARGET_VOL / rv)) if rv > 0 else 1.0

    # VIX adjustment
    vix_factor = _vix_multiplier(vix)

    if vix_factor == 0.0:
        return {"shares": 0, "reason": f"VIX={vix:.1f} above crisis threshold"}

    # Regime adjustment
    final_factor = vol_factor * vix_factor * regime_mul

    adj = int(base_shares * final_factor)

    # Cap by max % of capital
    max_by_capital = int((capital * max_pos_pct) / entry_price)
    shares = max(0, min(adj, max_by_capital))

    return {
        "shares":       shares,
        "invest":       round(shares * entry_price, 2),
        "risk_rs":      round(shares * stop_dist, 2),
        "reward_rs":    round(shares * stop_dist * 2.5, 2),
        "vol_factor":   round(vol_factor, 2),
        "vix_factor":   round(vix_factor, 2),
        "regime_mul":   round(regime_mul, 2),
        "final_factor": round(final_factor, 2),
        "realised_vol": round(rv * 100, 1),
    }
