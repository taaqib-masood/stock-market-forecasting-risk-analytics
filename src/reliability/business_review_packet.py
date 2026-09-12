"""Export controlled review templates for unresolved business classifications."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


REVIEW_FIELDS = [
    "decision", "evidence_path", "evidence_sha256", "reviewer_id",
    "reviewed_at", "notes",
]
PRIMARY_FIELDS = [
    "symbol", "source_type", "source", "required_action", "isin",
    "instrument_name", "proposed_business_type", *REVIEW_FIELDS,
]
INSURER_FIELDS = [
    "symbol", "business_type", "required_action", "isin", "instrument_name",
    "shariah_route", *REVIEW_FIELDS,
]


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for source in sorted(rows, key=lambda row: row.get("symbol", "")):
            evidence = source.get("evidence", {})
            row = {field: source.get(field, "") for field in fields}
            row["isin"] = evidence.get("isin", "")
            row["instrument_name"] = evidence.get("instrument_name", "")
            row["decision"] = "PENDING"
            writer.writerow(row)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_business_review_packet(
    report_path: str | Path,
    output_dir: str | Path,
) -> dict:
    report_path = Path(report_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = report_path.read_bytes()
    report = json.loads(raw)
    primary = report.get("review_queue", [])
    insurers = report.get("specialist_review_queue", [])

    primary_path = output_dir / "primary-business-reviews.csv"
    insurer_path = output_dir / "insurer-reviews.csv"
    _write_csv(primary_path, primary, PRIMARY_FIELDS)
    _write_csv(insurer_path, insurers, INSURER_FIELDS)
    manifest = {
        "policy_version": "business-classification-review-v1",
        "source_report": str(report_path),
        "source_report_sha256": hashlib.sha256(raw).hexdigest(),
        "primary_business_rows": len(primary),
        "insurer_rows": len(insurers),
        "primary_business_csv_sha256": _sha256(primary_path),
        "insurer_csv_sha256": _sha256(insurer_path),
        "acceptance": {
            "primary_business": (
                "APPROVED or EXCLUDED requires retained primary evidence, SHA-256, "
                "a supported business type, reviewer identity, and UTC review time"
            ),
            "insurer": (
                "APPROVED or EXCLUDED requires retained primary evidence, SHA-256, "
                "an explicit route from a qualified Shariah reviewer, reviewer identity, "
                "and UTC review time"
            ),
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "primary_business_csv": primary_path,
        "insurer_csv": insurer_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export business review packet")
    parser.add_argument("report")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    result = export_business_review_packet(args.report, args.output_dir)
    print(json.dumps({
        "primary_business_csv": str(result["primary_business_csv"]),
        "insurer_csv": str(result["insurer_csv"]),
        "manifest_path": str(result["manifest_path"]),
        **result["manifest"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
