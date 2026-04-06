"""
Main Trade Dashboard
====================
Scans NSE, ranks signals, shows actionable trade cards + journal.

Run:  python -m src.trade_dashboard
      python -m src.trade_dashboard --capital 80000
      python -m src.trade_dashboard --close 3 --exit 2945.50   (close trade #3)
"""

import os
import sys
import time
import argparse
import threading
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.scanner  import scan, DEFAULT_SCAN
from src.journal  import log_signal, close_trade, load_all, summary as journal_summary
from src.notify   import send_trade_cards, send_journal_summary
from src.watchlist import NIFTY_50

# ── ANSI ──────────────────────────────────────────────────────────────────────
R    = "\033[31m"
G    = "\033[32m"
Y    = "\033[33m"
B    = "\033[34m"
C    = "\033[36m"
W    = "\033[37m"
DIM  = "\033[2m"
BOLD = "\033[1m"
RESET= "\033[0m"
CLEAR= "\033[2J\033[H"

BAR_W = 66


def _bar(pct: float, width: int = 10) -> str:
    filled = int(pct / 100 * width)
    color  = G if pct >= 70 else Y if pct >= 50 else R
    return color + "█" * filled + DIM + "░" * (width - filled) + RESET


def _pct_col(val: float) -> str:
    col = G if val >= 0 else R
    return f"{col}{val:+.2f}%{RESET}"


def _rs_col(val: float) -> str:
    col = G if val >= 0 else R
    return f"{col}₹{val:+,.0f}{RESET}"


def render_header(capital: float, scan_time: str):
    now = datetime.now().strftime("%a %d %b %Y  %H:%M")
    print(CLEAR, end="")
    print(f"{BOLD}{C}{'━'*BAR_W}{RESET}")
    print(f"{BOLD}{C}  NSE TRADE INTELLIGENCE  {DIM}Capital: ₹{capital:,.0f}{RESET}")
    print(f"{DIM}  {now}   Last scan: {scan_time}{RESET}")
    print(f"{C}{'━'*BAR_W}{RESET}")


