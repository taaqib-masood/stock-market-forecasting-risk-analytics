"""
Live Terminal Dashboard
=======================
Shows real-time price, model signal, risk parameters, and P&L.
Run: python -m src.dashboard --ticker AAPL

Controls:
  q  — quit
  r  — force refresh
  t  — toggle ticker (cycle through watchlist)
"""

import os
import sys
import time
import json
import argparse
import threading
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── Optional dotenv ───────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

REFRESH_SECONDS = 30
WATCHLIST = ["AAPL", "MSFT", "TSLA", "NVDA", "SPY", "QQQ"]

# ── ANSI colours ──────────────────────────────────────────────────────────────
R  = "\033[31m"   # red
G  = "\033[32m"   # green
Y  = "\033[33m"   # yellow
B  = "\033[34m"   # blue
C  = "\033[36m"   # cyan
W  = "\033[37m"   # white
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
CLEAR = "\033[2J\033[H"


# ── Alpaca helpers ────────────────────────────────────────────────────────────

def _alpaca_headers():
    return {
        "APCA-API-KEY-ID":     os.environ.get("ALPACA_API_KEY", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
    }

def _alpaca_get(path: str, base: str = "https://data.alpaca.markets") -> dict:
    req = Request(f"{base}{path}", headers=_alpaca_headers())
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_latest_quote(ticker: str) -> dict:
    """Latest trade price from Alpaca."""
    try:
        data = _alpaca_get(f"/v2/stocks/{ticker}/trades/latest?feed=iex")
        trade = data.get("trade", {})
        return {"price": trade.get("p", 0), "size": trade.get("s", 0),
                "time": trade.get("t", "")[:19].replace("T", " ")}
    except Exception as e:
        return {"price": 0, "size": 0, "time": "", "error": str(e)}

def get_account() -> dict:
    """Paper account equity and P&L from Alpaca."""
    base = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    try:
        return _alpaca_get("/v2/account", base=base)
    except Exception as e:
        return {"error": str(e)}

def get_positions() -> list:
    """Open positions from Alpaca paper account."""
    base = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    try:
        return _alpaca_get("/v2/positions", base=base)
    except Exception:
        return []

def get_recent_orders(limit: int = 5) -> list:
    """Recent orders from Alpaca."""
    base = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    try:
        return _alpaca_get(f"/v2/orders?status=all&limit={limit}&direction=desc", base=base)
    except Exception:
        return []

def get_daily_bars(ticker: str, days: int = 10) -> list:
    """Last N daily bars for mini sparkline."""
    try:
        from datetime import timedelta
        end   = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
        data  = _alpaca_get(f"/v2/stocks/{ticker}/bars?timeframe=1Day&start={start}&end={end}&limit={days}&feed=iex")
        return data.get("bars", [])
    except Exception:
        return []


# ── Signal generation (lightweight, no full pipeline) ─────────────────────────

def quick_signal(ticker: str) -> dict:
    """
    Pull last 60 bars, compute RSI + MACD, return a quick directional signal.
    This is a fast indicator-based signal — not the full ensemble.
    """
    import importlib
    try:
        bars = get_daily_bars(ticker, days=60)
        if len(bars) < 30:
            return {"signal": "WAIT", "confidence": 0.0, "reason": "insufficient data"}

        import numpy as np

        closes = np.array([b["c"] for b in bars])

        # RSI
        delta = np.diff(closes)
        gain  = np.where(delta > 0, delta, 0)
        loss  = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])
        rsi = 100 - (100 / (1 + avg_gain / (avg_loss + 1e-10)))

        # MACD
        def ema(arr, span):
            k = 2 / (span + 1)
            e = arr[0]
            for v in arr[1:]:
                e = v * k + e * (1 - k)
            return e

        macd_line   = ema(closes, 12) - ema(closes, 26)
        signal_line = ema(closes[-9:], 9)
        hist        = macd_line - signal_line

        # Price vs SMA50
        sma50       = np.mean(closes[-50:])
        above_sma50 = closes[-1] > sma50

        # Score
        bullish = sum([
            rsi < 70,
            rsi > 40,
            hist > 0,
            above_sma50,
            closes[-1] > closes[-2],
        ])
        score = bullish / 5.0

        if score >= 0.7:
            signal, color = "BUY  ", G
        elif score <= 0.3:
            signal, color = "SELL ", R
        else:
            signal, color = "WAIT ", Y

        return {
            "signal":     signal,
            "color":      color,
            "confidence": round(score, 2),
            "rsi":        round(rsi, 1),
            "macd_hist":  round(hist, 4),
            "above_sma50": above_sma50,
            "sma50":      round(sma50, 2),
        }
    except Exception as e:
        return {"signal": "ERR  ", "color": R, "confidence": 0, "reason": str(e)}


