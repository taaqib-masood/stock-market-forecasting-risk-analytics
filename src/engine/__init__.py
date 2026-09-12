"""
Trading engine — Lean-style model separation (Phase 2 seam).
=============================================================
QuantConnect's Lean splits an algorithm into four swappable roles:

    Alpha  →  Portfolio  →  Risk  →  Execution

Today this codebase fuses them: `scanner.scan` generates signals AND applies the
regime/sector selection AND sizes via `risk_manager`, then `daily_briefing` places
orders. That coupling makes it hard to swap one piece (e.g. a new alpha) without
touching the rest.

This package is the **seam**, not a rewrite. Each role is a thin adapter over the
existing functions, so behaviour is unchanged and nothing else has to move:

    AlphaModel      → src.scanner        (rule scorer + scan pipeline)
    PortfolioModel  → src.regime_detector + src.sector_rotation (what to consider)
    RiskModel       → src.risk_manager + src.strategy_presets    (stops/targets/size)
    ExecutionModel  → src.paper_trader   (place / close orders)

`TradingEngine.scan()` still delegates to `scanner.scan` (identical output), while
the role objects expose the decomposed pieces. The migration target — recomposing
the pipeline FROM these roles instead of inside scanner — is documented in the plan
and happens later, gated by the walk-forward harness.
"""
from src.engine.alpha import AlphaModel
from src.engine.portfolio import PortfolioModel
from src.engine.risk import RiskModel
from src.engine.execution import ExecutionModel


class TradingEngine:
    """Wires the four roles. `scan()` delegates to the existing pipeline so the
    live path is untouched; the role attributes are the future seam."""

    def __init__(self, capital: float = 100_000):
        self.capital = capital
        self.alpha = AlphaModel()
        self.portfolio = PortfolioModel()
        self.risk = RiskModel()
        self.execution = ExecutionModel()

    def scan(self, **kwargs) -> dict:
        kwargs.setdefault("capital", self.capital)
        return self.alpha.scan(**kwargs)

    def __repr__(self) -> str:
        return (f"TradingEngine(alpha={self.alpha!r}, portfolio={self.portfolio!r}, "
                f"risk={self.risk!r}, execution={self.execution!r})")


__all__ = ["AlphaModel", "PortfolioModel", "RiskModel", "ExecutionModel", "TradingEngine"]
