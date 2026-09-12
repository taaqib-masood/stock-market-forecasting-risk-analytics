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
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src.scanner        import scan
from src.earnings_guard import filter_cards
from src.gtt_generator  import print_gtt
from src.paper_trader   import _load, portfolio_value, trade_stats, auto_scan_and_place
from src.notify         import _send, acknowledge_shadow_payload, send_journal_summary
from src.strategy       import RuleStrategy
from src.reliability.controls import ControlDecision

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[31m"; G = "\033[32m"; Y = "\033[33m"
C = "\033[36m"; W = "\033[37m"; DIM = "\033[2m"
BOLD = "\033[1m"; RESET = "\033[0m"
BAR = "━" * 66


def _release_gate() -> dict:
    """Evaluate the retained release evidence before any direct recommendation send."""
    from src.reliability.governance import evaluate_release, load_policy

    evidence_path = Path(os.environ.get(
        "BORO_RELEASE_EVIDENCE", "data/reliability/current-release-evidence.json"
    ))
    policy_path = Path(os.environ.get(
        "BORO_RELEASE_POLICY", "config/reliability-policy.json"
    ))
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        policy = load_policy(policy_path)
        from src.reliability.governance import load_release_corporate_action_audit
        result = evaluate_release(
            evidence, policy,
            corporate_action_audit=load_release_corporate_action_audit(),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {"approved": False, "blockers": ["RELEASE_EVIDENCE_INVALID"], "error": str(error)}
    return result


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


def _build_telegram_briefing(cards: list, blocked: list, regime: str,
                              emoji: str, nifty: float, capital: float,
                              state: dict, near_misses: list = None) -> str:
    """Build the full Telegram morning message without performing network I/O."""
    date  = datetime.now().strftime("%a %d %b %Y")

    lines = [
        f"🌅 <b>MORNING BRIEFING — {date}</b>",
        f"",
        f"Market : {emoji} <b>{regime}</b>  |  Nifty ₹{nifty:,.0f}",
        f"",
    ]

    if not cards:
        lines += [
            f"🔍 <b>No confirmed signals today.</b>",
            f"",
        ]
        if blocked:
            lines += [f"⛔ Earnings blocked: {', '.join(c['ticker'] for c in blocked)}", f""]
        if near_misses:
            lines.append(f"👀 <b>Stocks to watch (near misses):</b>")
            for nm in near_misses[:5]:
                lines.append(f"  • {nm['ticker']}  Score {nm['score']:.0f}/100  R:R {nm['rr']}:1  — not quite there yet")
            lines += [f"", f"<i>These are close. Check again tomorrow — one good day could push them over.</i>"]
        else:
            lines += [f"<i>Patience is a position. Check again tomorrow.</i>"]
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

    lines += [
        f"",
        f"⚠️ <i>Educational market information, not individualized financial advice. "
        f"Verify price, liquidity, halal status, and risk before acting. Send /stop to unsubscribe.</i>",
    ]

    return "\n".join(lines)


def _dispatch_briefing(message: str, cards: list, now: datetime | None = None):
    """Queue only through the durable, gated delivery path."""
    mode = os.environ.get("BORO_RELIABILITY_MODE", "research").lower()
    if mode != "shadow":
        gate = _release_gate()
        if mode not in {"private", "public"} or not gate.get("approved"):
            return {
                "queued": False,
                "blockers": ["RELEASE_GATE_NOT_APPROVED", *gate.get("blockers", [])],
                "release": gate,
            }
        from src.notify import (
            queue_recommendation_for_audience,
            send_outbox_payload,
        )
        from src.reliability.activation import assess_shadow_readiness
        from src.reliability.ledger import SignalLedger
        from src.reliability.outbox import DeliveryOutbox
        from src.reliability.shadow import ShadowCoordinator
        from src.reliability.store import ReliabilityStore
        from src.reliability.telegram_audience import TelegramAudience

        point = now or datetime.now(timezone.utc)
        db_path = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
        with ReliabilityStore(db_path) as store:
            coordinator = ShadowCoordinator(
                SignalLedger(store.connection), DeliveryOutbox(store.connection)
            )
            manifest = store.connection.execute(
                """
                SELECT content_hash FROM manifests
                WHERE available_at <= ? ORDER BY available_at DESC LIMIT 1
                """,
                (point.astimezone(timezone.utc).isoformat(timespec="seconds"),),
            ).fetchone()
            if manifest is None:
                return {"queued": False, "blockers": ["DATA_MANIFEST_MISSING"], "release": gate}

            from src.reliability.governance import load_release_corporate_action_audit
            corporate_action_audit = load_release_corporate_action_audit()
            readiness = assess_shadow_readiness(
                store, coordinator.ledger, coordinator.outbox,
                as_of=point, corporate_action_audit=corporate_action_audit,
            )
            if not readiness["ready"]:
                return {"queued": False, "blockers": readiness["blockers"],
                        "readiness": readiness, "release": gate}

            tickers = sorted({
                str(card.get("ticker", "")).upper()
                for card in cards if card.get("ticker")
            })
            universe = set(store.eligible_universe(point))
            if any(ticker not in universe for ticker in tickers):
                return {"queued": False, "blockers": ["SIGNAL_NOT_IN_UNIVERSE"],
                        "readiness": readiness, "release": gate}
            if any(
                not store.halal_as_of(ticker, point, max_age_days=200).get("tradeable", False)
                for ticker in tickers
            ):
                return {"queued": False, "blockers": ["SIGNAL_HALAL_BLOCKED"],
                        "readiness": readiness, "release": gate}
            snapshot = {
                "ticker": "BRIEFING:" + (",".join(tickers) if tickers else "NO_SIGNAL"),
                "decision_session": point.date().isoformat(),
                "strategy_version": RuleStrategy.version,
                "data_manifest_hash": manifest["content_hash"],
                "cards": cards,
                "release_mode": mode,
                "readiness_metrics": readiness["metrics"],
            }
            signal = coordinator.record_signal(
                snapshot,
                message,
                ControlDecision(allowed=True, hard_failures=()),
                now=point,
                enqueue=False,
            )
            audience_db = os.environ.get("BORO_TELEGRAM_AUDIENCE_DB", db_path)
            audience_context = (
                TelegramAudience(store.connection)
                if os.path.abspath(str(audience_db)) == os.path.abspath(str(db_path))
                else TelegramAudience(audience_db)
            )
            with audience_context as audience:
                queued = queue_recommendation_for_audience(
                    message,
                    signal["signal_id"],
                    audience,
                    coordinator.outbox,
                    now=point,
                )
            if not queued.get("queued"):
                return {**signal, **queued, "release": gate}
            delivery = coordinator.deliver_due(send_outbox_payload, now=point)
            return {**signal, **queued, "delivery": delivery, "release": gate}

    from src.reliability.activation import assess_shadow_readiness, queue_shadow_briefing
    from src.reliability.governance import load_release_corporate_action_audit
    from src.reliability.ledger import SignalLedger
    from src.reliability.outbox import DeliveryOutbox
    from src.reliability.shadow import ShadowCoordinator
    from src.reliability.store import ReliabilityStore

    point = now or datetime.now(timezone.utc)
    db_path = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    with ReliabilityStore(db_path) as store:
        coordinator = ShadowCoordinator(
            SignalLedger(store.connection), DeliveryOutbox(store.connection)
        )
        manifest = store.connection.execute(
            """
            SELECT content_hash FROM manifests
            WHERE available_at <= ? ORDER BY available_at DESC LIMIT 1
            """,
            (point.astimezone(timezone.utc).isoformat(timespec="seconds"),),
        ).fetchone()
        if manifest is None:
            readiness = assess_shadow_readiness(
                store,
                coordinator.ledger,
                coordinator.outbox,
                as_of=point,
                corporate_action_audit=load_release_corporate_action_audit(),
            )
            return {
                "queued": False,
                "blockers": ["DATA_MANIFEST_MISSING", *readiness["blockers"]],
                "readiness": readiness,
            }
        queued = queue_shadow_briefing(
            cards=cards,
            message=message,
            store=store,
            coordinator=coordinator,
            as_of=point,
            strategy_version=RuleStrategy.version,
            data_manifest_hash=manifest["content_hash"],
            corporate_action_audit=load_release_corporate_action_audit(),
        )
        if not queued.get("queued"):
            return queued
        # Shadow mode measures the durable outbox/ledger path without contacting
        # Telegram or relying on the retired default-chat delivery path.
        delivery = coordinator.deliver_due(acknowledge_shadow_payload, now=point)
        return {**queued, "delivery": delivery}


def _telegram_briefing(cards: list, blocked: list, regime: str,
                        emoji: str, nifty: float, capital: float,
                        state: dict, near_misses: list = None):
    message = _build_telegram_briefing(
        cards, blocked, regime, emoji, nifty, capital, state, near_misses
    )
    return _dispatch_briefing(message, cards)


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
    scan_result  = scan(capital=capital, top_n=5)
    raw_cards    = scan_result.get("cards", [])
    scan_blocked = scan_result.get("blocked", [])
    near_misses  = scan_result.get("near_misses", [])

    if scan_blocked:
        print(f"  {Y}Gap/regime blocked: "
              f"{', '.join(c['ticker'] for c in scan_blocked)}{RESET}")

    # ── Earnings guard ────────────────────────────────────────────────────────
    print(f"  Checking earnings calendar...")
    safe_cards, blocked = filter_cards(raw_cards, days=5)
    blocked = blocked + scan_blocked   # combine all blocked

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
    delivery = _telegram_briefing(
        safe_cards[:3], blocked, regime, emoji, nifty, capital, state, near_misses
    )
    if isinstance(delivery, dict):
        delivered = delivery.get("delivery", {}).get("delivered", 0)
        if delivered:
            print(f"  {G}✓ Shadow briefing persisted and acknowledged{RESET}")
        else:
            blockers = ", ".join(delivery.get("blockers", [])) or "delivery pending"
            print(f"  {Y}⚠ Shadow briefing blocked: {blockers}{RESET}")
    elif delivery:
        print(f"  {G}✓ Telegram sent{RESET}")
    else:
        print(f"  {Y}⚠ Telegram not configured or send failed{RESET}")

    print(f"\n{C}{BAR}{RESET}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capital",      default=50_000, type=float)
    parser.add_argument("--paper",        action="store_true",
                        help="Auto-place signals in paper portfolio")
    args = parser.parse_args()
    run(capital=args.capital, paper_auto_place=args.paper)
