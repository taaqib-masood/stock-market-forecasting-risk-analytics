"""Deterministic, non-authoritative evidence indexes for review queues."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections import defaultdict, deque
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from src.reliability.corporate_action_reviews import (
    IDENTITY_FIELDS,
    CorporateActionReviewError,
    build_review_rows,
)
from src.reliability.nse_normalizers import normalize_corporate_actions_snapshot_bytes
from src.reliability.preregistration import canonical_json_bytes


SCHEMA_VERSION = "corporate-action-evidence-index-v1"
_SOURCE_KINDS = {"corporate_actions", "corporate_announcements"}
_SOURCE_STATUSES = {"downloaded", "cached"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_KOLKATA = ZoneInfo("Asia/Kolkata")
_TYPE_PATTERNS = {
    "BONUS": re.compile(r"\bBONUS\b"),
    "SPLIT": re.compile(r"\bSPLIT\b|\bSUB[ -]DIVISION\b"),
    "DIVIDEND": re.compile(r"\bDIVIDEND\b"),
    "RIGHTS": re.compile(r"\bRIGHTS?\b"),
    "MERGER": re.compile(r"\bMERGER\b|\bAMALGAMATION\b"),
    "DEMERGER": re.compile(r"\bDE[ -]?MERGER\b"),
}
_PROHIBITED_AUTHORITY_FIELDS = {
    "audit_authority",
    "canonical_decision",
    "decision",
    "reviewed_corporate_action_audit",
}
_ROW_FIELDS = {
    "schema_version",
    "proposal_only",
    "review_id",
    "queue_kind",
    "review_identity",
    "action_source",
    "announcement_candidates",
    "candidate_resolution",
}
_REVIEW_IDENTITY_FIELDS = set(IDENTITY_FIELDS) - {"review_id"}
_ACTION_SOURCE_FIELDS = {"path", "sha256", "bytes", "available_at"}
_CANDIDATE_FIELDS = {
    "seq_id",
    "symbol",
    "broadcast_at",
    "description",
    "subject",
    "attachment_text",
    "attachment_url",
    "snapshot_path",
    "snapshot_sha256",
    "snapshot_bytes",
    "snapshot_available_at",
    "ambiguity_reason",
}


class EvidenceIndexError(ValueError):
    """Evidence cannot be indexed without weakening an integrity boundary."""


class EvidenceIndexDurabilityError(EvidenceIndexError):
    """The destination changed, but parent-directory durability is uncertain."""


def _parse_json_bytes(content: bytes, *, label: str) -> object:
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceIndexError(f"{label} is not valid JSON") from error


def _parse_catalogue_date(value: object, *, field: str) -> date:
    if not isinstance(value, str):
        raise EvidenceIndexError(f"catalogue {field} is invalid")
    for pattern in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise EvidenceIndexError(f"catalogue {field} is invalid")


def _resolve_source_path(raw_path: object, catalogue_path: Path) -> tuple[Path, str]:
    if not isinstance(raw_path, str) or not raw_path:
        raise EvidenceIndexError("retained source path is invalid")
    declared = Path(raw_path)
    catalogue_dir = catalogue_path.resolve().parent
    if declared.is_absolute():
        resolved = declared.resolve()
        logical = Path(os.path.relpath(resolved, catalogue_dir)).as_posix()
        return resolved, logical

    candidates: list[Path] = []
    for base in (catalogue_dir, *catalogue_dir.parents):
        candidate = (base / declared).resolve()
        if candidate not in candidates:
            candidates.append(candidate)
    resolved = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    logical = Path(os.path.normpath(raw_path)).as_posix()
    return resolved, logical


def _verified_source(record: Mapping[str, object], catalogue_path: Path) -> dict[str, object]:
    path, logical_path = _resolve_source_path(record.get("path"), catalogue_path)
    try:
        content = path.read_bytes()
    except OSError as error:
        raise EvidenceIndexError(f"retained source is missing: {path}") from error
    expected_bytes = record.get("bytes")
    expected_sha256 = record.get("sha256")
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if (
        type(expected_bytes) is not int
        or expected_bytes < 0
        or len(content) != expected_bytes
        or not isinstance(expected_sha256, str)
        or _SHA256.fullmatch(expected_sha256) is None
        or actual_sha256 != expected_sha256
    ):
        raise EvidenceIndexError(f"retained source integrity mismatch: {path}")
    params = record.get("params")
    if not isinstance(params, dict):
        raise EvidenceIndexError("catalogue source params are invalid")
    range_start = _parse_catalogue_date(params.get("from_date"), field="from_date")
    range_end = _parse_catalogue_date(params.get("to_date"), field="to_date")
    if range_start > range_end:
        raise EvidenceIndexError("catalogue source range is invalid")
    available_at = record.get("available_at")
    if not isinstance(available_at, str) or not available_at:
        raise EvidenceIndexError("catalogue source available_at is invalid")
    return {
        "kind": record["kind"],
        "path": logical_path,
        "sha256": actual_sha256,
        "bytes": len(content),
        "available_at": available_at,
        "range_start": range_start,
        "range_end": range_end,
        "content": content,
    }


def _load_sources(catalogue_path: Path) -> list[dict[str, object]]:
    try:
        catalogue_content = catalogue_path.read_bytes()
    except OSError as error:
        raise EvidenceIndexError("source catalogue is missing") from error
    try:
        lines = catalogue_content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise EvidenceIndexError("source catalogue is not UTF-8") from error

    eligible: list[dict[str, object]] = []
    seen_ranges: dict[tuple[str, str, str], int] = {}
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvidenceIndexError(f"source catalogue line {number} is invalid JSON") from error
        if not isinstance(record, dict):
            raise EvidenceIndexError(f"source catalogue line {number} is not an object")
        if record.get("status") not in _SOURCE_STATUSES or record.get("kind") not in _SOURCE_KINDS:
            continue
        params = record.get("params")
        if not isinstance(params, dict):
            raise EvidenceIndexError(f"source catalogue line {number} has invalid params")
        range_start = _parse_catalogue_date(params.get("from_date"), field="from_date")
        range_end = _parse_catalogue_date(params.get("to_date"), field="to_date")
        if range_start > range_end:
            raise EvidenceIndexError("catalogue source range is invalid")
        key = (record["kind"], range_start.isoformat(), range_end.isoformat())
        previous_line = seen_ranges.get(key)
        if previous_line is not None:
            raise EvidenceIndexError(
                "duplicate eligible source catalogue records for "
                f"{key[0]} {key[1]} to {key[2]} on lines {previous_line} and {number}"
            )
        seen_ranges[key] = number
        eligible.append(record)
    if not eligible:
        raise EvidenceIndexError("source catalogue has no retained corporate-action sources")
    return [_verified_source(record, catalogue_path) for record in eligible]


def _load_baseline(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise EvidenceIndexError("baseline report is missing") from error
    value = _parse_json_bytes(content, label="baseline report")
    if not isinstance(value, dict):
        raise EvidenceIndexError("baseline report must be an object")
    for key in ("visibility_review_queue", "factor_review_queue"):
        queue = value.get(key)
        if not isinstance(queue, list) or any(not isinstance(row, dict) for row in queue):
            raise EvidenceIndexError(f"baseline report {key} is invalid")
    return value, content


def _read_packet_identities(path: Path) -> list[dict[str, str]]:
    try:
        content = path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise EvidenceIndexError(f"review packet file is unreadable: {path.name}") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None or any(field not in reader.fieldnames for field in IDENTITY_FIELDS):
        raise EvidenceIndexError(f"review packet identity fields are missing: {path.name}")
    rows = [{field: raw.get(field, "") for field in IDENTITY_FIELDS} for raw in reader]
    ids = [row["review_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise EvidenceIndexError("review packet contains a duplicate review ID")
    return rows


def _verify_packet(
    packet_dir: Path,
    baseline_content: bytes,
    expected_by_kind: Mapping[str, list[dict[str, object]]],
) -> None:
    if not packet_dir.is_dir():
        raise EvidenceIndexError("review packet directory is missing")
    try:
        manifest_content = (packet_dir / "manifest.json").read_bytes()
    except OSError as error:
        raise EvidenceIndexError("review packet manifest is missing") from error
    manifest = _parse_json_bytes(manifest_content, label="review packet manifest")
    if not isinstance(manifest, dict):
        raise EvidenceIndexError("review packet manifest must be an object")
    if manifest.get("source_report_sha256") != hashlib.sha256(baseline_content).hexdigest():
        raise EvidenceIndexError("review packet baseline binding is invalid")

    manifest_ids = manifest.get("row_identities")
    manifest_counts = manifest.get("queue_counts")
    if not isinstance(manifest_ids, dict) or not isinstance(manifest_counts, dict):
        raise EvidenceIndexError("review packet manifest identity binding is invalid")
    all_ids: list[str] = []
    for queue_kind, filename in (
        ("visibility", "visibility-reviews.csv"),
        ("factor", "factor-reviews.csv"),
    ):
        expected = expected_by_kind[queue_kind]
        packet_rows = _read_packet_identities(packet_dir / filename)
        expected_identities = [
            {field: str(row.get(field, "")) for field in IDENTITY_FIELDS}
            for row in expected
        ]
        if packet_rows != expected_identities:
            raise EvidenceIndexError(f"review packet identity mismatch: {queue_kind}")
        expected_ids = [str(row["review_id"]) for row in expected]
        if (
            manifest_ids.get(queue_kind) != expected_ids
            or manifest_counts.get(queue_kind) != len(expected)
        ):
            raise EvidenceIndexError("review packet manifest identity binding is invalid")
        all_ids.extend(expected_ids)
    if len(all_ids) != len(set(all_ids)):
        raise EvidenceIndexError("review packet contains a duplicate review ID")


def _action_key(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    return (
        str(row.get("symbol", "")),
        str(row.get("action_type", "")),
        str(row.get("ex_date", "")),
        str(row.get("purpose", "")),
    )


def _action_sources(sources: list[dict[str, object]]) -> dict[tuple[str, str, str, str], deque[dict[str, object]]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    for source in sources:
        if source["kind"] != "corporate_actions":
            continue
        try:
            actions = normalize_corporate_actions_snapshot_bytes(
                source["content"],
                available_at=source["available_at"],
            )
        except (TypeError, ValueError) as error:
            raise EvidenceIndexError("retained corporate-action source is invalid") from error
        for action in actions:
            reference = {
                "path": source["path"],
                "sha256": source["sha256"],
                "bytes": source["bytes"],
                "available_at": source["available_at"],
                "range_start": source["range_start"],
                "range_end": source["range_end"],
            }
            grouped[_action_key({
                "symbol": action["symbol"],
                "action_type": action["action_type"],
                "ex_date": action["ex_date"],
                "purpose": action["payload"].get("purpose", ""),
            })].append(reference)
    return {key: deque(values) for key, values in grouped.items()}


def _parse_announcement_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceIndexError("announcement timestamp is missing")
    text = value.strip()
    parsed: datetime | None = None
    for pattern in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, pattern)
            break
        except ValueError:
            pass
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as error:
            raise EvidenceIndexError("announcement timestamp is invalid") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_KOLKATA)
    return parsed.astimezone(_KOLKATA)


def _announcement_rows(source: dict[str, object]) -> list[dict[str, object]]:
    value = _parse_json_bytes(source["content"], label="announcement snapshot")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise EvidenceIndexError("announcement snapshot must be an array of objects")
    return value


def _terms_compatible(action_type: str, text: str) -> bool:
    pattern = _TYPE_PATTERNS.get(action_type)
    if pattern is None:
        return False
    return pattern.search(text.upper()) is not None


def _candidate_rows(
    queue_row: Mapping[str, object],
    action_source: Mapping[str, object],
    announcement_sources: list[dict[str, object]],
) -> list[dict[str, object]]:
    try:
        ex_date = date.fromisoformat(str(queue_row["ex_date"]))
    except (KeyError, ValueError) as error:
        raise EvidenceIndexError("review queue ex-date is invalid") from error
    cutoff = datetime.combine(ex_date, time(9, 15), tzinfo=_KOLKATA)
    candidates: list[dict[str, object]] = []
    for source in announcement_sources:
        if (
            source["range_end"] < action_source["range_start"] - timedelta(days=180)
            or source["range_start"] > action_source["range_end"]
        ):
            continue
        rows = source.get("rows")
        if not isinstance(rows, list):
            raise EvidenceIndexError("announcement snapshot was not prepared")
        for raw in rows:
            symbol = str(raw.get("symbol", "")).strip().upper()
            if symbol != queue_row["symbol"]:
                continue
            broadcast = _parse_announcement_timestamp(raw.get("an_dt") or raw.get("sort_date"))
            if broadcast >= cutoff:
                continue
            text = " ".join(
                str(raw.get(field, ""))
                for field in ("desc", "subject", "attchmntText")
            ).strip()
            if not _terms_compatible(str(queue_row["action_type"]), text):
                continue
            candidates.append({
                "seq_id": str(raw.get("seq_id", "")),
                "symbol": symbol,
                "broadcast_at": broadcast.isoformat(timespec="seconds"),
                "description": str(raw.get("desc", "")),
                "subject": str(raw.get("subject", "")),
                "attachment_text": str(raw.get("attchmntText", "")),
                "attachment_url": str(raw.get("attchmntFile", "")),
                "snapshot_path": source["path"],
                "snapshot_sha256": source["sha256"],
                "snapshot_bytes": source["bytes"],
                "snapshot_available_at": source["available_at"],
                "ambiguity_reason": "CANDIDATE_NOT_CANONICAL",
            })
    candidates.sort(key=lambda row: (
        row["broadcast_at"],
        row["seq_id"],
        row["snapshot_sha256"],
        row["attachment_url"],
    ))
    return candidates


def build_evidence_index(
    *,
    catalogue_path: str | Path,
    baseline_report_path: str | Path,
    packet_dir: str | Path,
) -> list[dict[str, object]]:
    """Build proposal-only evidence rows bound to the canonical review identities."""
    catalogue = Path(catalogue_path)
    baseline, baseline_content = _load_baseline(Path(baseline_report_path))
    try:
        expected_by_kind = {
            "visibility": build_review_rows(
                "visibility", baseline["visibility_review_queue"],
            ),
            "factor": build_review_rows("factor", baseline["factor_review_queue"]),
        }
    except (CorporateActionReviewError, TypeError, ValueError) as error:
        raise EvidenceIndexError("baseline review identities are invalid") from error
    _verify_packet(Path(packet_dir), baseline_content, expected_by_kind)

    sources = _load_sources(catalogue)
    announcement_sources = [
        source for source in sources if source["kind"] == "corporate_announcements"
    ]
    for source in announcement_sources:
        source["rows"] = _announcement_rows(source)
    action_source_groups = _action_sources(sources)
    output: list[dict[str, object]] = []
    for queue_kind in ("visibility", "factor"):
        actions = {
            key: deque(references) for key, references in action_source_groups.items()
        }
        queue_rows = baseline[f"{queue_kind}_review_queue"]
        for queue_row, identity in zip(queue_rows, expected_by_kind[queue_kind], strict=True):
            matches = actions.get(_action_key(queue_row))
            if not matches:
                raise EvidenceIndexError("review row has no retained corporate-action source")
            source = matches.popleft()
            candidates = _candidate_rows(queue_row, source, announcement_sources)
            output.append({
                "schema_version": SCHEMA_VERSION,
                "proposal_only": True,
                "review_id": identity["review_id"],
                "queue_kind": queue_kind,
                "review_identity": {
                    field: identity[field] for field in IDENTITY_FIELDS if field != "review_id"
                },
                "action_source": {
                    key: source[key]
                    for key in ("path", "sha256", "bytes", "available_at")
                },
                "announcement_candidates": candidates,
                "candidate_resolution": (
                    "AMBIGUOUS_REVIEW_REQUIRED"
                    if candidates else "NO_COMPATIBLE_CANDIDATE"
                ),
            })
    return output


def _reject_nested_authority(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise EvidenceIndexError("proposal output keys must be strings")
            if key.lower() in _PROHIBITED_AUTHORITY_FIELDS:
                raise EvidenceIndexError("proposal output cannot carry audit authority")
            _reject_nested_authority(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_nested_authority(nested)


def _require_exact_fields(
    value: object,
    expected: set[str],
    *,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise EvidenceIndexError(f"evidence index {label} schema is invalid")
    return value


def _validate_proposal_rows(rows: object) -> list[dict[str, object]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise EvidenceIndexError("evidence index rows must be a list of objects")
    seen: set[str] = set()
    for row in rows:
        _reject_nested_authority(row)
        _require_exact_fields(row, _ROW_FIELDS, label="row")
        if row.get("schema_version") != SCHEMA_VERSION:
            raise EvidenceIndexError("evidence index schema version is invalid")
        if row.get("proposal_only") is not True:
            raise EvidenceIndexError("evidence index proposal_only must be true")
        review_id = row.get("review_id")
        if not isinstance(review_id, str) or _SHA256.fullmatch(review_id) is None:
            raise EvidenceIndexError("evidence index review ID is invalid")
        if review_id in seen:
            raise EvidenceIndexError("evidence index contains a duplicate review ID")
        seen.add(review_id)
        if row.get("queue_kind") not in {"visibility", "factor"}:
            raise EvidenceIndexError("evidence index queue kind is invalid")

        identity = _require_exact_fields(
            row.get("review_identity"),
            _REVIEW_IDENTITY_FIELDS,
            label="review identity",
        )
        if any(not isinstance(identity[field], str) for field in identity):
            raise EvidenceIndexError("evidence index review identity is invalid")
        source = _require_exact_fields(
            row.get("action_source"),
            _ACTION_SOURCE_FIELDS,
            label="action source",
        )
        if (
            not isinstance(source.get("path"), str)
            or not source["path"]
            or not isinstance(source.get("sha256"), str)
            or _SHA256.fullmatch(source["sha256"]) is None
            or type(source.get("bytes")) is not int
            or source["bytes"] < 0
            or not isinstance(source.get("available_at"), str)
            or not source["available_at"]
        ):
            raise EvidenceIndexError("evidence index action source is invalid")

        candidates = row.get("announcement_candidates")
        if not isinstance(candidates, list):
            raise EvidenceIndexError("evidence index announcement candidates are invalid")
        for candidate_value in candidates:
            candidate = _require_exact_fields(
                candidate_value,
                _CANDIDATE_FIELDS,
                label="announcement candidate",
            )
            string_fields = _CANDIDATE_FIELDS - {"snapshot_bytes"}
            if (
                any(not isinstance(candidate.get(field), str) for field in string_fields)
                or candidate.get("ambiguity_reason") != "CANDIDATE_NOT_CANONICAL"
                or _SHA256.fullmatch(candidate["snapshot_sha256"]) is None
                or type(candidate.get("snapshot_bytes")) is not int
                or candidate["snapshot_bytes"] < 0
            ):
                raise EvidenceIndexError("evidence index announcement candidate is invalid")
        expected_resolution = (
            "AMBIGUOUS_REVIEW_REQUIRED"
            if candidates else "NO_COMPATIBLE_CANDIDATE"
        )
        if row.get("candidate_resolution") != expected_resolution:
            raise EvidenceIndexError("evidence index candidate resolution is invalid")
    return rows


def write_evidence_index(
    rows: list[dict[str, object]],
    output_path: str | Path,
) -> dict[str, object]:
    """Write canonical JSONL with explicit replacement and durability semantics.

    File fsync and replacement failures preserve the prior destination. Replacement
    is atomic once reached. A later parent fsync failure raises a durability error,
    but the new destination remains visible and must not be treated as rolled back.
    """
    validated = _validate_proposal_rows(rows)
    try:
        output_bytes = b"".join(canonical_json_bytes(row) for row in validated)
    except (TypeError, ValueError) as error:
        raise EvidenceIndexError("evidence index rows are not canonical JSON") from error
    output = Path(output_path)
    part = output.with_name(output.name + ".part")
    try:
        handle = part.open("xb")
    except FileExistsError as error:
        raise EvidenceIndexError("temporary output already exists") from error
    except OSError as error:
        raise EvidenceIndexError(
            "evidence index output failed before destination replacement"
        ) from error

    created_part = True
    destination_replaced = False
    try:
        with handle:
            handle.write(output_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(part, output)
        destination_replaced = True
        created_part = False
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(output.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        if not destination_replaced and created_part:
            try:
                part.unlink()
            except OSError:
                pass
        if destination_replaced:
            raise EvidenceIndexDurabilityError(
                "destination was replaced but parent directory durability is uncertain"
            ) from error
        raise EvidenceIndexError(
            "evidence index output failed before destination replacement"
        ) from error
    return {
        "schema_version": SCHEMA_VERSION,
        "row_count": len(validated),
        "sha256": hashlib.sha256(output_bytes).hexdigest(),
    }
