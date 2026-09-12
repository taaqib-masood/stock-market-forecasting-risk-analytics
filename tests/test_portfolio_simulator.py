import pandas as pd

from src.reliability.portfolio_simulator import simulate_shared_portfolio


def _trade(ticker, confidence, exit_price):
    return {
        "ticker": ticker,
        "signal_date": pd.Timestamp("2024-01-01"),
        "entry_date": pd.Timestamp("2024-01-02"),
        "date": pd.Timestamp("2024-01-04"),
        "entry": 100.0,
        "exit": exit_price,
        "direction": 1,
        "shares": 10,
        "pnl": (exit_price - 100.0) * 10,
        "confidence": confidence,
    }


def test_shared_portfolio_ranks_entries_and_enforces_position_limit():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    prices = pd.DataFrame({"A": [100, 100, 105, 110], "B": [100, 100, 110, 120]}, index=dates)

    result = simulate_shared_portfolio(
        pd.DataFrame([_trade("A", 0.7, 110), _trade("B", 0.9, 120)]),
        prices,
        initial_capital=100_000,
        max_positions=1,
        max_position_fraction=0.5,
    )

    assert result["accepted_trades"]["ticker"].tolist() == ["B"]
    assert result["skipped_entries"] == 1
    assert result["equity"].iloc[0] == 100_000
    assert result["equity"].iloc[-1] == 110_000


def test_shared_portfolio_has_no_pnl_before_next_bar_entry():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    prices = pd.DataFrame({"A": [80, 100, 105, 110]}, index=dates)

    result = simulate_shared_portfolio(
        pd.DataFrame([_trade("A", 1.0, 110)]), prices,
        initial_capital=100_000, max_positions=2, max_position_fraction=0.5,
    )

    assert result["returns"].loc[pd.Timestamp("2024-01-01")] == 0.0
    assert result["equity"].loc[pd.Timestamp("2024-01-02")] == 100_000


def test_shared_portfolio_rejects_invalid_limits():
    dates = pd.date_range("2024-01-01", periods=2)
    try:
        simulate_shared_portfolio(pd.DataFrame(), pd.DataFrame(index=dates), max_positions=0)
    except ValueError as exc:
        assert "max_positions" in str(exc)
    else:
        raise AssertionError("invalid max_positions must fail")
