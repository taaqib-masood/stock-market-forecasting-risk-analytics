"""Create a hash-bound, non-destructive remediation of a source catalogue."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from src.reliability.corporate_action_evidence_index import _verified_source
from src.reliability.preregistration import canonical_json_bytes


SCHEMA_VERSION = "corporate-action-source-catalogue-remediation-v1"
_ELIGIBLE_STATUSES = {"downloaded", "cached"}
_ELIGIBLE_KINDS = {"corporate_actions", "corporate_announcements"}


class CatalogueRemediationError(ValueError):
    """A source catalogue cannot be remediated without weakening provenance."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _request_key(record: Mapping[str, Any]) -> tuple[object, ...]:
    params = record.get("params")
    if not isinstance(params, Mapping):
        raise CatalogueRemediationError("catalogue params are invalid")
    return (
        record.get("kind"),
        params.get("from_date"),
        params.get("to_date"),
    )


def _content_identity(record: Mapping[str, Any]) -> tuple[object, ...]:
    params = record.get("params")
    return (
        *_request_key(record),
        record.get("url"),
        record.get("path"),
        record.get("sha256"),
        record.get("bytes"),
        json.dumps(params, sort_keys=True, separators=(",", ":")),
    )


def _load_lines(path: Path) -> list[tuple[int, dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogueRemediationError("source catalogue is unreadable") from error
    parsed: list[tuple[int, dict[str, Any]]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise CatalogueRemediationError(f"source catalogue line {number} is blank")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise CatalogueRemediationError(
                f"source catalogue line {number} is invalid JSON"
            ) from error
        if not isinstance(value, dict):
            raise CatalogueRemediationError(
                f"source catalogue line {number} is not an object"
            )
        parsed.append((number, value))
    if not parsed:
        raise CatalogueRemediationError("source catalogue is empty")
    return parsed


def remediate_catalogue(
    catalogue_path: str | Path,
    *,
    output_path: str | Path,
    manifest_path: str | Path,
) -> dict[str, object]:
    """Write a new catalogue while preserving the original byte-for-byte."""

    source = Path(catalogue_path)
    output = Path(output_path)
    manifest = Path(manifest_path)
    if source.resolve() in {output.resolve(), manifest.resolve()}:
        raise CatalogueRemediationError("remediation outputs must differ from source")
    original = source.read_bytes()
    rows = _load_lines(source)
    seen: dict[tuple[object, ...], tuple[int, dict[str, Any]]] = {}
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, object]] = []

    for line_number, record in rows:
        if (
            record.get("status") not in _ELIGIBLE_STATUSES
            or record.get("kind") not in _ELIGIBLE_KINDS
        ):
            kept.append(record)
            continue
        key = _request_key(record)
        previous = seen.get(key)
        if previous is None:
            _verified_source(record, source)
            seen[key] = (line_number, record)
            kept.append(record)
            continue
        previous_line, previous_record = previous
        if _content_identity(previous_record) != _content_identity(record):
            raise CatalogueRemediationError(
                "conflicting eligible source records for "
                f"{key[0]} {key[1]} to {key[2]} on lines "
                f"{previous_line} and {line_number}"
            )
        _verified_source(record, source)
        removed.append({
            "line": line_number,
            "kept_line": previous_line,
            "kind": key[0],
            "from_date": key[1],
            "to_date": key[2],
            "path": record.get("path"),
            "sha256": record.get("sha256"),
        })

    output_bytes = b"".join(canonical_json_bytes(row) for row in kept)
    remediation = {
        "schema_version": SCHEMA_VERSION,
        "proposal_only": True,
        "source_path": str(source),
        "source_sha256": _sha256(original),
        "source_bytes": len(original),
        "output_path": str(output),
        "output_sha256": _sha256(output_bytes),
        "output_bytes": len(output_bytes),
        "input_record_count": len(rows),
        "output_record_count": len(kept),
        "removed_duplicate_count": len(removed),
        "removed_duplicates": removed,
    }
    manifest_bytes = canonical_json_bytes(remediation)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as handle:
            handle.write(output_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        with manifest.open("xb") as handle:
            handle.write(manifest_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    except (FileExistsError, OSError) as error:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        raise CatalogueRemediationError("remediation output publication failed") from error
    return remediation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue")
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    try:
        result = remediate_catalogue(
            args.catalogue,
            output_path=args.output,
            manifest_path=args.manifest,
        )
    except (CatalogueRemediationError, OSError, TypeError, ValueError) as error:
        print(json.dumps({
            "status": "BLOCKED",
            "blocker": str(error),
            "proposal_only": True,
        }, sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps({
        "status": "COMPLETED",
        "proposal_only": True,
        "source_sha256": result["source_sha256"],
        "output_sha256": result["output_sha256"],
        "removed_duplicate_count": result["removed_duplicate_count"],
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
