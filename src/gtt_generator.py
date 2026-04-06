"""
Zerodha GTT Order Generator
============================
Converts scanner trade cards into exact GTT (Good Till Triggered)
order instructions for Zerodha Kite.

GTT = set-and-forget order. You place it once, Zerodha automatically
triggers the stop-loss OR target whenever price hits either level.
No need to watch the screen all day.

Run:
    python -m src.gtt_generator              → scan + print GTT cards
    python -m src.gtt_generator --capital 50000
"""

import argparse
from datetime import datetime

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"
C = "\033[36m"; W = "\033[37m"; DIM = "\033[2m"
BOLD = "\033[1m"; RESET = "\033[0m"
BAR = "━" * 66


def _pct(a: float, b: float) -> str:
    p = (b / a - 1) * 100
    col = G if p >= 0 else R
    return f"{col}{p:+.2f}%{RESET}"


def print_gtt(card: dict, rank: int, capital: float):
    """Print a single GTT order card."""
    entry  = card["entry"]
    stop   = card["stop"]
    target = card["target"]
    shares = card["shares"]

    # Zerodha GTT requires a trigger price slightly away from limit
    # Convention: trigger = limit ± 0.5% buffer
    stop_trigger   = round(stop   * 1.005, 2)   # trigger slightly above stop (for sell)
    target_trigger = round(target * 0.995, 2)   # trigger slightly below target (for sell)

    invest   = round(entry  * shares, 2)
    risk_rs  = round((entry - stop)   * shares, 2)
    reward_rs= round((target - entry) * shares, 2)
    cap_pct  = round(invest / capital * 100, 1)

    print(f"\n  {BOLD}{C}#{rank}  {W}{card['ticker']}{RESET}  "
          f"Score: {card['score']:.0f}/100  "
          f"RSI: {card['rsi']}  Vol surge: {card['vol_surge']}x")
    print(f"  {C}{'─'*62}{RESET}")

    # ── Step 1: Buy order ─────────────────────────────────────────────────────
    print(f"\n  {BOLD}STEP 1 — PLACE BUY ORDER{RESET}")
    print(f"  {'Exchange':<18} NSE")
    print(f"  {'Stock':<18} {W}{card['ticker']}{RESET}")
    print(f"  {'Order Type':<18} CNC  {DIM}(delivery — holds overnight){RESET}")
    print(f"  {'Qty':<18} {BOLD}{shares} shares{RESET}")
    print(f"  {'Price':<18} ₹{entry:,.2f}  {DIM}(limit order){RESET}")
    print(f"  {'Total invest':<18} ₹{invest:,.0f}  {DIM}({cap_pct}% of capital){RESET}")

    # ── Step 2: GTT OCO ───────────────────────────────────────────────────────
    print(f"\n  {BOLD}STEP 2 — SET GTT (OCO) IMMEDIATELY AFTER BUY{RESET}")
    print(f"  {DIM}Kite → GTT → Two-leg OCO (one cancels other){RESET}\n")

    print(f"  {R}STOP-LOSS LEG{RESET}")
    print(f"    Trigger price  ₹{stop_trigger:,.2f}  "
          f"{DIM}(when price falls here, order fires){RESET}")
    print(f"    Limit price    ₹{stop:,.2f}  {_pct(entry, stop)}")
    print(f"    Qty            {shares} shares")
    print(f"    Max loss       {R}₹{risk_rs:,.0f}{RESET}")

    print(f"\n  {G}TARGET LEG{RESET}")
    print(f"    Trigger price  ₹{target_trigger:,.2f}  "
          f"{DIM}(when price rises here, order fires){RESET}")
    print(f"    Limit price    ₹{target:,.2f}  {_pct(entry, target)}")
    print(f"    Qty            {shares} shares")
    print(f"    Max gain       {G}₹{reward_rs:,.0f}{RESET}")

    print(f"\n  {BOLD}SUMMARY{RESET}")
    print(f"  {'R:R Ratio':<18} {G}{card['rr']} : 1{RESET}")
    print(f"  {'Risk':<18} {R}₹{risk_rs:,.0f}{RESET}  →  "
          f"Reward: {G}₹{reward_rs:,.0f}{RESET}")
    print(f"  {'Capital used':<18} ₹{invest:,.0f} of ₹{capital:,.0f} ({cap_pct}%)")

    # ── Kite path ─────────────────────────────────────────────────────────────
    print(f"\n  {DIM}HOW TO DO IT ON ZERODHA KITE:{RESET}")
    print(f"  {DIM}1. kite.zerodha.com → search '{card['ticker']}'{RESET}")
    print(f"  {DIM}2. Click BUY → CNC → Qty: {shares} → Price: {entry:.2f} → PLACE{RESET}")
    print(f"  {DIM}3. After order fills → GTT → New GTT → OCO{RESET}")
    print(f"  {DIM}4. Paste stop trigger: {stop_trigger} / limit: {stop:.2f}{RESET}")
    print(f"  {DIM}5. Paste target trigger: {target_trigger} / limit: {target:.2f}{RESET}")
    print(f"  {DIM}6. GTT stays active until one leg triggers — done.{RESET}")


def generate(capital: float = 50_000):
    from src.scanner import scan
    from src.earnings_guard import filter_cards

    print(f"\n{BOLD}{C}{BAR}{RESET}")
    print(f"{BOLD}{C}  ZERODHA GTT ORDER GENERATOR{RESET}")
    print(f"{DIM}  {datetime.now().strftime('%a %d %b %Y  %H:%M')}  |  "
          f"Capital: ₹{capital:,.0f}{RESET}")
    print(f"{C}{BAR}{RESET}")

    print(f"\n{C}  Scanning NSE...{RESET}")
    cards = scan(capital=capital, top_n=5)

    if not cards:
        print(f"\n  {Y}No signals today. Market may be bearish — no GTT orders needed.{RESET}")
        print(f"  {DIM}Cash is a position. Run again tomorrow at 9 AM.{RESET}\n")
        return []

    # Run earnings guard
    print(f"  Checking earnings calendar...")
    safe_cards, blocked = filter_cards(cards, days=5)

    if blocked:
        print(f"\n  {Y}⛔ EARNINGS BLOCKED ({len(blocked)} stocks skipped):{RESET}")
        for c in blocked:
            print(f"  {DIM}  {c['ticker']:<12} — {c['blocked_reason']}{RESET}")

    if not safe_cards:
        print(f"\n  {Y}All signals blocked by earnings guard. No trades today.{RESET}\n")
        return []

    print(f"\n  {G}✓ {len(safe_cards)} safe signal(s) — generating GTT orders:{RESET}")

    for i, card in enumerate(safe_cards[:3], 1):   # max 3 per day
        print_gtt(card, i, capital)
        print(f"\n  {C}{'─'*62}{RESET}")

    print(f"\n  {BOLD}RISK REMINDER{RESET}")
    print(f"  {DIM}• Max 2 trades open at a time with ₹50,000 capital{RESET}")
    print(f"  {DIM}• Set GTT immediately after every buy — non-negotiable{RESET}")
    print(f"  {DIM}• Never move your stop-loss to avoid a loss{RESET}")
    print(f"  {DIM}• If Nifty drops >2% in a day — don't open new trades{RESET}")
    print(f"\n{C}{BAR}{RESET}\n")

    return safe_cards


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital", default=50_000, type=float)
    args = parser.parse_args()
    generate(capital=args.capital)
