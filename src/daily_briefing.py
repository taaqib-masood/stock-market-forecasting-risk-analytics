"""
Daily Briefing — runs every morning at 9 AM
============================================
1. Scans NSE for signals
2. Runs earnings guard
3. Generates GTT orders
4. Sends Telegram message
5. Prints to terminal

Cron (add via: crontab -e):
  30 3 * * 1-5  cd ~/stock-market-forecasting-risk-analytics && python -m src.daily_briefing
  # 3:30 UTC = 9:00 AM IST, Mon–Fri

Run manually:
  python -m src.daily_briefing
  python -m src.daily_briefing --capital 50000
"""

import argparse
from datetime import datetime

from src.scanner        import scan
from src.earnings_guard import filter_cards
from src.gtt_generator  import print_gtt
from src.paper_trader   import _load, portfolio_value, trade_stats, auto_scan_and_place
from src.notify         import _send, send_journal_summary

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"
C = "\033[36m"; W = "\033[37m"; DIM = "\033[2m"
BOLD = "\033[1m"; RESET = "\033[0m"
BAR = "━" * 66


def _market_regime() -> tuple[str, str, float]:
    """Returns (regime_str, emoji, nifty_price)."""
    try:
        import yfinance as yf
        import contextlib, io, numpy as np
        with contextlib.redirect_stderr(io.StringIO()):
            df = yf.download("^NSEI", period="60d", interval="1d",
                             progress=False, auto_adjust=True)
        if df.empty:
            return "UNKNOWN", "❓", 0.0
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        c_ = df["Close"].values
        sma20 = np.mean(c_[-20:])
        sma50 = np.mean(c_[-50:]) if len(c_) >= 50 else sma20
        price = float(c_[-1])
        ret1w = (price / c_[-6] - 1) * 100 if len(c_) >= 6 else 0

        if price > sma20 > sma50 and ret1w > 0:
            return "BULL", "🟢", price
        elif price < sma20 < sma50 and ret1w < 0:
            return "BEAR", "🔴", price
        else:
            return "SIDEWAYS", "🟡", price
    except Exception:
        return "UNKNOWN", "❓", 0.0


def _telegram_briefing(cards: list, blocked: list, regime: str,
                        emoji: str, nifty: float, capital: float,
                        state: dict):
    """Build and send the full Telegram morning message."""
    pv    = portfolio_value(state)
    stats = trade_stats(state)
    date  = datetime.now().strftime("%a %d %b %Y")

    lines = [
        f"🌅 <b>MORNING BRIEFING — {date}</b>",
        f"",
        f"Market : {emoji} <b>{regime}</b>  |  Nifty ₹{nifty:,.0f}",
        f"Capital: ₹{capital:,.0f}  |  Portfolio: ₹{pv['total_val']:,.2f} "
        f"({pv['total_pnl_pct']:+.2f}%)",
        f"",
    ]

    if not cards:
        lines += [
            f"🔍 <b>No signals today.</b>",
            f"",
            f"{'⛔ Earnings blocked: ' + ', '.join(c['ticker'] for c in blocked) if blocked else ''}",
            f"",
            f"<i>Patience is a position. Check again tomorrow.</i>",
        ]
    else:
        lines.append(f"🎯 <b>TODAY'S TRADE SETUPS ({len(cards)})</b>")
        lines.append("")
        for i, c in enumerate(cards, 1):
            stop_pct = round((c["stop"] / c["entry"] - 1) * 100, 2)
            tgt_pct  = round((c["target"] / c["entry"] - 1) * 100, 2)
            lines += [
                f"<b>#{i} {c['ticker']}</b>  Score: {c['score']:.0f}/100",
                f"  Entry  : ₹{c['entry']:,.2f}",
                f"  Stop   : ₹{c['stop']:,.2f}  ({stop_pct:+.1f}%)",
                f"  Target : ₹{c['target']:,.2f}  ({tgt_pct:+.1f}%)",
                f"  R:R    : {c['rr']} : 1  |  Shares: {c['shares']}",
                f"  Risk   : ₹{c['risk_rs']:,.0f}  Reward: ₹{c['reward_rs']:,.0f}",
                f"",
            ]

        if blocked:
            lines += [
                f"⛔ Earnings blocked: "
                f"{', '.join(c['ticker'] for c in blocked)}",
                f"",
            ]

        lines += [
            f"📋 <b>Zerodha steps:</b>",
            f"1. Search ticker on Kite → BUY → CNC",
            f"2. Immediately set GTT (OCO) with stop + target",
            f"3. Log trade: <code>python -m src.paper_trader --buy TICKER N PRICE</code>",
        ]

    if stats and stats.get("total", 0) > 0:
        lines += [
            f"",
            f"📊 <b>Your stats</b>: {stats['win_rate']}% win rate  |  "
            f"PF: {stats['profit_factor']}  |  "
            f"P&L: ₹{stats['total_pnl']:+,.2f}",
        ]

    _send("\n".join(lines))


