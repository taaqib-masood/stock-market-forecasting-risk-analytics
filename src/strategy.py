"""
Unified strategy interface — the single source of truth for signal generation.

Goal (V-1.0 "unify the paths"): both the live path and the historical backtest
call the SAME Strategy on the SAME engineered features
(src.feature_engineering.add_features), then feed the SAME risk/execution engine
(src.risk_manager). This guarantees live == backtest.

`RuleStrategy` ports the scanner's 7-criteria bullish score (previously hand-coded
in NumPy in src.scanner._score, and *separately and divergently* in
src.backtest_filter) onto engineered feature columns, so there is ONE definition
of "the signal" instead of three. The ML ensemble will later become a second
`Strategy` behind this same interface.
"""
from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """Maps an engineered-feature DataFrame to trade signals."""

    name: str = "base"

    @abstractmethod
    def generate_signals(self, features: pd.DataFrame) -> pd.DataFrame:
        """
        Returns a DataFrame indexed like `features` with columns:
          - score      : 0-100 signal strength
          - signal     : 1 (BUY) / 0 (flat) / -1 (SELL, only if shorts allowed)
          - confidence : 0-1, fed to RiskManager.evaluate

        Works identically on a full history (backtest) or a single latest row
        (live), because it is fully vectorized.
        """
        raise NotImplementedError


class RuleStrategy(Strategy):
    """
    7-criteria bullish score, computed from engineered feature columns so live
    and backtest share one definition.

    Criteria (each contributes equally to the 0-100 score):
      1. RSI healthy   : 40 <= rsi_14 <= 68
      2. MACD bullish  : macd_hist > 0
      3. Above SMA20   : price_vs_sma20 > 0
      4. Above SMA50   : price_vs_sma50 > 0
      5. Volume surge  : volume_ratio >= 1.2
      6. BB position   : 0.4 <= bb_pct_b <= 0.85
      7. Momentum      : return_5d > 0

    BUY when >= `min_criteria` are met. Halal default: BUY-only (no shorts).
    """

    name = "rule_7criteria"

    REQUIRED_COLS = [
        "rsi_14", "macd_hist", "price_vs_sma20", "price_vs_sma50",
        "volume_ratio", "bb_pct_b", "return_5d",
    ]
    N_CRITERIA = 7

    def __init__(self, min_criteria: int = 5, allow_short: bool = False):
        self.min_criteria = min_criteria
        self.allow_short = allow_short

    def criteria(self, features: pd.DataFrame) -> pd.DataFrame:
        """The 7 per-bar boolean criteria — the single source of truth used by
        both the score/signal and the live trade-card display fields."""
        missing = [c for c in self.REQUIRED_COLS if c not in features.columns]
        if missing:
            raise KeyError(
                f"RuleStrategy needs columns {missing}; "
                f"run feature_engineering.add_features first."
            )
        c = pd.DataFrame(index=features.index)
        c["rsi_healthy"] = features["rsi_14"].between(40, 68)         # inclusive
        c["macd_bullish"] = features["macd_hist"] > 0
        c["above_sma20"] = features["price_vs_sma20"] > 0
        c["above_sma50"] = features["price_vs_sma50"] > 0
        c["volume_surge"] = features["volume_ratio"] >= 1.2
        c["bb_position"] = features["bb_pct_b"].between(0.4, 0.85)
        c["momentum"] = features["return_5d"] > 0
        return c

    def generate_signals(self, features: pd.DataFrame) -> pd.DataFrame:
        c = self.criteria(features)
        count = c.sum(axis=1)
        score = count / self.N_CRITERIA * 100.0

        signal = pd.Series(0, index=features.index, dtype=int)
        signal[count >= self.min_criteria] = 1
        if self.allow_short:
            # Symmetric to the long rule: SELL when bullish count is as low as
            # the long rule is high (matches src.scanner: SELL when count <= 2).
            signal[count <= (self.N_CRITERIA - self.min_criteria)] = -1

        return pd.DataFrame({
            "score": score.round(1),
            "signal": signal.astype(int),
            "confidence": (score / 100.0).round(4),
        })


class RuleStrategyV2(RuleStrategy):
    """
    Track-A candidate: the base 7 criteria PLUS daily-bar additions, to be GATED
    through src.walk_forward (kept only if it beats RuleStrategy net-of-cost OOS).

    Additions (each toggleable so the harness can isolate its marginal lift):
      - ADX gate        : require adx_14 >= adx_gate (trade only in real trends).
      - Donchian break  : +1 scored criterion when close clears the prior 20-day
                          high AND volume z-score confirms (>= vol_z_min).
      - Squeeze release : +1 scored criterion when band width is in its low
                          percentile AND volume z + MACD confirm expansion.

    min_criteria is auto-scaled to the active criterion count to preserve the
    base's ~71% (5/7) selectivity, so a fair vote — not a looser one.
    """

    name = "rule_v2"

    def __init__(self, allow_short: bool = False, adx_gate: float = 20.0,
                 use_donchian: bool = True, use_squeeze: bool = True,
                 vol_z_min: float = 1.0, selectivity: float = 5 / 7):
        super().__init__(min_criteria=5, allow_short=allow_short)
        self.adx_gate = adx_gate
        self.use_donchian = use_donchian
        self.use_squeeze = use_squeeze
        self.vol_z_min = vol_z_min
        self.selectivity = selectivity

    def criteria(self, features: pd.DataFrame) -> pd.DataFrame:
        c = super().criteria(features)  # base 7
        if self.use_donchian:
            c["donchian_break"] = (features["donchian_break_20"] == 1) & \
                                  (features["volume_zscore"] >= self.vol_z_min)
        if self.use_squeeze:
            c["squeeze_break"] = (features["bb_squeeze_pct"] <= 0.25) & \
                                 (features["volume_zscore"] >= self.vol_z_min) & \
                                 (features["macd_hist"] > 0)
        return c

    def generate_signals(self, features: pd.DataFrame) -> pd.DataFrame:
        c = self.criteria(features)
        n = c.shape[1]
        count = c.sum(axis=1)
        score = count / n * 100.0

        import math
        min_needed = max(1, math.ceil(n * self.selectivity))
        buy = count >= min_needed
        if self.adx_gate:
            buy = buy & (features["adx_14"] >= self.adx_gate)

        signal = pd.Series(0, index=features.index, dtype=int)
        signal[buy] = 1
        if self.allow_short:
            signal[count <= (n - min_needed)] = -1

        return pd.DataFrame({
            "score": score.round(1),
            "signal": signal.astype(int),
            "confidence": (score / 100.0).round(4),
        })
