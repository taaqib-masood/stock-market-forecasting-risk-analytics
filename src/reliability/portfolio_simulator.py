"""Shared-capital portfolio simulation from leak-free per-symbol trade paths."""

from __future__ import annotations

import pandas as pd


def simulate_shared_portfolio(
    trades: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    initial_capital: float = 100_000.0,
    max_positions: int = 10,
    max_position_fraction: float = 0.10,
) -> dict:
    if max_positions < 1:
        raise ValueError("max_positions must be positive")
    if not 0 < max_position_fraction <= 1:
        raise ValueError("max_position_fraction must be in (0, 1]")
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    dates = pd.DatetimeIndex(prices.index).sort_values().unique()
    frame = trades.copy()
    if not frame.empty:
        for column in ("signal_date", "entry_date", "date"):
            frame[column] = pd.to_datetime(frame[column])
        frame = frame.sort_values(
            ["entry_date", "confidence", "ticker"], ascending=[True, False, True]
        )

    cash = float(initial_capital)
    positions: dict[str, dict] = {}
    accepted = []
    skipped = 0
    equity_values = []

    for day in dates:
        for ticker, position in list(positions.items()):
            if position["exit_date"] <= day:
                cash += position["allocation"] * (1.0 + position["trade_return"])
                del positions[ticker]

        entries = frame[frame["entry_date"] == day] if not frame.empty else frame
        for _, trade in entries.iterrows():
            ticker = str(trade["ticker"])
            if ticker in positions or len(positions) >= max_positions:
                skipped += 1
                continue
            marked_equity = cash + sum(
                position["units"] * _price(prices, day, held_ticker, position["entry"])
                for held_ticker, position in positions.items()
            )
            allocation = min(cash, marked_equity * max_position_fraction)
            if allocation <= 0:
                skipped += 1
                continue
            notional = float(trade["entry"]) * float(trade["shares"])
            trade_return = float(trade["pnl"]) / notional if notional else 0.0
            positions[ticker] = {
                "entry": float(trade["entry"]),
                "exit_date": pd.Timestamp(trade["date"]),
                "allocation": allocation,
                "units": allocation / float(trade["entry"]),
                "trade_return": trade_return,
            }
            cash -= allocation
            accepted.append(trade.to_dict())

        equity_values.append(cash + sum(
            position["units"] * _price(prices, day, ticker, position["entry"])
            for ticker, position in positions.items()
        ))

    equity = pd.Series(equity_values, index=dates, name="equity", dtype=float)
    returns = equity.pct_change().fillna(0.0).rename("strategy")
    return {
        "equity": equity,
        "returns": returns,
        "accepted_trades": pd.DataFrame(accepted),
        "skipped_entries": skipped,
    }


def _price(prices: pd.DataFrame, day: pd.Timestamp, ticker: str, fallback: float) -> float:
    if ticker not in prices.columns:
        return fallback
    value = prices.at[day, ticker]
    return fallback if pd.isna(value) else float(value)
