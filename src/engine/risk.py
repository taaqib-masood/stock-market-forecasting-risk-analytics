"""
Risk model — stops, targets, sizing.
Wraps `risk_manager.RiskManager`, parameterised by the active holding-period
preset (`strategy_presets`), so the chosen horizon (intra-week / swing /
intra-month) flows through to stop width and reward-to-risk automatically.
"""
from __future__ import annotations


class RiskModel:
    def __init__(self, preset: str | None = None):
        # None → follow the cockpit's active preset at call time.
        self._preset = preset

    def _rm_kwargs(self) -> dict:
        from src import strategy_presets as sp
        return sp.rm_kwargs(self._preset or sp.active())

    def manager(self, capital: float = 100_000):
        """A RiskManager pre-loaded with the active preset's risk params."""
        from src.risk_manager import RiskManager
        return RiskManager(capital=capital, **self._rm_kwargs())

    def evaluate(self, **kwargs) -> dict:
        """Stop/target/size decision for one entry (delegates to RiskManager)."""
        capital = kwargs.pop("capital", 100_000)
        return self.manager(capital).evaluate(**kwargs)

    def max_hold_days(self) -> int:
        from src import strategy_presets as sp
        return sp.max_hold_days(self._preset or sp.active())

    def __repr__(self) -> str:
        return f"RiskModel(preset={self._preset or 'active'})"