def render_market_regime():
    """Simple regime indicator based on Nifty 50 index."""
    try:
        import yfinance as yf
        df = yf.download("^NSEI", period="60d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        closes = df["Close"].values
        sma20  = float(closes[-20:].mean())
        sma50  = float(closes[-50:].mean()) if len(closes) >= 50 else sma20
        price  = float(closes[-1])
        ret1w  = (price / closes[-6] - 1) * 100 if len(closes) >= 6 else 0

        if price > sma20 > sma50 and ret1w > 0:
            regime, col = "BULL  ▲", G
        elif price < sma20 < sma50 and ret1w < 0:
            regime, col = "BEAR  ▼", R
        else:
            regime, col = "SIDEW ▶", Y

        print(f"\n  Market Regime  {col}{BOLD}{regime}{RESET}  "
              f"Nifty: ₹{price:,.0f}  "
              f"1W: {_pct_col(ret1w)}  "
              f"SMA20: ₹{sma20:,.0f}")
    except Exception:
        print(f"\n  {DIM}Market regime unavailable{RESET}")


def render_trade_cards(cards: list[dict], capital: float):
    if not cards:
        print(f"\n  {Y}No high-conviction setups today.{RESET}")
        print(f"  {DIM}Criteria: score ≥ 70, R:R ≥ 2.0, BUY signal only.{RESET}")
        print(f"  {DIM}Patience is a position.{RESET}\n")
        return

    print(f"\n  {BOLD}TOP {len(cards)} TRADE SETUPS  {DIM}(ranked by signal score){RESET}\n")

    for i, c in enumerate(cards, 1):
        sig_col   = G if c["signal"] == "BUY" else R
        stop_pct  = round((c["stop"]  / c["entry"] - 1) * 100, 2)
        tgt_pct   = round((c["target"]/ c["entry"] - 1) * 100, 2)
        cap_used  = round(c["invest"] / capital * 100, 1)

        print(f"  {BOLD}#{i}  {W}{c['ticker']:<14}{RESET}"
              f"Score: {_bar(c['score'])} {c['score']:.0f}/100  "
              f"{sig_col}{BOLD}{c['signal']}{RESET}")

        print(f"  {'─'*62}")

        print(f"  {'Entry':<10} {W}₹{c['entry']:>9,.2f}{RESET}   "
              f"{'Shares':<10} {W}{c['shares']}{RESET}")

        print(f"  {'Stop':<10} {R}₹{c['stop']:>9,.2f}{RESET}  "
              f"{_pct_col(stop_pct)}   "
              f"{'Invest':<10} {W}₹{c['invest']:>8,.0f}  ({cap_used}% capital){RESET}")

        print(f"  {'Target':<10} {G}₹{c['target']:>9,.2f}{RESET}  "
              f"{_pct_col(tgt_pct)}   "
              f"{'Risk':<10} {R}₹{c['risk_rs']:>7,.0f}{RESET}")

        print(f"  {'R:R':<10} {G}{c['rr']} : 1{RESET}          "
              f"  {'Reward':<10} {G}₹{c['reward_rs']:>7,.0f}{RESET}")

        print(f"  {'RSI(14)':<10} {Y}{c['rsi']}{RESET}           "
              f"  {'Vol surge':<10} {C}{c['vol_surge']}x{RESET}")

        print(f"  {'5d return':<10} {_pct_col(c['ret_5d'])}")

        # Criteria met
        met = [k.replace("_", " ") for k, v in c["criteria"].items() if v]
        print(f"  {DIM}✓ {', '.join(met)}{RESET}")
        print()

    print(f"  {DIM}HOW TO PLACE ON ZERODHA:{RESET}")
    print(f"  {DIM}1. Open Kite app / kite.zerodha.com{RESET}")
    print(f"  {DIM}2. Search ticker → BUY → CNC (delivery) → Market/Limit order{RESET}")
    print(f"  {DIM}3. After entry: set GTT order (stop-loss + target) immediately{RESET}\n")


def render_open_trades():
    """Show all currently open (not yet closed) journal entries."""
    open_trades = [r for r in load_all() if r["outcome"] == "OPEN"]
    print(f"  {BOLD}OPEN POSITIONS  {DIM}({len(open_trades)} trades){RESET}")

    if not open_trades:
        print(f"  {DIM}No open positions tracked.{RESET}\n")
        return

    print(f"  {'#':<4} {'Ticker':<10} {'Signal':<6} {'Entry':>8} "
          f"{'Stop':>8} {'Target':>8} {'Shares':>6} {'Date':<18}")
    print(f"  {'─'*72}")

    for row in open_trades:
        print(f"  {row['id']:<4} {row['ticker']:<10} {row['signal']:<6} "
              f"₹{float(row['entry']):>7,.2f} "
              f"₹{float(row['stop']):>7,.2f} "
              f"₹{float(row['target']):>7,.2f} "
              f"{row['shares']:>6} "
              f"{row['date_signaled'][:16]}")
    print()


def render_journal_summary():
    s = journal_summary()
    print(f"  {BOLD}TRADE JOURNAL SUMMARY{RESET}")
    if s.get("trades", 0) == 0:
        print(f"  {DIM}No closed trades yet. Start tracking to build your stats.{RESET}\n")
        return

    wr_col = G if s["win_rate"] >= 55 else Y if s["win_rate"] >= 45 else R
    pf_col = G if s["profit_factor"] >= 1.5 else Y if s["profit_factor"] >= 1.0 else R

    print(f"  Closed: {s['trades']}   "
          f"Open: {s.get('open', 0)}   "
          f"Win Rate: {wr_col}{s['win_rate']}%{RESET}   "
          f"Profit Factor: {pf_col}{s['profit_factor']}{RESET}")
    print(f"  Total P&L: {_rs_col(s['total_pnl'])}   "
          f"Avg Win: {_rs_col(s['avg_win'])}   "
          f"Avg Loss: {_rs_col(s['avg_loss'])}\n")


def render_footer(last_scan_cards: list):
    print(f"  {C}{'─'*62}{RESET}")
    print(f"  {DIM}Commands:{RESET}")
    print(f"  {DIM}  [s] rescan   [l] log signal #N   [c] close trade   [q] quit{RESET}")
    if last_scan_cards:
        for i, card in enumerate(last_scan_cards, 1):
            print(f"  {DIM}  → log {i}: python -m src.trade_dashboard --log {i}{RESET}")
    print(f"  {C}{'━'*BAR_W}{RESET}\n")


def full_render(cards: list, capital: float, scan_time: str):
    render_header(capital, scan_time)
    render_market_regime()
    print(f"\n  {C}{'─'*62}{RESET}")
    render_trade_cards(cards, capital)
    print(f"  {C}{'─'*62}{RESET}")
    render_open_trades()
    print(f"  {C}{'─'*62}{RESET}")
    render_journal_summary()
    render_footer(cards)


def run(capital: float = 100_000, auto_notify: bool = False):
    import tty, termios
    fd = sys.stdin.fileno()
    interactive = sys.stdin.isatty()

    if interactive:
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)

    cards = []
    scan_time = "—"
    _key_buf = []

    def _input_thread():
        while True:
            try:
                _key_buf.append(sys.stdin.read(1).lower())
            except Exception:
                break

    if interactive:
        threading.Thread(target=_input_thread, daemon=True).start()

    try:
        print(f"\n{C}  Scanning NSE top {len(DEFAULT_SCAN)} stocks...{RESET}")
        cards = scan(capital=capital, top_n=3)
        scan_time = datetime.now().strftime("%H:%M:%S")
        full_render(cards, capital, scan_time)

        if auto_notify:
            date_str = datetime.now().strftime("%a %d %b")
            ok = send_trade_cards(cards, date_str)
            if ok:
                print(f"  {G}✓ Telegram notification sent{RESET}\n")

        if not interactive:
            return cards

        while True:
            if _key_buf:
                key = _key_buf.pop(0)
                if key == "q":
                    break
                elif key == "s":
                    print(f"\n{C}  Re-scanning...{RESET}")
                    cards = scan(capital=capital, top_n=3)
                    scan_time = datetime.now().strftime("%H:%M:%S")
                    full_render(cards, capital, scan_time)
            time.sleep(0.1)

    finally:
        if interactive:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print(f"{RESET}")

    return cards


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital",  default=100_000, type=float,
                        help="Your trading capital in ₹")
    parser.add_argument("--notify",   action="store_true",
                        help="Send Telegram notification after scan")
    parser.add_argument("--log",      type=int, default=None,
                        help="Log signal #N from last scan to journal")
    parser.add_argument("--close",    type=int, default=None,
                        help="Close journal trade by ID")
    parser.add_argument("--exit",     type=float, default=None,
                        help="Exit price when closing a trade")
    args = parser.parse_args()

    if args.close and args.exit:
        close_trade(args.close, args.exit)
        print(f"{G}✓ Trade #{args.close} closed at ₹{args.exit}{RESET}")
        s = journal_summary()
        print(f"  Updated P&L: ₹{s['total_pnl']:+,.2f}  |  "
              f"Win rate: {s['win_rate']}%  |  "
              f"Profit factor: {s['profit_factor']}")
    else:
        cards = run(capital=args.capital, auto_notify=args.notify)

        if args.log and cards and 1 <= args.log <= len(cards):
            card = cards[args.log - 1]
            row  = log_signal(card)
            print(f"{G}✓ Logged: {card['ticker']} BUY @ ₹{card['entry']} "
                  f"(Journal ID: {row['id']}){RESET}")