# ── Sparkline ─────────────────────────────────────────────────────────────────

def sparkline(bars: list, width: int = 20) -> str:
    if not bars:
        return "─" * width
    closes = [b["c"] for b in bars[-width:]]
    lo, hi = min(closes), max(closes)
    blocks = " ▁▂▃▄▅▆▇█"
    if hi == lo:
        return "─" * len(closes)
    chars = []
    for c in closes:
        idx = int((c - lo) / (hi - lo) * (len(blocks) - 1))
        chars.append(blocks[idx])
    trend_color = G if closes[-1] >= closes[0] else R
    return trend_color + "".join(chars) + RESET


# ── Render ────────────────────────────────────────────────────────────────────

def render(ticker: str, state: dict):
    quote    = state.get("quote", {})
    account  = state.get("account", {})
    positions = state.get("positions", [])
    orders   = state.get("orders", [])
    signal   = state.get("signal", {})
    bars     = state.get("bars", [])
    updated  = state.get("updated", "—")

    price    = quote.get("price", 0)
    sig_col  = signal.get("color", W)
    sig_txt  = signal.get("signal", "----")

    equity   = float(account.get("equity",         0))
    cash     = float(account.get("cash",            0))
    pl_day   = float(account.get("unrealized_pl",  0) or 0)
    pl_pct   = float(account.get("unrealized_plpc", 0) or 0) * 100
    pl_col   = G if pl_day >= 0 else R

    width = 58

    print(CLEAR, end="")
    print(f"{BOLD}{C}{'━'*width}{RESET}")
    print(f"{BOLD}{C}  TRADING DASHBOARD  {DIM}powered by Alpaca + ML Ensemble{RESET}")
    print(f"{C}{'━'*width}{RESET}")

    # ── Price block ───────────────────────────────────────────────────────────
    price_col = G if bars and price >= bars[-1]["o"] else R
    print(f"\n  {BOLD}{W}{ticker:<6}{RESET}  "
          f"{price_col}{BOLD}${price:>10.2f}{RESET}  "
          f"{DIM}as of {quote.get('time','—')}{RESET}")
    print(f"  Sparkline (10d): {sparkline(bars)}")

    # ── Signal block ──────────────────────────────────────────────────────────
    conf    = signal.get("confidence", 0)
    rsi     = signal.get("rsi", "—")
    conf_bar = ("█" * int(conf * 10)).ljust(10)

    print(f"\n  {DIM}{'─'*54}{RESET}")
    print(f"  {BOLD}Signal{RESET}      {sig_col}{BOLD}{sig_txt}{RESET}   "
          f"Confidence: {sig_col}{conf_bar} {int(conf*100)}%{RESET}")
    print(f"  RSI(14)     {Y}{rsi}{RESET}   "
          f"MACD Hist: {signal.get('macd_hist','—')}   "
          f"{'↑ Above' if signal.get('above_sma50') else '↓ Below'} SMA50 "
          f"({signal.get('sma50','—')})")

    # ── Account block ─────────────────────────────────────────────────────────
    print(f"\n  {DIM}{'─'*54}{RESET}")
    print(f"  {BOLD}Account (Paper){RESET}")
    print(f"  Equity      {W}${equity:>12,.2f}{RESET}   "
          f"Cash: ${cash:>10,.2f}")
    print(f"  Unrealised  {pl_col}${pl_day:>+12,.2f}  ({pl_pct:>+.2f}%){RESET}")

    # ── Open positions ─────────────────────────────────────────────────────────
    print(f"\n  {DIM}{'─'*54}{RESET}")
    print(f"  {BOLD}Open Positions{RESET}")
    if positions:
        for p in positions[:5]:
            sym   = p.get("symbol", "")
            qty   = p.get("qty", "0")
            side  = p.get("side", "")
            upl   = float(p.get("unrealized_pl", 0))
            upl_c = G if upl >= 0 else R
            avg   = float(p.get("avg_entry_price", 0))
            cur   = float(p.get("current_price", 0))
            print(f"  {W}{sym:<6}{RESET} {qty:>5} {side:<5}  "
                  f"avg ${avg:.2f} → ${cur:.2f}  "
                  f"{upl_c}P&L ${upl:>+.2f}{RESET}")
    else:
        print(f"  {DIM}No open positions{RESET}")

    # ── Recent orders ─────────────────────────────────────────────────────────
    print(f"\n  {DIM}{'─'*54}{RESET}")
    print(f"  {BOLD}Recent Orders{RESET}")
    if orders:
        for o in orders[:4]:
            sym    = o.get("symbol", "")
            side   = o.get("side", "").upper()
            qty    = o.get("qty") or o.get("filled_qty", "—")
            status = o.get("status", "")
            price_ = o.get("filled_avg_price") or o.get("limit_price") or "MKT"
            s_col  = G if side == "BUY" else R
            st_col = G if status == "filled" else Y
            print(f"  {s_col}{side:<5}{RESET} {W}{sym:<6}{RESET} "
                  f"qty {qty:<6} @ ${price_}  "
                  f"{st_col}{status}{RESET}")
    else:
        print(f"  {DIM}No recent orders{RESET}")

    # ── Footer ────────────────────────────────────────────────────────────────
    print(f"\n  {DIM}{'─'*54}{RESET}")
    print(f"  {DIM}Updated: {updated}   Refreshes every {REFRESH_SECONDS}s{RESET}")
    print(f"  {DIM}[q] quit   [r] refresh   [t] next ticker{RESET}")
    print(f"{C}{'━'*width}{RESET}\n")


