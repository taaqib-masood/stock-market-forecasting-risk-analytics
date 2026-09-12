"""Resumable monthly acquisition of paired NSE action and announcement evidence."""

from __future__ import annotations

import argparse
import calendar
import json
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from src.reliability.nse_api_acquisition import (
    ApiSnapshotAcquirer,
    corporate_actions_request,
    corporate_announcements_request,
)


def monthly_ranges(start: date, end: date) -> list[tuple[date, date]]:
    if end < start:
        raise ValueError("end must be on or after start")
    ranges = []
    cursor = start
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        month_end = min(end, date(cursor.year, cursor.month, last_day))
        ranges.append((cursor, month_end))
        cursor = month_end + timedelta(days=1)
    return ranges


def backfill_pairs(
    acquirer: ApiSnapshotAcquirer,
    start: date,
    end: date,
    *,
    delay_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")
    requests = []
    for range_start, range_end in monthly_ranges(start, end):
        requests.extend((
            corporate_actions_request(range_start, range_end),
            corporate_announcements_request(range_start, range_end),
        ))

    output = []
    for index, request in enumerate(requests):
        result = acquirer.acquire(request)
        output.append({
            "period": request.snapshot_date.strftime("%Y-%m"),
            "kind": request.kind,
            "status": result.status,
            "path": str(result.path),
            "sha256": result.sha256,
            "bytes": result.byte_count,
            "available_at": result.available_at,
        })
        if index + 1 < len(requests) and delay_seconds:
            sleep(delay_seconds)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill paired NSE corporate-action evidence")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--output", default="data/reliability/corporate-actions-historical")
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--report")
    args = parser.parse_args()
    result = backfill_pairs(
        ApiSnapshotAcquirer(args.output),
        args.start,
        args.end,
        delay_seconds=args.delay_seconds,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report:
        destination = Path(args.report)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
