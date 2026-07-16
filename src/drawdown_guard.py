"""
Drawdown-guard "why I de-risked" explainer.

The passive overlay (`passive.drawdown_exposure`) decides how much of the basket to
hold based on the benchmark's drawdown from its trailing peak. On its own that's a
black-box number ("exposure = 0.62"). This module turns the SAME math into a plain-
language, rupee-denominated explanation: what the market did, which threshold it
crossed, how much cash the guard is holding today, and why — the transparency posture
the council flagged as the product's real value (certainty/trust, not a magic number).

It deliberately re-derives nothing: it reads the exact peak/drawdown/exposure formula
from `passive` so the explainer can never drift from what the backtest actually traded.

    python -m src.drawdown_guard --capital 50000
"""
from typing import Optional

import pandas as pd

# Same defaults as passive.drawdown_exposure — single source of truth for the band.
DD_START = -0.08      # ordinary dips above this: stay fully invested
DD_FULL = -0.20       # catastrophic drawdown: scale down to the floor
FLOOR = 0.30          # never below 30% invested (long-only, don't time the bottom)


def current_state(benchmark_close: pd.Series, dd_start: float = DD_START,
                  dd_full: float = DD_FULL, floor: float = FLOOR) -> dict:
    """Today's drawdown-guard state from a benchmark close series.

    Mirrors `passive.drawdown_exposure` exactly (rolling-252 peak, graded band) but
    returns the intermediate values so the decision can be EXPLAINED, not just applied.
    Uses the latest available bar (un-lagged) — this is the live "where are we now"
    read, whereas the backtest lags exposure by a day to avoid look-ahead.
    """
    peak = benchmark_close.rolling(252, min_periods=1).max()
    dd = float(benchmark_close.iloc[-1] / peak.iloc[-1] - 1.0)          # <= 0
    frac = min(max((dd - dd_start) / (dd_full - dd_start), 0.0), 1.0)
    exposure = 1.0 - frac * (1.0 - floor)

    if dd >= dd_start:
        status = "FULLY INVESTED"
    elif dd <= dd_full:
        status = "MAX DEFENSIVE"
    else:
        status = "DE-RISKING"

    return {
        "drawdown_pct": round(dd * 100, 1),
        "exposure_pct": round(exposure * 100, 1),
        "cash_pct": round((1 - exposure) * 100, 1),
        "status": status,
        "peak": round(float(peak.iloc[-1]), 1),
        "level": round(float(benchmark_close.iloc[-1]), 1),
        "dd_start_pct": round(dd_start * 100, 1),
        "dd_full_pct": round(dd_full * 100, 1),
        "floor_pct": round(floor * 100, 1),
    }


def explain(state: dict, benchmark_name: str = "Nifty 50") -> str:
    """One-paragraph reason for today's exposure, grounded in the state."""
    dd, off = state["drawdown_pct"], state["cash_pct"]
    if state["status"] == "FULLY INVESTED":
        return (f"{benchmark_name} is {abs(dd):.1f}% off its recent peak — shallower than "
                f"the {abs(state['dd_start_pct']):.0f}% de-risk line. Holding the basket in "
                f"full; ordinary dips aren't worth timing.")
    if state["status"] == "MAX DEFENSIVE":
        return (f"{benchmark_name} is {abs(dd):.1f}% off its peak — past the "
                f"{abs(state['dd_full_pct']):.0f}% catastrophic line. Exposure cut to the "
                f"{state['floor_pct']:.0f}% floor; {off:.0f}% parked in cash as crash insurance.")
    return (f"{benchmark_name} is {abs(dd):.1f}% off its peak — inside the de-risk band "
            f"({abs(state['dd_start_pct']):.0f}% to {abs(state['dd_full_pct']):.0f}%). "
            f"Trimmed to {state['exposure_pct']:.0f}% invested, {off:.0f}% in cash, and it "
            f"scales further if the drawdown deepens.")


def format_card(state: dict, capital: Optional[float] = None,
                benchmark_name: str = "Nifty 50") -> str:
    """Shareable card: status, the why, and the rupee split if capital is given."""
    icon = {"FULLY INVESTED": "🟢", "DE-RISKING": "🟡", "MAX DEFENSIVE": "🔴"}[state["status"]]
    lines = [f"{icon} Drawdown guard — {state['status']}  ({state['exposure_pct']:.0f}% invested)"]
    lines.append(f"  {explain(state, benchmark_name)}")
    lines.append(f"  {benchmark_name}: {state['level']:.0f} vs peak {state['peak']:.0f} "
                 f"({state['drawdown_pct']:+.1f}%)")
    if capital:
        invested = capital * state["exposure_pct"] / 100
        cash = capital - invested
        lines.append(f"  On ₹{capital:,.0f}: ₹{invested:,.0f} in basket · ₹{cash:,.0f} in cash.")
    lines.append("  ⚠️ Mechanical trend rule, not advice. Past drawdowns don't predict future ones.")
    return "\n".join(lines)


def live_card(benchmark: str = "^NSEI", capital: Optional[float] = None,
              benchmark_name: str = "Nifty 50") -> str:
    """Fetch the benchmark and render today's explainer (network)."""
    from src.passive import _fetch_benchmark
    bench = _fetch_benchmark(benchmark, years=2, start=None, end=None).dropna()
    return format_card(current_state(bench), capital=capital, benchmark_name=benchmark_name)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, default=None)
    p.add_argument("--benchmark", default="^NSEI")
    args = p.parse_args()
    print(live_card(args.benchmark, capital=args.capital))
