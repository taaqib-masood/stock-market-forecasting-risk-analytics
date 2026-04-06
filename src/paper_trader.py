"""
Paper Trading Engine — Virtual ₹50,000
=======================================
Uses real NSE prices from yfinance. Simulates entry/exit with slippage.
All state stored in results/paper_portfolio.json

Commands:
  python -m src.paper_trader            → show portfolio
  python -m src.paper_trader --scan     → scan + auto-place top signals
  python -m src.paper_trader --buy RELIANCE 5 2850  → manual buy
  python -m src.paper_trader --sell RELIANCE 5 2950 → manual sell
  python -m src.paper_trader --reset    → reset to ₹50,000 (wipes all trades)
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

import yfinance as yf

from src.watchlist import nse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── Config ────────────────────────────────────────────────────────────────────
STARTING_CAPITAL = 50_000.0
SLIPPAGE_PCT     = 0.001          # 0.1% per fill
COMMISSION       = 20.0           # ₹20 flat per order (Zerodha rate)
STATE_FILE       = Path("results/paper_portfolio.json")

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"
C = "\033[36m"; W = "\033[37m"; DIM = "\033[2m"
BOLD = "\033[1m"; RESET = "\033[0m"; CLEAR = "\033[2J\033[H"
BAR = "━" * 66


# ── State helpers ─────────────────────────────────────────────────────────────

def _load() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return _fresh()


def _save(state: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _fresh() -> dict:
    return {
        "capital":    STARTING_CAPITAL,
        "cash":       STARTING_CAPITAL,
        "positions":  {},   # ticker → {shares, avg_entry, stop, target}
        "trades":     [],   # closed trade log
        "created_at": datetime.now().isoformat(),
    }


# ── Live price ────────────────────────────────────────────────────────────────

def live_price(ticker: str) -> float:
    """Fetch latest close price for an NSE ticker."""
    try:
        df = yf.download(nse(ticker), period="2d", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return 0.0
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return float(df["Close"].iloc[-1])
    except Exception:
        return 0.0


def live_prices(tickers: list) -> dict:
    """Batch fetch prices for multiple tickers."""
    symbols = " ".join(nse(t) for t in tickers)
    try:
        df = yf.download(symbols, period="2d", interval="1d",
                         progress=False, auto_adjust=True, group_by="ticker")
        prices = {}
        for t in tickers:
            try:
                s = nse(t)
                if len(tickers) == 1:
                    col = df.columns
                    close = float(df["Close"].iloc[-1])
                else:
                    close = float(df[s]["Close"].iloc[-1])
                prices[t] = round(close, 2)
            except Exception:
                prices[t] = 0.0
        return prices
    except Exception:
        return {t: 0.0 for t in tickers}


# ── Trade execution ───────────────────────────────────────────────────────────

def buy(ticker: str, shares: int, price: float = None,
        stop: float = None, target: float = None,
        state: dict = None) -> dict:
    """
    Execute a paper BUY order.
    If price is None, fetches live price.
    Applies 0.1% slippage + ₹20 commission.
    """
    if state is None:
        state = _load()

    if price is None or price <= 0:
        price = live_price(ticker)
        if price <= 0:
            return {"ok": False, "reason": f"Could not fetch price for {ticker}"}

    fill_price = round(price * (1 + SLIPPAGE_PCT), 2)   # slip: pay slightly more
    total_cost = round(fill_price * shares + COMMISSION, 2)

    if total_cost > state["cash"]:
        return {
            "ok":     False,
            "reason": f"Insufficient cash. Need ₹{total_cost:,.0f}, have ₹{state['cash']:,.0f}"
        }

    state["cash"] = round(state["cash"] - total_cost, 2)

    pos = state["positions"].get(ticker)
    if pos:
        # Average up/down
        total_shares = pos["shares"] + shares
        avg = round((pos["avg_entry"] * pos["shares"] + fill_price * shares) / total_shares, 2)
        pos["shares"]    = total_shares
        pos["avg_entry"] = avg
        if stop:   pos["stop"]   = stop
        if target: pos["target"] = target
    else:
        state["positions"][ticker] = {
            "shares":    shares,
            "avg_entry": fill_price,
            "stop":      stop,
            "target":    target,
            "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    _save(state)
    return {
        "ok":         True,
        "ticker":     ticker,
        "shares":     shares,
        "fill_price": fill_price,
        "total_cost": total_cost,
        "cash_left":  state["cash"],
        "stop":       stop,
        "target":     target,
    }


def sell(ticker: str, shares: int = None, price: float = None,
         state: dict = None) -> dict:
    """
    Execute a paper SELL order.
    Sells all shares if shares=None.
    """
    if state is None:
        state = _load()

    pos = state["positions"].get(ticker)
    if not pos:
        return {"ok": False, "reason": f"No position in {ticker}"}

    if shares is None or shares >= pos["shares"]:
        shares = pos["shares"]

    if price is None or price <= 0:
        price = live_price(ticker)
        if price <= 0:
            return {"ok": False, "reason": f"Could not fetch price for {ticker}"}

    fill_price  = round(price * (1 - SLIPPAGE_PCT), 2)   # slip: receive slightly less
    proceeds    = round(fill_price * shares - COMMISSION, 2)
    entry_price = pos["avg_entry"]
    pnl         = round((fill_price - entry_price) * shares - COMMISSION, 2)
    pnl_pct     = round((fill_price / entry_price - 1) * 100, 2)

    state["cash"] = round(state["cash"] + proceeds, 2)

    trade_record = {
        "ticker":      ticker,
        "shares":      shares,
        "entry":       entry_price,
        "exit":        fill_price,
        "pnl":         pnl,
        "pnl_pct":     pnl_pct,
        "outcome":     "WIN" if pnl > 0 else "LOSS",
        "closed_at":   datetime.now().strftime("%Y-%m-%d %H:%M"),
        "entry_date":  pos.get("entry_date", ""),
    }
    state["trades"].append(trade_record)

    if shares >= pos["shares"]:
        del state["positions"][ticker]
    else:
        pos["shares"] -= shares

    _save(state)
    return {"ok": True, "cash_left": state["cash"], **trade_record}


# ── Portfolio valuation ───────────────────────────────────────────────────────

def portfolio_value(state: dict) -> dict:
    """Mark all open positions to market."""
    positions = state["positions"]
    if not positions:
        return {
            "cash":          state["cash"],
            "positions_val": 0.0,
            "total_val":     state["cash"],
            "total_pnl":     round(state["cash"] - STARTING_CAPITAL, 2),
            "total_pnl_pct": round((state["cash"] / STARTING_CAPITAL - 1) * 100, 2),
            "marked":        {},
        }

    prices = live_prices(list(positions.keys()))
    marked = {}
    positions_val = 0.0

    for ticker, pos in positions.items():
        cur = prices.get(ticker, pos["avg_entry"])
        mkt_val  = round(cur * pos["shares"], 2)
        unreal   = round((cur - pos["avg_entry"]) * pos["shares"], 2)
        unreal_p = round((cur / pos["avg_entry"] - 1) * 100, 2)
        positions_val += mkt_val
        marked[ticker] = {
            **pos,
            "current_price": cur,
            "market_value":  mkt_val,
            "unrealised":    unreal,
            "unrealised_pct":unreal_p,
        }

    total_val  = round(state["cash"] + positions_val, 2)
    total_pnl  = round(total_val - STARTING_CAPITAL, 2)
    total_pnl_pct = round((total_val / STARTING_CAPITAL - 1) * 100, 2)

    return {
        "cash":           state["cash"],
        "positions_val":  round(positions_val, 2),
        "total_val":      total_val,
        "total_pnl":      total_pnl,
        "total_pnl_pct":  total_pnl_pct,
        "marked":         marked,
    }


# ── Trade stats ───────────────────────────────────────────────────────────────

def trade_stats(state: dict) -> dict:
    trades = state["trades"]
    if not trades:
        return {}
    wins   = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    pnls   = [t["pnl"] for t in trades]
    return {
        "total":         len(trades),
        "wins":          len(wins),
        "losses":        len(losses),
        "win_rate":      round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_pnl":     round(sum(pnls), 2),
        "avg_win":       round(sum(wins)   / len(wins),   2) if wins   else 0,
        "avg_loss":      round(sum(losses) / len(losses), 2) if losses else 0,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2)
                         if losses and sum(losses) != 0 else float("inf"),
        "best":          round(max(pnls), 2),
        "worst":         round(min(pnls), 2),
    }


# ── Render ────────────────────────────────────────────────────────────────────

def _col(val: float) -> str:
    c = G if val >= 0 else R
    return f"{c}{val:+,.2f}{RESET}"


def render_portfolio(state: dict):
    pv    = portfolio_value(state)
    stats = trade_stats(state)
    now   = datetime.now().strftime("%a %d %b %Y  %H:%M")

    print(CLEAR, end="")
    print(f"{BOLD}{C}{BAR}{RESET}")
    print(f"{BOLD}{C}  PAPER TRADING PORTFOLIO  {DIM}₹{STARTING_CAPITAL:,.0f} starting capital{RESET}")
    print(f"{DIM}  {now}{RESET}")
    print(f"{C}{BAR}{RESET}")

    # ── Account summary ───────────────────────────────────────────────────────
    pnl_col = G if pv["total_pnl"] >= 0 else R
    print(f"""
  {BOLD}ACCOUNT SUMMARY{RESET}
  {'Starting Capital':<22} ₹{STARTING_CAPITAL:>10,.2f}
  {'Current Value':<22} ₹{pv['total_val']:>10,.2f}
  {'Cash Available':<22} ₹{pv['cash']:>10,.2f}
  {'Positions Value':<22} ₹{pv['positions_val']:>10,.2f}
  {'Total P&L':<22} {pnl_col}₹{pv['total_pnl']:>+10,.2f}  ({pv['total_pnl_pct']:+.2f}%){RESET}
