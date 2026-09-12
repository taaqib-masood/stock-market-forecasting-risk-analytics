"""Immutable, non-authoritative corporate-action AI proposal evidence."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import time
from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import requests

from src.reliability.corporate_action_candidate_evidence import (
    CandidateEvidenceError,
    retain_candidate_attachments,
)
from src.reliability.corporate_action_evidence_index import (
    EvidenceIndexError,
    build_evidence_index,
    write_evidence_index,
)
from src.reliability.corporate_action_factor_worksheets import (
    FORMULA,
    FactorWorksheetError,
    build_factor_worksheet,
)
from src.reliability.corporate_action_reviews import (
    CorporateActionReviewError,
    build_review_rows,
)
from src.reliability.preregistration import canonical_json_bytes


SCHEMA_VERSION = "corporate-action-ai-proposal-v1"
LOG_SCHEMA_VERSION = "corporate-action-ai-proposal-log-v1"
INDEX_SCHEMA_VERSION = "corporate-action-evidence-index-v1"
WORKSHEET_SCHEMA_VERSION = "corporate-action-factor-worksheet-v1"
CANDIDATE_EVIDENCE_SCHEMA_VERSION = "corporate-action-candidate-evidence-v1"
CLI_OUTPUT_SCHEMA_VERSION = "corporate-action-ai-cli-output-v1"
CLI_MANIFEST_SCHEMA_VERSION = "corporate-action-ai-cli-manifest-v1"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UTC_Z_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)
_REVIEW_FIELDS = {
    "review_id",
    "symbol",
    "action_type",
    "ex_date",
    "purpose",
    "reason",
}
_IDENTITY_FIELDS = {"symbol", "action_type", "ex_date", "purpose", "reason"}
_QUEUE_CONTEXT_FIELDS = {"queue_kind", "review_rows"}
_INDEX_FIELDS = {
    "schema_version",
    "proposal_only",
    "review_id",
    "queue_kind",
    "review_identity",
    "action_source",
    "announcement_candidates",
    "candidate_resolution",
}
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
_EVIDENCE_ENVELOPE_FIELDS = {"index_row", "retained_candidate_manifest"}
_CANDIDATE_MANIFEST_FIELDS = {"schema_version", "proposal_only", "records"}
_RETAINED_CANDIDATE_FIELDS = {
    "schema_version",
    "proposal_only",
    "review_id",
    "candidate_url",
    "attachment_sha256",
    "attachment_path",
    "byte_count",
    "attempted_at",
    "retrieved_at",
    "source_snapshot_sha256",
    "status",
    "failure_code",
}
_WORKSHEET_FIELDS = {
    "schema_version",
    "proposal_only",
    "review_id",
    "queue_kind",
    "review_identity",
    "retained_inputs",
    "parsed_terms",
    "calculation_inputs",
    "formula",
    "candidate_factor",
    "proposal_status",
    "manual_required_reasons",
}
_RETAINED_INPUT_FIELDS = {"value", "path", "sha256", "available_at"}
_PARSED_TERM_FIELDS = {
    "new_shares",
    "old_shares",
    "face_value",
    "premium",
    "issue_price",
    "issue_price_method",
}
_CALCULATION_INPUT_FIELDS = {
    "new_shares",
    "old_shares",
    "issue_price",
    "cum_rights_price",
}
_PROPOSAL_FIELDS = {
    "proposal_id",
    "schema_version",
    "proposal_only",
    "review_id",
    "queue_kind",
    "review_identity",
    "review_queue_context",
    "evidence_index",
    "retained_candidate_evidence",
    "factor_worksheet",
    "proposal_status",
    "model_id",
    "workflow_sha256",
    "generated_at",
    "rationale",
}
_PROPOSAL_STATUSES = {
    "AI_PROPOSED",
    "NO_SAFE_PROPOSAL",
    "MANUAL_REQUIRED",
}
_PROHIBITED_AUTHORITY_FIELDS = {
    "adjustment_factor",
    "approval",
    "approved",
    "audit_authority",
    "canonical_decision",
    "decision",
    "reviewed_at",
    "reviewed_corporate_action_audit",
    "reviewer_id",
}


class AIProposalError(ValueError):
    """Proposal evidence is invalid or would weaken append-only isolation."""


class AIProposalDurabilityError(AIProposalError):
    """An append completed, but its directory durability is uncertain."""


class AIProposalCLIError(AIProposalError):
    """A safe, machine-readable CLI blocker without sensitive details."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _reject_authority(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise AIProposalError("proposal keys must be strings")
            if key.lower() in _PROHIBITED_AUTHORITY_FIELDS:
                raise AIProposalError("proposal evidence cannot carry review authority")
            _reject_authority(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_authority(nested)


def _exact_mapping(
    value: object,
    fields: set[str],
    *,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise AIProposalError(f"{label} schema is invalid")
    return value


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _parse_generated_at(value: object) -> str:
    if not isinstance(value, str) or _UTC_Z_TIMESTAMP.fullmatch(value) is None:
        raise AIProposalError("generated_at must be a UTC Z timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise AIProposalError("generated_at must be a valid UTC Z timestamp") from error
    if parsed.utcoffset() is None:
        raise AIProposalError("generated_at must include a UTC offset")
    return value


def _parse_aware_timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AIProposalError(f"{label} timestamp is invalid")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise AIProposalError(f"{label} timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AIProposalError(f"{label} timestamp must include an offset")
    return value


def _canonical_copy(value: object) -> object:
    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise AIProposalError("proposal value is not canonical JSON") from error


def _normalize_review_row(review_row: Mapping[str, str]) -> dict[str, str]:
    _reject_authority(review_row)
    row = _exact_mapping(review_row, _REVIEW_FIELDS, label="review row")
    if any(not isinstance(row.get(field), str) for field in _REVIEW_FIELDS):
        raise AIProposalError("review row fields must be strings")
    if not _valid_sha256(row["review_id"]):
        raise AIProposalError("review ID is invalid")
    if any(not row[field] for field in _IDENTITY_FIELDS):
        raise AIProposalError("review identity fields cannot be blank")
    try:
        datetime.strptime(row["ex_date"], "%Y-%m-%d")
    except ValueError as error:
        raise AIProposalError("review ex-date is invalid") from error
    return {field: row[field] for field in sorted(_REVIEW_FIELDS)}


def _validate_queue_context(
    queue_rows: object,
    *,
    queue_kind: str,
    review: Mapping[str, str],
) -> dict[str, object]:
    if queue_kind not in {"visibility", "factor"}:
        raise AIProposalError("review queue kind is invalid")
    if not isinstance(queue_rows, list) or not queue_rows:
        raise AIProposalError("full review queue context is required")
    normalized_rows = [_normalize_review_row(row) for row in queue_rows]
    source_rows = [
        {
            field: row[field]
            for field in ("symbol", "action_type", "ex_date", "purpose", "reason")
        }
        for row in normalized_rows
    ]
    try:
        canonical_rows = build_review_rows(queue_kind, source_rows)
    except (CorporateActionReviewError, TypeError, ValueError) as error:
        raise AIProposalError("canonical review identity cannot be reproduced") from error
    if normalized_rows != canonical_rows:
        raise AIProposalError("review ID does not match canonical review identity")
    matches = [row for row in canonical_rows if row["review_id"] == review["review_id"]]
    if len(matches) != 1 or matches[0] != review:
        raise AIProposalError("review ID does not match canonical review identity")
    return {
        "queue_kind": queue_kind,
        "review_rows": canonical_rows,
    }


def _validate_stored_queue_context(
    value: object,
    *,
    queue_kind: str,
    review: Mapping[str, str],
) -> dict[str, object]:
    context = _exact_mapping(
        value,
        _QUEUE_CONTEXT_FIELDS,
        label="review queue context",
    )
    if context.get("queue_kind") != queue_kind:
        raise AIProposalError("review queue context kind is stale")
    normalized = _validate_queue_context(
        context.get("review_rows"),
        queue_kind=queue_kind,
        review=review,
    )
    if normalized != context:
        raise AIProposalError("review queue context is not canonical")
    return normalized


def _validate_identity(
    value: object,
    *,
    expected: Mapping[str, str],
    label: str,
) -> dict[str, str]:
    identity = _exact_mapping(value, _IDENTITY_FIELDS, label=label)
    if any(not isinstance(identity.get(field), str) for field in _IDENTITY_FIELDS):
        raise AIProposalError(f"{label} fields must be strings")
    normalized = {field: identity[field] for field in sorted(_IDENTITY_FIELDS)}
    expected_identity = {field: expected[field] for field in sorted(_IDENTITY_FIELDS)}
    if normalized != expected_identity:
        raise AIProposalError(f"{label} does not match review identity")
    return normalized


def _validate_index(
    value: Mapping[str, object],
    *,
    review: Mapping[str, str],
) -> dict[str, object]:
    _reject_authority(value)
    row = _exact_mapping(value, _INDEX_FIELDS, label="evidence index")
    if row.get("schema_version") != INDEX_SCHEMA_VERSION:
        raise AIProposalError("evidence index schema version is invalid")
    if row.get("proposal_only") is not True:
        raise AIProposalError("evidence index must be proposal-only")
    if row.get("review_id") != review["review_id"]:
        raise AIProposalError("evidence index review ID is stale")
    if row.get("queue_kind") not in {"visibility", "factor"}:
        raise AIProposalError("evidence index queue kind is invalid")
    _validate_identity(
        row.get("review_identity"),
        expected=review,
        label="evidence index identity",
    )

    source = _exact_mapping(
        row.get("action_source"),
        _ACTION_SOURCE_FIELDS,
        label="action source",
    )
    if (
        not isinstance(source.get("path"), str)
        or not source["path"]
        or not _valid_sha256(source.get("sha256"))
        or type(source.get("bytes")) is not int
        or source["bytes"] < 0
    ):
        raise AIProposalError("action source binding is invalid")
    _parse_aware_timestamp(source.get("available_at"), label="action source availability")

    candidates = row.get("announcement_candidates")
    if not isinstance(candidates, list):
        raise AIProposalError("announcement candidates must be a list")
    for candidate_value in candidates:
        candidate = _exact_mapping(
            candidate_value,
            _CANDIDATE_FIELDS,
            label="announcement candidate",
        )
        string_fields = _CANDIDATE_FIELDS - {"snapshot_bytes"}
        if any(not isinstance(candidate.get(field), str) for field in string_fields):
            raise AIProposalError("announcement candidate fields are invalid")
        if (
            not candidate["seq_id"]
            or candidate["symbol"] != review["symbol"]
            or not candidate["snapshot_path"]
            or not _valid_sha256(candidate["snapshot_sha256"])
            or type(candidate.get("snapshot_bytes")) is not int
            or candidate["snapshot_bytes"] < 0
            or candidate["ambiguity_reason"] != "CANDIDATE_NOT_CANONICAL"
        ):
            raise AIProposalError("announcement candidate binding is invalid")
        _parse_aware_timestamp(candidate["broadcast_at"], label="announcement broadcast")
        _parse_aware_timestamp(
            candidate["snapshot_available_at"],
            label="announcement snapshot availability",
        )

    expected_resolution = (
        "AMBIGUOUS_REVIEW_REQUIRED"
        if candidates
        else "NO_COMPATIBLE_CANDIDATE"
    )
    if row.get("candidate_resolution") != expected_resolution:
        raise AIProposalError("candidate resolution does not match candidate evidence")
    return copy.deepcopy(dict(row))


def _validate_nullable_string_mapping(
    value: object,
    fields: set[str],
    *,
    label: str,
) -> dict[str, str | None] | None:
    if value is None:
        return None
    mapping = _exact_mapping(value, fields, label=label)
    if any(
        nested is not None and not isinstance(nested, str)
        for nested in mapping.values()
    ):
        raise AIProposalError(f"{label} values are invalid")
    return {field: mapping[field] for field in sorted(fields)}


def _optional_aware_timestamp(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _parse_aware_timestamp(value, label=label)


def _validate_retained_candidate_records(
    records_value: object,
    *,
    index: Mapping[str, object],
    review: Mapping[str, str],
) -> list[dict[str, object]]:
    if not isinstance(records_value, list):
        raise AIProposalError("retained candidate records must be a list")
    candidate_bindings = {
        (candidate["attachment_url"], candidate["snapshot_sha256"])
        for candidate in index["announcement_candidates"]
    }
    relevant: list[dict[str, object]] = []
    seen_relevant: set[tuple[str, str]] = set()
    for value in records_value:
        _reject_authority(value)
        record = _exact_mapping(
            value,
            _RETAINED_CANDIDATE_FIELDS,
            label="retained candidate record",
        )
        if record.get("schema_version") != CANDIDATE_EVIDENCE_SCHEMA_VERSION:
            raise AIProposalError("retained candidate schema version is invalid")
        if record.get("proposal_only") is not True:
            raise AIProposalError("retained candidate evidence must be proposal-only")
        if not _valid_sha256(record.get("review_id")):
            raise AIProposalError("retained candidate review ID is invalid")
        if (
            not isinstance(record.get("candidate_url"), str)
            or not record["candidate_url"]
            or not _valid_sha256(record.get("source_snapshot_sha256"))
        ):
            raise AIProposalError("retained candidate source binding is invalid")
        attempted_at = _optional_aware_timestamp(
            record.get("attempted_at"),
            label="retained candidate attempted_at",
        )
        retrieved_at = _optional_aware_timestamp(
            record.get("retrieved_at"),
            label="retained candidate retrieved_at",
        )
        attachment_sha256 = record.get("attachment_sha256")
        if attachment_sha256 is not None and not _valid_sha256(attachment_sha256):
            raise AIProposalError("retained candidate attachment SHA-256 is invalid")
        status = record.get("status")
        if status in {"RETAINED", "REUSED"}:
            if (
                attachment_sha256 is None
                or not isinstance(record.get("attachment_path"), str)
                or not record["attachment_path"]
                or type(record.get("byte_count")) is not int
                or record["byte_count"] < 0
                or attempted_at is None
                or retrieved_at is None
                or record.get("failure_code") is not None
            ):
                raise AIProposalError("retained candidate successful binding is invalid")
        elif status == "FAILED":
            if (
                retrieved_at is not None
                or not isinstance(record.get("failure_code"), str)
                or not record["failure_code"]
            ):
                raise AIProposalError("retained candidate failure record is invalid")
            attachment_values = (
                record.get("attachment_sha256"),
                record.get("attachment_path"),
                record.get("byte_count"),
            )
            if any(value is not None for value in attachment_values) and not (
                _valid_sha256(attachment_values[0])
                and isinstance(attachment_values[1], str)
                and bool(attachment_values[1])
                and type(attachment_values[2]) is int
                and attachment_values[2] >= 0
            ):
                raise AIProposalError("retained candidate failure binding is invalid")
        else:
            raise AIProposalError("retained candidate status is invalid")

        if record["review_id"] != review["review_id"]:
            raise AIProposalError("retained candidate review ID is stale")
        binding = (record["candidate_url"], record["source_snapshot_sha256"])
        if binding not in candidate_bindings:
            raise AIProposalError("retained candidate does not match indexed candidate")
        if binding in seen_relevant:
            raise AIProposalError("retained candidate binding is duplicated")
        seen_relevant.add(binding)
        relevant.append(copy.deepcopy(dict(record)))
    return relevant


def _validate_candidate_manifest(
    value: object,
    *,
    index: Mapping[str, object],
    review: Mapping[str, str],
) -> list[dict[str, object]]:
    _reject_authority(value)
    manifest = _exact_mapping(
        value,
        _CANDIDATE_MANIFEST_FIELDS,
        label="retained candidate manifest",
    )
    if manifest.get("schema_version") != CANDIDATE_EVIDENCE_SCHEMA_VERSION:
        raise AIProposalError("retained candidate manifest schema version is invalid")
    if manifest.get("proposal_only") is not True:
        raise AIProposalError("retained candidate manifest must be proposal-only")
    return _validate_retained_candidate_records(
        manifest.get("records"),
        index=index,
        review=review,
    )


def _validate_evidence_input(
    value: Mapping[str, object],
    *,
    review: Mapping[str, str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    _reject_authority(value)
    if set(value) == _INDEX_FIELDS:
        return _validate_index(value, review=review), []
    envelope = _exact_mapping(
        value,
        _EVIDENCE_ENVELOPE_FIELDS,
        label="evidence input",
    )
    index = _validate_index(envelope.get("index_row"), review=review)  # type: ignore[arg-type]
    retained = _validate_candidate_manifest(
        envelope.get("retained_candidate_manifest"),
        index=index,
        review=review,
    )
    return index, retained


def _evidence_queue_kind(value: Mapping[str, object]) -> str:
    _reject_authority(value)
    if set(value) == _INDEX_FIELDS:
        index = value
    else:
        envelope = _exact_mapping(
            value,
            _EVIDENCE_ENVELOPE_FIELDS,
            label="evidence input",
        )
        index = _exact_mapping(
            envelope.get("index_row"),
            _INDEX_FIELDS,
            label="evidence index",
        )
    queue_kind = index.get("queue_kind")
    if queue_kind not in {"visibility", "factor"}:
        raise AIProposalError("evidence index queue kind is invalid")
    return queue_kind


def _validate_candidate_factor(value: object) -> str:
    if not isinstance(value, str):
        raise AIProposalError("candidate factor is invalid")
    try:
        factor = Decimal(value)
    except InvalidOperation as error:
        raise AIProposalError("candidate factor is invalid") from error
    if not factor.is_finite() or factor <= 0 or factor > 1:
        raise AIProposalError("candidate factor is outside proposal bounds")
    return value


def _validate_worksheet(
    value: Mapping[str, object],
    *,
    review: Mapping[str, str],
) -> dict[str, object]:
    _reject_authority(value)
    worksheet = _exact_mapping(value, _WORKSHEET_FIELDS, label="factor worksheet")
    if worksheet.get("schema_version") != WORKSHEET_SCHEMA_VERSION:
        raise AIProposalError("factor worksheet schema version is invalid")
    if worksheet.get("proposal_only") is not True:
        raise AIProposalError("factor worksheet must be proposal-only")
    if worksheet.get("review_id") != review["review_id"]:
        raise AIProposalError("factor worksheet review ID is stale")
    if worksheet.get("queue_kind") != "factor":
        raise AIProposalError("factor worksheet queue kind is invalid")
    _validate_identity(
        worksheet.get("review_identity"),
        expected=review,
        label="factor worksheet identity",
    )

    retained_inputs = worksheet.get("retained_inputs")
    if not isinstance(retained_inputs, Mapping):
        raise AIProposalError("factor worksheet retained inputs are invalid")
    for name, source_value in retained_inputs.items():
        if not isinstance(name, str) or not name:
            raise AIProposalError("factor worksheet retained input name is invalid")
        source = _exact_mapping(
            source_value,
            _RETAINED_INPUT_FIELDS,
            label="factor worksheet retained input",
        )
        if (
            any(not isinstance(source.get(field), str) for field in _RETAINED_INPUT_FIELDS)
            or not source["path"]
            or not _valid_sha256(source["sha256"])
        ):
            raise AIProposalError("factor worksheet retained input binding is invalid")
        _parse_aware_timestamp(
            source["available_at"],
            label="factor worksheet input availability",
        )

    parsed_terms = _validate_nullable_string_mapping(
        worksheet.get("parsed_terms"),
        _PARSED_TERM_FIELDS,
        label="factor worksheet parsed terms",
    )
    calculation_inputs = _validate_nullable_string_mapping(
        worksheet.get("calculation_inputs"),
        _CALCULATION_INPUT_FIELDS,
        label="factor worksheet calculation inputs",
    )
    reasons = worksheet.get("manual_required_reasons")
    if (
        not isinstance(reasons, list)
        or any(not isinstance(reason, str) or not reason for reason in reasons)
        or len(reasons) != len(set(reasons))
    ):
        raise AIProposalError("factor worksheet manual reasons are invalid")
    status = worksheet.get("proposal_status")
    if status == "AI_PROPOSED":
        _validate_candidate_factor(worksheet.get("candidate_factor"))
        if (
            reasons
            or parsed_terms is None
            or calculation_inputs is None
            or worksheet.get("formula") != FORMULA
        ):
            raise AIProposalError("complete factor worksheet is inconsistent")
    elif status == "MANUAL_REQUIRED":
        if worksheet.get("candidate_factor") is not None or not reasons:
            raise AIProposalError("manual factor worksheet is inconsistent")
        formula = worksheet.get("formula")
        if formula not in {None, FORMULA}:
            raise AIProposalError("factor worksheet formula is invalid")
    else:
        raise AIProposalError("factor worksheet proposal status is invalid")
    return copy.deepcopy(dict(worksheet))


def _expected_outcome(
    *,
    index: Mapping[str, object],
    worksheet: Mapping[str, object] | None,
) -> tuple[str, list[str]]:
    if index["queue_kind"] == "visibility":
        if worksheet is not None:
            raise AIProposalError("visibility proposals cannot carry factor worksheets")
        if index["announcement_candidates"]:
            return "MANUAL_REQUIRED", [
                "ANNOUNCEMENT_CANDIDATES_REQUIRE_HUMAN_SELECTION"
            ]
        return "NO_SAFE_PROPOSAL", ["NO_COMPATIBLE_ANNOUNCEMENT_CANDIDATE"]
    if worksheet is None:
        raise AIProposalError("factor proposals require a factor worksheet")
    if worksheet["proposal_status"] == "AI_PROPOSED":
        return "AI_PROPOSED", [
            "FACTOR_WORKSHEET_COMPLETE_HUMAN_ADOPTION_REQUIRED"
        ]
    return "MANUAL_REQUIRED", list(worksheet["manual_required_reasons"])


def _proposal_content(record: Mapping[str, object]) -> dict[str, object]:
    content = copy.deepcopy(dict(record))
    content.pop("proposal_id", None)
    content.pop("generated_at", None)
    return content


def _proposal_id(record: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(_proposal_content(record))).hexdigest()


def build_ai_proposal(
    *,
    review_row: Mapping[str, str],
    evidence_index: Mapping[str, object],
    factor_worksheet: Mapping[str, object] | None,
    model_id: str,
    workflow_sha256: str,
    generated_at: str,
    review_queue_rows: list[Mapping[str, str]] | None = None,
) -> dict[str, object]:
    """Build one authority-free proposal bound to an exact review identity."""

    queue_kind = _evidence_queue_kind(evidence_index)
    review = _normalize_review_row(review_row)
    queue_context = _validate_queue_context(
        [review] if review_queue_rows is None else review_queue_rows,
        queue_kind=queue_kind,
        review=review,
    )
    index, retained_candidates = _validate_evidence_input(
        evidence_index,
        review=review,
    )
    worksheet = (
        None
        if factor_worksheet is None
        else _validate_worksheet(factor_worksheet, review=review)
    )
    if not isinstance(model_id, str) or not model_id or model_id != model_id.strip():
        raise AIProposalError("model ID must be nonblank and canonical")
    if not _valid_sha256(workflow_sha256):
        raise AIProposalError("workflow SHA-256 is invalid")
    generated = _parse_generated_at(generated_at)
    status, rationale = _expected_outcome(index=index, worksheet=worksheet)
    if status not in _PROPOSAL_STATUSES:
        raise AIProposalError("proposal status is invalid")

    record: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "proposal_only": True,
        "review_id": review["review_id"],
        "queue_kind": index["queue_kind"],
        "review_identity": {
            field: review[field] for field in sorted(_IDENTITY_FIELDS)
        },
        "review_queue_context": queue_context,
        "evidence_index": index,
        "retained_candidate_evidence": retained_candidates,
        "factor_worksheet": worksheet,
        "proposal_status": status,
        "model_id": model_id,
        "workflow_sha256": workflow_sha256,
        "generated_at": generated,
        "rationale": rationale,
    }
    record["proposal_id"] = _proposal_id(record)
    return _canonical_copy(record)  # type: ignore[return-value]


def _validate_proposal(value: Mapping[str, object]) -> dict[str, object]:
    _reject_authority(value)
    record = _exact_mapping(value, _PROPOSAL_FIELDS, label="AI proposal")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise AIProposalError("AI proposal schema version is invalid")
    if record.get("proposal_only") is not True:
        raise AIProposalError("AI proposal must be proposal-only")
    if not _valid_sha256(record.get("proposal_id")):
        raise AIProposalError("proposal ID is invalid")
    if not _valid_sha256(record.get("review_id")):
        raise AIProposalError("proposal review ID is invalid")
    if record.get("queue_kind") not in {"visibility", "factor"}:
        raise AIProposalError("proposal queue kind is invalid")
    if (
        not isinstance(record.get("model_id"), str)
        or not record["model_id"]
        or record["model_id"] != record["model_id"].strip()
    ):
        raise AIProposalError("model ID must be nonblank and canonical")
    if not _valid_sha256(record.get("workflow_sha256")):
        raise AIProposalError("workflow SHA-256 is invalid")
    _parse_generated_at(record.get("generated_at"))

    identity = _exact_mapping(
        record.get("review_identity"),
        _IDENTITY_FIELDS,
        label="proposal review identity",
    )
    review = {"review_id": record["review_id"], **identity}
    review = _normalize_review_row(review)  # type: ignore[arg-type]
    _validate_stored_queue_context(
        record.get("review_queue_context"),
        queue_kind=record["queue_kind"],
        review=review,
    )
    index = _validate_index(record.get("evidence_index"), review=review)  # type: ignore[arg-type]
    if index["queue_kind"] != record["queue_kind"]:
        raise AIProposalError("proposal queue kind is stale")
    retained_candidates = _validate_retained_candidate_records(
        record.get("retained_candidate_evidence"),
        index=index,
        review=review,
    )
    if retained_candidates != record["retained_candidate_evidence"]:
        raise AIProposalError("retained candidate evidence is not canonical")
    worksheet_value = record.get("factor_worksheet")
    worksheet = (
        None
        if worksheet_value is None
        else _validate_worksheet(worksheet_value, review=review)  # type: ignore[arg-type]
    )
    expected_status, expected_rationale = _expected_outcome(
        index=index,
        worksheet=worksheet,
    )
    if record.get("proposal_status") != expected_status:
        raise AIProposalError("proposal status is inconsistent")
    if record.get("rationale") != expected_rationale:
        raise AIProposalError("proposal rationale is inconsistent")
    if record["proposal_id"] != _proposal_id(record):
        raise AIProposalError("proposal ID conflicts with authority-free content")
    return copy.deepcopy(dict(record))


def _json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


def _read_history(handle) -> tuple[bytes, list[dict[str, object]]]:
    handle.seek(0)
    content = handle.read()
    if not content:
        return b"", []
    if not content.endswith(b"\n"):
        raise AIProposalError("proposal history is not newline-terminated")

    records: list[dict[str, object]] = []
    seen_records: set[bytes] = set()
    content_by_id: dict[str, bytes] = {}
    for line in content.splitlines(keepends=True):
        if line == b"\n":
            raise AIProposalError("proposal history contains a blank line")
        try:
            value = json.loads(line, parse_constant=_json_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise AIProposalError("proposal history contains invalid JSON") from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != line:
            raise AIProposalError("proposal history contains a noncanonical record")
        record = _validate_proposal(value)
        encoded = canonical_json_bytes(record)
        if encoded in seen_records:
            raise AIProposalError("proposal history contains a duplicate record")
        seen_records.add(encoded)
        proposal_id = record["proposal_id"]
        authority_free = canonical_json_bytes(_proposal_content(record))
        existing_content = content_by_id.setdefault(proposal_id, authority_free)
        if existing_content != authority_free:
            raise AIProposalError("proposal history contains a conflicting proposal ID")
        records.append(record)
    return content, records


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    return flags


@contextmanager
def _open_destination_parent(path: Path):
    raw_parts = path.parts
    if ".." in raw_parts:
        raise AIProposalError("proposal path cannot contain parent traversal")
    absolute = Path(os.path.abspath(os.fspath(path)))
    parts = absolute.parts
    if len(parts) < 2 or not parts[-1]:
        raise AIProposalError("proposal destination path is invalid")

    descriptors: list[int] = []
    try:
        current = os.open(parts[0], _directory_open_flags())
        descriptors.append(current)
        for component in parts[1:-1]:
            try:
                child = os.open(
                    component,
                    _directory_open_flags(),
                    dir_fd=current,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
                try:
                    child = os.open(
                        component,
                        _directory_open_flags(),
                        dir_fd=current,
                    )
                except OSError as error:
                    raise AIProposalError(
                        "proposal path components cannot be symlinks or non-directories"
                    ) from error
            except OSError as error:
                raise AIProposalError(
                    "proposal path components cannot be symlinks or non-directories"
                ) from error
            if not stat.S_ISDIR(os.fstat(child).st_mode):
                os.close(child)
                raise AIProposalError(
                    "proposal path components cannot be symlinks or non-directories"
                )
            descriptors.append(child)
            current = child
        yield absolute, current, parts[-1]
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _fsync_parent(descriptor: int) -> None:
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        raise AIProposalError("proposal parent must be a directory")
    os.fsync(descriptor)


def _write_all(handle, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = handle.write(remaining)
        if not isinstance(written, int) or written <= 0:
            raise OSError("proposal append made no progress")
        remaining = remaining[written:]


def _assert_destination_binding(parent_descriptor: int, name: str, handle) -> None:
    descriptor_stat = os.fstat(handle.fileno())
    if not stat.S_ISREG(descriptor_stat.st_mode) or descriptor_stat.st_nlink != 1:
        raise AIProposalError("proposal destination must be a single-link regular file")
    try:
        path_stat = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as error:
        raise AIProposalError("proposal destination path binding changed") from error
    if (
        not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_dev != descriptor_stat.st_dev
        or path_stat.st_ino != descriptor_stat.st_ino
    ):
        raise AIProposalError("proposal destination path binding changed")


def _open_locked(parent_descriptor: int, name: str):
    flags = os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(
            name,
            flags | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_descriptor,
        )
        created = True
    except FileExistsError:
        try:
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
            created = False
        except OSError as error:
            raise AIProposalError(
                "proposal destination must be a regular file"
            ) from error
    except OSError as error:
        raise AIProposalError("proposal destination must be a regular file") from error
    handle = None
    try:
        handle = os.fdopen(descriptor, "r+b", buffering=0)
        _assert_destination_binding(parent_descriptor, name, handle)
        return handle, created
    except Exception:
        if handle is not None:
            handle.close()
        else:
            os.close(descriptor)
        raise


def append_ai_proposals(
    path: str | Path,
    proposals: Iterable[Mapping[str, object]],
    *,
    parent_descriptor: int | None = None,
) -> dict[str, object]:
    """Append canonical proposal records under one lock without rewriting history."""

    try:
        candidate_values = list(proposals)
    except TypeError as error:
        raise AIProposalError("proposals must be iterable mappings") from error
    validated: list[dict[str, object]] = []
    for value in candidate_values:
        if not isinstance(value, Mapping):
            raise AIProposalError("proposal must be a mapping")
        validated.append(_validate_proposal(value))

    destination = Path(path)
    parent_context = (
        _open_destination_parent(destination)
        if parent_descriptor is None
        else nullcontext((destination, parent_descriptor, destination.name))
    )
    with parent_context as (
        _absolute_destination,
        parent_descriptor,
        destination_name,
    ):
        handle, created = _open_locked(parent_descriptor, destination_name)
        with handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                _assert_destination_binding(
                    parent_descriptor,
                    destination_name,
                    handle,
                )
                prior, existing = _read_history(handle)
                seen_records = {
                    canonical_json_bytes(record) for record in existing
                }
                content_by_id = {
                    record["proposal_id"]: canonical_json_bytes(
                        _proposal_content(record)
                    )
                    for record in existing
                }
                to_append: list[bytes] = []
                for record in validated:
                    encoded = canonical_json_bytes(record)
                    authority_free = canonical_json_bytes(
                        _proposal_content(record)
                    )
                    proposal_id = record["proposal_id"]
                    known = content_by_id.get(proposal_id)
                    if known is not None and known != authority_free:
                        raise AIProposalError(
                            "proposal ID conflicts with authority-free content"
                        )
                    content_by_id.setdefault(proposal_id, authority_free)
                    if encoded in seen_records:
                        continue
                    seen_records.add(encoded)
                    to_append.append(encoded)

                appended = b"".join(to_append)
                if appended:
                    handle.seek(0, os.SEEK_END)
                    try:
                        _write_all(handle, appended)
                        handle.flush()
                        os.fsync(handle.fileno())
                        _assert_destination_binding(
                            parent_descriptor,
                            destination_name,
                            handle,
                        )
                    except Exception as error:
                        try:
                            handle.seek(len(prior))
                            handle.truncate()
                            handle.flush()
                            os.fsync(handle.fileno())
                        except Exception as rollback_error:
                            raise AIProposalDurabilityError(
                                "proposal append failed and prior-history restoration is uncertain"
                            ) from rollback_error
                        raise AIProposalError(
                            "proposal append failed; prior history restored"
                        ) from error
                elif created:
                    os.fsync(handle.fileno())

                final = prior + appended
                if appended or created:
                    try:
                        _fsync_parent(parent_descriptor)
                    except Exception as error:
                        raise AIProposalDurabilityError(
                            "proposal destination changed but parent durability is uncertain"
                        ) from error
                return {
                    "schema_version": LOG_SCHEMA_VERSION,
                    "existing_count": len(existing),
                    "appended_count": len(to_append),
                    "proposal_count": len(existing) + len(to_append),
                    "sha256": hashlib.sha256(final).hexdigest(),
                }
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


_PACKET_CSV_NAMES = ("visibility-reviews.csv", "factor-reviews.csv")
_CLI_ARTIFACT_NAMES = {
    "evidence_index": "evidence-index.jsonl",
    "factor_worksheets": "factor-worksheets.jsonl",
    "ai_proposals": "ai-proposals.jsonl",
}
_CLI_MANIFEST_FIELDS = {
    "schema_version",
    "proposal_only",
    "packet_dir",
    "packet_csv_sha256",
    "inputs",
    "artifacts",
}
_CLI_ARTIFACT_FIELDS = {"path", "sha256", "count", "status"}
_MAX_CLI_INPUT_BYTES = 25_000_000
_MAX_CANDIDATE_BYTES = 25_000_000


class _CLIArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AIProposalCLIError("INVALID_ARGUMENTS")


def _read_regular_bytes(path: Path, *, max_bytes: int = _MAX_CLI_INPUT_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise AIProposalCLIError("INVALID_INPUT_BINDING") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > max_bytes:
            raise AIProposalCLIError("INVALID_INPUT_BINDING")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > max_bytes:
            raise AIProposalCLIError("INVALID_INPUT_BINDING")
        final = os.fstat(descriptor)
        if (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        ) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
        ):
            raise AIProposalCLIError("INPUT_CHANGED_DURING_READ")
        return content
    finally:
        os.close(descriptor)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _assert_no_symlink_components(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise AIProposalCLIError("ROOT_ISOLATION_VIOLATION") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise AIProposalCLIError("ROOT_ISOLATION_VIOLATION")
    return absolute


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _root_identity(path: Path) -> tuple[int, int]:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise AIProposalCLIError("ROOT_BINDING_CHANGED") from error
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise AIProposalCLIError("ROOT_BINDING_CHANGED")
    return metadata.st_dev, metadata.st_ino


def _prepare_roots(
    proposal_root: str,
    packet_dir: str,
) -> tuple[Path, Path, tuple[int, int]]:
    proposal = _assert_no_symlink_components(Path(proposal_root))
    packet = _assert_no_symlink_components(Path(packet_dir))
    if (
        proposal == packet
        or _is_within(proposal, packet)
        or _is_within(packet, proposal)
    ):
        raise AIProposalCLIError("ROOT_ISOLATION_VIOLATION")
    if not packet.is_dir():
        raise AIProposalCLIError("INVALID_PACKET_BINDING")
    try:
        proposal.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AIProposalCLIError("ROOT_ISOLATION_VIOLATION") from error
    if not proposal.is_dir():
        raise AIProposalCLIError("ROOT_ISOLATION_VIOLATION")
    return proposal, packet, _root_identity(proposal)


def _stable_descriptor_path(descriptor: int, fallback: Path) -> Path:
    for root in (Path("/proc/self/fd"), Path("/dev/fd")):
        candidate = root / str(descriptor)
        if candidate.exists():
            # Path-based writers cannot create children beneath the fd symlink on
            # macOS. Keep the already validated path and re-check its identity
            # immediately before each command's first write.
            return fallback
    raise AIProposalCLIError("ROOT_DESCRIPTOR_UNAVAILABLE")


@contextmanager
def _cli_transaction(
    root: Path,
    expected_identity: tuple[int, int],
):
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        root_descriptor = os.open(root, flags)
    except OSError as error:
        raise AIProposalCLIError("ROOT_BINDING_CHANGED") from error
    lock_descriptor: int | None = None
    try:
        root_metadata = os.fstat(root_descriptor)
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or (root_metadata.st_dev, root_metadata.st_ino) != expected_identity
        ):
            raise AIProposalCLIError("ROOT_BINDING_CHANGED")
        lock_flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        lock_error: OSError | None = None
        for _attempt in range(50):
            try:
                lock_descriptor = os.open(
                    ".cli.lock",
                    lock_flags,
                    0o600,
                    dir_fd=root_descriptor,
                )
                lock_error = None
                break
            except OSError as error:
                lock_error = error
                time.sleep(0.005)
        if lock_descriptor is None:
            raise AIProposalCLIError("ROOT_LOCK_REJECTED") from lock_error
        lock_metadata = os.fstat(lock_descriptor)
        if not stat.S_ISREG(lock_metadata.st_mode):
            raise AIProposalCLIError("ROOT_LOCK_REJECTED")
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        if _root_identity(root) != expected_identity:
            raise AIProposalCLIError("ROOT_BINDING_CHANGED")
        stable_root = _stable_descriptor_path(root_descriptor, root)
        _assert_no_part_artifacts(stable_root)
        yield stable_root, root_descriptor
        if _root_identity(root) != expected_identity:
            raise AIProposalCLIError("ROOT_BINDING_CHANGED")
        os.fsync(root_descriptor)
    finally:
        if lock_descriptor is not None:
            try:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
            finally:
                os.close(lock_descriptor)
        os.close(root_descriptor)


def _command_roots(args: argparse.Namespace) -> tuple[Path, Path]:
    root = getattr(args, "_proposal_root_path", None)
    packet = getattr(args, "_packet_dir_path", None)
    if not isinstance(root, Path) or not isinstance(packet, Path):
        raise AIProposalCLIError("ROOT_TRANSACTION_REQUIRED")
    return root, packet


def _assert_command_root(args: argparse.Namespace, root: Path) -> None:
    expected = getattr(args, "_root_identity", None)
    if expected is None or _root_identity(root) != expected:
        raise AIProposalCLIError("ROOT_BINDING_CHANGED")


def _assert_no_part_artifacts(root: Path) -> None:
    for directory, names, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in [*names, *filenames]:
            path = directory_path / name
            try:
                metadata = path.lstat()
            except OSError as error:
                raise AIProposalCLIError("PREEXISTING_PART_ARTIFACT") from error
            if stat.S_ISLNK(metadata.st_mode):
                raise AIProposalCLIError("ROOT_ISOLATION_VIOLATION")
            if name.endswith(".part") or ".part." in name:
                raise AIProposalCLIError("PREEXISTING_PART_ARTIFACT")


def _packet_hashes(packet_dir: Path) -> dict[str, str]:
    return {
        name: _sha256_bytes(_read_regular_bytes(packet_dir / name))
        for name in _PACKET_CSV_NAMES
    }


def _load_json(content: bytes) -> object:
    try:
        return json.loads(
            content,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AIProposalCLIError("MALFORMED_ARTIFACT") from error


def _load_json_path(path: Path) -> object:
    return _load_json(_read_regular_bytes(path))


def _load_canonical_jsonl(path: Path) -> tuple[list[dict[str, object]], bytes]:
    content = _read_regular_bytes(path)
    if content and not content.endswith(b"\n"):
        raise AIProposalCLIError("MALFORMED_ARTIFACT")
    rows: list[dict[str, object]] = []
    for line in content.splitlines(keepends=True):
        value = _load_json(line)
        if not isinstance(value, dict) or canonical_json_bytes(value) != line:
            raise AIProposalCLIError("MALFORMED_ARTIFACT")
        rows.append(value)
    return rows, content


def _relative_artifact(path: Path, root: Path) -> str:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if not _is_within(absolute, root):
        raise AIProposalCLIError("ROOT_ISOLATION_VIOLATION")
    return absolute.relative_to(root).as_posix()


def _artifact_path(root: Path, record: Mapping[str, object]) -> Path:
    if set(record) != _CLI_ARTIFACT_FIELDS:
        raise AIProposalCLIError("MALFORMED_MANIFEST")
    relative = record.get("path")
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or not _valid_sha256(record.get("sha256"))
        or type(record.get("count")) is not int
        or record["count"] < 0
        or record.get("status") != "CURRENT"
    ):
        raise AIProposalCLIError("MALFORMED_MANIFEST")
    path = root / relative
    if not _is_within(Path(os.path.abspath(os.fspath(path))), root):
        raise AIProposalCLIError("ROOT_ISOLATION_VIOLATION")
    return path


def _artifact_record(
    path: Path,
    root: Path,
    *,
    count: int,
    status: str = "CURRENT",
) -> dict[str, object]:
    content = _read_regular_bytes(path)
    return {
        "path": _relative_artifact(path, root),
        "sha256": _sha256_bytes(content),
        "count": count,
        "status": status,
    }


def _new_manifest(packet_dir: Path, packet_hashes: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": CLI_MANIFEST_SCHEMA_VERSION,
        "proposal_only": True,
        "packet_dir": str(packet_dir),
        "packet_csv_sha256": dict(packet_hashes),
        "inputs": {},
        "artifacts": {},
    }


def _validate_manifest(
    value: object,
    *,
    packet_dir: Path,
    packet_hashes: dict[str, str],
) -> dict[str, object]:
    try:
        _reject_authority(value)
    except AIProposalError as error:
        raise AIProposalCLIError("STALE_OR_MALFORMED_MANIFEST") from error
    if not isinstance(value, dict) or set(value) != _CLI_MANIFEST_FIELDS:
        raise AIProposalCLIError("MALFORMED_MANIFEST")
    if (
        value.get("schema_version") != CLI_MANIFEST_SCHEMA_VERSION
        or value.get("proposal_only") is not True
        or value.get("packet_dir") != str(packet_dir)
        or value.get("packet_csv_sha256") != packet_hashes
        or not isinstance(value.get("inputs"), dict)
        or not isinstance(value.get("artifacts"), dict)
    ):
        raise AIProposalCLIError("STALE_OR_MALFORMED_MANIFEST")
    if not set(value["inputs"]).issubset({
        "catalogue", "baseline_report", "retained_inputs",
    }) or not set(value["artifacts"]).issubset({
        "evidence_index",
        "candidate_manifest",
        "factor_worksheets",
        "ai_proposals",
    }):
        raise AIProposalCLIError("STALE_OR_MALFORMED_MANIFEST")
    for record in value["artifacts"].values():
        if (
            not isinstance(record, Mapping)
            or record.get("status") != "CURRENT"
        ):
            raise AIProposalCLIError("STALE_OR_MALFORMED_MANIFEST")
    return copy.deepcopy(value)


def _load_manifest(
    root: Path,
    packet_dir: Path,
    packet_hashes: dict[str, str],
    *,
    required: bool = False,
) -> dict[str, object]:
    path = root / "manifest.json"
    if not path.exists():
        if required:
            raise AIProposalCLIError("MISSING_MANIFEST")
        return _new_manifest(packet_dir, packet_hashes)
    value = _validate_manifest(
        _load_json_path(path),
        packet_dir=packet_dir,
        packet_hashes=packet_hashes,
    )
    for record in value["artifacts"].values():
        if not isinstance(record, Mapping):
            raise AIProposalCLIError("MALFORMED_MANIFEST")
        _artifact_path(root, record)
    return value


def _invalidate_downstream(
    manifest: dict[str, object],
    *artifact_names: str,
) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise AIProposalCLIError("MALFORMED_MANIFEST")
    for name in artifact_names:
        artifacts.pop(name, None)


def _atomic_replace_in_directory(
    directory: Path,
    name: str,
    content: bytes,
    *,
    directory_fd: int | None = None,
) -> None:
    owns_directory_fd = directory_fd is None
    if owns_directory_fd:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            directory_fd = os.open(directory, flags)
        except OSError as error:
            raise AIProposalCLIError("ARTIFACT_WRITE_FAILED") from error
    assert directory_fd is not None
    part_name = name + ".part"
    replaced = False
    try:
        try:
            descriptor = os.open(
                part_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
        except (FileExistsError, OSError) as error:
            raise AIProposalCLIError("PREEXISTING_PART_ARTIFACT") from error
        try:
            offset = 0
            while offset < len(content):
                offset += os.write(descriptor, content[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(
            part_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        replaced = True
        os.fsync(directory_fd)
    except OSError as error:
        if not replaced:
            try:
                os.unlink(part_name, dir_fd=directory_fd)
            except OSError:
                pass
            raise AIProposalCLIError("ARTIFACT_WRITE_FAILED") from error
        raise AIProposalCLIError("ARTIFACT_DURABILITY_UNCERTAIN") from error
    finally:
        if owns_directory_fd:
            os.close(directory_fd)


def _atomic_replace(
    path: Path,
    content: bytes,
    *,
    directory_fd: int | None = None,
) -> None:
    _atomic_replace_in_directory(
        path.parent,
        path.name,
        content,
        directory_fd=directory_fd,
    )


def _write_manifest(
    root: Path,
    manifest: Mapping[str, object],
    *,
    directory_fd: int | None = None,
) -> None:
    _atomic_replace(
        root / "manifest.json",
        canonical_json_bytes(manifest),
        directory_fd=directory_fd,
    )


def _input_binding(path: Path) -> dict[str, str]:
    content = _read_regular_bytes(path)
    return {"path": str(path), "sha256": _sha256_bytes(content)}


def _assert_binding_current(value: object) -> Path:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"path", "sha256"}
        or not isinstance(value.get("path"), str)
        or not _valid_sha256(value.get("sha256"))
    ):
        raise AIProposalCLIError("MALFORMED_MANIFEST")
    path = Path(value["path"])
    if _sha256_bytes(_read_regular_bytes(path)) != value["sha256"]:
        raise AIProposalCLIError("STALE_INPUT_BINDING")
    return path


def _assert_packet_unchanged(packet_dir: Path, expected: dict[str, str]) -> None:
    if _packet_hashes(packet_dir) != expected:
        raise AIProposalCLIError("CANONICAL_PACKET_CHANGED")


def _write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    directory_fd: int | None = None,
) -> None:
    content = b"".join(canonical_json_bytes(row) for row in rows)
    if path.exists() and _read_regular_bytes(path) == content:
        return
    _atomic_replace(path, content, directory_fd=directory_fd)


def _baseline_review_rows(path: Path) -> dict[str, list[dict[str, str]]]:
    value = _load_json_path(path)
    if not isinstance(value, dict):
        raise AIProposalCLIError("INVALID_BASELINE")
    try:
        return {
            "visibility": build_review_rows(
                "visibility", value["visibility_review_queue"],
            ),
            "factor": build_review_rows("factor", value["factor_review_queue"]),
        }
    except (KeyError, TypeError, ValueError, CorporateActionReviewError) as error:
        raise AIProposalCLIError("INVALID_BASELINE") from error


def _command_output(
    command: str,
    *,
    artifacts: Sequence[Mapping[str, object]],
    counts: Mapping[str, int],
    blocker_categories: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "schema_version": CLI_OUTPUT_SCHEMA_VERSION,
        "proposal_only": True,
        "command": command,
        "status": "COMPLETED",
        "artifacts": [copy.deepcopy(dict(value)) for value in artifacts],
        "counts": dict(counts),
        "blocker_categories": sorted(set(blocker_categories)),
    }


def _read_manifest_artifact(
    root: Path,
    manifest: Mapping[str, object],
    name: str,
) -> tuple[Path, dict[str, object]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping) or name not in artifacts:
        raise AIProposalCLIError("MISSING_REQUIRED_ARTIFACT")
    record = artifacts[name]
    if not isinstance(record, Mapping):
        raise AIProposalCLIError("MALFORMED_MANIFEST")
    path = _artifact_path(root, record)
    content = _read_regular_bytes(path)
    if _sha256_bytes(content) != record["sha256"]:
        raise AIProposalCLIError("ARTIFACT_HASH_MISMATCH")
    return path, copy.deepcopy(dict(record))


def _run_build_index(args: argparse.Namespace) -> dict[str, object]:
    root, packet = _command_roots(args)
    _assert_command_root(args, root)
    packet_before = _packet_hashes(packet)
    manifest = _load_manifest(root, packet, packet_before)
    _invalidate_downstream(
        manifest,
        "candidate_manifest",
        "factor_worksheets",
        "ai_proposals",
    )
    catalogue = _assert_no_symlink_components(Path(args.catalogue))
    baseline = _assert_no_symlink_components(Path(args.baseline_report))
    catalogue_binding = _input_binding(catalogue)
    baseline_binding = _input_binding(baseline)
    try:
        rows = build_evidence_index(
            catalogue_path=catalogue,
            baseline_report_path=baseline,
            packet_dir=packet,
        )
        _assert_command_root(args, root)
        output = root / _CLI_ARTIFACT_NAMES["evidence_index"]
        index_bytes = b"".join(canonical_json_bytes(row) for row in rows)
        _atomic_replace(
            output,
            index_bytes,
            directory_fd=args._root_descriptor,
        )
        metadata = {
            "sha256": _sha256_bytes(index_bytes),
            "row_count": len(rows),
        }
    except EvidenceIndexError as error:
        raise AIProposalCLIError("EVIDENCE_INDEX_REJECTED") from error
    if _input_binding(catalogue) != catalogue_binding or _input_binding(baseline) != baseline_binding:
        raise AIProposalCLIError("INPUT_CHANGED_DURING_COMMAND")
    _assert_packet_unchanged(packet, packet_before)
    record = _artifact_record(output, root, count=len(rows))
    if record["sha256"] != metadata["sha256"]:
        raise AIProposalCLIError("ARTIFACT_HASH_MISMATCH")
    manifest["inputs"]["catalogue"] = catalogue_binding
    manifest["inputs"]["baseline_report"] = baseline_binding
    manifest["artifacts"]["evidence_index"] = record
    _write_manifest(root, manifest, directory_fd=args._root_descriptor)
    counts = {
        "visibility": sum(row["queue_kind"] == "visibility" for row in rows),
        "factor": sum(row["queue_kind"] == "factor" for row in rows),
        "total": len(rows),
    }
    return _command_output("build-index", artifacts=[record], counts=counts)


def _run_retain_candidates(args: argparse.Namespace) -> dict[str, object]:
    root, packet = _command_roots(args)
    if (
        type(args.max_bytes) is not int
        or args.max_bytes <= 0
        or args.max_bytes > _MAX_CANDIDATE_BYTES
    ):
        raise AIProposalCLIError("MAX_BYTES_OUT_OF_POLICY")
    packet_before = _packet_hashes(packet)
    manifest = _load_manifest(root, packet, packet_before, required=True)
    _invalidate_downstream(manifest, "factor_worksheets", "ai_proposals")
    index_path, _ = _read_manifest_artifact(root, manifest, "evidence_index")
    index_rows, _ = _load_canonical_jsonl(index_path)
    session = requests.Session()
    session.trust_env = False
    try:
        candidate_manifest = retain_candidate_attachments(
            index_rows,
            output_dir=root / "evidence",
            allowed_hosts=set(args.allowed_host),
            session=session,
            max_bytes=args.max_bytes,
            root_descriptor=args._root_descriptor,
        )
    except CandidateEvidenceError as error:
        raise AIProposalCLIError("CANDIDATE_RETENTION_REJECTED") from error
    finally:
        session.close()
    _assert_packet_unchanged(packet, packet_before)
    manifest_bytes = canonical_json_bytes(candidate_manifest)
    digest = _sha256_bytes(manifest_bytes)
    path = root / "evidence" / "manifests" / "sha256" / digest[:2] / f"{digest}.json"
    if _read_regular_bytes(path) != manifest_bytes:
        raise AIProposalCLIError("ARTIFACT_HASH_MISMATCH")
    records = candidate_manifest["records"]
    artifact = _artifact_record(path, root, count=len(records))
    manifest["artifacts"]["candidate_manifest"] = artifact
    _write_manifest(root, manifest, directory_fd=args._root_descriptor)
    statuses = [record["status"] for record in records]
    failures = [
        str(record["failure_code"])
        for record in records
        if record["status"] == "FAILED"
    ]
    return _command_output(
        "retain-candidates",
        artifacts=[artifact],
        counts={
            "candidate_records": len(records),
            "retained": sum(status in {"RETAINED", "REUSED"} for status in statuses),
            "failed": statuses.count("FAILED"),
        },
        blocker_categories=failures,
    )


def _retained_input_rows(path: Path) -> tuple[dict[str, Mapping[str, object]], bytes]:
    rows, content = _load_canonical_jsonl(path)
    by_id: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if set(row) != {"review_id", "retained_inputs"} or not _valid_sha256(row.get("review_id")):
            raise AIProposalCLIError("INVALID_RETAINED_INPUTS")
        review_id = str(row["review_id"])
        inputs = row.get("retained_inputs")
        if review_id in by_id or not isinstance(inputs, Mapping):
            raise AIProposalCLIError("INVALID_RETAINED_INPUTS")
        for value in inputs.values():
            if not isinstance(value, Mapping) or set(value) != {
                "value", "path", "sha256", "available_at",
            }:
                raise AIProposalCLIError("INVALID_RETAINED_INPUTS")
            source_path = Path(str(value["path"]))
            if _sha256_bytes(_read_regular_bytes(source_path)) != value["sha256"]:
                raise AIProposalCLIError("STALE_INPUT_BINDING")
        by_id[review_id] = inputs
    return by_id, content


def _run_build_worksheets(args: argparse.Namespace) -> dict[str, object]:
    root, packet = _command_roots(args)
    packet_before = _packet_hashes(packet)
    manifest = _load_manifest(root, packet, packet_before, required=True)
    _invalidate_downstream(manifest, "ai_proposals")
    baseline = _assert_no_symlink_components(Path(args.baseline_report))
    retained_inputs = _assert_no_symlink_components(Path(args.retained_inputs))
    baseline_binding = _input_binding(baseline)
    retained_binding = _input_binding(retained_inputs)
    prior_baseline_binding = manifest["inputs"].get("baseline_report")
    if (
        prior_baseline_binding is not None
        and prior_baseline_binding != baseline_binding
    ):
        raise AIProposalCLIError("UPSTREAM_INPUT_BINDING_CHANGED")
    reviews = _baseline_review_rows(baseline)
    inputs_by_id, _ = _retained_input_rows(retained_inputs)
    expected_ids = {row["review_id"] for row in reviews["factor"]}
    if set(inputs_by_id) != expected_ids:
        raise AIProposalCLIError("INCOMPLETE_RETAINED_INPUTS")
    try:
        worksheets = [
            build_factor_worksheet(
                review,
                retained_inputs=inputs_by_id[review["review_id"]],
            )
            for review in reviews["factor"]
        ]
    except FactorWorksheetError as error:
        raise AIProposalCLIError("FACTOR_WORKSHEET_REJECTED") from error
    _assert_command_root(args, root)
    output = root / _CLI_ARTIFACT_NAMES["factor_worksheets"]
    _write_jsonl(
        output,
        worksheets,
        directory_fd=args._root_descriptor,
    )
    if _input_binding(baseline) != baseline_binding or _input_binding(retained_inputs) != retained_binding:
        raise AIProposalCLIError("INPUT_CHANGED_DURING_COMMAND")
    _assert_packet_unchanged(packet, packet_before)
    record = _artifact_record(output, root, count=len(worksheets))
    manifest["inputs"]["baseline_report"] = baseline_binding
    manifest["inputs"]["retained_inputs"] = retained_binding
    manifest["artifacts"]["factor_worksheets"] = record
    _assert_command_root(args, root)
    _write_manifest(root, manifest, directory_fd=args._root_descriptor)
    statuses = [row["proposal_status"] for row in worksheets]
    return _command_output(
        "build-worksheets",
        artifacts=[record],
        counts={
            "ai_proposed": statuses.count("AI_PROPOSED"),
            "manual_required": statuses.count("MANUAL_REQUIRED"),
            "total": len(worksheets),
        },
    )


def _run_append_proposals(args: argparse.Namespace) -> dict[str, object]:
    root, packet = _command_roots(args)
    packet_before = _packet_hashes(packet)
    manifest = _load_manifest(root, packet, packet_before, required=True)
    baseline = _assert_no_symlink_components(Path(args.baseline_report))
    baseline_binding = _input_binding(baseline)
    prior_baseline_binding = manifest["inputs"].get("baseline_report")
    if (
        prior_baseline_binding is not None
        and prior_baseline_binding != baseline_binding
    ):
        raise AIProposalCLIError("UPSTREAM_INPUT_BINDING_CHANGED")
    reviews = _baseline_review_rows(baseline)
    review_by_id = {
        row["review_id"]: (kind, row)
        for kind, rows in reviews.items()
        for row in rows
    }
    index_path, _ = _read_manifest_artifact(root, manifest, "evidence_index")
    index_rows, _ = _load_canonical_jsonl(index_path)
    worksheets: dict[str, dict[str, object]] = {}
    if "factor_worksheets" in manifest["artifacts"]:
        worksheet_path, _ = _read_manifest_artifact(
            root, manifest, "factor_worksheets",
        )
        worksheet_rows, _ = _load_canonical_jsonl(worksheet_path)
        worksheets = {str(row.get("review_id")): row for row in worksheet_rows}
        if len(worksheets) != len(worksheet_rows):
            raise AIProposalCLIError("DUPLICATE_FACTOR_WORKSHEET")
    candidate_manifest: dict[str, object] | None = None
    if "candidate_manifest" in manifest["artifacts"]:
        candidate_manifest, _ = _load_strict_candidate_manifest(
            root,
            manifest,
            index_rows=index_rows,
        )

    proposals: list[dict[str, object]] = []
    try:
        for index in index_rows:
            review_id = str(index.get("review_id"))
            if review_id not in review_by_id:
                raise AIProposalCLIError("STALE_REVIEW_ID")
            kind, review = review_by_id[review_id]
            if kind != index.get("queue_kind"):
                raise AIProposalCLIError("STALE_REVIEW_ID")
            worksheet = worksheets.get(review_id)
            if kind == "factor" and worksheet is None:
                raise AIProposalCLIError("MISSING_FACTOR_WORKSHEET")
            if kind == "visibility" and worksheet is not None:
                raise AIProposalCLIError("UNEXPECTED_FACTOR_WORKSHEET")
            evidence: Mapping[str, object] = index
            if candidate_manifest is not None:
                records = candidate_manifest.get("records")
                if not isinstance(records, list):
                    raise AIProposalCLIError("MALFORMED_ARTIFACT")
                evidence = {
                    "index_row": index,
                    "retained_candidate_manifest": {
                        "schema_version": candidate_manifest.get("schema_version"),
                        "proposal_only": candidate_manifest.get("proposal_only"),
                        "records": [
                            record for record in records
                            if isinstance(record, Mapping)
                            and record.get("review_id") == review_id
                        ],
                    },
                }
            proposals.append(build_ai_proposal(
                review_row=review,
                review_queue_rows=reviews[kind],
                evidence_index=evidence,
                factor_worksheet=worksheet,
                model_id=args.model_id,
                workflow_sha256=args.workflow_sha256,
                generated_at=args.generated_at,
            ))
        result = append_ai_proposals(
            root / _CLI_ARTIFACT_NAMES["ai_proposals"],
            proposals,
            parent_descriptor=args._root_descriptor,
        )
    except AIProposalCLIError:
        raise
    except AIProposalCLIError:
        raise
    except AIProposalError as error:
        raise AIProposalCLIError("AI_PROPOSAL_REJECTED") from error
    if _input_binding(baseline) != baseline_binding:
        raise AIProposalCLIError("INPUT_CHANGED_DURING_COMMAND")
    _assert_packet_unchanged(packet, packet_before)
    output = root / _CLI_ARTIFACT_NAMES["ai_proposals"]
    record = _artifact_record(output, root, count=result["proposal_count"])
    if record["sha256"] != result["sha256"]:
        raise AIProposalCLIError("ARTIFACT_HASH_MISMATCH")
    manifest["inputs"]["baseline_report"] = baseline_binding
    manifest["artifacts"]["ai_proposals"] = record
    _write_manifest(root, manifest, directory_fd=args._root_descriptor)
    return _command_output(
        "append-proposals",
        artifacts=[record],
        counts={
            "existing": result["existing_count"],
            "appended": result["appended_count"],
            "total": result["proposal_count"],
        },
    )


def _verify_retained_attachments(root: Path, candidate_manifest: Mapping[str, object]) -> None:
    records = candidate_manifest.get("records")
    if not isinstance(records, list):
        raise AIProposalCLIError("MALFORMED_ARTIFACT")
    for record in records:
        if not isinstance(record, Mapping):
            raise AIProposalCLIError("MALFORMED_ARTIFACT")
        if record.get("status") not in {"RETAINED", "REUSED"}:
            continue
        relative = record.get("attachment_path")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise AIProposalCLIError("ARTIFACT_BINDING_MISMATCH")
        path = _assert_no_symlink_components(root / "evidence" / relative)
        content = _read_regular_bytes(path, max_bytes=_MAX_CANDIDATE_BYTES)
        if (
            _sha256_bytes(content) != record.get("attachment_sha256")
            or len(content) != record.get("byte_count")
        ):
            raise AIProposalCLIError("ARTIFACT_BINDING_MISMATCH")


def _validate_candidate_manifest_strict(
    value: object,
    *,
    index_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    try:
        _reject_authority(value)
        manifest = _exact_mapping(
            value,
            _CANDIDATE_MANIFEST_FIELDS,
            label="retained candidate manifest",
        )
        if manifest.get("schema_version") != CANDIDATE_EVIDENCE_SCHEMA_VERSION:
            raise AIProposalError("candidate manifest schema version is invalid")
        if manifest.get("proposal_only") is not True:
            raise AIProposalError("candidate manifest must be proposal-only")
        records = manifest.get("records")
        if not isinstance(records, list):
            raise AIProposalError("candidate manifest records are invalid")

        expected_bindings: Counter[tuple[str, str, str]] = Counter()
        actual_bindings: Counter[tuple[str, str, str]] = Counter()
        known_review_ids: set[str] = set()
        for index in index_rows:
            review_id = index.get("review_id")
            identity = index.get("review_identity")
            candidates = index.get("announcement_candidates")
            if (
                not isinstance(review_id, str)
                or not isinstance(identity, Mapping)
                or not isinstance(candidates, list)
            ):
                raise AIProposalError("evidence index is invalid")
            review = {"review_id": review_id, **dict(identity)}
            relevant = [
                record
                for record in records
                if isinstance(record, Mapping)
                and record.get("review_id") == review_id
            ]
            _validate_candidate_manifest(
                {
                    "schema_version": manifest["schema_version"],
                    "proposal_only": manifest["proposal_only"],
                    "records": relevant,
                },
                index=index,
                review=review,
            )
            known_review_ids.add(review_id)
            expected_bindings.update(
                (review_id, candidate["attachment_url"], candidate["snapshot_sha256"])
                for candidate in candidates
            )
        for record in records:
            if not isinstance(record, Mapping):
                raise AIProposalError("candidate manifest record is invalid")
            review_id = record.get("review_id")
            if review_id not in known_review_ids:
                raise AIProposalError("candidate record review ID is stale")
            status = record.get("status")
            if status not in {"RETAINED", "REUSED", "FAILED"}:
                raise AIProposalError("candidate record status is invalid")
            actual_bindings.update([(
                str(review_id),
                str(record.get("candidate_url")),
                str(record.get("source_snapshot_sha256")),
            )])
        if actual_bindings != expected_bindings:
            raise AIProposalError("candidate manifest is incomplete or inconsistent")
    except (AIProposalError, TypeError, ValueError) as error:
        raise AIProposalCLIError("CANDIDATE_MANIFEST_REJECTED") from error
    return copy.deepcopy(dict(manifest))


def _load_strict_candidate_manifest(
    root: Path,
    cli_manifest: Mapping[str, object],
    *,
    index_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    path, record = _read_manifest_artifact(
        root,
        cli_manifest,
        "candidate_manifest",
    )
    content = _read_regular_bytes(path)
    digest = _sha256_bytes(content)
    expected_relative = (
        Path("evidence")
        / "manifests"
        / "sha256"
        / digest[:2]
        / f"{digest}.json"
    ).as_posix()
    if record["path"] != expected_relative:
        raise AIProposalCLIError("CANDIDATE_MANIFEST_REJECTED")
    value = _load_json(content)
    strict = _validate_candidate_manifest_strict(value, index_rows=index_rows)
    records = strict["records"]
    if len(records) != record["count"]:
        raise AIProposalCLIError("CANDIDATE_MANIFEST_REJECTED")
    return strict, record


def _validate_proposal_set(
    proposal_rows: Sequence[Mapping[str, object]],
    *,
    index_rows: Sequence[Mapping[str, object]],
    worksheet_rows: Sequence[Mapping[str, object]],
    candidate_manifest: Mapping[str, object],
    require_complete: bool,
) -> None:
    try:
        index_by_id = {
            str(row["review_id"]): row
            for row in index_rows
        }
        worksheet_by_id = {
            str(row["review_id"]): row
            for row in worksheet_rows
        }
        if (
            len(index_by_id) != len(index_rows)
            or len(worksheet_by_id) != len(worksheet_rows)
        ):
            raise AIProposalError("cross-artifact review IDs are duplicated")
        records = candidate_manifest.get("records")
        if not isinstance(records, list):
            raise AIProposalError("candidate manifest records are invalid")
        proposal_review_ids: set[str] = set()
        for value in proposal_rows:
            proposal = _validate_proposal(value)
            review_id = str(proposal["review_id"])
            if review_id in proposal_review_ids:
                raise AIProposalError("proposal review IDs are duplicated")
            index = index_by_id.get(review_id)
            if index is None or proposal["evidence_index"] != index:
                raise AIProposalError("proposal evidence index is not current")
            expected_candidates = [
                record
                for record in records
                if isinstance(record, Mapping)
                and record.get("review_id") == review_id
            ]
            if proposal["retained_candidate_evidence"] != expected_candidates:
                raise AIProposalError("proposal candidate evidence is not current")
            expected_worksheet = worksheet_by_id.get(review_id)
            if proposal["queue_kind"] == "factor":
                if expected_worksheet is None:
                    raise AIProposalError("factor proposal worksheet is missing")
            elif expected_worksheet is not None:
                raise AIProposalError("visibility proposal has a factor worksheet")
            if proposal["factor_worksheet"] != expected_worksheet:
                raise AIProposalError("proposal factor worksheet is not current")
            proposal_review_ids.add(review_id)
        current_ids = set(index_by_id)
        if not proposal_review_ids.issubset(current_ids):
            raise AIProposalError("proposal set contains stale review IDs")
        if require_complete and proposal_review_ids != current_ids:
            raise AIProposalError("proposal set is incomplete")
    except (AIProposalError, KeyError, TypeError, ValueError) as error:
        raise AIProposalCLIError("PROPOSAL_SET_MISMATCH") from error


def _run_verify(args: argparse.Namespace) -> dict[str, object]:
    root, packet = _command_roots(args)
    packet_current = _packet_hashes(packet)
    manifest = _load_manifest(root, packet, packet_current, required=True)
    required = {
        "evidence_index",
        "candidate_manifest",
        "factor_worksheets",
        "ai_proposals",
    }
    if set(manifest["artifacts"]) != required:
        raise AIProposalCLIError("INCOMPLETE_PROPOSAL_ARTIFACT_SET")
    verified_records: list[dict[str, object]] = []
    for name in sorted(required):
        _path, record = _read_manifest_artifact(root, manifest, name)
        verified_records.append(record)

    inputs = manifest["inputs"]
    if not isinstance(inputs, Mapping):
        raise AIProposalCLIError("MALFORMED_MANIFEST")
    catalogue = _assert_binding_current(inputs.get("catalogue"))
    baseline = _assert_binding_current(inputs.get("baseline_report"))
    retained_inputs = _assert_binding_current(inputs.get("retained_inputs"))
    reviews = _baseline_review_rows(baseline)
    try:
        rebuilt_index = build_evidence_index(
            catalogue_path=catalogue,
            baseline_report_path=baseline,
            packet_dir=packet,
        )
    except EvidenceIndexError as error:
        raise AIProposalCLIError("EVIDENCE_INDEX_REJECTED") from error
    index_path, index_record = _read_manifest_artifact(root, manifest, "evidence_index")
    index_rows, index_bytes = _load_canonical_jsonl(index_path)
    rebuilt_bytes = b"".join(canonical_json_bytes(row) for row in rebuilt_index)
    if rebuilt_bytes != index_bytes or len(index_rows) != index_record["count"]:
        raise AIProposalCLIError("STALE_SOURCE_BINDING")

    inputs_by_id, _ = _retained_input_rows(retained_inputs)
    worksheet_path, worksheet_record = _read_manifest_artifact(
        root, manifest, "factor_worksheets",
    )
    worksheet_rows, _ = _load_canonical_jsonl(worksheet_path)
    if len(worksheet_rows) != worksheet_record["count"]:
        raise AIProposalCLIError("ARTIFACT_COUNT_MISMATCH")
    expected_worksheets = []
    try:
        for review in reviews["factor"]:
            expected_worksheets.append(build_factor_worksheet(
                review,
                retained_inputs=inputs_by_id[review["review_id"]],
            ))
    except (KeyError, FactorWorksheetError) as error:
        raise AIProposalCLIError("FACTOR_WORKSHEET_REJECTED") from error
    if worksheet_rows != expected_worksheets:
        raise AIProposalCLIError("STALE_SOURCE_BINDING")

    candidate_value, candidate_record = _load_strict_candidate_manifest(
        root,
        manifest,
        index_rows=index_rows,
    )
    _verify_retained_attachments(root, candidate_value)

    proposal_path, proposal_record = _read_manifest_artifact(
        root, manifest, "ai_proposals",
    )
    proposal_rows, _ = _load_canonical_jsonl(proposal_path)
    if len(proposal_rows) != proposal_record["count"]:
        raise AIProposalCLIError("ARTIFACT_COUNT_MISMATCH")
    try:
        for proposal in proposal_rows:
            _validate_proposal(proposal)
        _validate_proposal_set(
            proposal_rows,
            index_rows=index_rows,
            worksheet_rows=worksheet_rows,
            candidate_manifest=candidate_value,
            require_complete=True,
        )
    except AIProposalCLIError:
        raise
    except AIProposalError as error:
        raise AIProposalCLIError("AI_PROPOSAL_REJECTED") from error
    _assert_packet_unchanged(packet, packet_current)
    manifest_record = _artifact_record(
        root / "manifest.json", root, count=len(required),
    )
    return _command_output(
        "verify",
        artifacts=[*verified_records, manifest_record],
        counts={
            "artifacts": len(required),
            "packet_csvs": len(_PACKET_CSV_NAMES),
            "proposals": len(proposal_rows),
        },
    )


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = _CLIArgumentParser(
        description="Build isolated, non-authoritative corporate-action AI proposals",
    )
    common = _CLIArgumentParser(add_help=False)
    common.add_argument("--proposal-root", required=True)
    common.add_argument("--packet-dir", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    build_index_parser = commands.add_parser("build-index", parents=[common])
    build_index_parser.add_argument("--catalogue", required=True)
    build_index_parser.add_argument("--baseline-report", required=True)

    retain_parser = commands.add_parser("retain-candidates", parents=[common])
    retain_parser.add_argument("--allowed-host", action="append", required=True)
    retain_parser.add_argument("--max-bytes", type=int, default=25_000_000)

    worksheet_parser = commands.add_parser("build-worksheets", parents=[common])
    worksheet_parser.add_argument("--baseline-report", required=True)
    worksheet_parser.add_argument("--retained-inputs", required=True)

    append_parser = commands.add_parser("append-proposals", parents=[common])
    append_parser.add_argument("--baseline-report", required=True)
    append_parser.add_argument("--model-id", required=True)
    append_parser.add_argument("--workflow-sha256", required=True)
    append_parser.add_argument("--generated-at", required=True)

    commands.add_parser("verify", parents=[common])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _build_cli_parser().parse_args(argv)
        handlers = {
            "build-index": _run_build_index,
            "retain-candidates": _run_retain_candidates,
            "build-worksheets": _run_build_worksheets,
            "append-proposals": _run_append_proposals,
            "verify": _run_verify,
        }
        root, packet, root_identity = _prepare_roots(
            args.proposal_root,
            args.packet_dir,
        )
        with _cli_transaction(root, root_identity) as transaction:
            stable_root, root_descriptor = transaction
            args._proposal_root_path = stable_root
            args._packet_dir_path = packet
            args._root_identity = root_identity
            args._root_descriptor = root_descriptor
            result = handlers[args.command](args)
    except AIProposalCLIError as error:
        failure = {
            "schema_version": CLI_OUTPUT_SCHEMA_VERSION,
            "proposal_only": True,
            "status": "BLOCKED",
            "blocker_categories": [error.category],
        }
        sys.stderr.write(json.dumps(failure, sort_keys=True, separators=(",", ":")) + "\n")
        return 2
    except (
        AIProposalError,
        CandidateEvidenceError,
        EvidenceIndexError,
        FactorWorksheetError,
        OSError,
        TypeError,
        ValueError,
    ):
        failure = {
            "schema_version": CLI_OUTPUT_SCHEMA_VERSION,
            "proposal_only": True,
            "status": "BLOCKED",
            "blocker_categories": ["COMMAND_REJECTED"],
        }
        sys.stderr.write(json.dumps(failure, sort_keys=True, separators=(",", ":")) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
