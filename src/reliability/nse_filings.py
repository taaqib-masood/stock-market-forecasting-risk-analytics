"""Operator CLI for retained NSE corporate actions and financial XBRL filings."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

from src.reliability.nse_api_acquisition import (
    ApiSnapshotAcquirer,
    annual_reports_request,
    corporate_actions_request,
    financial_results_request,
    financial_results_range_request,
)
from src.reliability.nse_normalizers import normalize_financial_result_index
from src.reliability.filing_coverage import execute_download_manifest
from src.reliability.xbrl import XbrlAcquirer, parse_halal_financial_facts


def acquire_index_documents(
    index_path: str | Path,
    output_path: str | Path,
    *,
    limit: int,
    delay_seconds: float = 2.0,
    acquirer: XbrlAcquirer | None = None,
) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError("XBRL limit must be between 1 and 100")
    if delay_seconds < 0:
        raise ValueError("delay cannot be negative")
    index_path = Path(index_path)
    output_path = Path(output_path)
    acquirer = acquirer or XbrlAcquirer(output_path.parent)
    filings = normalize_financial_result_index(index_path)
    selected = []
    seen = set()
    for filing in filings:
        url = filing.get("xbrl_url")
        key = (filing["symbol"], filing["period_end"], url)
        if not url or key in seen:
            continue
        seen.add(key)
        selected.append(filing)
        if len(selected) == limit:
            break

    facts = []
    failures = []
    for position, filing in enumerate(selected):
        if position:
            time.sleep(delay_seconds)
        try:
            document = acquirer.acquire(filing["xbrl_url"])
            facts.append(parse_halal_financial_facts(
                document.path,
                symbol=filing["symbol"],
                period_end=filing["period_end"],
                available_at=filing["available_at"],
            ))
        except Exception as exc:
            failures.append({"symbol": filing["symbol"], "url": filing["xbrl_url"],
                             "error": str(exc)})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"selected": len(selected), "downloaded": len(facts), "failures": failures,
            "output": str(output_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire NSE filing evidence")
    parser.add_argument("--output", default="data/reliability/raw")
    sub = parser.add_subparsers(dest="command", required=True)

    actions = sub.add_parser("actions")
    actions.add_argument("--start", required=True, type=date.fromisoformat)
    actions.add_argument("--end", required=True, type=date.fromisoformat)

    results = sub.add_parser("results")
    results.add_argument("--period", choices=("Quarterly", "Annual", "Half-Yearly", "Others"),
                         default="Annual")
    results.add_argument("--start", type=date.fromisoformat)
    results.add_argument("--end", type=date.fromisoformat)

    xbrl = sub.add_parser("xbrl")
    xbrl.add_argument("--index", required=True)
    xbrl.add_argument("--facts-output", required=True)
    xbrl.add_argument("--limit", required=True, type=int)
    xbrl.add_argument("--delay-seconds", type=float, default=2.0)

    batch = sub.add_parser("xbrl-manifest")
    batch.add_argument("--manifest", required=True)
    batch.add_argument("--facts-output", required=True)
    batch.add_argument("--delay-seconds", type=float, default=2.0)

    annual_reports = sub.add_parser("annual-reports")
    annual_reports.add_argument("--symbol", required=True)
    args = parser.parse_args()

    if args.command == "xbrl-manifest":
        report = execute_download_manifest(
            args.manifest, args.facts_output, delay_seconds=args.delay_seconds,
            acquirer=XbrlAcquirer(args.output),
        )
    elif args.command == "xbrl":
        report = acquire_index_documents(
            args.index, args.facts_output, limit=args.limit,
            delay_seconds=args.delay_seconds, acquirer=XbrlAcquirer(args.output),
        )
    else:
        acquirer = ApiSnapshotAcquirer(args.output)
        if args.command == "annual-reports":
            request = annual_reports_request(args.symbol, date.today())
        elif args.command == "actions":
            request = corporate_actions_request(args.start, args.end)
        elif args.start or args.end:
            if not args.start or not args.end:
                parser.error("results requires both --start and --end")
            request = financial_results_range_request(args.start, args.end, args.period)
        else:
            request = financial_results_request(date.today(), args.period)
        result = acquirer.acquire(request)
        report = {"status": result.status, "path": str(result.path),
                  "sha256": result.sha256, "bytes": result.byte_count,
                  "available_at": result.available_at}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
