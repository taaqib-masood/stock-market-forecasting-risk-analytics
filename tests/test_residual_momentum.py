import math

import numpy as np
import pandas as pd
import pytest

from src.reliability.residual_momentum import (
    allocate_weights,
    compute_scores,
    initial_stop,
    resolve_exit,
    select_candidates,
)


def _correlated_returns() -> pd.DataFrame:
    base = np.array([(-1) ** i * (i + 1) for i in range(63)], dtype=float)
    return pd.DataFrame(
        {
            "AAA": base,
            "BBB": base * 1.2,
            "CCC": np.roll(base, 1),
        }
    )


def _bars(values: dict[str, float] | None = None) -> dict[str, float]:
    bar = {"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0}
    bar.update(values or {})
    return bar


def test_score_uses_t_minus_252_to_t_minus_21_and_subtracts_tri():
    index = pd.bdate_range("2020-01-01", periods=253)
    closes = pd.DataFrame({"AAA": np.linspace(100, 140, 253)}, index=index)
    tri = pd.Series(np.linspace(1000, 1100, 253), index=index)

    result = compute_scores(closes, tri)

    expected = closes["AAA"].iloc[-22] / closes["AAA"].iloc[0] - 1
    expected -= tri.iloc[-22] / tri.iloc[0] - 1
    assert result["AAA"] == pytest.approx(expected)


def test_scores_reject_nonpositive_interior_benchmark_and_security_history():
    index = pd.bdate_range("2020-01-01", periods=253)
    tri = pd.Series(1000.0, index=index)
    closes = pd.DataFrame({"GOOD": 100.0, "BAD": 100.0}, index=index)
    closes.loc[index[100], "BAD"] = 0.0
    tri.loc[index[100]] = -1.0

    assert compute_scores(closes, tri).empty

    tri.loc[index[100]] = 1000.0
    result = compute_scores(closes, tri)
    assert result.index.tolist() == ["GOOD"]


def test_score_alignment_is_deterministic_for_unsorted_indices():
    index = pd.bdate_range("2020-01-01", periods=253)
    closes = pd.DataFrame({"AAA": np.linspace(100, 140, 253)}, index=index)
    tri = pd.Series(np.linspace(1000, 1100, 253), index=index)

    sorted_result = compute_scores(closes, tri)
    unsorted_result = compute_scores(closes.iloc[::-1], tri.iloc[::-1])

    assert unsorted_result.equals(sorted_result)


def test_scores_fail_closed_for_insufficient_or_nonfinite_inputs():
    closes = pd.DataFrame({"AAA": [100.0] * 252})
    tri = pd.Series([1000.0] * 252)
    assert compute_scores(closes, tri).empty

    closes.loc[0, "AAA"] = np.nan
    assert compute_scores(pd.concat([closes] * 2, ignore_index=True),
                          pd.Series([1000.0] * 504)).empty


def test_selection_breaks_score_ties_by_symbol_and_skips_high_correlation():
    scores = pd.Series({"BBB": 0.2, "AAA": 0.2, "CCC": 0.1})

    assert select_candidates(scores, _correlated_returns(), limit=2) == ["AAA", "CCC"]


def test_selection_allows_exact_correlation_boundary():
    x = np.arange(63, dtype=float) - 31.0
    z = np.arange(63, dtype=float) ** 2
    z -= z.mean()
    z -= x * (np.dot(x, z) / np.dot(x, x))
    z /= np.linalg.norm(z)
    x /= np.linalg.norm(x)
    y = 0.80 * x + 0.60 * z
    returns = pd.DataFrame({"AAA": x, "BBB": y})
    exact_correlation = float(returns["AAA"].corr(returns["BBB"]))

    assert exact_correlation == pytest.approx(0.80)
    assert select_candidates(
        pd.Series({"AAA": 0.2, "BBB": 0.1}),
        returns,
        limit=2,
        max_correlation=exact_correlation,
    ) == ["AAA", "BBB"]


def test_selection_requires_finite_trailing_returns_and_positive_limit():
    returns = _correlated_returns()
    returns.loc[62, "CCC"] = np.nan
    scores = pd.Series({"AAA": 0.2, "CCC": 0.1})

    assert select_candidates(scores, returns) == ["AAA"]
    assert select_candidates(scores, returns, limit=0) == []


def test_inverse_volatility_weights_are_normalized_to_gross_cap():
    values = np.arange(63, dtype=float)
    returns = pd.DataFrame({"AAA": values, "BBB": values * 2.0})

    result = allocate_weights(
        ["AAA", "BBB"],
        returns,
        {"AAA": "A", "BBB": "B"},
        {"AAA": 1.0, "BBB": 1.0},
        gross_cap=0.80,
        security_cap=1.0,
        sector_cap=1.0,
    )

    assert result["AAA"] == pytest.approx(0.80 * 2 / 3)
    assert result["BBB"] == pytest.approx(0.80 / 3)


def test_allocator_applies_security_sector_and_liquidity_caps_without_redistribution():
    returns = pd.DataFrame({symbol: np.arange(63, dtype=float) for symbol in "ABCD"})
    sectors = {symbol: "same" for symbol in "ABCD"}
    liquidity = {symbol: 1.0 for symbol in "ABCD"}
    liquidity["A"] = 0.05

    result = allocate_weights(list("ABCD"), returns, sectors, liquidity)

    assert result.keys() == {"A", "B", "C", "D"}
    assert result["A"] == pytest.approx(0.05)
    assert result["B"] == pytest.approx(0.10)
    assert result["C"] == pytest.approx(0.10)
    assert result["D"] == pytest.approx(0.05)
    assert sum(result.values()) == pytest.approx(0.30)


def test_allocator_enforces_security_and_gross_caps():
    returns = pd.DataFrame({symbol: np.arange(63, dtype=float) for symbol in "ABCDEFGHIJ"})
    sectors = {symbol: symbol for symbol in "ABCDEFGHIJ"}
    liquidity = {symbol: 1.0 for symbol in "ABCDEFGHIJ"}

    result = allocate_weights(list("ABCDEFGHIJ"), returns, sectors, liquidity)

    assert len(result) == 10
    assert all(weight == pytest.approx(0.08) for weight in result.values())
    assert sum(result.values()) == pytest.approx(0.80)


def test_allocator_excludes_zero_volatility_and_unknown_metadata():
    returns = pd.DataFrame(
        {
            "ZERO": [0.0] * 63,
            "GOOD": np.arange(63, dtype=float),
            "UNKNOWN": np.arange(63, dtype=float),
        }
    )

    result = allocate_weights(
        ["ZERO", "GOOD", "UNKNOWN"],
        returns,
        {"ZERO": "A", "GOOD": "A"},
        {"ZERO": 1.0, "GOOD": 1.0},
    )

    assert result == {"GOOD": 0.10}
    assert sum(result.values()) <= 0.80


@pytest.mark.parametrize(
    ("kwargs", "liquidity_caps"),
    [
        ({"gross_cap": np.nan}, {"AAA": 1.0}),
        ({"security_cap": -0.01}, {"AAA": 1.0}),
        ({"sector_cap": "unknown"}, {"AAA": 1.0}),
        ({}, {"AAA": np.inf}),
    ],
)
def test_allocator_rejects_invalid_cap_values(kwargs, liquidity_caps):
    returns = pd.DataFrame({"AAA": np.arange(63, dtype=float)})

    assert allocate_weights(
        ["AAA"],
        returns,
        {"AAA": "A"},
        liquidity_caps,
        **kwargs,
    ) == {}


def test_initial_stop_is_two_point_five_atr_below_entry():
    assert initial_stop(100.0, 4.0) == pytest.approx(90.0)


def test_initial_stop_rejects_nonfinite_or_nonpositive_inputs():
    with pytest.raises(ValueError):
        initial_stop(100.0, 0.0)
    with pytest.raises(ValueError):
        initial_stop(math.inf, 4.0)
    with pytest.raises(ValueError):
        initial_stop(100.0, 40.0)
    with pytest.raises(ValueError):
        initial_stop(100.0, 50.0)


def test_stop_gap_fills_at_open_before_other_exits():
    assert resolve_exit(
        _bars({"open": 94.0, "low": 90.0}),
        stop=95.0,
        rank_exit=True,
        held_sessions=20,
        forced_exit=True,
    ) == ("stop", 94.0)


def test_intraday_stop_fills_at_stop_price():
    assert resolve_exit(
        _bars({"low": 94.0}),
        stop=95.0,
        rank_exit=False,
        held_sessions=0,
        forced_exit=False,
    ) == ("stop", 95.0)


def test_forced_exit_precedes_rank_exit_at_open():
    assert resolve_exit(
        _bars({"low": 96.0}),
        stop=95.0,
        rank_exit=True,
        held_sessions=0,
        forced_exit=True,
    ) == ("forced_exit", 100.0)


def test_rank_exit_and_twentieth_fully_held_session_exit_at_open():
    assert resolve_exit(
        _bars({"low": 96.0}),
        stop=95.0,
        rank_exit=True,
        held_sessions=0,
        forced_exit=False,
    ) == ("rank_exit", 100.0)
    assert resolve_exit(
        _bars({"low": 96.0}),
        stop=95.0,
        rank_exit=False,
        held_sessions=20,
        forced_exit=False,
    ) == ("max_hold", 100.0)
    assert resolve_exit(
        _bars({"low": 96.0}),
        stop=95.0,
        rank_exit=False,
        held_sessions=19,
        forced_exit=False,
    ) is None


@pytest.mark.parametrize(
    ("rank_exit", "forced_exit", "held_sessions", "expected_reason"),
    [
        (False, False, 19, None),
        (False, False, 20, "max_hold"),
        (True, False, 19, "rank_exit"),
        (True, False, 20, "rank_exit"),
        (False, True, 19, "forced_exit"),
        (False, True, 20, "forced_exit"),
        (True, True, 19, "forced_exit"),
        (True, True, 20, "forced_exit"),
    ],
)
def test_same_open_exit_reason_precedence(
    rank_exit, forced_exit, held_sessions, expected_reason
):
    result = resolve_exit(
        _bars({"low": 96.0}),
        stop=95.0,
        rank_exit=rank_exit,
        held_sessions=held_sessions,
        forced_exit=forced_exit,
    )

    if expected_reason is None:
        assert result is None
    else:
        assert result == (expected_reason, 100.0)


@pytest.mark.parametrize(
    ("stop_bar", "expected_reason", "expected_fill"),
    [
        ({"open": 94.0, "low": 90.0}, "stop", 94.0),
        ({"open": 100.0, "low": 94.0}, "rank_exit", 100.0),
    ],
    ids=["gap-stop", "intraday-after-open-exit"],
)
@pytest.mark.parametrize(
    ("rank_exit", "forced_exit", "held_sessions"),
    [
        (False, True, 19),
        (True, False, 19),
        (False, False, 20),
        (True, True, 20),
    ],
    ids=["forced", "rank", "max-hold", "all-open-reasons"],
)
def test_gap_precedes_open_exits_but_intraday_stop_follows_them(
    stop_bar, expected_reason, expected_fill, rank_exit, forced_exit, held_sessions
):
    expected_reason = expected_reason
    if expected_reason == "rank_exit":
        if forced_exit:
            expected_reason = "forced_exit"
        elif not rank_exit and held_sessions >= 20:
            expected_reason = "max_hold"
        elif not rank_exit:
            expected_reason = "stop"
    assert resolve_exit(
        _bars(stop_bar),
        stop=95.0,
        rank_exit=rank_exit,
        held_sessions=held_sessions,
        forced_exit=forced_exit,
    ) == (expected_reason, expected_fill)


def test_exit_rejects_missing_ambiguous_or_nonfinite_ohlc():
    assert resolve_exit(
        {"open": 100.0, "high": 105.0, "low": 95.0},
        stop=95.0,
        rank_exit=False,
        held_sessions=0,
        forced_exit=False,
    ) is None
    assert resolve_exit(
        _bars({"high": 94.0}),
        stop=95.0,
        rank_exit=False,
        held_sessions=0,
        forced_exit=False,
    ) is None
    assert resolve_exit(
        _bars({"low": np.nan}),
        stop=95.0,
        rank_exit=False,
        held_sessions=0,
        forced_exit=False,
    ) is None
    assert resolve_exit(
        {**_bars(), "Open": 100.0},
        stop=95.0,
        rank_exit=False,
        held_sessions=0,
        forced_exit=False,
    ) is None
    assert resolve_exit(
        _bars(),
        stop=0.0,
        rank_exit=True,
        held_sessions=0,
        forced_exit=False,
    ) is None
    assert resolve_exit(
        _bars(),
        stop=-1.0,
        rank_exit=False,
        held_sessions=20,
        forced_exit=False,
    ) is None


def test_rules_do_not_mutate_caller_owned_data():
    index = pd.bdate_range("2020-01-01", periods=253)
    closes = pd.DataFrame({"AAA": np.linspace(100, 140, 253)}, index=index)
    tri = pd.Series(np.linspace(1000, 1100, 253), index=index)
    returns = pd.DataFrame({"AAA": np.arange(63, dtype=float)})
    closes_before = closes.copy(deep=True)
    tri_before = tri.copy(deep=True)
    returns_before = returns.copy(deep=True)

    compute_scores(closes, tri)
    select_candidates(pd.Series({"AAA": 0.2}), returns)
    allocate_weights(["AAA"], returns, {"AAA": "A"}, {"AAA": 1.0})

    pd.testing.assert_frame_equal(closes, closes_before)
    pd.testing.assert_series_equal(tri, tri_before)
    pd.testing.assert_frame_equal(returns, returns_before)