""")

    # ── Open positions ─────────────────────────────────────────────────────────
    print(f"  {BOLD}OPEN POSITIONS{RESET}")
    if not pv["marked"]:
        print(f"  {DIM}No open positions. Run --scan to find trades.{RESET}\n")
    else:
        print(f"  {'Ticker':<12} {'Shares':>6} {'Avg Entry':>10} "
              f"{'Current':>10} {'Mkt Value':>11} "
              f"{'Unrealised':>12} {'Stop':>8} {'Target':>8}")
        print(f"  {'─'*90}")
        for ticker, m in pv["marked"].items():
            u_col = G if m["unrealised"] >= 0 else R
            stop_str   = f"₹{m['stop']:,.2f}"   if m["stop"]   else "  —  "
            target_str = f"₹{m['target']:,.2f}" if m["target"] else "  —  "
            print(f"  {W}{ticker:<12}{RESET} {m['shares']:>6} "
                  f"₹{m['avg_entry']:>9,.2f} "
                  f"₹{m['current_price']:>9,.2f} "
                  f"₹{m['market_value']:>10,.2f} "
                  f"{u_col}₹{m['unrealised']:>+10,.2f} ({m['unrealised_pct']:+.1f}%){RESET} "
                  f"{stop_str:>9} {target_str:>9}")
        print()

    # ── Closed trades ──────────────────────────────────────────────────────────
    print(f"  {BOLD}CLOSED TRADES{RESET}")
    if not state["trades"]:
        print(f"  {DIM}No closed trades yet.{RESET}\n")
    else:
        recent = state["trades"][-8:][::-1]
        print(f"  {'Ticker':<12} {'Shares':>6} {'Entry':>8} "
              f"{'Exit':>8} {'P&L':>10} {'%':>7} {'Result':<6} {'Date'}")
        print(f"  {'─'*75}")
        for t in recent:
            o_col = G if t["pnl"] > 0 else R
            print(f"  {W}{t['ticker']:<12}{RESET} {t['shares']:>6} "
                  f"₹{t['entry']:>7,.2f} ₹{t['exit']:>7,.2f} "
                  f"{o_col}₹{t['pnl']:>+9,.2f} {t['pnl_pct']:>+6.1f}%{RESET} "
                  f"{o_col}{t['outcome']:<6}{RESET} {t['closed_at'][:10]}")
        print()

    # ── Stats ──────────────────────────────────────────────────────────────────
    print(f"  {BOLD}PERFORMANCE STATS  {DIM}(closed trades){RESET}")
    if not stats:
        print(f"  {DIM}No closed trades to analyse yet.{RESET}\n")
    else:
        wr_col = G if stats["win_rate"] >= 55 else Y if stats["win_rate"] >= 45 else R
        pf_col = G if stats["profit_factor"] >= 1.5 else Y
        print(f"  {'Trades':<18} {stats['total']}  "
              f"(W:{stats['wins']} / L:{stats['losses']})")
        print(f"  {'Win Rate':<18} {wr_col}{stats['win_rate']}%{RESET}")
        print(f"  {'Profit Factor':<18} {pf_col}{stats['profit_factor']}{RESET}")
        print(f"  {'Avg Win':<18} {G}₹{stats['avg_win']:+,.2f}{RESET}   "
              f"Avg Loss: {R}₹{stats['avg_loss']:+,.2f}{RESET}")
        print(f"  {'Best Trade':<18} {G}₹{stats['best']:+,.2f}{RESET}   "
              f"Worst: {R}₹{stats['worst']:+,.2f}{RESET}")
        print()

    # ── Footer ─────────────────────────────────────────────────────────────────
    print(f"  {C}{'─'*62}{RESET}")
    print(f"  {DIM}Commands:{RESET}")
    print(f"  {DIM}  --scan              scan NSE & auto-place top signals{RESET}")
    print(f"  {DIM}  --buy TICKER N P    buy N shares of TICKER at price P{RESET}")
    print(f"  {DIM}  --sell TICKER N P   sell N shares of TICKER at price P{RESET}")
    print(f"  {DIM}  --reset             wipe portfolio, restart with ₹50,000{RESET}")
    print(f"  {C}{BAR}{RESET}\n")


# ── Auto-place from scanner ───────────────────────────────────────────────────

def auto_scan_and_place(state: dict, top_n: int = 2) -> list:
    """Scan NSE, pick top signals, paper-buy them if cash allows."""
    from src.scanner import scan as nse_scan
    print(f"\n{C}  Scanning NSE... (takes ~20s){RESET}")
    cards = nse_scan(capital=state["cash"], top_n=top_n)

    if not cards:
        print(f"  {Y}No high-conviction setups right now. Market may be bearish.{RESET}\n")
        return []

    placed = []
    for card in cards:
        # Skip if already holding
        if card["ticker"] in state["positions"]:
            print(f"  {DIM}Already holding {card['ticker']} — skipping.{RESET}")
            continue

        # Position size: max 30% of cash per trade
        max_invest = state["cash"] * 0.30
        shares     = min(card["shares"], int(max_invest / card["entry"]))
        if shares < 1:
            print(f"  {Y}Not enough cash for {card['ticker']} ({shares} shares).{RESET}")
            continue

        result = buy(
            ticker=card["ticker"],
            shares=shares,
            price=card["entry"],
            stop=card["stop"],
            target=card["target"],
            state=state,
        )
        if result["ok"]:
            print(f"  {G}✓ BOUGHT {card['ticker']:>10}  "
                  f"{shares} shares @ ₹{result['fill_price']:,.2f}  "
                  f"Cost: ₹{result['total_cost']:,.0f}  "
                  f"Cash left: ₹{result['cash_left']:,.0f}{RESET}")
            print(f"    {DIM}Stop: ₹{card['stop']:,.2f}  "
                  f"Target: ₹{card['target']:,.2f}  R:R: {card['rr']}{RESET}")
            placed.append(result)
        else:
            print(f"  {R}✗ {card['ticker']}: {result['reason']}{RESET}")

    return placed


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan",  action="store_true", help="Scan NSE and auto-place signals")
    parser.add_argument("--buy",   nargs=3, metavar=("TICKER", "SHARES", "PRICE"),
                        help="Paper buy: --buy RELIANCE 5 2850")
    parser.add_argument("--sell",  nargs=3, metavar=("TICKER", "SHARES", "PRICE"),
                        help="Paper sell: --sell RELIANCE 5 2950")
    parser.add_argument("--reset", action="store_true", help="Reset portfolio to ₹50,000")
    args = parser.parse_args()

    if args.reset:
        confirm = input(f"{R}Reset portfolio? This wipes all trades. (yes/no): {RESET}")
        if confirm.strip().lower() == "yes":
            _save(_fresh())
            print(f"{G}✓ Portfolio reset to ₹{STARTING_CAPITAL:,.0f}{RESET}\n")
        else:
            print("Cancelled.")
        sys.exit(0)

    state = _load()

    if args.buy:
        ticker, shares, price = args.buy[0].upper(), int(args.buy[1]), float(args.buy[2])
        r = buy(ticker, shares, price, state=state)
        if r["ok"]:
            print(f"\n{G}✓ BOUGHT {shares} × {ticker} @ ₹{r['fill_price']:,.2f}  "
                  f"Cost: ₹{r['total_cost']:,.0f}  Cash left: ₹{r['cash_left']:,.0f}{RESET}\n")
        else:
            print(f"\n{R}✗ {r['reason']}{RESET}\n")

    elif args.sell:
        ticker, shares, price = args.sell[0].upper(), int(args.sell[1]), float(args.sell[2])
        r = sell(ticker, shares, price, state=state)
        if r["ok"]:
            pnl_col = G if r["pnl"] >= 0 else R
            print(f"\n{G}✓ SOLD {shares} × {ticker} @ ₹{r['exit']:,.2f}  "
                  f"P&L: {pnl_col}₹{r['pnl']:+,.2f} ({r['pnl_pct']:+.1f}%){RESET}  "
                  f"Cash: ₹{r['cash_left']:,.0f}\n")
        else:
            print(f"\n{R}✗ {r['reason']}{RESET}\n")

    elif args.scan:
        auto_scan_and_place(state, top_n=2)
        render_portfolio(state)

    else:
        render_portfolio(state)
