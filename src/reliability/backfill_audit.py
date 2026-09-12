"""Reconcile expected NSE sessions against retained acquisition evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from src.reliability.nse_acquisition import existing_weekdays


def audit_backfill(
    catalogue_path: str | Path,
    kind: str,
    start: date,
    end: date,
    holidays: set[date] | None = None,
) -> dict:
    catalogue_path = Path(catalogue_path)
    holidays = holidays or set()
    latest: dict[str, dict] = {}
    if catalogue_path.exists():
        for number, line in enumerate(catalogue_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"invalid catalogue JSON at line {number}") from exc
            session = record.get("session_date")
            if record.get("kind") == kind and session:
                latest[session] = record

    sessions: dict[str, str] = {}
    expected = 0
    counts = {"expected": 0, "complete": 0, "missing_report": 0,
              "failed": 0, "absent": 0, "integrity_failure": 0}
    for day in existing_weekdays(start, end):
        key = day.isoformat()
        if day in holidays:
            sessions[key] = "holiday"
            continue
        expected += 1
        record = latest.get(key)
        if record is None:
            status = "absent"
        elif record.get("status") in ("downloaded", "cached"):
            status = "complete" if _record_integrity(record, catalogue_path.parent) else "integrity_failure"
        elif record.get("status") == "missing_report":
            status = "missing_report"
        else:
            status = "failed"
        sessions[key] = status
        counts[status] += 1
    counts["expected"] = expected
    blockers = [name.upper() for name in ("missing_report", "failed", "absent", "integrity_failure")
                if counts[name]]
    return {
        "kind": kind, "start": start.isoformat(), "end": end.isoformat(),
        "complete": counts["complete"] == expected and not blockers,
        "counts": counts, "blockers": blockers, "sessions": sessions,
    }


def _record_integrity(record: dict, catalogue_parent: Path) -> bool:
    value = record.get("archive_path") or record.get("path")
    expected = record.get("sha256")
    if not value or not expected:
        return False
    path = Path(value)
    if not path.exists() and not path.is_absolute():
        candidate = catalogue_parent / path
        if candidate.exists():
            path = candidate
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit NSE backfill completeness")
    parser.add_argument("catalogue")
    parser.add_argument("kind")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--holiday", action="append", default=[], type=date.fromisoformat)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit_backfill(args.catalogue, args.kind, args.start, args.end, set(args.holiday))
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not result["complete"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
