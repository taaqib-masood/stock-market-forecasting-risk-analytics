"""Pure, deterministic residual-momentum portfolio rules."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _valid_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _numeric_series(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").astype(float)


def _numeric_frame(values: pd.DataFrame) -> pd.DataFrame:
    return values.apply(pd.to_numeric, errors="coerce").astype(float)


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def compute_scores(
    closes: pd.DataFrame,
    benchmark_tri: pd.Series,
    *,
    long_lag: int = 252,
    skip: int = 21,
) -> pd.Series:
    """Return the latest residual 12-minus-1-month momentum scores.

    The calculation uses observations at ``t - long_lag`` and ``t - skip``
    from the common aligned history. Invalid symbols are omitted, while an
    invalid benchmark makes the whole score set empty.
    """
    if not _valid_positive_int(long_lag) or not _valid_positive_int(skip):
        return pd.Series(dtype=float)
    if skip >= long_lag or not isinstance(closes, pd.DataFrame):
        return pd.Series(dtype=float)
    if not isinstance(benchmark_tri, pd.Series):
        return pd.Series(dtype=float)
    if closes.columns.has_duplicates or closes.index.has_duplicates:
        return pd.Series(dtype=float)
    if benchmark_tri.index.has_duplicates or "__benchmark_tri__" in closes.columns:
        return pd.Series(dtype=float)

    frame = closes.copy()
    frame["__benchmark_tri__"] = benchmark_tri
    frame = frame.sort_index().loc[:, list(closes.columns) + ["__benchmark_tri__"]]
    numeric = _numeric_frame(frame)
    benchmark = numeric["__benchmark_tri__"]
    if len(numeric) < long_lag + 1 or not (np.isfinite(benchmark) & (benchmark > 0)).all():
        return pd.Series(dtype=float)

    start = -(long_lag + 1)
    end = -(skip + 1)
    benchmark_start = float(benchmark.iloc[start])
    benchmark_end = float(benchmark.iloc[end])
    if benchmark_start <= 0 or benchmark_end <= 0:
        return pd.Series(dtype=float)
    benchmark_momentum = benchmark_end / benchmark_start - 1.0

    scores: dict[str, float] = {}
    for symbol in sorted(closes.columns, key=str):
        if not isinstance(symbol, str) or not symbol:
            continue
        series = numeric[symbol]
        if not (np.isfinite(series) & (series > 0)).all():
            continue
        security_start = float(series.iloc[start])
        security_end = float(series.iloc[end])
        if security_start <= 0 or security_end <= 0:
            continue
        score = security_end / security_start - 1.0 - benchmark_momentum
        if math.isfinite(score):
            scores[symbol] = float(score)
    return pd.Series(scores, dtype=float)


def select_candidates(
    scores: pd.Series,
    returns: pd.DataFrame,
    *,
    limit: int = 10,
    lookback: int = 63,
    max_correlation: float = 0.80,
) -> list[str]:
    """Select ranked symbols while skipping highly correlated holdings."""
    if not _valid_positive_int(limit) or not _valid_positive_int(lookback):
        return []
    if lookback < 2 or not isinstance(scores, pd.Series) or not isinstance(returns, pd.DataFrame):
        return []
    max_correlation = _finite_number(max_correlation)
    if max_correlation is None or not 0.0 <= max_correlation <= 1.0:
        return []
    if scores.index.has_duplicates or returns.columns.has_duplicates or returns.index.has_duplicates:
        return []
    if len(returns) < lookback:
        return []

    numeric_returns = _numeric_frame(returns.sort_index()).tail(lookback)
    numeric_scores = _numeric_series(scores)
    ranked = [
        (str(symbol), float(score))
        for symbol, score in numeric_scores.items()
        if isinstance(symbol, str)
        and symbol
        and math.isfinite(float(score))
        and symbol in numeric_returns.columns
    ]
    ranked.sort(key=lambda item: (-item[1], item[0]))

    selected: list[str] = []
    for symbol, _score in ranked:
        if len(selected) >= limit:
            break
        candidate = numeric_returns[symbol]
        if not np.isfinite(candidate).all() or float(candidate.std(ddof=1)) <= 0:
            continue
        correlations = []
        for existing in selected:
            correlation = float(candidate.corr(numeric_returns[existing]))
            if not math.isfinite(correlation):
                correlations = [math.inf]
                break
            correlations.append(correlation)
        if correlations and max(correlations) > max_correlation:
            continue
        selected.append(symbol)
    return selected


def allocate_weights(
    selected: list[str],
    returns: pd.DataFrame,
    sectors: dict[str, str],
    liquidity_caps: dict[str, float],
    *,
    gross_cap: float = 0.80,
    security_cap: float = 0.10,
    sector_cap: float = 0.30,
    lookback: int = 63,
) -> dict[str, float]:
    """Allocate inverse-volatility NAV weights under frozen caps.

    Raw weights are normalized to gross capacity once. Each candidate is then
    clipped in selected order; clipped capacity is never redistributed.
    """
    if not _valid_positive_int(lookback) or lookback < 2:
        return {}
    caps = [_finite_number(cap) for cap in (gross_cap, security_cap, sector_cap)]
    if any(cap is None or cap < 0 for cap in caps):
        return {}
    gross_cap, security_cap, sector_cap = caps
    if not isinstance(selected, list):
        return {}
    if any(not isinstance(symbol, str) or not symbol for symbol in selected):
        return {}
    if len(set(selected)) != len(selected):
        return {}
    if not isinstance(returns, pd.DataFrame) or returns.columns.has_duplicates or returns.index.has_duplicates:
        return {}
    if not isinstance(sectors, dict) or not isinstance(liquidity_caps, dict):
        return {}
    if len(returns) < lookback:
        return {}

    numeric_returns = _numeric_frame(returns.sort_index()).tail(lookback)
    valid: list[tuple[str, float, str, float]] = []
    for symbol in selected:
        if symbol not in numeric_returns.columns or symbol not in sectors or symbol not in liquidity_caps:
            continue
        sector = sectors[symbol]
        liquidity_cap = _finite_number(liquidity_caps[symbol])
        if not isinstance(sector, str) or not sector:
            continue
        if liquidity_cap is None or liquidity_cap < 0:
            continue
        series = numeric_returns[symbol]
        if not np.isfinite(series).all():
            continue
        volatility = float(series.std(ddof=1))
        if not math.isfinite(volatility) or volatility <= 0:
            continue
        valid.append((symbol, 1.0 / volatility, sector, liquidity_cap))

    if not valid or gross_cap <= 0:
        return {}
    inverse_vol_total = sum(item[1] for item in valid)
    if not math.isfinite(inverse_vol_total) or inverse_vol_total <= 0:
        return {}

    weights: dict[str, float] = {}
    sector_used: dict[str, float] = {}
    gross_used = 0.0
    for symbol, inverse_vol, sector, liquidity_cap in valid:
        raw = gross_cap * inverse_vol / inverse_vol_total
        available_sector = max(0.0, sector_cap - sector_used.get(sector, 0.0))
        available_gross = max(0.0, gross_cap - gross_used)
        weight = min(raw, security_cap, available_sector, available_gross, liquidity_cap)
        if not math.isfinite(weight) or weight <= 0:
            continue
        weights[symbol] = float(weight)
        sector_used[sector] = sector_used.get(sector, 0.0) + float(weight)
        gross_used += float(weight)
    return weights


def initial_stop(entry_price: float, atr14: float) -> float:
    """Return the frozen initial stop at 2.5 ATR below entry."""
    entry = _finite_number(entry_price)
    atr = _finite_number(atr14)
    if entry is None or atr is None or entry <= 0 or atr <= 0:
        raise ValueError("entry_price and atr14 must be finite and positive")
    stop = entry - 2.5 * atr
    if stop <= 0:
        raise ValueError("derived stop must be positive")
    return stop


def _bar_value(bar: dict[str, Any], name: str) -> float | None:
    lower = name.lower()
    upper = name.capitalize()
    keys = [key for key in (lower, upper) if key in bar]
    if len(keys) != 1:
        return None
    value = bar[keys[0]]
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def resolve_exit(
    bar: dict,
    *,
    stop: float,
    rank_exit: bool,
    held_sessions: int,
    forced_exit: bool,
) -> tuple[str, float] | None:
    """Resolve the earliest deterministic exit for one OHLC session."""
    if not isinstance(bar, dict) or isinstance(stop, bool):
        return None
    try:
        stop = float(stop)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(stop) or stop <= 0:
        return None
    if not isinstance(held_sessions, int) or isinstance(held_sessions, bool) or held_sessions < 0:
        return None
    if not isinstance(rank_exit, bool) or not isinstance(forced_exit, bool):
        return None

    values = {name: _bar_value(bar, name) for name in ("open", "high", "low", "close")}
    if any(value is None for value in values.values()):
        return None
    open_price = values["open"]
    high = values["high"]
    low = values["low"]
    close = values["close"]
    assert open_price is not None and high is not None and low is not None and close is not None
    if min(open_price, high, low, close) <= 0 or low > min(open_price, close) or high < max(open_price, close):
        return None

    if open_price < stop:
        return ("stop", open_price)
    if forced_exit:
        return ("forced_exit", open_price)
    if rank_exit:
        return ("rank_exit", open_price)
    if held_sessions >= 20:
        return ("max_hold", open_price)
    if low <= stop:
        return ("stop", stop)
    return None
