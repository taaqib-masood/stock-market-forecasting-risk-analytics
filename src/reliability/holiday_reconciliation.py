"""Verify missing NSE reports against retained official holiday evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


OFFICIAL_NSE_HOSTS = {"archives.nseindia.com", "nsearchives.nseindia.com"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invalid_reason(source: dict, manifest_path: Path) -> str | None:
    if source.get("segment") != "capital_market":
        return "WRONG_SEGMENT"
    if urlparse(str(source.get("url", ""))).hostname not in OFFICIAL_NSE_HOSTS:
        return "UNOFFICIAL_SOURCE"
    value = source.get("path")
    if not value:
        return "MISSING_PATH"
    path = Path(value)
    if not path.is_absolute():
        path = manifest_path.parent / path
    if not path.is_file():
        return "MISSING_FILE"
    expected = source.get("sha256")
    if not expected or _sha256(path) != expected:
        return "SHA256_MISMATCH"
    if not source.get("source_id"):
        return "MISSING_SOURCE_ID"
    return None


def reconcile_holiday_gaps(
    review_path: str | Path,
    evidence_manifest_path: str | Path,
) -> dict:
    """Return a fail-closed reconciliation of report gaps to holiday evidence."""
    review_path = Path(review_path)
    manifest_path = Path(evidence_manifest_path)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    gaps = sorted(set(review.get("missing_report_dates", [])))

    confirmed: dict[str, list[str]] = {}
    invalid_sources: list[dict[str, str]] = []
    for source in manifest.get("sources", []):
        reason = _invalid_reason(source, manifest_path)
        if reason:
            invalid_sources.append({
                "source_id": str(source.get("source_id", "UNKNOWN")),
                "reason": reason,
            })
            continue
        source_id = str(source["source_id"])
        for value in source.get("holiday_dates", []):
            if value in gaps:
                confirmed.setdefault(value, []).append(source_id)

    confirmed = {key: sorted(set(value)) for key, value in sorted(confirmed.items())}
    unresolved = sorted(set(gaps) - set(confirmed))
    complete = bool(gaps) and not unresolved and not invalid_sources
    return {
        "status": "VERIFIED" if complete else "REVIEW_REQUIRED",
        "complete": complete,
        "review_path": str(review_path),
        "evidence_manifest_path": str(manifest_path),
        "counts": {
            "gaps": len(gaps),
            "confirmed_holidays": len(confirmed),
            "unresolved": len(unresolved),
        },
        "confirmed_holidays": confirmed,
        "unresolved_dates": unresolved,
        "invalid_sources": invalid_sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile missing NSE reports against retained holiday evidence"
    )
    parser.add_argument("review")
    parser.add_argument("evidence_manifest")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = reconcile_holiday_gaps(args.review, args.evidence_manifest)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
