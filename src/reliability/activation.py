"""Readiness gate and queueing entry point for production shadow briefings."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from typing import Any

from src.reliability.controls import ControlDecision
from src.reliability.corporate_action_reviews import (
    VerifiedCorporateActionAudit,
    verified_corporate_action_audit_sha256,
)
from src.reliability.ledger import SignalLedger
from src.reliability.outbox import DeliveryOutbox
from src.reliability.shadow import ShadowCoordinator
from src.reliability.store import ReliabilityStore


def _dt(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        text = value.replace("Z", "+00:00")
        if len(text) == 10:
            text += "T00:00:00+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assess_shadow_readiness(
    store: ReliabilityStore,
    ledger: SignalLedger,
    outbox: DeliveryOutbox,
    *,
    as_of: str | date | datetime,
    corporate_action_audit: VerifiedCorporateActionAudit | None = None,
    max_bar_age_days: int = 5,
    max_halal_age_days: int = 200,
) -> dict[str, Any]:
    point = _dt(as_of)
    point_iso = point.isoformat(timespec="seconds")
    universe = store.eligible_universe(point)
    missing_bars: list[str] = []
    stale_bars: list[str] = []
    missing_halal: list[str] = []
    non_tradeable: list[str] = []
    for symbol in universe:
        row = store.connection.execute(
            """
            SELECT session_date, available_at FROM bars
            WHERE symbol = ? AND session_date <= ? AND available_at <= ?
            ORDER BY session_date DESC, available_at DESC LIMIT 1
            """,
            (symbol, point_iso, point_iso),
        ).fetchone()
        if row is None:
            missing_bars.append(symbol)
        elif (point - _dt(row["session_date"])).days > max_bar_age_days:
            stale_bars.append(symbol)
        halal = store.halal_as_of(symbol, point, max_age_days=max_halal_age_days)
        if halal.get("tier") == "UNKNOWN" or halal.get("reason") == "halal classification is stale":
            missing_halal.append(symbol)
        elif not halal.get("tradeable", False):
            non_tradeable.append(symbol)

    chain = ledger.verify_chain()
    delivery = outbox.metrics()
    blockers = []
    if not universe:
        blockers.append("UNIVERSE_EMPTY")
    if missing_bars:
        blockers.append("BAR_COVERAGE")
    if stale_bars:
        blockers.append("BAR_FRESHNESS")
    if missing_halal:
        blockers.append("HALAL_COVERAGE")
    if not chain["valid"]:
        blockers.append("LEDGER_INTEGRITY")
    if delivery.get("unreconciled", 0):
        blockers.append("DELIVERY_UNRECONCILED")
    if delivery.get("dead_letter", 0):
        blockers.append("DELIVERY_DEAD_LETTER")
    verified_audit_sha256 = verified_corporate_action_audit_sha256(
        corporate_action_audit
    )
    if verified_audit_sha256 is None:
        blockers.append("CORPORATE_ACTION_REVIEW")
    denominator = len(universe)
    metrics = {
        "universe_size": denominator,
        "bar_coverage": (denominator - len(missing_bars) - len(stale_bars)) / denominator
                        if denominator else 0.0,
        "halal_coverage": (denominator - len(missing_halal)) / denominator
                          if denominator else 0.0,
        "missing_bars": missing_bars,
        "stale_bars": stale_bars,
        "blocked_halal": missing_halal,
        "non_tradeable": non_tradeable,
        "ledger_events": chain["events"],
        "delivery": delivery,
    }
    if verified_audit_sha256 is not None:
        metrics["corporate_action_audit_sha256"] = verified_audit_sha256
    return {
        "ready": not blockers,
        "blockers": blockers,
        "metrics": metrics,
    }


def queue_shadow_briefing(
    *,
    cards: list[dict[str, Any]],
    message: str,
    store: ReliabilityStore,
    coordinator: ShadowCoordinator,
    as_of: str | date | datetime,
    strategy_version: str,
    data_manifest_hash: str,
    corporate_action_audit: VerifiedCorporateActionAudit | None = None,
) -> dict[str, Any]:
    readiness = assess_shadow_readiness(
        store,
        coordinator.ledger,
        coordinator.outbox,
        as_of=as_of,
        corporate_action_audit=corporate_action_audit,
    )
    if not readiness["ready"]:
        return {"queued": False, "blockers": readiness["blockers"], "readiness": readiness}
    tickers = sorted({str(card.get("ticker", "")).upper() for card in cards if card.get("ticker")})
    point = _dt(as_of)
    universe = set(store.eligible_universe(point))
    signal_blockers = []
    if any(ticker not in universe for ticker in tickers):
        signal_blockers.append("SIGNAL_NOT_IN_UNIVERSE")
    if any(not store.halal_as_of(ticker, point, max_age_days=200).get("tradeable", False)
           for ticker in tickers):
        signal_blockers.append("SIGNAL_HALAL_BLOCKED")
    if signal_blockers:
        return {"queued": False, "blockers": signal_blockers, "readiness": readiness}
    snapshot = {
        "ticker": "BRIEFING:" + (",".join(tickers) if tickers else "NO_SIGNAL"),
        "decision_session": point.date().isoformat(),
        "strategy_version": strategy_version,
        "data_manifest_hash": data_manifest_hash,
        "cards": cards,
        "readiness_metrics": readiness["metrics"],
    }
    result = coordinator.record_signal(
        snapshot,
        message,
        ControlDecision(allowed=True, hard_failures=()),
        now=point,
    )
    return {**result, "blockers": [], "readiness": readiness}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Boro shadow activation readiness")
    parser.add_argument("--db", default="results/reliability.db")
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).isoformat())
    args = parser.parse_args()
    with ReliabilityStore(args.db) as store:
        result = assess_shadow_readiness(
            store, SignalLedger(store.connection), DeliveryOutbox(store.connection),
            as_of=args.as_of,
            corporate_action_audit=None,
        )
    print(json.dumps(result, indent=2))
    if not result["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
