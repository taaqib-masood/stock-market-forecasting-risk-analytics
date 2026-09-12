"""Explicit-consent Telegram audience registry for future approved releases."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CHAT_ID = re.compile(r"-?\d+\Z")


class TelegramAudienceError(ValueError):
    """A subscriber record would be invalid or ambiguous."""


def _iso(value: str | datetime) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


class TelegramAudience:
    """SQLite-backed consent and revocation state for Telegram recipients."""

    def __init__(self, database: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(database, sqlite3.Connection)
        if self._owns_connection:
            path = Path(database)
            if str(database) != ":memory:":
                path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(str(database))
        else:
            self.connection = database
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS telegram_subscribers (
                chat_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'REVOKED')),
                consent_version TEXT NOT NULL,
                consented_at TEXT NOT NULL,
                revoked_at TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_telegram_subscribers_status
                ON telegram_subscribers(status, chat_id);
            CREATE TABLE IF NOT EXISTS telegram_updates (
                update_id INTEGER PRIMARY KEY,
                received_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def claim_update(self, update_id: int, *, now: str | datetime) -> bool:
        """Claim a Telegram update once; provider retries return ``False``."""
        try:
            value = int(update_id)
        except (TypeError, ValueError) as error:
            raise TelegramAudienceError("Telegram update ID must be an integer") from error
        if value < 0:
            raise TelegramAudienceError("Telegram update ID must be non-negative")
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO telegram_updates (update_id, received_at) VALUES (?, ?)",
                (value, _iso(now)),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _validate_chat_id(chat_id: str) -> str:
        value = str(chat_id).strip()
        if not _CHAT_ID.fullmatch(value):
            raise TelegramAudienceError("chat ID must be a numeric Telegram ID")
        return value

    def subscribe(
        self, chat_id: str, consent_version: str, *, now: str | datetime
    ) -> dict[str, Any]:
        normalized = self._validate_chat_id(chat_id)
        version = str(consent_version).strip()
        if not version:
            raise TelegramAudienceError("consent version is required")
        timestamp = _iso(now)
        exists = self.connection.execute(
            "SELECT 1 FROM telegram_subscribers WHERE chat_id = ?", (normalized,)
        ).fetchone() is not None
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO telegram_subscribers
                    (chat_id, status, consent_version, consented_at, revoked_at, updated_at)
                VALUES (?, 'ACTIVE', ?, ?, NULL, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    status = 'ACTIVE', consent_version = excluded.consent_version,
                    consented_at = excluded.consented_at, revoked_at = NULL,
                    updated_at = excluded.updated_at
                """,
                (normalized, version, timestamp, timestamp),
            )
        return {"chat_id": normalized, "status": "ACTIVE", "created": not exists}

    def revoke(self, chat_id: str, *, now: str | datetime) -> bool:
        normalized = self._validate_chat_id(chat_id)
        timestamp = _iso(now)
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE telegram_subscribers
                SET status = 'REVOKED', revoked_at = ?, updated_at = ?
                WHERE chat_id = ? AND status = 'ACTIVE'
                """,
                (timestamp, timestamp, normalized),
            )
        return cursor.rowcount == 1

    def active_chat_ids(self, consent_version: str | None = None) -> list[str]:
        return [record["chat_id"] for record in self.active_subscribers(consent_version)]

    def active_subscribers(self, consent_version: str | None = None) -> list[dict[str, str]]:
        """Return active recipients with the exact consent version bound to them."""
        query = """
            SELECT chat_id, consent_version, consented_at
            FROM telegram_subscribers
            WHERE status = 'ACTIVE'
        """
        params: tuple[str, ...] = ()
        if consent_version is not None:
            query += " AND consent_version = ?"
            params = (str(consent_version).strip(),)
        query += " ORDER BY chat_id"
        rows = self.connection.execute(query, params).fetchall()
        return [
            {
                "chat_id": str(row["chat_id"]),
                "consent_version": str(row["consent_version"]),
                "consented_at": str(row["consented_at"]),
            }
            for row in rows
        ]

    def consent_is_active(self, chat_id: str, consent_version: str) -> bool:
        normalized = self._validate_chat_id(chat_id)
        row = self.connection.execute(
            """
            SELECT 1 FROM telegram_subscribers
            WHERE chat_id = ? AND status = 'ACTIVE' AND consent_version = ?
            """,
            (normalized, str(consent_version).strip()),
        ).fetchone()
        return row is not None

    @staticmethod
    def idempotency_key(signal_id: str, chat_id: str) -> str:
        normalized = TelegramAudience._validate_chat_id(chat_id)
        signal = str(signal_id).strip()
        if not signal:
            raise TelegramAudienceError("signal ID is required")
        digest = hashlib.sha256(f"{signal}\0{normalized}".encode()).hexdigest()[:32]
        return f"telegram:{signal}:{digest}"

    def close(self) -> None:
        if self._owns_connection:
            self.connection.close()

    def __enter__(self) -> "TelegramAudience":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
