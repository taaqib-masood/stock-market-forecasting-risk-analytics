"""Bounded operator CLI for acquiring raw NSE archives."""

from __future__ import annotations

import argparse
import calendar
import json
from datetime import date
from pathlib import Path

from src.reliability.nse_acquisition import (
    ArchiveDownloader,
    DownloadSpec,
    legacy_bhavcopy_spec,
    plan_weekdays,
    security_master_spec,
    udiff_bhavcopy_spec,
)


UDIFF_CUTOVER = date(2024, 7, 8)
MAX_RANGE_DAYS = 31


def monthly_ranges(start: date, end: date) -> list[tuple[date, date]]:
    if end < start:
        raise ValueError("end date must be on or after start date")
    output = []
    cursor = start
    while cursor <= end:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        chunk_end = min(month_end, end)
        output.append((cursor, chunk_end))
        cursor = date.fromordinal(chunk_end.toordinal() + 1)
    return output


def parse_date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("dates must use YYYY-MM-DD")
    return parsed


def build_specs(
    source: str,
    start: date,
    end: date,
    holidays: set[date],
    template: str | None = None,
) -> list[DownloadSpec]:
    specs = []
    for day in plan_weekdays(start, end, holidays):
        if source == "bhavcopy":
            if day < UDIFF_CUTOVER:
                specs.append(legacy_bhavcopy_spec(day))
            else:
                specs.append(udiff_bhavcopy_spec(day, template) if template else udiff_bhavcopy_spec(day))
        elif source == "security_master":
            specs.append(security_master_spec(day, template) if template else security_master_spec(day))
        else:
            raise ValueError(f"unsupported source: {source}")
    return specs


def run(
    source: str,
    start: date,
    end: date,
    output: str | Path,
    delay_seconds: float,
    holidays: set[date],
    template: str | None,
    dry_run: bool,
) -> list[dict]:
    if end < start or (end - start).days >= MAX_RANGE_DAYS:
        raise ValueError("acquisition must use an ordered range of at most 31 days")
    if delay_seconds <= 0:
        raise ValueError("rate delay must be positive")
    specs = build_specs(source, start, end, holidays, template)
    if dry_run:
        return [{
            "status": "planned",
            "kind": spec.kind,
            "session_date": spec.session_date.isoformat(),
            "url": spec.url,
            "filename": spec.filename,
        } for spec in specs]

    downloader = ArchiveDownloader(output)
    results = downloader.acquire_range(specs, delay_seconds=delay_seconds)
    return [{
        "status": result.status,
        "kind": result.spec.kind,
        "session_date": result.spec.session_date.isoformat(),
        "url": result.spec.url,
        "archive_path": str(result.archive_path) if result.archive_path else None,
        "extracted_paths": [str(path) for path in result.extracted_paths],
        "sha256": result.sha256,
        "bytes": result.byte_count,
    } for result in results]


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire retained, integrity-checked NSE reports")
    parser.add_argument("source", choices=("bhavcopy", "security_master"))
    parser.add_argument("--start", required=True, type=parse_date)
    parser.add_argument("--end", required=True, type=parse_date)
    parser.add_argument("--output", default="data/reliability/raw")
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--holiday", action="append", default=[], type=parse_date)
    parser.add_argument("--url-template", help="Override source URL; supports {filename} and {date}")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = run(
        args.source,
        args.start,
        args.end,
        args.output,
        args.delay_seconds,
        set(args.holiday),
        args.url_template,
        args.dry_run,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
