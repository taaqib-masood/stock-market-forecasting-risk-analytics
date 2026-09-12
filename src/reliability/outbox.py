"""Transactional outbox for idempotent, retryable alert delivery."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


def _dt(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: str | datetime) -> str:
    return _dt(value).isoformat(timespec="seconds")


class DeliveryOutbox:
    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        max_attempts: int = 5,
        base_delay_seconds: int = 60,
        lease_seconds: int = 300,
    ):
        if max_attempts < 1 or base_delay_seconds < 1 or lease_seconds < 1:
            raise ValueError("outbox limits must be positive")
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.lease_seconds = lease_seconds
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS delivery_outbox (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL UNIQUE,
                signal_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                lease_until TEXT,
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                provider_message_id TEXT,
                last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_delivery_due
                ON delivery_outbox(status, next_attempt_at, lease_until);
            """
        )
        self.connection.commit()

    def enqueue(
        self,
        idempotency_key: str,
        signal_id: str,
        payload: str,
        *,
        now: str | datetime,
    ) -> dict[str, Any]:
        timestamp = _iso(now)
        created = False
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO delivery_outbox
                    (idempotency_key, signal_id, payload, status, next_attempt_at, created_at)
                VALUES (?, ?, ?, 'QUEUED', ?, ?)
                """,
                (idempotency_key, signal_id, payload, timestamp, timestamp),
            )
            created = cursor.rowcount == 1
        row = self.connection.execute(
            "SELECT message_id FROM delivery_outbox WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return {"message_id": row["message_id"], "created": created}

    def claim_due(self, now: str | datetime, limit: int = 100) -> list[dict[str, Any]]:
        timestamp = _iso(now)
        lease_until = _iso(_dt(now) + timedelta(seconds=self.lease_seconds))
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            rows = self.connection.execute(
                """
                SELECT * FROM delivery_outbox
                WHERE (
                    status IN ('QUEUED', 'RETRYING') AND next_attempt_at <= ?
                ) OR (
                    status = 'SENDING' AND lease_until <= ?
                )
                ORDER BY message_id LIMIT ?
                """,
                (timestamp, timestamp, int(limit)),
            ).fetchall()
            if not rows:
                self.connection.commit()
                return []
            ids = [row["message_id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            self.connection.execute(
                f"UPDATE delivery_outbox SET status = 'SENDING', lease_until = ? "
                f"WHERE message_id IN ({placeholders})",
                (lease_until, *ids),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return [dict(row) for row in rows]

    def mark_delivered(
        self,
        message_id: int,
        provider_message_id: str,
        *,
        now: str | datetime,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE delivery_outbox
                SET status = 'DELIVERED', attempt_count = attempt_count + 1,
                    delivered_at = ?, provider_message_id = ?, lease_until = NULL,
                    last_error = NULL
                WHERE message_id = ?
                """,
                (_iso(now), str(provider_message_id), int(message_id)),
            )

    def mark_failed(self, message_id: int, error: str, *, now: str | datetime) -> str:
        row = self.connection.execute(
            "SELECT attempt_count FROM delivery_outbox WHERE message_id = ?", (message_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown outbox message {message_id}")
        attempts = int(row["attempt_count"]) + 1
        if attempts >= self.max_attempts:
            status = "DEAD_LETTER"
            next_attempt = _iso(now)
        else:
            status = "RETRYING"
            delay = self.base_delay_seconds * (2 ** (attempts - 1))
            next_attempt = _iso(_dt(now) + timedelta(seconds=delay))
        with self.connection:
            self.connection.execute(
                """
                UPDATE delivery_outbox
                SET status = ?, attempt_count = ?, next_attempt_at = ?, lease_until = NULL,
                    last_error = ?
                WHERE message_id = ?
                """,
                (status, attempts, next_attempt, str(error)[:1000], int(message_id)),
            )
        return status

    def mark_unreconciled(self, message_id: int, error: str) -> None:
        """Record a provider-acknowledged message whose audit callback failed."""
        with self.connection:
            self.connection.execute(
                """
                UPDATE delivery_outbox
                SET status = 'DELIVERED_UNRECONCILED', last_error = ?, lease_until = NULL
                WHERE message_id = ? AND status = 'DELIVERED'
                """,
                (str(error)[:1000], int(message_id)),
            )

    def deliver_due(
        self,
        sender: Callable[[str], Any],
        *,
        now: str | datetime,
        limit: int = 100,
        on_delivered: Callable[[dict[str, Any], Any], None] | None = None,
        on_failed: Callable[[dict[str, Any], Exception, str], None] | None = None,
    ) -> dict[str, int]:
        result = {"delivered": 0, "failed": 0, "dead_letter": 0}
        for message in self.claim_due(now, limit=limit):
            try:
                acknowledgement = sender(message["payload"])
                if isinstance(acknowledgement, dict):
                    provider_id = acknowledgement.get("message_id")
                else:
                    provider_id = getattr(acknowledgement, "message_id", None)
                if provider_id is None:
                    raise RuntimeError("provider did not acknowledge a message_id")
            except Exception as exc:
                status = self.mark_failed(message["message_id"], str(exc), now=now)
                if on_failed is not None:
                    on_failed(message, exc, status)
                if status == "DEAD_LETTER":
                    result["dead_letter"] += 1
                else:
                    result["failed"] += 1
                continue

            self.mark_delivered(message["message_id"], str(provider_id), now=now)
            if on_delivered is not None:
                try:
                    on_delivered(message, acknowledgement)
                except Exception as exc:
                    self.mark_unreconciled(message["message_id"], str(exc))
                    result["unreconciled"] = result.get("unreconciled", 0) + 1
                    continue
            result["delivered"] += 1
        return result

    def metrics(self) -> dict[str, float | int]:
        rows = self.connection.execute(
            "SELECT status, COUNT(*) AS count FROM delivery_outbox GROUP BY status"
        ).fetchall()
        counts = {row["status"]: int(row["count"]) for row in rows}
        delivered = counts.get("DELIVERED", 0)
        dead = counts.get("DEAD_LETTER", 0)
        unreconciled = counts.get("DELIVERED_UNRECONCILED", 0)
        final = delivered + dead + unreconciled
        return {
            "total": sum(counts.values()),
            "queued": counts.get("QUEUED", 0),
            "retrying": counts.get("RETRYING", 0) + counts.get("SENDING", 0),
            "delivered": delivered,
            "dead_letter": dead,
            "unreconciled": unreconciled,
            "acknowledged_delivery_rate": delivered / final if final else 0.0,
        }