# ── Data fetch thread ─────────────────────────────────────────────────────────

def fetch_all(ticker: str) -> dict:
    state = {"updated": datetime.now().strftime("%H:%M:%S")}

    # Run fetches concurrently
    results = {}
    def run(key, fn, *args):
        try:
            results[key] = fn(*args)
        except Exception as e:
            results[key] = {"error": str(e)}

    threads = [
        threading.Thread(target=run, args=("quote",     get_latest_quote, ticker)),
        threading.Thread(target=run, args=("account",   get_account)),
        threading.Thread(target=run, args=("positions", get_positions)),
        threading.Thread(target=run, args=("orders",    get_recent_orders, 5)),
        threading.Thread(target=run, args=("signal",    quick_signal, ticker)),
        threading.Thread(target=run, args=("bars",      get_daily_bars, ticker, 20)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=12)

    state.update(results)
    return state


# ── Input thread (non-blocking keypress) ──────────────────────────────────────

_key_queue = []

def _input_thread():
    while True:
        try:
            ch = sys.stdin.read(1)
            _key_queue.append(ch.lower())
        except Exception:
            break

threading.Thread(target=_input_thread, daemon=True).start()


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(ticker: str):
    import tty, termios

    fd = sys.stdin.fileno()
    interactive = sys.stdin.isatty()

    if interactive:
        old_settings = termios.tcgetattr(fd)
        tty.setcbreak(fd)

    watch_idx = WATCHLIST.index(ticker) if ticker in WATCHLIST else 0
    WATCHLIST[0] = ticker

    try:
        print(f"{C}  Loading data for {ticker}...{RESET}")
        state = fetch_all(ticker)
        render(ticker, state)
        last_refresh = time.time()

        if not interactive:
            return  # non-interactive: render once and exit

        while True:
            if _key_queue:
                key = _key_queue.pop(0)
                if key == "q":
                    break
                elif key == "r":
                    state = fetch_all(ticker)
                    render(ticker, state)
                    last_refresh = time.time()
                elif key == "t":
                    watch_idx = (watch_idx + 1) % len(WATCHLIST)
                    ticker = WATCHLIST[watch_idx]
                    print(f"{C}  Switching to {ticker}...{RESET}")
                    state = fetch_all(ticker)
                    render(ticker, state)
                    last_refresh = time.time()

            if time.time() - last_refresh >= REFRESH_SECONDS:
                state = fetch_all(ticker)
                render(ticker, state)
                last_refresh = time.time()

            time.sleep(0.1)

    finally:
        if interactive:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        print(f"\n{RESET}Dashboard closed.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="AAPL", help="Starting ticker")
    args = parser.parse_args()
    run(args.ticker.upper())
