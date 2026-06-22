"""
Run a src.pipeline backtest for one ticker and append the result to the
dashboard's backtest history (data/backtest_history.json -> backtest_data.js).

Triggered by the dashboard's "Run Backtest" button via the research-backtest
GitHub Actions job — but also runnable directly:
    python -m scripts.export_backtest --ticker RELIANCE --years 5
"""
import argparse
import datetime
import json
import re
from pathlib import Path

from src.pipeline import run, monte_carlo_backtest
from src.metrics import summarise

HISTORY_PATH = Path("data/backtest_history.json")
JS_PATH = Path("backtest_data.js")
TICKER_RE = re.compile(r"^[A-Za-z0-9.&-]{1,15}$")
MAX_HISTORY = 100


def load_history() -> list:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text())
    return []


def save_history(history: list) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))
    JS_PATH.write_text("window.BACKTEST_HISTORY = " + json.dumps(history, indent=2) + ";\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--capital", type=float, default=100_000)
    parser.add_argument("--threshold", type=float, default=0.62)
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()
    if not TICKER_RE.match(ticker):
        raise SystemExit(f"Invalid ticker: {args.ticker!r}")
    years = max(1, min(args.years, 15))

    entry = {
        "ticker": ticker,
        "years": years,
        "capital": args.capital,
        "threshold": args.threshold,
        "run_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

    try:
        trade_log = run(ticker=ticker, years=years, capital=args.capital,
                         confidence_threshold=args.threshold)
    except Exception as e:
        entry["status"] = "error"
        entry["error"] = str(e)[:300]
        history = load_history()
        history.append(entry)
        save_history(history[-MAX_HISTORY:])
        raise

    if trade_log.empty:
        entry["status"] = "no_trades"
    else:
        trade_returns = trade_log["pnl"] / args.capital
        summary = summarise(trade_returns, label=ticker)
        mc = monte_carlo_backtest(trade_returns.values, capital=args.capital,
                                   n_simulations=1000, out_dir=None)
        entry["status"] = "ok"
        entry["metrics"] = summary
        entry["monte_carlo"] = {k: v for k, v in mc.items() if k != "plain_english"} if "error" not in mc else mc
        entry["equity_curve"] = trade_log["equity"].round(2).tolist()

    history = load_history()
    history.append(entry)
    save_history(history[-MAX_HISTORY:])
    print(f"Backtest history updated: {len(history)} run(s) total — latest: {ticker} ({entry['status']})")


if __name__ == "__main__":
    main()
