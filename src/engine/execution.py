"""
Execution model — order placement only.
The single halal-constrained gateway to the book: BUY to enter, close-only to
exit (never a naked sell = short). Wraps `paper_trader`; a live broker (Zerodha
GTT via `gtt_generator`) can drop in behind the same interface later.
"""
from __future__ import annotations


class ExecutionModel:
    venue = "paper"

    def buy(self, ticker: str, shares: int, price: float | None = None,
            stop: float | None = None, target: float | None = None) -> dict:
        ticker = str(ticker).strip().upper()
        if not ticker.isalnum():
            return {"ok": False, "reason": "ticker must be an alphanumeric NSE symbol"}
        if not (isinstance(shares, int) and shares > 0):
            return {"ok": False, "reason": "shares must be a positive integer"}
        from src import paper_trader as pt
        return pt.buy(ticker, shares, price, stop=stop, target=target)

    def close(self, ticker: str) -> dict:
        """Close a HELD position in full — the only halal exit (no shorting)."""
        ticker = str(ticker).strip().upper()
        from src import paper_trader as pt
        state = pt._load()
        if ticker not in state.get("positions", {}):
            return {"ok": False, "reason": f"no open position in {ticker} — refusing to short"}
        return pt.sell(ticker)

    def positions(self) -> dict:
        from src import paper_trader as pt
        return pt.portfolio_value(pt._load()).get("marked", {})

    def __repr__(self) -> str:
        return f"ExecutionModel({self.venue})"
