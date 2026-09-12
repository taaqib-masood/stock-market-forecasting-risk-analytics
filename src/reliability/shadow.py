"""Coordinates control decisions, immutable snapshots, and shadow delivery."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Callable

from src.reliability.controls import ControlDecision
from src.reliability.ledger import SignalLedger
from src.reliability.outbox import DeliveryOutbox


class ShadowCoordinator:
    def __init__(self, ledger: SignalLedger, outbox: DeliveryOutbox):
        self.ledger = ledger
        self.outbox = outbox

    @staticmethod
    def signal_id(snapshot: dict[str, Any]) -> str:
        required = ("ticker", "decision_session", "strategy_version", "data_manifest_hash")
        missing = [key for key in required if not snapshot.get(key)]
        if missing:
            raise ValueError(f"shadow snapshot missing required fields: {', '.join(missing)}")
        if len(str(snapshot["data_manifest_hash"])) != 64:
            raise ValueError("data_manifest_hash must be a SHA-256 digest")
        material = "|".join(str(snapshot[key]) for key in required)
        return "sig-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]

    def record_signal(
        self,
        snapshot: dict[str, Any],
        message: str,
        controls: ControlDecision,
        *,
        now: str | datetime,
        enqueue: bool = True,
    ) -> dict[str, Any]:
        signal_id = self.signal_id(snapshot)
        existing = self.ledger.events(signal_id)
        payload = {
            **snapshot,
            "control_allowed": controls.allowed,
            "control_failures": list(controls.hard_failures),
            "control_warnings": list(controls.warnings),
        }
        if not existing:
            event_type = "SIGNAL_CREATED" if controls.allowed else "SIGNAL_REJECTED"
            self.ledger.append(event_type, signal_id, payload, created_at=now)
        if not controls.allowed:
            return {"signal_id": signal_id, "created": not existing, "queued": False}

        if not enqueue:
            return {"signal_id": signal_id, "created": not existing, "queued": False}

        queued = self.outbox.enqueue(
            idempotency_key=signal_id,
            signal_id=signal_id,
            payload=message,
            now=now,
        )
        return {
            "signal_id": signal_id,
            "created": not existing,
            "queued": True,
            "message_id": queued["message_id"],
        }

    def deliver_due(
        self,
        sender: Callable[[str], Any],
        *,
        now: str | datetime,
        limit: int = 100,
    ) -> dict[str, int]:
        def acknowledged(message: dict[str, Any], ack: Any) -> None:
            provider_id = ack.get("message_id") if isinstance(ack, dict) else ack.message_id
            if not any(
                event["event_type"] == "DELIVERY_ACKNOWLEDGED"
                for event in self.ledger.events(message["signal_id"])
            ):
                self.ledger.append(
                    "DELIVERY_ACKNOWLEDGED",
                    message["signal_id"],
                    {"provider_message_id": str(provider_id), "outbox_message_id": message["message_id"]},
                    created_at=now,
                )

        def failed(message: dict[str, Any], exc: Exception, status: str) -> None:
            event_type = f"DELIVERY_FAILED_{int(message['attempt_count']) + 1}"
            if not any(event["event_type"] == event_type for event in self.ledger.events(message["signal_id"])):
                self.ledger.append(
                    event_type,
                    message["signal_id"],
                    {"error": str(exc), "status": status, "outbox_message_id": message["message_id"]},
                    created_at=now,
                )

        return self.outbox.deliver_due(
            sender,
            now=now,
            limit=limit,
            on_delivered=acknowledged,
            on_failed=failed,
        )
