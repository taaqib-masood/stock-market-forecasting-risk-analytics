"""
Dynamic & Trailing Stop Loss
=============================
Replaces fixed ATR stops with adaptive stops that:

1. Trail upward as price moves in your favour (locks in profits)
2. Tighten as trade matures (reduce risk over time)
3. Expand during high-volatility periods (avoid shake-outs)

Stop types:
  FIXED     — traditional 2×ATR, never moves
  TRAILING  — follows price up, never down (swing trade default)
  CHANDELIER— price - N×ATR over trailing window (institutional standard)
  BREAKEVEN — moves to entry once trade reaches 1:1 R

Usage:
  from src.dynamic_stops import StopManager
  sm = StopManager("RELIANCE", entry=1285, initial_stop=1251, target=1370)
  new_stop = sm.update(current_price=1310, atr=12.5)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StopType(str, Enum):
    FIXED      = "FIXED"
    TRAILING   = "TRAILING"
    CHANDELIER = "CHANDELIER"
    BREAKEVEN  = "BREAKEVEN"


@dataclass
class StopManager:
    ticker:        str
    entry:         float
    initial_stop:  float
    target:        float
    stop_type:     StopType = StopType.CHANDELIER
    atr_multiplier: float   = 2.0
    trail_window:  int      = 3        # chandelier: highest close over N days

    # Runtime state
    current_stop:  float = field(init=False)
    highest_close: float = field(init=False)
    moved_to_be:   bool  = field(init=False, default=False)
    days_held:     int   = field(init=False, default=0)

    def __post_init__(self):
        self.current_stop  = self.initial_stop
        self.highest_close = self.entry

    @property
    def risk(self) -> float:
        return abs(self.entry - self.initial_stop)

    @property
    def rr_achieved(self) -> float:
        gain = self.highest_close - self.entry
        return round(gain / self.risk, 2) if self.risk > 0 else 0

    def update(self, current_price: float, atr: float) -> dict:
        """
        Update stop based on current price and ATR.
        Returns dict with new_stop, action, locked_profit_pct.
        """
        self.days_held     += 1
        self.highest_close  = max(self.highest_close, current_price)
        old_stop            = self.current_stop
        action              = "HOLD"

        if self.stop_type == StopType.FIXED:
            pass  # never moves

        elif self.stop_type == StopType.TRAILING:
            # Simple trailing: stop = highest_close - 2×ATR
            trail = self.highest_close - self.atr_multiplier * atr
            if trail > self.current_stop:
                self.current_stop = round(trail, 2)
                action = "TRAILED"

        elif self.stop_type == StopType.CHANDELIER:
            # Chandelier: tighter as trade matures
            mult = max(1.0, self.atr_multiplier - self.days_held * 0.05)
            trail = self.highest_close - mult * atr
            if trail > self.current_stop:
                self.current_stop = round(trail, 2)
                action = "CHANDELIER_TRAIL"

        elif self.stop_type == StopType.BREAKEVEN:
            # Move to breakeven once 1:1 R achieved
            if not self.moved_to_be and (current_price - self.entry) >= self.risk:
                self.current_stop = round(self.entry + 0.01, 2)   # tiny above entry
                self.moved_to_be  = True
                action = "MOVED_TO_BREAKEVEN"

        # Never let stop go below initial stop
        self.current_stop = max(self.current_stop, self.initial_stop)

        # Check hit
        status = "OPEN"
        if current_price <= self.current_stop:
            status = "STOP_HIT"
        elif current_price >= self.target:
            status = "TARGET_HIT"

        locked_profit = max(0, self.current_stop - self.entry)
        locked_pct    = round(locked_profit / self.entry * 100, 2)

        return {
            "ticker":          self.ticker,
            "current_price":   current_price,
            "stop":            self.current_stop,
            "prev_stop":       old_stop,
            "target":          self.target,
            "status":          status,
            "action":          action,
            "rr_achieved":     self.rr_achieved,
            "locked_profit":   round(locked_profit, 2),
            "locked_pct":      locked_pct,
            "days_held":       self.days_held,
            "highest_close":   self.highest_close,
        }

    def suggest_type(entry: float, target: float, stop: float) -> StopType:
        """Recommend stop type based on R:R and target distance."""
        rr = abs(target - entry) / abs(entry - stop) if stop != entry else 1
        if rr >= 3.0:
            return StopType.CHANDELIER   # high reward — trail aggressively
        elif rr >= 2.0:
            return StopType.TRAILING
        else:
            return StopType.BREAKEVEN    # low reward — at least protect capital


def recommend_stop(
    entry: float,
    atr: float,
    regime_name: str,
    rr: float = 2.5,
) -> dict:
    """
    Given entry, ATR and regime, return recommended stop and type.
    """
    regime_multipliers = {
        "TRENDING_UP":   2.0,
        "RANGING":       1.5,
        "BREAKOUT":      2.5,
        "TRENDING_DOWN": 1.5,
        "CRASH":         1.0,
    }
    mult      = regime_multipliers.get(regime_name, 2.0)
    stop_dist = mult * atr
    stop      = round(entry - stop_dist, 2)
    target    = round(entry + stop_dist * rr, 2)
    stop_type = StopType.suggest_type(entry, target, stop)

    return {
        "stop":            stop,
        "target":          target,
        "stop_type":       stop_type.value,
        "stop_dist":       round(stop_dist, 2),
        "atr_multiplier":  mult,
        "regime":          regime_name,
    }
