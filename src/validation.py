"""
Look-ahead / data-leakage detection (freqtrade-style truncation invariance).

The single most important guard before trusting ANY backtest number: confirm the
strategy doesn't peek at the future. A feature leaks if the signal it produces at
bar t changes once you append bars after t.

`detect_lookahead` recomputes features + signals on the data truncated at several
cut points, and compares the most recent bars of each truncated run against the
full-data run. Any mismatch means a feature used information that didn't exist yet.

This is reusable: it will catch leakage the day someone adds a leaky feature, and
right now it empirically certifies the 7 RuleStrategy features are clean.
"""
from typing import Optional

import pandas as pd

from src.feature_engineering import add_features
from src.strategy import Strategy, RuleStrategy


def detect_lookahead(
    df: pd.DataFrame,
    strategy: Optional[Strategy] = None,
    n_checks: int = 12,
    tail: int = 5,
    min_history: int = 230,
) -> dict:
    """
    Empirical look-ahead detector.

    Parameters
    ----------
    df          : raw OHLCV with a DatetimeIndex
    strategy    : Strategy to test (default RuleStrategy)
    n_checks    : number of truncation cut points to test
    tail        : how many of the most-recent bars to compare at each cut point
    min_history : minimum bars a truncated slice must have to be testable

    Returns
    -------
    {"clean": bool, "checks": int, "mismatches": [ {date, truncated_signal, full_signal} ]}
    """
    strategy = strategy or RuleStrategy()

    full_feats = add_features(df, fetch_context=False)
    full_sig = strategy.generate_signals(full_feats)

    # Candidate cut points: feature dates with enough history behind them, and not
    # the very last bar (so "full" has bars after the cut to potentially leak from).
    pos = {d: df.index.get_loc(d) for d in full_sig.index}
    candidates = [d for d in full_sig.index if min_history <= pos[d] < len(df) - 1]

    if len(candidates) > n_checks:
        step = len(candidates) / n_checks
        cut_dates = [candidates[int(i * step)] for i in range(n_checks)]
    else:
        cut_dates = candidates

    mismatches = []
    checks = 0
    for cut in cut_dates:
        truncated = df.iloc[: pos[cut] + 1]
        t_feats = add_features(truncated, fetch_context=False)
        if t_feats.empty:
            continue
        t_sig = strategy.generate_signals(t_feats)

        # Compare the most recent `tail` bars of the truncated run vs full.
        for d in [d for d in t_sig.index[-tail:] if d in full_sig.index]:
            checks += 1
            ts = int(t_sig.loc[d, "signal"])
            fs = int(full_sig.loc[d, "signal"])
            if ts != fs:
                mismatches.append({
                    "date": str(pd.Timestamp(d).date()),
                    "bars_before_cut": int(pos[cut] - pos[d]),
                    "truncated_signal": ts,
                    "full_signal": fs,
                })

    return {"clean": len(mismatches) == 0, "checks": checks, "mismatches": mismatches}
