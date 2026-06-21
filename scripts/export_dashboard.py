"""
Export live dashboard data → dashboard_data.js  (the demo-boro.html data feed).

Mirrors the halal_data.js pattern: dumps a single `window.DASH = {...}` blob the
static dashboard reads with no backend. Each section degrades independently — a
no-network run still writes a valid file (empty/last-known sections), so the UI
never breaks.

Run from repo root (venv active):
    python -m scripts.export_dashboard --capital 50000

Sections:
    signals    scanner.scan()  → ranked BUY trade cards + regime + sectors + GTT legs
    portfolio  paper_trader     → marked-to-market open positions, P&L, drawdown
    equity     latest results/<ts>/<TICKER>_trade_log.csv → backtest equity curve
"""
from __future__ import annotations
import argparse, glob, json, os
from datetime import datetime
from pathlib import Path

OUT = Path("dashboard_data.js")


def _signals(capital: float) -> dict:
    """Run the live scanner and shape cards + GTT legs for the dashboard."""
    try:
        from src.scanner import scan
    except Exception as e:
        return {"error": f"scanner import failed: {e}", "cards": []}
    try:
        res = scan(capital=capital, top_n=8)
    except Exception as e:
        return {"error": f"scan failed (offline?): {e}", "cards": []}

    def card_out(c: dict) -> dict:
        entry, stop, target = c["entry"], c["stop"], c["target"]
        return {
            **{k: c.get(k) for k in (
                "ticker", "signal", "score", "price", "entry", "stop", "target",
                "rr", "shares", "invest", "risk_rs", "reward_rs", "rsi",
                "vol_surge", "ret_5d", "criteria")},
            # GTT OCO legs (same convention as gtt_generator)
            "stop_trigger":   round(stop * 1.005, 2),
            "target_trigger": round(target * 0.995, 2),
            "cap_pct":        round(c["invest"] / capital * 100, 1) if capital else 0,
        }

    return {
        "cards":       [card_out(c) for c in res.get("cards", [])],
        "blocked":     [c.get("ticker") for c in res.get("blocked", [])],
        "near_misses": [card_out(c) for c in res.get("near_misses", [])],
        "regime":      res.get("regime", {}),
        "sectors":     res.get("sectors", []),
        "capital":     capital,
    }


def _portfolio() -> dict:
    """Mark the paper portfolio to market."""
    try:
        from src import paper_trader as pt
        state = pt._load()
        pv = pt.portfolio_value(state)
        stats = pt.trade_stats(state) if hasattr(pt, "trade_stats") else {}
        return {**pv, "stats": stats, "trades": state.get("trades", [])[-10:]}
    except Exception as e:
        return {"error": f"portfolio unavailable: {e}", "marked": {}}


def _equity() -> dict:
    """Pull the most recent backtest equity curve from results/."""
    try:
        logs = sorted(glob.glob("results/**/*_trade_log.csv", recursive=True),
                      key=os.path.getmtime, reverse=True)
        if not logs:
            return {"curve": [], "note": "no backtest runs yet — run src.pipeline"}
        import csv
        path = logs[0]
        ticker = Path(path).name.replace("_trade_log.csv", "")
        curve = []
        with open(path) as f:
            for row in csv.DictReader(f):
                if row.get("equity"):
                    curve.append(round(float(row["equity"]), 2))
        return {"ticker": ticker, "curve": curve, "source": path,
                "asof": datetime.fromtimestamp(os.path.getmtime(path)).isoformat()}
    except Exception as e:
        return {"curve": [], "error": str(e)}


_TECH_TICKERS = ["RELIANCE", "TCS", "INFY", "HINDUNILVR", "HCLTECH",
                 "MARUTI", "LT", "ULTRACEMCO", "NESTLEIND", "GRASIM"]


def _technicals(tickers=None):
    """Per-ticker indicators for the Technical drill-down (real bars → scanner._score)."""
    try:
        import contextlib, io
        import yfinance as yf
        from src.scanner import _score
        from src.watchlist import nse
    except Exception as e:
        return {"data": {}, "error": str(e)}
    tickers = tickers or _TECH_TICKERS

    def one(t):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                df = yf.download(nse(t), period="1y", interval="1d",
                                 progress=False, auto_adjust=True)
            if df.empty or len(df) < 60:
                return t, None
            c = df["Close"].astype(float).values.flatten().tolist()
            h = df["High"].astype(float).values.flatten().tolist()
            l = df["Low"].astype(float).values.flatten().tolist()
            v = df["Volume"].astype(float).values.flatten().tolist()
            s = _score(c, h, l, v)
            return t, {
                "price": s["price"], "rsi": s["rsi"], "macd_hist": s["macd_hist"],
                "bb_pctb": s["bb_pctb"], "sma20": s["sma20"], "sma50": s["sma50"],
                "atr": s["atr"], "vol_surge": s["vol_surge"], "ret_5d": s["ret_5d"],
                "score": s["score"], "signal": s["signal"],
                "hi20": round(max(h[-20:]), 2), "lo20": round(min(l[-20:]), 2),
                "closes": [round(x, 2) for x in c[-60:]],
            }
        except Exception:
            return t, None

    from concurrent.futures import ThreadPoolExecutor
    out = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for t, r in pool.map(one, tickers):
            if r:
                out[t] = r
    return {"data": out, "asof": datetime.now().isoformat(timespec="seconds")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=50_000)
    args = ap.parse_args()

    blob = {
        "asof":      datetime.now().isoformat(timespec="seconds"),
        "signals":   _signals(args.capital),
        "portfolio": _portfolio(),
        "equity":    _equity(),
        "technicals": _technicals(),
    }
    OUT.write_text(
        "// Auto-generated by scripts/export_dashboard.py — live dashboard feed.\n"
        "// demo-boro.html reads window.DASH. Re-run after a scan / paper trade / backtest.\n"
        "window.DASH = " + json.dumps(blob, indent=2, default=str) + ";\n",
        encoding="utf-8")
    n = len(blob["signals"].get("cards", []))
    print(f"Wrote {OUT}  | {n} signal cards | portfolio "
          f"{'ok' if 'error' not in blob['portfolio'] else 'EMPTY'} | "
          f"equity points: {len(blob['equity'].get('curve', []))}")


if __name__ == "__main__":
    main()
