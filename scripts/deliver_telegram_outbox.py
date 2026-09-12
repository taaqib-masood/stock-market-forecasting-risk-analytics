"""Deliver due, consent-bound Telegram outbox messages once.

This is intentionally a one-shot command. Run it from cron, a container
schedule, or a CI worker; it never bypasses the release gate, kill switch,
recipient consent, or the transactional outbox.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.notify import _recommendation_delivery_approved, send_outbox_payload
from src.reliability.controls import operational_kill_switch_active
from src.reliability.outbox import DeliveryOutbox
from src.reliability.store import ReliabilityStore


def _blocked_report(reason: str, blockers: list[str] | None = None) -> dict[str, object]:
    return {
        "ok": False,
        "blocked": True,
        "reason": reason,
        "blockers": list(dict.fromkeys(blockers or [reason])),
        "delivered": 0,
        "failed": 0,
        "dead_letter": 0,
        "unreconciled": 0,
    }


def deliver_outbox(
    *,
    database: str | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> dict[str, object]:
    """Deliver due messages and return a secret-free operational report."""
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if operational_kill_switch_active():
        return _blocked_report("OPERATIONAL_KILL_SWITCH_ACTIVE")
    if not _recommendation_delivery_approved():
        blockers = ["RELEASE_GATE_NOT_APPROVED"]
        try:
            from src.control_server import _release_status
            blockers.extend(_release_status().get("blockers", []))
        except (OSError, TypeError, ValueError):
            pass
        return _blocked_report("RELEASE_GATE_NOT_APPROVED", blockers)
    if not os.environ.get("TELEGRAM_TOKEN", "").strip():
        return _blocked_report("TELEGRAM_CREDENTIALS_MISSING")
    if not os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip():
        return _blocked_report("TELEGRAM_WEBHOOK_SECRET_MISSING")

    point = now or datetime.now(timezone.utc)
    db_path = database or os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    with ReliabilityStore(db_path) as store:
        outbox = DeliveryOutbox(store.connection)
        delivery = outbox.deliver_due(send_outbox_payload, now=point, limit=limit)
        metrics = outbox.metrics()

    failed = int(delivery.get("failed", 0))
    dead_letter = int(delivery.get("dead_letter", 0))
    unreconciled = int(delivery.get("unreconciled", 0))
    return {
        "ok": not (failed or dead_letter or unreconciled),
        "blocked": False,
        "delivered": int(delivery.get("delivered", 0)),
        "failed": failed,
        "dead_letter": dead_letter,
        "unreconciled": unreconciled,
        "health": {
            "queued": int(metrics.get("queued", 0)),
            "retrying": int(metrics.get("retrying", 0)),
            "delivered": int(metrics.get("delivered", 0)),
            "dead_letter": int(metrics.get("dead_letter", 0)),
            "unreconciled": int(metrics.get("unreconciled", 0)),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", help="override BORO_RELIABILITY_DB")
    parser.add_argument("--limit", type=int, default=100, help="maximum messages per run (1-1000)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    try:
        report = deliver_outbox(database=args.database, limit=args.limit)
    except (OSError, ValueError, RuntimeError):
        return 2
    print(json.dumps(report, sort_keys=True) if args.json else (
        "Telegram outbox: " + ("OK" if report["ok"] else "BLOCKED/DEGRADED")
        + f" · delivered={report['delivered']} failed={report['failed']}"
        + f" dead_letter={report['dead_letter']} unreconciled={report['unreconciled']}"
    ))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
