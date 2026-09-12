"""
Portfolio model — selection & rotation only.
Answers "what universe should we even consider right now": the market regime gate
(block new BUYs in down/crash regimes) and sector rotation (trade only the leading
sectors). Wraps `regime_detector` and `sector_rotation`.
"""
from __future__ import annotations


class PortfolioModel:
    def regime(self):
        """Current market regime object (network call to yfinance)."""
        from src.regime_detector import detect
        return detect()

    def regime_ok(self, regime=None) -> bool:
        """True when new longs are allowed. position_size_mul == 0 is how the
        regime table encodes TRENDING_DOWN / CRASH ('all longs forbidden')."""
        r = regime if regime is not None else self.regime()
        return getattr(r, "position_size_mul", 0.0) > 0.0

    def max_positions(self, regime=None) -> int:
        r = regime if regime is not None else self.regime()
        return int(getattr(r, "max_positions", 0))

    def top_sectors(self, top_n: int = 2):
        from src.sector_rotation import rank_sectors
        return rank_sectors(top_n=top_n)

    def candidates(self, sectors=None):
        """The tickers eligible to be scanned given current rotation."""
        from src.sector_rotation import rank_sectors, stocks_in_sectors
        return stocks_in_sectors(sectors or rank_sectors(top_n=2))

    def __repr__(self) -> str:
        return "PortfolioModel(regime+sector)"
