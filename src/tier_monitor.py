"""
Halal tier-change monitor.

After each fundamentals refresh, diff today's 🟢/🟡/🔴 tiers against the last snapshot
and surface only the TRANSITIONS — e.g. a holding that crossed the AAOIFI debt/interest
line and went 🟢→🔴. This protects users from silently holding a stock that quietly
turned non-compliant (the #1 risk in a halal portfolio).

Run after the quarterly refresh:
    python -m src.tier_monitor
"""
import json
import hashlib
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from src.halal_screen import screen_cached, GREEN, YELLOW, RED
from src.fundamentals import _load as _load_cache

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "tier_snapshot.json"
_SEVERITY = {GREEN: 0, YELLOW: 1, RED: 2}


def current_tiers(cache: Optional[dict] = None) -> dict:
    """Screen every cached ticker → {ticker: {tier, debt_to_assets, interest_income_ratio}}."""
    data = cache if cache is not None else _load_cache()
    out = {}
    for tkr in data:
        r = screen_cached(tkr, cache=data)
        out[tkr] = {"tier": r["tier"], "debt_to_assets": r["debt_to_assets"],
                    "interest_income_ratio": r["interest_income_ratio"]}
    return out


def diff_tiers(old: dict, new: dict) -> list:
    """Tier transitions between two snapshots (only changed tickers; worsened ones first)."""
    changes = []
    for tkr, cur in new.items():
        prev = old.get(tkr)
        if prev is None or prev.get("tier") == cur.get("tier"):
            continue  # new ticker or unchanged
        changes.append({
            "ticker": tkr, "from": prev.get("tier"), "to": cur.get("tier"),
            "worsened": _SEVERITY.get(cur.get("tier"), 0) > _SEVERITY.get(prev.get("tier"), 0),
            "debt_to_assets": cur.get("debt_to_assets"),
            "interest_income_ratio": cur.get("interest_income_ratio"),
        })
    changes.sort(key=lambda c: not c["worsened"])  # 🟢→🔴 first
    return changes


def check_and_snapshot(snapshot_path: Path = SNAPSHOT_PATH, cache: Optional[dict] = None) -> list:
    """Load previous snapshot, compute current tiers, diff, save new snapshot.
    Returns the transitions (empty on first run / no changes)."""
    try:
        old = json.loads(snapshot_path.read_text())
    except Exception:
        old = {}
    new = current_tiers(cache=cache)
    changes = diff_tiers(old, new)
    snapshot_path.parent.mkdir(exist_ok=True)
    snapshot_path.write_text(json.dumps(new, indent=2))
    return changes


def format_changes(changes: list) -> str:
    if not changes:
        return "✅ No halal tier changes since last check."
    lines = ["⚠️ <b>Halal tier changes</b>:"]
    for c in changes:
        flag = "  ← now NON-TRADEABLE" if c["to"] == RED else ""
        lines.append(f"  {c['ticker']}: {c['from']}→{c['to']}{flag}")
    return "\n".join(lines)


def queue_tier_change_alert(changes: list, *, now: str | datetime | None = None) -> dict:
    """Queue tier changes only for approved, explicitly-consented recipients."""
    if not changes:
        return {"queued": 0, "created": 0, "blockers": []}
    from src.notify import queue_recommendation_for_audience, send_outbox_payload
    from src.reliability.outbox import DeliveryOutbox
    from src.reliability.store import ReliabilityStore
    from src.reliability.telegram_audience import TelegramAudience

    point = now or datetime.now(timezone.utc)
    database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    signal_hash = hashlib.sha256(
        json.dumps(changes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    signal_id = f"halal-tier:{point.date().isoformat()}:{signal_hash}"
    with ReliabilityStore(database) as store:
        audience = TelegramAudience(store.connection)
        outbox = DeliveryOutbox(store.connection)
        queued = queue_recommendation_for_audience(
            format_changes(changes), signal_id, audience, outbox, now=point
        )
        if not queued.get("queued"):
            return queued
        return {**queued, "delivery": outbox.deliver_due(send_outbox_payload, now=point)}


if __name__ == "__main__":
    import sys

    changes = check_and_snapshot()
    msg = format_changes(changes)
    print(msg)

    # --notify: push tier transitions to Telegram (used by the quarterly CI re-screen).
    # Only queues changed tiers for approved, explicitly-consented recipients.
    if "--notify" in sys.argv and changes:
        result = queue_tier_change_alert(changes)
        delivered = result.get("delivery", {}).get("delivered", 0)
        print(f"[tier_monitor] telegram push: {'sent' if delivered else 'skipped (gate, consent, credentials, or delivery)'}")
