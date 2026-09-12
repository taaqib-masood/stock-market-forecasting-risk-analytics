"""Audit a survivorship-free daily tradable universe from retained bhavcopies."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.reliability.nse_normalizers import normalize_bhavcopy


def audit_tradable_universe(
    paths: list[str | Path],
    *,
    current_symbols: set[str],
) -> dict:
    history: dict[str, dict] = {}
    sessions = set()
    source_hashes = []
    for value in sorted(map(Path, paths)):
        content = value.read_bytes()
        source_hashes.append({"filename": value.name,
                              "sha256": hashlib.sha256(content).hexdigest()})
        for row in normalize_bhavcopy(value, available_at="2100-01-01T00:00:00Z"):
            symbol = row["symbol"]
            day = row["session_date"]
            sessions.add(day)
            record = history.setdefault(symbol, {
                "first_seen": day, "last_seen": day, "sessions": 0
            })
            record["first_seen"] = min(record["first_seen"], day)
            record["last_seen"] = max(record["last_seen"], day)
            record["sessions"] += 1
    observed = set(history)
    return {
        "sessions": len(sessions),
        "unique_symbols": len(observed),
        "historical_not_current": sorted(observed - current_symbols),
        "current_not_historical": sorted(current_symbols - observed),
        "symbol_history": dict(sorted(history.items())),
        "source_files": source_hashes,
    }
