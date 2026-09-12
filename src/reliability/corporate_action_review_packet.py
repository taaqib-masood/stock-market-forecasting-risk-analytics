"""Export controlled human-review templates from corporate-action audit queues."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from src.reliability.corporate_action_reviews import (
    FACTOR_FIELDS,
    VISIBILITY_FIELDS,
    build_review_rows,
)


PACKET_MANIFEST_SCHEMA_VERSION = "corporate-action-review-packet-v2"
_V1_POLICY_KEYS = [
    "policy_version",
    "authorized_reviewers",
    "prohibited_reviewers",
    "allowed_evidence_hosts",
]
_V2_POLICY_KEYS = [
    "policy_version",
    "authorized_reviewers",
    "prohibited_reviewers",
    "prohibited_actor_types",
    "allowed_evidence_hosts",
]
_V2_PRINCIPAL_KEYS = [
    "reviewer_id",
    "actor_type",
    "scopes",
    "valid_from",
    "valid_through",
    "revoked",
    "independence_evidence_path",
    "independence_evidence_sha256",
    "governance_owner_id",
    "approved_at",
    "approval_evidence_path",
    "approval_evidence_sha256",
]


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for source in rows:
            row = {field: source.get(field, "") for field in fields}
            row["decision"] = "PENDING"
            writer.writerow(row)


def template_sha256(rows: list[dict], fields: list[str]) -> str:
    """Hash a review template while excluding completed decision evidence."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for source in rows:
        row = {
            field: source.get(field, "") if field in {"review_id", "symbol", "action_type", "ex_date", "purpose", "reason"} else ""
            for field in fields
        }
        row["decision"] = "PENDING"
        writer.writerow(row)
    return hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()


def export_review_packet(
    report_path: str | Path,
    output_dir: str | Path,
    *,
    reviewer_policy_version: str = "corporate-action-review-policy-v1",
) -> dict:
    """Export immutable review templates for a declared reviewer policy version."""
    if reviewer_policy_version not in {
        "corporate-action-review-policy-v1",
        "corporate-action-review-policy-v2",
    }:
        raise ValueError("reviewer policy version is unsupported")
    report_path = Path(report_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw = report_path.read_bytes()
    report = json.loads(raw)
    visibility = report.get("visibility_review_queue", [])
    factors = report.get("factor_review_queue", [])

    visibility_path = output_dir / "visibility-reviews.csv"
    factor_path = output_dir / "factor-reviews.csv"
    _write_csv(
        visibility_path,
        build_review_rows("visibility", visibility),
        VISIBILITY_FIELDS,
    )
    _write_csv(
        factor_path,
        build_review_rows("factor", factors),
        FACTOR_FIELDS,
    )
    visibility_rows = build_review_rows("visibility", visibility)
    factor_rows = build_review_rows("factor", factors)
    policy_contract = {
        "policy_version": "corporate-action-review-policy-v1",
        "required_keys": _V1_POLICY_KEYS,
    }
    schema_version = PACKET_MANIFEST_SCHEMA_VERSION
    if reviewer_policy_version == "corporate-action-review-policy-v2":
        schema_version = "corporate-action-review-packet-v3"
        policy_contract = {
            "policy_version": reviewer_policy_version,
            "required_keys": _V2_POLICY_KEYS,
            "required_principal_keys": _V2_PRINCIPAL_KEYS,
            "governance_directory": "governance",
        }
    manifest = {
        "schema_version": schema_version,
        "source_report_path": str(report_path.resolve()),
        "source_report_sha256": hashlib.sha256(raw).hexdigest(),
        "queue_counts": {"visibility": len(visibility_rows), "factor": len(factor_rows)},
        "template_sha256": {
            "visibility": template_sha256(visibility_rows, VISIBILITY_FIELDS),
            "factor": template_sha256(factor_rows, FACTOR_FIELDS),
        },
        "row_identities": {
            "visibility": [row["review_id"] for row in visibility_rows],
            "factor": [row["review_id"] for row in factor_rows],
        },
        "reviewer_policy_contract": policy_contract,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "visibility_csv": visibility_path,
        "factor_csv": factor_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export corporate-action review packet")
    parser.add_argument("report")
    parser.add_argument("output_dir")
    args = parser.parse_args()
    result = export_review_packet(args.report, args.output_dir)
    print(json.dumps({
        "visibility_csv": str(result["visibility_csv"]),
        "factor_csv": str(result["factor_csv"]),
        "manifest_path": str(result["manifest_path"]),
        **result["manifest"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