def run(capital: float = 50_000, paper_auto_place: bool = False):
    print(f"\n{BOLD}{C}{BAR}{RESET}")
    print(f"{BOLD}{C}  DAILY BRIEFING — "
          f"{datetime.now().strftime('%a %d %b %Y  %H:%M')}{RESET}")
    print(f"{C}{BAR}{RESET}\n")

    # ── Market regime ─────────────────────────────────────────────────────────
    regime, emoji, nifty = _market_regime()
    regime_col = G if regime == "BULL" else R if regime == "BEAR" else Y
    print(f"  Market Regime : {regime_col}{BOLD}{regime}{RESET}  "
          f"Nifty: ₹{nifty:,.0f}\n")

    # ── Scan ──────────────────────────────────────────────────────────────────
    print(f"  {C}Scanning NSE...{RESET}")
    raw_cards = scan(capital=capital, top_n=5)

    # ── Earnings guard ────────────────────────────────────────────────────────
    print(f"  Checking earnings calendar...")
    safe_cards, blocked = filter_cards(raw_cards, days=5)

    if blocked:
        print(f"\n  {Y}⛔ Earnings-blocked ({len(blocked)}): "
              f"{', '.join(c['ticker'] for c in blocked)}{RESET}")

    # ── Print GTT cards ───────────────────────────────────────────────────────
    if not safe_cards:
        print(f"\n  {Y}No signals pass all filters today.{RESET}")
        print(f"  {DIM}{'Market is bearish — cash is the safest position.' if regime == 'BEAR' else 'Check again tomorrow.'}{RESET}")
    else:
        print(f"\n  {G}{len(safe_cards)} signal(s) found:{RESET}")
        for i, card in enumerate(safe_cards[:3], 1):
            print_gtt(card, i, capital)

    # ── Paper auto-place ──────────────────────────────────────────────────────
    state = _load()
    if paper_auto_place and safe_cards:
        print(f"\n  {C}Auto-placing in paper portfolio...{RESET}")
        auto_scan_and_place(state, top_n=2)

    # ── Portfolio snapshot ────────────────────────────────────────────────────
    pv    = portfolio_value(state)
    stats = trade_stats(state)
    pnl_col = G if pv["total_pnl"] >= 0 else R
    print(f"\n  {BOLD}PORTFOLIO{RESET}  "
          f"₹{pv['total_val']:,.2f}  "
          f"{pnl_col}({pv['total_pnl_pct']:+.2f}%){RESET}  "
          f"Cash: ₹{pv['cash']:,.2f}")

    if stats:
        wr_col = G if stats.get("win_rate", 0) >= 55 else Y
        print(f"  {BOLD}STATS{RESET}      "
              f"Win rate: {wr_col}{stats.get('win_rate', 0)}%{RESET}  "
              f"PF: {stats.get('profit_factor', 0)}  "
              f"Total P&L: {pnl_col}₹{stats.get('total_pnl', 0):+,.2f}{RESET}")

    # ── Telegram ──────────────────────────────────────────────────────────────
    print(f"\n  {C}Sending Telegram briefing...{RESET}")
    _telegram_briefing(safe_cards[:3], blocked, regime, emoji, nifty, capital, state)
    import os
    if os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        print(f"  {G}✓ Telegram sent{RESET}")
    else:
        print(f"  {Y}⚠ Telegram not configured "
              f"(add TELEGRAM_TOKEN + TELEGRAM_CHAT_ID to .env){RESET}")

    print(f"\n{C}{BAR}{RESET}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital",      default=50_000, type=float)
    parser.add_argument("--paper",        action="store_true",
                        help="Auto-place signals in paper portfolio")
    args = parser.parse_args()
    run(capital=args.capital, paper_auto_place=args.paper)
