"""
Trade Journal — auto-tracks every signal and outcome.
Stored as a simple CSV: results/journal.csv
"""

import csv
import os
from datetime import datetime
from pathlib import Path

JOURNAL_PATH = Path("results/journal.csv")

FIELDS = [
    "id", "date_signaled", "ticker", "signal", "score",
    "entry", "stop", "target", "rr", "shares", "invest",
    "risk_rs", "reward_rs",
    "date_closed", "exit_price", "pnl", "outcome",  # filled when closed
    "notes",
]


def _next_id() -> int:
    rows = load_all()
    if not rows:
        return 1
    return max(int(r["id"]) for r in rows) + 1


def load_all() -> list[dict]:
    if not JOURNAL_PATH.exists():
        return []
    with open(JOURNAL_PATH, newline="") as f:
        return list(csv.DictReader(f))


def log_signal(card: dict, notes: str = "") -> dict:
    """Log a new trade signal. Returns the journal row."""
    JOURNAL_PATH.parent.mkdir(exist_ok=True)
    write_header = not JOURNAL_PATH.exists()

    row = {
        "id":            _next_id(),
        "date_signaled": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ticker":        card["ticker"],
        "signal":        card["signal"],
        "score":         card["score"],
        "entry":         card["entry"],
        "stop":          card["stop"],
        "target":        card["target"],
        "rr":            card["rr"],
        "shares":        card["shares"],
        "invest":        card["invest"],
        "risk_rs":       card["risk_rs"],
        "reward_rs":     card["reward_rs"],
        "date_closed":   "",
        "exit_price":    "",
        "pnl":           "",
        "outcome":       "OPEN",
        "notes":         notes,
    }

    with open(JOURNAL_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    return row


def close_trade(trade_id: int, exit_price: float, notes: str = ""):
    """Mark a trade as closed and calculate P&L."""
    rows = load_all()
    updated = []
    for row in rows:
        if int(row["id"]) == trade_id and row["outcome"] == "OPEN":
            shares    = int(row["shares"])
            entry     = float(row["entry"])
            direction = 1 if row["signal"] == "BUY" else -1
            pnl       = round((exit_price - entry) * shares * direction, 2)
            outcome   = "WIN" if pnl > 0 else "LOSS"
            row.update({
                "date_closed": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "exit_price":  exit_price,
                "pnl":         pnl,
                "outcome":     outcome,
                "notes":       notes or row["notes"],
            })
        updated.append(row)

    with open(JOURNAL_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(updated)


def summary() -> dict:
    """Return win rate, profit factor, total P&L for closed trades."""
    closed = [r for r in load_all() if r["outcome"] in ("WIN", "LOSS")]
    if not closed:
        return {"trades": 0}

    wins   = [float(r["pnl"]) for r in closed if r["outcome"] == "WIN"]
    losses = [float(r["pnl"]) for r in closed if r["outcome"] == "LOSS"]
    pnls   = [float(r["pnl"]) for r in closed]

    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))

    return {
        "trades":        len(closed),
        "open":          len([r for r in load_all() if r["outcome"] == "OPEN"]),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(closed) * 100, 1),
        "total_pnl":     round(sum(pnls), 2),
        "avg_win":       round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss":      round(sum(losses) / len(losses), 2) if losses else 0,
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else float("inf"),
        "best_trade":    round(max(pnls), 2),
        "worst_trade":   round(min(pnls), 2),
    }
