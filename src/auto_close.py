"""
Auto Stop-Loss & Target Checker
=================================
Run every evening at 3:45 PM (before NSE closes at 3:30 PM).
Checks all open paper positions against live prices.
Auto-closes any position that hit its stop or target during the day.
Sends Telegram notification with outcome.

Cron (add via: crontab -e):
  15 10 * * 1-5  cd ~/stock-market-forecasting-risk-analytics && python -m src.auto_close
  # Runs Mon–Fri at 3:45 PM IST (10:15 UTC)

Run manually:
  python -m src.auto_close
  python -m src.auto_close --dry-run   (shows what would close, doesn't actually close)
"""

import argparse
import sys
from datetime import datetime

from src.paper_trader import _load, _save, live_prices, sell, portfolio_value, trade_stats
from src.notify import _send

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"
C = "\033[36m"; W = "\033[37m"; DIM = "\033[2m"
BOLD = "\033[1m"; RESET = "\033[0m"


def check_and_close(dry_run: bool = False) -> list[dict]:
    """
    Fetch live prices for all open positions.
    Close any that hit stop or target.
    Returns list of closed trade results.
    """
    state     = _load()
    positions = state["positions"]

    if not positions:
        print(f"  {DIM}No open positions to check.{RESET}")
        return []

    tickers = list(positions.keys())
    prices  = live_prices(tickers)
    closed  = []
    now     = datetime.now().strftime("%H:%M")

    print(f"\n{BOLD}{C}  AUTO CLOSE — {datetime.now().strftime('%a %d %b %Y  %H:%M')}{RESET}\n")
    print(f"  {'Ticker':<12} {'Shares':>6} {'Entry':>8} "
          f"{'Current':>9} {'Stop':>8} {'Target':>9} {'Status'}")
    print(f"  {'─'*68}")

    for ticker, pos in list(positions.items()):
        price  = prices.get(ticker, 0)
        entry  = pos["avg_entry"]
        stop   = pos.get("stop")
        target = pos.get("target")
        shares = pos["shares"]

        if price <= 0:
            print(f"  {W}{ticker:<12}{RESET} {shares:>6} "
                  f"₹{entry:>7,.2f}  {'N/A':>8}  — price unavailable")
            continue

        hit_stop   = stop   and price <= stop
        hit_target = target and price >= target

        stop_str   = f"₹{stop:,.2f}"   if stop   else "  none "
        target_str = f"₹{target:,.2f}" if target else "  none "

        if hit_stop:
            status_str = f"{R}⛔ STOP HIT{RESET}"
        elif hit_target:
            status_str = f"{G}🎯 TARGET HIT{RESET}"
        else:
            unreal = (price - entry) * shares
            col    = G if unreal >= 0 else R
            status_str = f"{col}Open  ₹{unreal:+,.0f}{RESET}"

        print(f"  {W}{ticker:<12}{RESET} {shares:>6} "
              f"₹{entry:>7,.2f} ₹{price:>8,.2f} "
              f"{stop_str:>9} {target_str:>9}  {status_str}")

        if (hit_stop or hit_target) and not dry_run:
            result = sell(ticker, shares=shares, price=price, state=state)
            if result["ok"]:
                result["reason"] = "stop" if hit_stop else "target"
                closed.append(result)

    if dry_run and (any(
        (pos.get("stop") and prices.get(t, 0) <= pos["stop"]) or
        (pos.get("target") and prices.get(t, 0) >= pos["target"])
        for t, pos in positions.items()
    )):
        print(f"\n  {Y}[DRY RUN] Above positions would be closed.{RESET}")

    return closed


def _telegram_summary(closed: list[dict], state: dict):
    """Send Telegram message with close outcomes + portfolio update."""
    if not closed:
        return

    pv    = portfolio_value(state)
    stats = trade_stats(state)
    now   = datetime.now().strftime("%a %d %b  %H:%M")

    lines = [f"🔔 <b>Auto-Close Report — {now}</b>\n"]

    for t in closed:
        icon = "✅" if t["pnl"] > 0 else "❌"
        lines.append(
            f"{icon} <b>{t['ticker']}</b> closed — {t['reason'].upper()}\n"
            f"   Entry ₹{t['entry']:,.2f} → Exit ₹{t['exit']:,.2f}\n"
            f"   P&L: ₹{t['pnl']:+,.2f} ({t['pnl_pct']:+.1f}%)\n"
        )

    lines.append(
        f"\n📊 <b>Portfolio</b>\n"
        f"Value : ₹{pv['total_val']:,.2f}  "
        f"({pv['total_pnl_pct']:+.2f}%)\n"
        f"Cash  : ₹{pv['cash']:,.2f}"
    )

    if stats:
        lines.append(
            f"\n🏆 Overall: {stats['win_rate']}% win rate  |  "
            f"PF: {stats['profit_factor']}  |  "
            f"Total P&L: ₹{stats['total_pnl']:+,.2f}"
        )

    _send("\n".join(lines))


def run(dry_run: bool = False):
    closed = check_and_close(dry_run=dry_run)
    state  = _load()

    if not closed:
        print(f"\n  {DIM}No positions closed today.{RESET}")
    else:
        print(f"\n  {BOLD}CLOSED {len(closed)} POSITION(S){RESET}")
        total_pnl = sum(t["pnl"] for t in closed)
        col = G if total_pnl >= 0 else R
        for t in closed:
            p_col = G if t["pnl"] > 0 else R
            print(f"  {W}{t['ticker']:<12}{RESET} "
                  f"{t['reason'].upper():<8}  "
                  f"{p_col}₹{t['pnl']:>+8,.2f}  ({t['pnl_pct']:>+5.1f}%){RESET}")
        print(f"\n  Session P&L: {col}₹{total_pnl:+,.2f}{RESET}")

        if not dry_run:
            _telegram_summary(closed, state)
            pv = portfolio_value(state)
            print(f"  Portfolio: ₹{pv['total_val']:,.2f}  "
                  f"({pv['total_pnl_pct']:+.2f}% total)\n")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would close without actually closing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
