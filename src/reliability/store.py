"""SQLite-backed point-in-time market and compliance data store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


def _utc(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        text = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: str | date | datetime) -> str:
    return _utc(value).isoformat(timespec="seconds")


class ReliabilityStore:
    """Owns versioned records whose visibility is constrained by ``available_at``."""

    def __init__(self, path: str | Path = "results/reliability.db"):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS manifests (
                content_hash TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                available_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memberships (
                symbol TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                available_at TEXT NOT NULL,
                manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash),
                PRIMARY KEY (symbol, valid_from, available_at)
            );
            CREATE TABLE IF NOT EXISTS bars (
                symbol TEXT NOT NULL,
                session_date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                available_at TEXT NOT NULL,
                manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash),
                PRIMARY KEY (symbol, session_date, available_at)
            );
            CREATE TABLE IF NOT EXISTS corporate_actions (
                symbol TEXT NOT NULL,
                action_type TEXT NOT NULL,
                ex_date TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                available_at TEXT NOT NULL,
                manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash),
                PRIMARY KEY (symbol, action_type, ex_date, available_at)
            );
            CREATE TABLE IF NOT EXISTS fundamentals (
                symbol TEXT NOT NULL,
                period_end TEXT NOT NULL,
                debt_to_assets REAL,
                interest_income_ratio REAL,
                payload_json TEXT NOT NULL,
                available_at TEXT NOT NULL,
                manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash),
                PRIMARY KEY (symbol, period_end, available_at)
            );
            CREATE TABLE IF NOT EXISTS business_classifications (
                symbol TEXT NOT NULL,
                business_type TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                methodology_version TEXT NOT NULL,
                reason TEXT NOT NULL,
                available_at TEXT NOT NULL,
                manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash),
                PRIMARY KEY (symbol, effective_from, available_at, methodology_version)
            );
            CREATE TABLE IF NOT EXISTS halal_classifications (
                symbol TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                tier TEXT NOT NULL,
                tradeable INTEGER NOT NULL,
                ruleset_version TEXT NOT NULL,
                reason TEXT,
                available_at TEXT NOT NULL,
                manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash),
                PRIMARY KEY (symbol, effective_from, available_at, ruleset_version)
            );
            CREATE INDEX IF NOT EXISTS idx_membership_asof
                ON memberships(symbol, valid_from, valid_to, available_at);
            CREATE INDEX IF NOT EXISTS idx_halal_asof
                ON halal_classifications(symbol, effective_from, available_at);
            CREATE INDEX IF NOT EXISTS idx_business_asof
                ON business_classifications(symbol, effective_from, available_at);
            """
        )
        self.connection.commit()

    def register_manifest(
        self,
        source: str,
        content: bytes,
        available_at: str | date | datetime,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        digest = hashlib.sha256(content).hexdigest()
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO manifests VALUES (?, ?, ?, ?)",
                (digest, source, _iso(available_at), json.dumps(metadata or {}, sort_keys=True)),
            )
        return digest

    def manifest(self, content_hash: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM manifests WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if row is None:
            return None
        return {
            "content_hash": row["content_hash"],
            "source": row["source"],
            "available_at": row["available_at"],
            "metadata": json.loads(row["metadata_json"]),
        }

    def put_membership(
        self,
        symbol: str,
        valid_from: str | date | datetime,
        available_at: str | date | datetime,
        manifest_hash: str,
        valid_to: str | date | datetime | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO memberships VALUES (?, ?, ?, ?, ?)",
                (symbol.upper(), _iso(valid_from), _iso(valid_to) if valid_to else None,
                 _iso(available_at), manifest_hash),
            )

    def put_bar(
        self,
        symbol: str,
        session_date: str | date | datetime,
        open_: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        available_at: str | date | datetime,
        manifest_hash: str,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (symbol.upper(), _iso(session_date), float(open_), float(high), float(low),
                 float(close), float(volume), _iso(available_at), manifest_hash),
            )

    def put_bars(self, rows: list[dict[str, Any]], manifest_hash: str) -> None:
        values = [(
            row["symbol"].upper(), _iso(row["session_date"]), float(row["open"]),
            float(row["high"]), float(row["low"]), float(row["close"]),
            float(row["volume"]), _iso(row["available_at"]), manifest_hash,
        ) for row in rows]
        with self.connection:
            self.connection.executemany(
                "INSERT OR IGNORE INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", values
            )

    def put_corporate_action(
        self,
        symbol: str,
        action_type: str,
        ex_date: str | date | datetime,
        payload: dict[str, Any],
        available_at: str | date | datetime,
        manifest_hash: str,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO corporate_actions VALUES (?, ?, ?, ?, ?, ?)",
                (symbol.upper(), action_type.upper(), _iso(ex_date),
                 json.dumps(payload, sort_keys=True), _iso(available_at), manifest_hash),
            )

    def put_fundamental(
        self,
        symbol: str,
        period_end: str | date | datetime,
        available_at: str | date | datetime,
        manifest_hash: str,
        debt_to_assets: float | None = None,
        interest_income_ratio: float | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO fundamentals VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol.upper(), _iso(period_end), debt_to_assets, interest_income_ratio,
                 json.dumps(payload or {}, sort_keys=True), _iso(available_at), manifest_hash),
            )

    def put_halal_classification(
        self,
        symbol: str,
        effective_from: str | date | datetime,
        tier: str,
        tradeable: bool,
        ruleset_version: str,
        available_at: str | date | datetime,
        manifest_hash: str,
        reason: str = "",
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO halal_classifications VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (symbol.upper(), _iso(effective_from), tier.upper(), int(tradeable),
                ruleset_version, reason, _iso(available_at), manifest_hash),
            )

    def put_business_classification(
        self,
        symbol: str,
        business_type: str,
        effective_from: str | date | datetime,
        methodology_version: str,
        available_at: str | date | datetime,
        manifest_hash: str,
        reason: str,
    ) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT OR IGNORE INTO business_classifications VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol.upper(), business_type.upper(), _iso(effective_from),
                 methodology_version, reason, _iso(available_at), manifest_hash),
            )

    def eligible_universe(self, as_of: str | date | datetime) -> list[str]:
        point = _iso(as_of)
        rows = self.connection.execute(
            """
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY symbol, valid_from ORDER BY available_at DESC
                ) AS revision_rank
                FROM memberships
                WHERE available_at <= ?
            )
            SELECT DISTINCT symbol FROM ranked
            WHERE revision_rank = 1 AND valid_from <= ?
              AND (valid_to IS NULL OR valid_to > ?)
            ORDER BY symbol
            """,
            (point, point, point),
        ).fetchall()
        return [row["symbol"] for row in rows]

    def tradable_universe(
        self,
        session_date: str | date | datetime,
        as_of: str | date | datetime,
    ) -> list[str]:
        """Return symbols with an EQ bar retained and visible for one exact session."""
        rows = self.connection.execute(
            """
            WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY symbol, session_date ORDER BY available_at DESC
                ) AS revision_rank
                FROM bars
                WHERE session_date = ? AND available_at <= ?
            )
            SELECT symbol FROM ranked WHERE revision_rank = 1 ORDER BY symbol
            """,
            (_iso(session_date), _iso(as_of)),
        ).fetchall()
        return [row["symbol"] for row in rows]

    def halal_as_of(
        self,
        symbol: str,
        as_of: str | date | datetime,
        max_age_days: int | None = None,
    ) -> dict[str, Any]:
        point = _iso(as_of)
        row = self.connection.execute(
            """
            SELECT * FROM halal_classifications
            WHERE symbol = ? AND effective_from <= ? AND available_at <= ?
            ORDER BY effective_from DESC, available_at DESC LIMIT 1
            """,
            (symbol.upper(), point, point),
        ).fetchone()
        if row is None:
            return {
                "symbol": symbol.upper(), "tier": "UNKNOWN", "tradeable": False,
                "reason": "no point-in-time halal classification",
            }

        result = {
            "symbol": row["symbol"],
            "tier": row["tier"],
            "tradeable": bool(row["tradeable"]),
            "reason": row["reason"],
            "effective_from": row["effective_from"],
            "available_at": row["available_at"],
            "ruleset_version": row["ruleset_version"],
            "manifest_hash": row["manifest_hash"],
        }
        if max_age_days is not None:
            age = _utc(as_of) - _utc(row["available_at"])
            if age.total_seconds() > max_age_days * 86400:
                result["tradeable"] = False
                result["reason"] = "halal classification is stale"
        return result

    def business_as_of(
        self,
        symbol: str,
        as_of: str | date | datetime,
    ) -> dict[str, Any]:
        point = _iso(as_of)
        row = self.connection.execute(
            """
            SELECT * FROM business_classifications
            WHERE symbol = ? AND effective_from <= ? AND available_at <= ?
            ORDER BY effective_from DESC, available_at DESC LIMIT 1
            """,
            (symbol.upper(), point, point),
        ).fetchone()
        if row is None:
            return {
                "symbol": symbol.upper(),
                "business_type": "UNKNOWN",
                "reason": "no point-in-time business classification",
            }
        return {
            "symbol": row["symbol"],
            "business_type": row["business_type"],
            "effective_from": row["effective_from"],
            "available_at": row["available_at"],
            "methodology_version": row["methodology_version"],
            "manifest_hash": row["manifest_hash"],
            "reason": row["reason"],
        }

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ReliabilityStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
