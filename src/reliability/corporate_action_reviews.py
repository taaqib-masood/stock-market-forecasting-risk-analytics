"""Fail-closed validation for independently completed corporate-action reviews."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import stat
from datetime import datetime, time, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlparse
import weakref
from zoneinfo import ZoneInfo

from src.reliability.preregistration import canonical_json_bytes


BASE_FIELDS = ["symbol", "action_type", "ex_date", "purpose", "reason"]
IDENTITY_FIELDS = ["review_id", *BASE_FIELDS]
REVIEW_FIELDS = [
    "decision",
    "evidence_path",
    "evidence_sha256",
    "evidence_source_url",
    "reviewer_id",
    "reviewed_at",
    "notes",
]
VISIBILITY_FIELDS = IDENTITY_FIELDS + ["confirmed_available_at"] + REVIEW_FIELDS
FACTOR_FIELDS = IDENTITY_FIELDS + [
    "confirmed_available_at",
    "adjustment_factor",
    "method",
] + REVIEW_FIELDS
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_CANONICAL_ACTOR_TYPE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_V1_POLICY_KEYS = (
    "policy_version",
    "authorized_reviewers",
    "prohibited_reviewers",
    "allowed_evidence_hosts",
)
_V2_POLICY_KEYS = (
    "policy_version",
    "authorized_reviewers",
    "prohibited_reviewers",
    "prohibited_actor_types",
    "allowed_evidence_hosts",
)
_V2_PRINCIPAL_KEYS = (
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
)
_PACKET_MANIFEST_SCHEMA_V1 = "corporate-action-review-packet-v2"
_PACKET_MANIFEST_SCHEMA_V2 = "corporate-action-review-packet-v3"
_PACKET_MANIFEST_KEYS = {
    "schema_version",
    "source_report_path",
    "source_report_sha256",
    "queue_counts",
    "template_sha256",
    "row_identities",
    "reviewer_policy_contract",
}


class CorporateActionReviewError(ValueError):
    """A packet or reviewer policy failed a mandatory verification gate."""


class _IdentityCapabilityRegistry:
    """Keep immutable capability payloads by exact token identity only."""

    def __init__(self) -> None:
        self._entries: dict[int, tuple[weakref.ReferenceType[object], object]] = {}

    def issue(self, token: object, payload: object) -> None:
        token_id = id(token)

        def cleanup(reference: weakref.ReferenceType[object]) -> None:
            entry = self._entries.get(token_id)
            if entry is not None and entry[0] is reference:
                self._entries.pop(token_id, None)

        self._entries[token_id] = (weakref.ref(token, cleanup), payload)

    def payload_for(
        self,
        value: object,
        token_type: type,
        authority_fields: tuple[str, ...],
    ) -> object | None:
        if type(value) is not token_type:
            return None
        if any(hasattr(value, field) for field in authority_fields):
            return None
        entry = self._entries.get(id(value))
        if entry is None or entry[0]() is not value:
            return None
        return entry[1]


def _freeze_capability_value(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CorporateActionReviewError("capability payload keys must be strings")
        return MappingProxyType({
            key: _freeze_capability_value(item) for key, item in value.items()
        })
    if isinstance(value, list):
        return tuple(_freeze_capability_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_capability_value(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise CorporateActionReviewError("capability payload contains unsupported value")


def _copy_capability_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _copy_capability_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_copy_capability_value(item) for item in value]
    return value


class ReviewedFactorOverrides:
    """Opaque factor capability whose trusted data stays outside the token."""

    __slots__ = ("_artifact_binding", "_audit_sha256", "_rows", "__weakref__")

    def __new__(cls, *_args: object, **_kwargs: object) -> ReviewedFactorOverrides:
        raise CorporateActionReviewError(
            "reviewed factor overrides must be loaded from a verified audit"
        )

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("reviewed factor overrides are immutable")

    @property
    def audit_sha256(self) -> str:
        return _factor_payload(self)["audit_sha256"]

    @property
    def artifact_binding(self) -> dict[str, object]:
        return _copy_capability_value(_factor_payload(self)["artifact_binding"])

    @property
    def rows(self) -> tuple[dict[str, object], ...]:
        rows = _factor_payload(self)["rows"]
        return tuple(_copy_capability_value(row) for row in rows)


class VerifiedCorporateActionAudit:
    """Opaque complete-audit capability whose data stays outside the token."""

    __slots__ = (
        "_artifact_binding",
        "_audit_sha256",
        "_complete",
        "_unresolved_factors",
        "_unresolved_visibility",
        "__weakref__",
    )

    def __new__(
        cls, *_args: object, **_kwargs: object,
    ) -> VerifiedCorporateActionAudit:
        raise CorporateActionReviewError(
            "verified corporate-action audit must be loaded from a verified audit"
        )

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("verified corporate-action audit is immutable")

    @property
    def audit_sha256(self) -> str:
        return _audit_payload(self)["audit_sha256"]

    @property
    def artifact_binding(self) -> dict[str, object]:
        return _copy_capability_value(_audit_payload(self)["artifact_binding"])

    @property
    def complete(self) -> bool:
        return _audit_payload(self)["complete"]

    @property
    def unresolved_visibility(self) -> int:
        return _audit_payload(self)["unresolved_visibility"]

    @property
    def unresolved_factors(self) -> int:
        return _audit_payload(self)["unresolved_factors"]


_ISSUED_FACTOR_OVERRIDES = _IdentityCapabilityRegistry()
_ISSUED_VERIFIED_AUDITS = _IdentityCapabilityRegistry()
_FACTOR_AUTHORITY_FIELDS = ("_artifact_binding", "_audit_sha256", "_rows")
_AUDIT_AUTHORITY_FIELDS = (
    "_artifact_binding",
    "_audit_sha256",
    "_complete",
    "_unresolved_factors",
    "_unresolved_visibility",
)
_AUDIT_REVALIDATION_SOURCE_FIELDS = (
    "reviewed_audit_path",
    "expected_sha256",
    "packet_dir",
    "policy_path",
    "baseline_report_path",
)


def _factor_payload(value: object) -> Mapping[str, object]:
    payload = _ISSUED_FACTOR_OVERRIDES.payload_for(
        value,
        ReviewedFactorOverrides,
        _FACTOR_AUTHORITY_FIELDS,
    )
    if not isinstance(payload, Mapping):
        raise CorporateActionReviewError(
            "reviewed factor overrides must be loaded from a verified audit"
        )
    return payload


def _audit_payload(value: object) -> Mapping[str, object]:
    payload = _ISSUED_VERIFIED_AUDITS.payload_for(
        value,
        VerifiedCorporateActionAudit,
        _AUDIT_AUTHORITY_FIELDS,
    )
    if not isinstance(payload, Mapping):
        raise CorporateActionReviewError(
            "verified corporate-action audit must be loaded from a verified audit"
        )
    return payload


def _issue_reviewed_factor_overrides(
    *,
    audit_sha256: str,
    rows: tuple[Mapping[str, object], ...],
    artifact_binding: Mapping[str, str],
) -> ReviewedFactorOverrides:
    capability = object.__new__(ReviewedFactorOverrides)
    _ISSUED_FACTOR_OVERRIDES.issue(
        capability,
        _freeze_capability_value({
            "audit_sha256": audit_sha256,
            "rows": rows,
            "artifact_binding": artifact_binding,
        }),
    )
    return capability


def _issue_verified_corporate_action_audit(
    *,
    audit_sha256: str,
    artifact_binding: Mapping[str, object],
    complete: bool,
    unresolved_visibility: int,
    unresolved_factors: int,
    revalidation_sources: Mapping[str, str] | None = None,
) -> VerifiedCorporateActionAudit:
    if (
        complete is not True
        or unresolved_visibility != 0
        or unresolved_factors != 0
    ):
        raise CorporateActionReviewError("verified audit cannot issue incomplete authority")
    capability = object.__new__(VerifiedCorporateActionAudit)
    source_payload: Mapping[str, str] | None = None
    if revalidation_sources is not None:
        if set(revalidation_sources) != set(_AUDIT_REVALIDATION_SOURCE_FIELDS):
            raise CorporateActionReviewError("verified audit revalidation sources are invalid")
        if any(
            not isinstance(value, str) or not value
            for value in revalidation_sources.values()
        ):
            raise CorporateActionReviewError("verified audit revalidation sources are invalid")
        source_payload = dict(revalidation_sources)
    _ISSUED_VERIFIED_AUDITS.issue(
        capability,
        _freeze_capability_value({
            "audit_sha256": audit_sha256,
            "artifact_binding": artifact_binding,
            "complete": complete,
            "unresolved_visibility": unresolved_visibility,
            "unresolved_factors": unresolved_factors,
            "revalidation_sources": source_payload,
        }),
    )
    return capability


def is_verified_reviewed_factor_overrides(value: object) -> bool:
    """Return whether this process issued the capability after full verification."""
    return _ISSUED_FACTOR_OVERRIDES.payload_for(
        value,
        ReviewedFactorOverrides,
        _FACTOR_AUTHORITY_FIELDS,
    ) is not None


def is_verified_corporate_action_audit(value: object) -> bool:
    """Return whether authority remains current under full source revalidation."""
    return verified_corporate_action_audit_sha256(value) is not None


def verified_corporate_action_audit_sha256(value: object) -> str | None:
    """Consume verified audit authority atomically, failing closed on source drift."""
    payload = _ISSUED_VERIFIED_AUDITS.payload_for(
        value,
        VerifiedCorporateActionAudit,
        _AUDIT_AUTHORITY_FIELDS,
    )
    if not isinstance(payload, Mapping):
        return None
    audit_sha256 = payload.get("audit_sha256")
    sources = payload.get("revalidation_sources")
    if (
        not isinstance(audit_sha256, str)
        or _SHA256.fullmatch(audit_sha256) is None
        or not isinstance(sources, Mapping)
        or set(sources) != set(_AUDIT_REVALIDATION_SOURCE_FIELDS)
        or any(not isinstance(source, str) or not source for source in sources.values())
    ):
        return None
    try:
        _report, validation, verified_sha256 = _load_and_revalidate_reviewed_audit(
            sources["reviewed_audit_path"],
            expected_sha256=sources["expected_sha256"],
            packet_dir=sources["packet_dir"],
            policy_path=sources["policy_path"],
            baseline_report_path=sources["baseline_report_path"],
        )
    except Exception:
        return None
    if (
        verified_sha256 != audit_sha256
        or validation.get("review_artifact_binding")
        != payload.get("artifact_binding")
    ):
        return None
    return audit_sha256


def build_review_rows(queue_kind: str, rows: list[dict]) -> list[dict]:
    """Bind every source queue row to a deterministic immutable review identity."""
    if not isinstance(queue_kind, str):
        raise CorporateActionReviewError("queue kind must be a string")
    canonical_queue_kind = queue_kind.strip().lower()
    if canonical_queue_kind not in {"visibility", "factor"}:
        raise CorporateActionReviewError("unsupported queue kind")
    if not isinstance(rows, list):
        raise CorporateActionReviewError("review queue must be a list")

    occurrences: dict[str, int] = {}
    output = []
    for source in rows:
        if not isinstance(source, dict):
            raise CorporateActionReviewError("review queue row must be an object")
        source_fields = {field: source.get(field, "") for field in BASE_FIELDS}
        try:
            source_key = json.dumps(
                source_fields, separators=(",", ":"), sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise CorporateActionReviewError("queue row is not JSON serializable") from error
        occurrence = occurrences.get(source_key, 0)
        occurrences[source_key] = occurrence + 1
        identity = {
            "duplicate_occurrence": occurrence,
            "queue_kind": canonical_queue_kind,
            "source_fields": source_fields,
        }
        review_id = hashlib.sha256(json.dumps(
            identity, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")).hexdigest()
        output.append({"review_id": review_id, **source_fields})
    return output


def validate_review_packet(
    packet_dir: str | Path,
    *,
    visibility_queue: list[dict],
    factor_queue: list[dict],
    policy_path: str | Path,
    baseline_report_path: str | Path,
) -> dict:
    """Return only decisions that satisfy immutable, policy, and evidence gates."""
    packet_dir = Path(packet_dir).resolve()
    if not packet_dir.is_dir():
        raise CorporateActionReviewError("packet directory is missing")
    policy, policy_binding = _read_policy(Path(policy_path))
    policy["_packet_dir"] = packet_dir
    expected_visibility = build_review_rows("visibility", visibility_queue)
    expected_factors = build_review_rows("factor", factor_queue)
    visibility, visibility_sha256 = _read_packet_rows(
        packet_dir / "visibility-reviews.csv",
        VISIBILITY_FIELDS,
        expected_visibility,
    )
    factors, factor_sha256 = _read_packet_rows(
        packet_dir / "factor-reviews.csv",
        FACTOR_FIELDS,
        expected_factors,
    )
    manifest_binding = _validate_packet_manifest(
        packet_dir,
        baseline_report_path=Path(baseline_report_path),
        policy=policy,
        visibility_rows=expected_visibility,
        factor_rows=expected_factors,
        visibility_template_rows=visibility,
        factor_template_rows=factors,
    )

    accepted_visibility, visibility_counts = _validate_rows(
        packet_dir, visibility, policy, "visibility",
    )
    accepted_factors, factor_counts = _validate_rows(
        packet_dir, factors, policy, "factor",
    )
    review_artifact_binding = {
        "schema_version": "reviewed-corporate-action-audit-v2",
        **manifest_binding,
        "visibility_reviews_path": str(
            (packet_dir / "visibility-reviews.csv").resolve(strict=True)
        ),
        "visibility_reviews_sha256": visibility_sha256,
        "factor_reviews_path": str(
            (packet_dir / "factor-reviews.csv").resolve(strict=True)
        ),
        "factor_reviews_sha256": factor_sha256,
        **policy_binding,
    }
    return {
        "accepted_visibility": accepted_visibility,
        "accepted_factors": accepted_factors,
        "visibility_decisions": {
            row["review_id"]: row.copy() for row in visibility
        },
        "factor_decisions": {
            row["review_id"]: row.copy() for row in factors
        },
        "counts": {
            "visibility": visibility_counts,
            "factor": factor_counts,
        },
        "review_artifact_binding": review_artifact_binding,
    }


def load_reviewed_factor_overrides(
    reviewed_audit_path: str | Path,
    *,
    expected_sha256: str,
    packet_dir: str | Path,
    policy_path: str | Path,
    baseline_report_path: str | Path,
) -> ReviewedFactorOverrides:
    """Load factors only from a complete, canonical, revalidated review audit."""
    report, validation, verified_sha256 = _load_and_revalidate_reviewed_audit(
        reviewed_audit_path,
        expected_sha256=expected_sha256,
        packet_dir=packet_dir,
        policy_path=policy_path,
        baseline_report_path=baseline_report_path,
    )
    expected_overrides = report["reviewed_factor_overrides"]
    return _issue_reviewed_factor_overrides(
        audit_sha256=verified_sha256,
        rows=tuple(MappingProxyType(row) for row in expected_overrides),
        artifact_binding=validation["review_artifact_binding"],
    )


def load_verified_corporate_action_audit(
    reviewed_audit_path: str | Path,
    *,
    expected_sha256: str,
    packet_dir: str | Path,
    policy_path: str | Path,
    baseline_report_path: str | Path,
) -> VerifiedCorporateActionAudit:
    """Issue complete-audit authority only after full audit revalidation."""
    report, validation, verified_sha256 = _load_and_revalidate_reviewed_audit(
        reviewed_audit_path,
        expected_sha256=expected_sha256,
        packet_dir=packet_dir,
        policy_path=policy_path,
        baseline_report_path=baseline_report_path,
    )
    complete, unresolved_visibility, unresolved_factors = (
        _fresh_complete_audit_state(report, validation)
    )
    return _issue_verified_corporate_action_audit(
        audit_sha256=verified_sha256,
        artifact_binding=validation["review_artifact_binding"],
        complete=complete,
        unresolved_visibility=unresolved_visibility,
        unresolved_factors=unresolved_factors,
        revalidation_sources=_audit_revalidation_sources(
            reviewed_audit_path,
            expected_sha256=expected_sha256,
            packet_dir=packet_dir,
            policy_path=policy_path,
            baseline_report_path=baseline_report_path,
        ),
    )


def _audit_revalidation_sources(
    reviewed_audit_path: str | Path,
    *,
    expected_sha256: str,
    packet_dir: str | Path,
    policy_path: str | Path,
    baseline_report_path: str | Path,
) -> dict[str, str]:
    """Capture only immutable filesystem inputs needed to revalidate authority."""
    try:
        return {
            "reviewed_audit_path": str(Path(reviewed_audit_path).resolve(strict=True)),
            "expected_sha256": expected_sha256,
            "packet_dir": str(Path(packet_dir).resolve(strict=True)),
            "policy_path": str(Path(policy_path).resolve(strict=True)),
            "baseline_report_path": str(Path(baseline_report_path).resolve(strict=True)),
        }
    except OSError as error:
        raise CorporateActionReviewError(
            "verified audit revalidation sources are unreadable"
        ) from error


def _load_and_revalidate_reviewed_audit(
    reviewed_audit_path: str | Path,
    *,
    expected_sha256: str,
    packet_dir: str | Path,
    policy_path: str | Path,
    baseline_report_path: str | Path,
) -> tuple[dict, dict, str]:
    """Return a canonical reviewed audit only after every binding revalidates."""
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise CorporateActionReviewError("reviewed audit SHA-256 is invalid")
    path = Path(reviewed_audit_path).resolve()
    try:
        content = path.read_bytes()
        report = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorporateActionReviewError("reviewed audit is unreadable") from error
    if (
        not isinstance(report, dict)
        or content != canonical_json_bytes(report)
        or hashlib.sha256(content).hexdigest() != expected_sha256
    ):
        raise CorporateActionReviewError("reviewed audit is not canonical or hash-bound")
    _validate_reviewed_audit_state(report)
    snapshot = report.get("review_decision_snapshot")
    if not isinstance(snapshot, dict) or set(snapshot) != {"visibility", "factor"}:
        raise CorporateActionReviewError("reviewed audit decision snapshot is invalid")
    queues = {}
    for queue_kind in ("visibility", "factor"):
        rows = snapshot[queue_kind]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise CorporateActionReviewError("reviewed audit decision snapshot is invalid")
        queues[queue_kind] = [
            {field: row.get(field) for field in BASE_FIELDS}
            for row in rows
        ]
    validation = validate_review_packet(
        packet_dir,
        visibility_queue=queues["visibility"],
        factor_queue=queues["factor"],
        policy_path=policy_path,
        baseline_report_path=baseline_report_path,
    )
    if report.get("review_artifact_binding") != validation.get(
        "review_artifact_binding"
    ):
        raise CorporateActionReviewError("reviewed audit artifact bindings are invalid")
    if (
        validation["visibility_decisions"]
        != {row["review_id"]: row for row in snapshot["visibility"]}
        or validation["factor_decisions"]
        != {row["review_id"]: row for row in snapshot["factor"]}
    ):
        raise CorporateActionReviewError("reviewed audit decision snapshot drifted")
    expected_overrides = _accepted_factor_overrides(validation["accepted_factors"])
    if report.get("reviewed_factor_overrides") != expected_overrides:
        raise CorporateActionReviewError("reviewed audit factor overrides are invalid")
    _fresh_complete_audit_state(report, validation)
    return report, validation, expected_sha256


def _fresh_complete_audit_state(
    report: dict,
    validation: dict,
) -> tuple[bool, int, int]:
    """Derive complete status only from freshly validated queue state."""
    snapshot = report.get("review_decision_snapshot")
    report_counts = report.get("counts")
    validation_counts = validation.get("counts")
    if (
        not isinstance(snapshot, dict)
        or not isinstance(report_counts, dict)
        or not isinstance(validation_counts, dict)
    ):
        raise CorporateActionReviewError("fresh review state is invalid")

    unresolved = {}
    for queue_kind, stored_fields in {
        "visibility": (
            "reviewed_visibility_actions",
            "pending_visibility_actions",
            "rejected_visibility_actions",
        ),
        "factor": (
            "reviewed_factor_actions",
            "pending_factor_actions",
            "rejected_factor_actions",
        ),
    }.items():
        queue_counts = validation_counts.get(queue_kind)
        decisions = validation.get(f"{queue_kind}_decisions")
        accepted = validation.get({
            "visibility": "accepted_visibility",
            "factor": "accepted_factors",
        }[queue_kind])
        snapshot_rows = snapshot.get(queue_kind)
        if (
            not isinstance(queue_counts, dict)
            or set(queue_counts) != {"accepted", "pending", "rejected"}
            or any(
                not isinstance(value, int) or value < 0
                for value in queue_counts.values()
            )
            or not isinstance(decisions, dict)
            or not isinstance(accepted, dict)
            or not isinstance(snapshot_rows, list)
        ):
            raise CorporateActionReviewError("fresh review state is invalid")
        if (
            queue_counts["accepted"] != len(accepted)
            or queue_counts["accepted"] + queue_counts["pending"]
            + queue_counts["rejected"] != len(snapshot_rows)
            or set(decisions) != {
                row.get("review_id") for row in snapshot_rows
                if isinstance(row, dict)
            }
        ):
            raise CorporateActionReviewError("fresh review counts are invalid")
        stored_reviewed, stored_pending, stored_rejected = stored_fields
        if (
            report_counts.get(stored_reviewed) != queue_counts["accepted"]
            or report_counts.get(stored_pending) != queue_counts["pending"]
            or report_counts.get(stored_rejected) != queue_counts["rejected"]
        ):
            raise CorporateActionReviewError(
                "fresh review counts conflict with stored audit"
            )
        unresolved[queue_kind] = (
            queue_counts["pending"] + queue_counts["rejected"]
        )

    if unresolved["visibility"] or unresolved["factor"]:
        raise CorporateActionReviewError("fresh review is incomplete")
    return True, unresolved["visibility"], unresolved["factor"]


def _validate_reviewed_audit_state(report: dict) -> None:
    counts = report.get("counts")
    if (
        report.get("status") != "VERIFIED"
        or report.get("complete") is not True
        or report.get("blockers") != []
        or not isinstance(counts, dict)
        or report.get("visibility_review_queue") != []
        or report.get("factor_review_queue") != []
    ):
        raise CorporateActionReviewError("reviewed audit is not fully resolved")
    zero_fields = (
        "retrieval_only_price_actions",
        "unquantifiable_price_actions",
        "pending_visibility_actions",
        "rejected_visibility_actions",
        "pending_factor_actions",
        "rejected_factor_actions",
    )
    if any(counts.get(field) != 0 for field in zero_fields):
        raise CorporateActionReviewError("reviewed audit is not fully resolved")


def _accepted_factor_overrides(accepted: dict) -> list[dict[str, object]]:
    if not isinstance(accepted, dict):
        raise CorporateActionReviewError("accepted factor decisions are invalid")
    rows = []
    for review_id, decision in accepted.items():
        try:
            factor = float(decision["adjustment_factor"])
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise CorporateActionReviewError("accepted factor decisions are invalid") from error
        rows.append({
            "review_id": review_id,
            "symbol": decision["symbol"],
            "action_type": decision["action_type"],
            "ex_date": decision["ex_date"],
            "purpose": decision["purpose"],
            "adjustment_factor": factor,
            "method": decision["method"],
            "evidence_path": decision["evidence_path"],
            "evidence_sha256": decision["evidence_sha256"],
            "evidence_source_url": decision["evidence_source_url"],
            "confirmed_available_at": decision["confirmed_available_at"],
            "reviewer_id": decision["reviewer_id"],
            "reviewed_at": decision["reviewed_at"],
        })
    return sorted(rows, key=lambda row: (
        str(row["ex_date"]),
        str(row["symbol"]),
        str(row["action_type"]),
        str(row["purpose"]),
        str(row["review_id"]),
    ))


def _validate_packet_manifest(
    packet_dir: Path,
    *,
    baseline_report_path: Path,
    policy: dict,
    visibility_rows: list[dict],
    factor_rows: list[dict],
    visibility_template_rows: list[dict],
    factor_template_rows: list[dict],
) -> dict[str, str]:
    try:
        content = (packet_dir / "manifest.json").read_bytes()
        manifest = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorporateActionReviewError("packet manifest is unreadable") from error
    if not isinstance(manifest, dict) or set(manifest) != _PACKET_MANIFEST_KEYS:
        raise CorporateActionReviewError("packet manifest is malformed")
    expected_schema = (
        _PACKET_MANIFEST_SCHEMA_V2
        if policy["policy_version"] == "corporate-action-review-policy-v2"
        else _PACKET_MANIFEST_SCHEMA_V1
    )
    if manifest.get("schema_version") != expected_schema:
        raise CorporateActionReviewError("packet manifest schema version is invalid")
    try:
        expected_baseline = baseline_report_path.resolve(strict=True)
        baseline_content = expected_baseline.read_bytes()
        baseline_sha256 = hashlib.sha256(baseline_content).hexdigest()
    except OSError as error:
        raise CorporateActionReviewError("expected baseline report is unreadable") from error
    if (
        manifest.get("source_report_path") != str(expected_baseline)
        or manifest.get("source_report_sha256") != baseline_sha256
    ):
        raise CorporateActionReviewError("packet manifest baseline binding is invalid")
    expected_counts = {"visibility": len(visibility_rows), "factor": len(factor_rows)}
    if manifest.get("queue_counts") != expected_counts:
        raise CorporateActionReviewError("packet manifest queue counts are invalid")
    expected_templates = {
        "visibility": _template_sha256(visibility_template_rows, VISIBILITY_FIELDS),
        "factor": _template_sha256(factor_template_rows, FACTOR_FIELDS),
    }
    if manifest.get("template_sha256") != expected_templates:
        raise CorporateActionReviewError("packet manifest template hashes are invalid")
    expected_ids = {
        "visibility": [row["review_id"] for row in visibility_rows],
        "factor": [row["review_id"] for row in factor_rows],
    }
    if manifest.get("row_identities") != expected_ids:
        raise CorporateActionReviewError("packet manifest row identities are invalid")
    if manifest.get("reviewer_policy_contract") != _policy_contract(policy):
        raise CorporateActionReviewError("packet manifest reviewer policy contract is invalid")
    return {
        "baseline_report_path": str(expected_baseline),
        "baseline_report_sha256": baseline_sha256,
        "packet_manifest_path": str((packet_dir / "manifest.json").resolve(strict=True)),
        "packet_manifest_sha256": hashlib.sha256(content).hexdigest(),
    }


def _template_sha256(rows: list[dict], fields: list[str]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for source in rows:
        row = {
            field: source.get(field, "") if field in IDENTITY_FIELDS else ""
            for field in fields
        }
        row["decision"] = "PENDING"
        writer.writerow(row)
    return hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()


def _read_policy(path: Path) -> tuple[dict, dict[str, str]]:
    try:
        resolved = path.resolve(strict=True)
        content = resolved.read_bytes()
        payload = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorporateActionReviewError("reviewer policy is unreadable") from error
    if not isinstance(payload, dict):
        raise CorporateActionReviewError("reviewer policy must be an object")
    if (
        not isinstance(payload.get("policy_version"), str)
        or not payload["policy_version"].strip()
    ):
        raise CorporateActionReviewError("reviewer policy version is invalid")
    if payload["policy_version"] not in {
        "corporate-action-review-policy-v1",
        "corporate-action-review-policy-v2",
    }:
        raise CorporateActionReviewError("reviewer policy version is unsupported")
    if payload["policy_version"] == "corporate-action-review-policy-v2":
        policy = _normalize_v2_policy(payload)
    else:
        policy = _normalize_v1_policy(payload)
    return policy, {
        "reviewer_policy_path": str(resolved),
        "reviewer_policy_sha256": hashlib.sha256(content).hexdigest(),
    }


def _normalize_v1_policy(payload: dict) -> dict:
    if any(key not in payload for key in _V1_POLICY_KEYS):
        raise CorporateActionReviewError("reviewer policy is missing required keys")
    for key in ("authorized_reviewers", "prohibited_reviewers", "allowed_evidence_hosts"):
        values = payload[key]
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise CorporateActionReviewError(f"reviewer policy {key} is invalid")
    if not payload["prohibited_reviewers"] or not payload["allowed_evidence_hosts"]:
        raise CorporateActionReviewError("reviewer policy required lists are empty")
    return {
        "policy_version": payload["policy_version"],
        "reviewer_principals": None,
        "authorized_reviewers": tuple(payload["authorized_reviewers"]),
        "prohibited_reviewers": tuple(payload["prohibited_reviewers"]),
        "allowed_evidence_hosts": tuple(payload["allowed_evidence_hosts"]),
    }


def _normalize_v2_policy(payload: dict) -> dict:
    if set(payload) != set(_V2_POLICY_KEYS):
        raise CorporateActionReviewError("reviewer policy v2 keys are invalid")
    prohibited_reviewers = _normalize_identity_list(
        payload["prohibited_reviewers"], "reviewer policy prohibited_reviewers",
    )
    prohibited_actor_types = _normalize_actor_type_list(
        payload["prohibited_actor_types"], "reviewer policy prohibited_actor_types",
    )
    allowed_evidence_hosts = _normalize_nonempty_string_list(
        payload["allowed_evidence_hosts"], "reviewer policy allowed_evidence_hosts",
    )
    if not prohibited_reviewers or not allowed_evidence_hosts:
        raise CorporateActionReviewError("reviewer policy required lists are empty")
    principals = payload["authorized_reviewers"]
    if not isinstance(principals, list) or not principals:
        raise CorporateActionReviewError("reviewer policy authorized_reviewers is invalid")
    normalized_principals = []
    reviewer_ids = set()
    for principal in principals:
        if not isinstance(principal, dict) or set(principal) != set(_V2_PRINCIPAL_KEYS):
            raise CorporateActionReviewError("reviewer policy principal keys are invalid")
        for key in (
            "independence_evidence_path",
            "independence_evidence_sha256", "governance_owner_id", "approved_at",
            "approval_evidence_path", "approval_evidence_sha256",
        ):
            if not isinstance(principal[key], str) or not principal[key].strip():
                raise CorporateActionReviewError(f"reviewer policy principal {key} is invalid")
        reviewer_id = _canonical_identity(principal["reviewer_id"], "reviewer ID")
        governance_owner_id = _canonical_identity(
            principal["governance_owner_id"], "governance owner ID",
        )
        actor_type = _canonical_actor_type(principal["actor_type"], "reviewer actor type")
        scopes = _normalize_scopes(principal["scopes"])
        if not isinstance(principal["revoked"], bool):
            raise CorporateActionReviewError("reviewer policy principal revoked is invalid")
        valid_from = _parse_timestamp(principal["valid_from"], "valid_from")
        valid_through = _parse_timestamp(principal["valid_through"], "valid_through")
        approved_at = _parse_timestamp(principal["approved_at"], "approved_at")
        if valid_from > valid_through:
            raise CorporateActionReviewError("reviewer policy principal validity is invalid")
        if approved_at > valid_through:
            raise CorporateActionReviewError("reviewer policy principal approval chronology is invalid")
        if governance_owner_id == reviewer_id:
            raise CorporateActionReviewError("governance owner must be independent")
        if governance_owner_id in prohibited_reviewers:
            raise CorporateActionReviewError("governance owner is prohibited")
        if governance_owner_id in {
            actor.casefold() for actor in prohibited_actor_types
        }:
            raise CorporateActionReviewError("governance owner cannot be an actor type")
        if (
            _SHA256.fullmatch(principal["independence_evidence_sha256"]) is None
            or _SHA256.fullmatch(principal["approval_evidence_sha256"]) is None
        ):
            raise CorporateActionReviewError("reviewer policy principal governance SHA-256 is invalid")
        if reviewer_id in reviewer_ids:
            raise CorporateActionReviewError("reviewer policy contains duplicate reviewers")
        reviewer_ids.add(reviewer_id)
        normalized = dict(principal)
        normalized["reviewer_id"] = reviewer_id
        normalized["governance_owner_id"] = governance_owner_id
        normalized["actor_type"] = actor_type
        normalized["scopes"] = tuple(scopes)
        normalized_principals.append(normalized)
    return {
        "policy_version": payload["policy_version"],
        "reviewer_principals": tuple(normalized_principals),
        "authorized_reviewers": tuple(principal["reviewer_id"] for principal in normalized_principals),
        "prohibited_reviewers": tuple(prohibited_reviewers),
        "prohibited_actor_types": tuple(prohibited_actor_types),
        "allowed_evidence_hosts": tuple(allowed_evidence_hosts),
    }


def _canonical_identity(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _CANONICAL_ID.fullmatch(value) is None
    ):
        raise CorporateActionReviewError(f"{field} must be canonical")
    return value.casefold()


def _canonical_actor_type(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _CANONICAL_ACTOR_TYPE.fullmatch(value) is None
    ):
        raise CorporateActionReviewError(f"{field} must be canonical")
    return value


def _normalize_identity_list(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise CorporateActionReviewError(f"{field} is invalid")
    normalized = tuple(_canonical_identity(value, field) for value in values)
    if len(set(normalized)) != len(normalized):
        raise CorporateActionReviewError(f"{field} contains duplicates")
    return normalized


def _normalize_actor_type_list(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise CorporateActionReviewError(f"{field} is invalid")
    normalized = tuple(_canonical_actor_type(value, field) for value in values)
    if len(set(normalized)) != len(normalized):
        raise CorporateActionReviewError(f"{field} contains duplicates")
    return normalized


def _normalize_nonempty_string_list(values: object, field: str) -> tuple[str, ...]:
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise CorporateActionReviewError(f"{field} is invalid")
    return tuple(values)


def _normalize_scopes(values: object) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        raise CorporateActionReviewError("reviewer policy principal scopes are invalid")
    allowed_scopes = {"visibility", "factor"}
    if any(
        not isinstance(scope, str)
        or scope != scope.strip()
        or scope not in allowed_scopes
        for scope in values
    ):
        raise CorporateActionReviewError("reviewer policy principal scopes are invalid")
    normalized = tuple(values)
    if len(set(normalized)) != len(normalized):
        raise CorporateActionReviewError("reviewer policy principal scopes contain duplicates")
    return normalized


def _policy_contract(policy: dict) -> dict:
    if policy["policy_version"] != "corporate-action-review-policy-v2":
        return {
            "policy_version": policy["policy_version"],
            "required_keys": list(_V1_POLICY_KEYS),
        }
    return {
        "policy_version": "corporate-action-review-policy-v2",
        "required_keys": list(_V2_POLICY_KEYS),
        "required_principal_keys": list(_V2_PRINCIPAL_KEYS),
        "governance_directory": "governance",
    }


def _read_packet_rows(
    path: Path,
    fields: list[str],
    expected_rows: list[dict],
) -> tuple[list[dict], str]:
    try:
        content = path.read_bytes()
        handle = io.StringIO(content.decode("utf-8"), newline="")
        reader = csv.DictReader(handle, strict=True)
        if reader.fieldnames != fields:
            raise CorporateActionReviewError("review template columns do not match")
        rows = list(reader)
    except csv.Error as error:
        raise CorporateActionReviewError("review template contains malformed CSV") from error
    except (OSError, UnicodeDecodeError) as error:
        raise CorporateActionReviewError("review template is unreadable") from error
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise CorporateActionReviewError("review template contains malformed rows")
    expected_by_id = {row["review_id"]: row for row in expected_rows}
    review_ids = [row["review_id"] for row in rows]
    if len(review_ids) != len(set(review_ids)):
        raise CorporateActionReviewError("review template contains duplicate review IDs")
    if len(rows) != len(expected_rows) or set(review_ids) != set(expected_by_id):
        raise CorporateActionReviewError("review template does not match current queue")
    for row in rows:
        expected = expected_by_id[row["review_id"]]
        if any(row[field] != expected[field] for field in IDENTITY_FIELDS):
            raise CorporateActionReviewError("review template immutable fields changed")
    return rows, hashlib.sha256(content).hexdigest()


def _validate_rows(packet_dir: Path, rows: list[dict], policy: dict, queue_kind: str) -> tuple[dict, dict]:
    accepted = {}
    counts = {"accepted": 0, "pending": 0, "rejected": 0}
    accepted_decision = {"visibility": "CONFIRMED", "factor": "APPROVED"}[queue_kind]
    for row in rows:
        decision = row["decision"]
        if decision == "PENDING":
            counts["pending"] += 1
            continue
        if decision == "REJECTED":
            _validate_completed_evidence(
                packet_dir, row, policy, queue_kind=queue_kind,
            )
            _validate_availability_timestamps(row)
            _required(row, "notes")
            counts["rejected"] += 1
            continue
        if decision != accepted_decision:
            raise CorporateActionReviewError("review decision is unsupported")
        _validate_completed_evidence(
            packet_dir, row, policy, queue_kind=queue_kind,
        )
        _validate_availability_timestamps(row)
        if queue_kind == "factor":
            _validate_factor(row)
        accepted[row["review_id"]] = row.copy()
        counts["accepted"] += 1
    return accepted, counts


def _validate_completed_evidence(
    packet_dir: Path,
    row: dict,
    policy: dict,
    *,
    queue_kind: str,
) -> None:
    evidence_path = _required(row, "evidence_path")
    evidence_sha256 = _required(row, "evidence_sha256")
    evidence_source_url = _required(row, "evidence_source_url")
    reviewer_id = _required(row, "reviewer_id")
    reviewed_at = _parse_timestamp(_required(row, "reviewed_at"), "reviewed_at")
    if reviewed_at > datetime.now(timezone.utc):
        raise CorporateActionReviewError("reviewed_at cannot be in the future")
    _authorized_reviewer(policy, reviewer_id, queue_kind, reviewed_at)
    _validate_evidence_file(packet_dir, evidence_path, evidence_sha256)
    _validate_evidence_url(evidence_source_url, policy["allowed_evidence_hosts"])


def _authorized_reviewer(
    policy: dict,
    reviewer_id: str,
    queue_kind: str,
    reviewed_at: datetime,
) -> dict:
    """Return the principal only when its policy authority applies to this review."""
    if policy.get("reviewer_principals") is None:
        if reviewer_id in policy["prohibited_reviewers"]:
            raise CorporateActionReviewError("reviewer is prohibited")
        if reviewer_id not in policy["authorized_reviewers"]:
            raise CorporateActionReviewError("reviewer is not authorized")
        return {"reviewer_id": reviewer_id}
    canonical_reviewer_id = _canonical_identity(reviewer_id, "reviewer ID")
    if canonical_reviewer_id in policy["prohibited_reviewers"]:
        raise CorporateActionReviewError("reviewer is prohibited")
    if queue_kind not in {"visibility", "factor"}:
        raise CorporateActionReviewError("review queue kind is invalid")
    if not isinstance(reviewed_at, datetime) or reviewed_at.tzinfo != timezone.utc:
        raise CorporateActionReviewError("reviewed_at must be RFC 3339 UTC")
    principal = next(
        (
            candidate for candidate in policy["reviewer_principals"]
            if candidate["reviewer_id"] == canonical_reviewer_id
        ),
        None,
    )
    if principal is None:
        raise CorporateActionReviewError("reviewer is not authorized")
    if principal["actor_type"] != "HUMAN" or principal["actor_type"] in policy[
        "prohibited_actor_types"
    ]:
        raise CorporateActionReviewError("reviewer actor type is not authorized")
    if queue_kind not in principal["scopes"]:
        raise CorporateActionReviewError("reviewer is not authorized for review queue")
    if principal["revoked"]:
        raise CorporateActionReviewError("reviewer authorization is revoked")
    valid_from = _parse_timestamp(principal["valid_from"], "valid_from")
    valid_through = _parse_timestamp(principal["valid_through"], "valid_through")
    approved_at = _parse_timestamp(principal["approved_at"], "approved_at")
    if not valid_from <= reviewed_at <= valid_through:
        raise CorporateActionReviewError("reviewer authorization is outside validity")
    if approved_at > reviewed_at:
        raise CorporateActionReviewError("governance owner approval follows review")
    _validate_governance_evidence(policy, principal)
    return dict(principal)


def _validate_governance_evidence(policy: dict, principal: dict) -> None:
    packet_dir = policy.get("_packet_dir")
    if not isinstance(packet_dir, Path):
        raise CorporateActionReviewError("reviewer governance evidence cannot be resolved")
    _validate_governance_file(
        packet_dir,
        principal["independence_evidence_path"],
        principal["independence_evidence_sha256"],
    )
    _validate_governance_file(
        packet_dir,
        principal["approval_evidence_path"],
        principal["approval_evidence_sha256"],
    )


def _validate_governance_file(
    packet_dir: Path,
    value: str,
    expected_sha256: str,
) -> None:
    relative_path = Path(value)
    parts = relative_path.parts
    if (
        relative_path.is_absolute()
        or ".." in parts
        or not parts
        or parts[0] != "governance"
    ):
        raise CorporateActionReviewError("governance evidence path must be relative")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    nonblocking = getattr(os, "O_NONBLOCK", None)
    if no_follow is None or directory is None or nonblocking is None:
        raise CorporateActionReviewError("secure governance evidence opening is unavailable")
    flags = os.O_RDONLY | nonblocking | getattr(os, "O_CLOEXEC", 0)
    directory_flags = flags | directory | no_follow
    root_fd = None
    current_fd = None
    file_fd = None
    try:
        root_fd = os.open(str(packet_dir), directory_flags)
        current_fd = root_fd
        for part in parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(parts[-1], flags | no_follow, dir_fd=current_fd)
        mode = os.fstat(file_fd).st_mode
        if not stat.S_ISREG(mode):
            raise CorporateActionReviewError("governance evidence path is not a regular file")
        digest = hashlib.sha256()
        while chunk := os.read(file_fd, 65536):
            digest.update(chunk)
    except OSError as error:
        raise CorporateActionReviewError("governance evidence file is unreadable") from error
    finally:
        for descriptor in (file_fd, current_fd, root_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
    if digest.hexdigest() != expected_sha256:
        raise CorporateActionReviewError("governance evidence SHA-256 does not match")


def _validate_evidence_file(packet_dir: Path, value: str, expected_sha256: str) -> None:
    if not _SHA256.fullmatch(expected_sha256):
        raise CorporateActionReviewError("evidence SHA-256 is invalid")
    relative_path = Path(value)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise CorporateActionReviewError("evidence path must be relative")
    candidate = packet_dir / relative_path
    evidence_root = (packet_dir / "evidence").resolve()
    try:
        resolved = candidate.resolve()
        resolved.relative_to(evidence_root)
    except ValueError as error:
        raise CorporateActionReviewError("evidence path escapes packet evidence") from error
    _reject_symlink_components(candidate, packet_dir)
    try:
        mode = candidate.stat().st_mode
    except OSError as error:
        raise CorporateActionReviewError("evidence file is unreadable") from error
    if not stat.S_ISREG(mode):
        raise CorporateActionReviewError("evidence path is not a regular file")
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise CorporateActionReviewError("evidence SHA-256 does not match")


def _reject_symlink_components(path: Path, packet_dir: Path) -> None:
    current = path
    while current != packet_dir:
        if current.is_symlink():
            raise CorporateActionReviewError("evidence path cannot contain symlinks")
        if packet_dir not in current.parents:
            raise CorporateActionReviewError("evidence path escapes packet")
        current = current.parent


def _validate_evidence_url(value: str, allowed_hosts: list[str]) -> None:
    try:
        parsed = urlparse(value)
        host = parsed.hostname
        _port = parsed.port
    except ValueError as error:
        raise CorporateActionReviewError("evidence source URL is malformed") from error
    allowed = {host.lower() for host in allowed_hosts}
    if (
        parsed.scheme != "https"
        or not host
        or host.lower() not in allowed
    ):
        raise CorporateActionReviewError("evidence source URL is not allowed")


def _validate_availability_timestamps(row: dict) -> None:
    available_at = _parse_timestamp(
        _required(row, "confirmed_available_at"), "confirmed_available_at",
    )
    reviewed_at = _parse_timestamp(row["reviewed_at"], "reviewed_at")
    if available_at > datetime.now(timezone.utc):
        raise CorporateActionReviewError("confirmed_available_at cannot be in the future")
    if reviewed_at < available_at:
        raise CorporateActionReviewError("reviewed_at precedes confirmed_available_at")
    try:
        ex_date = datetime.strptime(row["ex_date"], "%Y-%m-%d").date()
    except ValueError as error:
        raise CorporateActionReviewError("ex_date is invalid") from error
    cutoff = datetime.combine(
        ex_date, time(9, 15), tzinfo=ZoneInfo("Asia/Kolkata"),
    ).astimezone(timezone.utc)
    if available_at >= cutoff:
        raise CorporateActionReviewError("confirmed availability misses the ex-date open")


def _validate_factor(row: dict) -> None:
    try:
        factor = float(_required(row, "adjustment_factor"))
    except ValueError as error:
        raise CorporateActionReviewError("adjustment factor is invalid") from error
    if not math.isfinite(factor) or not 0 < factor <= 1:
        raise CorporateActionReviewError("adjustment factor is outside (0, 1]")
    _required(row, "method")


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise CorporateActionReviewError(f"{field} must be RFC 3339 UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise CorporateActionReviewError(f"{field} is invalid") from error


def _required(row: dict, field: str) -> str:
    value = row[field]
    if not isinstance(value, str) or not value.strip():
        raise CorporateActionReviewError(f"{field} is required")
    return value
