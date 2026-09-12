"""Generate an NSE bundle-pipeline config from verified acquisition records."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


def build_pipeline_config(
    catalogue_path: str | Path, start: date, end: date,
    *, financials: list[str | Path] | None = None,
) -> dict:
    catalogue_path = Path(catalogue_path)
    latest: dict[tuple[str, str], dict] = {}
    if catalogue_path.exists():
        for number, line in enumerate(catalogue_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"invalid catalogue JSON at line {number}") from exc
            session = record.get("session_date")
            if session and record.get("kind") in ("security_master", "bhavcopy"):
                latest[(record["kind"], session)] = record

    security_candidates = []
    bhavcopies = []
    for (kind, session), record in latest.items():
        day = date.fromisoformat(session)
        path = _extracted_file(record)
        if record.get("status") not in ("downloaded", "cached") or path is None:
            continue
        if kind == "security_master" and day <= end:
            security_candidates.append((day, path))
        elif kind == "bhavcopy" and start <= day <= end:
            bhavcopies.append({"path": str(path), "available_at": f"{session}T18:00:00Z"})

    security_snapshots = []
    if security_candidates:
        day, path = max(security_candidates, key=lambda item: item[0])
        security_snapshots.append({
            "path": str(path), "snapshot_date": day.isoformat(),
            "available_at": f"{day.isoformat()}T03:00:00Z",
        })
    bhavcopies.sort(key=lambda item: item["available_at"])
    blockers = []
    if not security_snapshots:
        blockers.append("SECURITY_SNAPSHOT_ABSENT")
    if not bhavcopies:
        blockers.append("BHAVCOPY_ABSENT")
    base = catalogue_path.parent.resolve()
    return {
        "as_of": f"{end.isoformat()}T23:59:59Z",
        "output": str(base / "candidate-bundle.json"),
        "quality_report": str(base / "candidate-quality.json"),
        "max_price_age_days": 7,
        "max_fundamental_age_days": 200,
        "security_snapshots": security_snapshots,
        "bhavcopies": bhavcopies,
        "corporate_actions": [],
        "financials": [str(Path(path).resolve()) for path in (financials or [])],
        "generation_blockers": blockers,
    }


def _extracted_file(record: dict) -> Path | None:
    values = record.get("extracted_paths") or []
    if not values:
        return None
    path = Path(values[0]).resolve()
    return path if path.is_file() else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a candidate NSE bundle config")
    parser.add_argument("catalogue")
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--financial", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = build_pipeline_config(args.catalogue, args.start, args.end, financials=args.financial)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"config": str(destination), "blockers": config["generation_blockers"]}, indent=2))
    if config["generation_blockers"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
