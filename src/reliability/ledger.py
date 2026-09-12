"""Append-only, hash-chained signal lifecycle ledger."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _timestamp(value: str | datetime | None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _event_hash(
    previous_hash: str,
    event_type: str,
    signal_id: str,
    created_at: str,
    payload_json: str,
) -> str:
    material = "|".join((previous_hash, event_type, signal_id, created_at, payload_json))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class SignalLedger:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS signal_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                UNIQUE(signal_id, event_type)
            );
            CREATE INDEX IF NOT EXISTS idx_signal_events_signal
                ON signal_events(signal_id, event_id);
            CREATE TRIGGER IF NOT EXISTS signal_events_no_update
            BEFORE UPDATE ON signal_events
            BEGIN
                SELECT RAISE(ABORT, 'signal_events is append-only');
            END;
            CREATE TRIGGER IF NOT EXISTS signal_events_no_delete
            BEFORE DELETE ON signal_events
            BEGIN
                SELECT RAISE(ABORT, 'signal_events is append-only');
            END;
            """
        )
        self.connection.commit()

    def append(
        self,
        event_type: str,
        signal_id: str,
        payload: dict[str, Any],
        *,
        created_at: str | datetime | None = None,
    ) -> str:
        event_type = event_type.strip().upper()
        signal_id = signal_id.strip()
        if not event_type or not signal_id:
            raise ValueError("event_type and signal_id are required")
        payload_json = _canonical(payload)
        timestamp = _timestamp(created_at)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT event_hash FROM signal_events ORDER BY event_id DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous["event_hash"] if previous else "0" * 64
            digest = _event_hash(previous_hash, event_type, signal_id, timestamp, payload_json)
            self.connection.execute(
                """
                INSERT INTO signal_events
                    (signal_id, event_type, created_at, payload_json, previous_hash, event_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (signal_id, event_type, timestamp, payload_json, previous_hash, digest),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as exc:
            self.connection.rollback()
            raise ValueError(f"{event_type} already exists for signal {signal_id}") from exc
        except Exception:
            self.connection.rollback()
            raise
        return digest

    def events(self, signal_id: str | None = None) -> list[dict[str, Any]]:
        if signal_id is None:
            rows = self.connection.execute(
                "SELECT * FROM signal_events ORDER BY event_id"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM signal_events WHERE signal_id = ? ORDER BY event_id",
                (signal_id,),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "signal_id": row["signal_id"],
                "event_type": row["event_type"],
                "created_at": row["created_at"],
                "payload": json.loads(row["payload_json"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
            }
            for row in rows
        ]

    def verify_chain(self) -> dict[str, Any]:
        rows = self.connection.execute(
            "SELECT * FROM signal_events ORDER BY event_id"
        ).fetchall()
        expected_previous = "0" * 64
        for row in rows:
            expected_hash = _event_hash(
                expected_previous,
                row["event_type"],
                row["signal_id"],
                row["created_at"],
                row["payload_json"],
            )
            if row["previous_hash"] != expected_previous or row["event_hash"] != expected_hash:
                return {"valid": False, "events": len(rows), "broken_at": row["event_id"]}
            expected_previous = row["event_hash"]
        return {"valid": True, "events": len(rows), "broken_at": None}
