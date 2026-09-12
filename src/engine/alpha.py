"""
Alpha model — signal generation only.
Wraps the pure-NumPy rule scorer (`scanner._score`) and the full scan pipeline
(`scanner.scan`). This is the "what looks attractive" role; it owns no sizing,
selection, or execution logic.
"""
from __future__ import annotations


class AlphaModel:
    name = "rule_scorer_v1"

    def score(self, closes, highs, lows, volumes) -> dict:
        """Raw 0–100 technical score for one name (the 7-criteria scorer)."""
        from src.scanner import _score
        return _score(closes, highs, lows, volumes)

    def scan(self, **kwargs) -> dict:
        """Full ranked scan. Delegates to scanner.scan so the live path is
        identical; recomposition from the role objects comes later."""
        from src.scanner import scan
        return scan(**kwargs)

    def __repr__(self) -> str:
        return f"AlphaModel({self.name})"
