"""Evidence-based release governance for Boro reliability modes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.reliability.corporate_action_reviews import (
    VerifiedCorporateActionAudit,
    CorporateActionReviewError,
    load_verified_corporate_action_audit,
    verified_corporate_action_audit_sha256,
)

def _dt(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_policy(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        policy = json.load(handle)
    if policy.get("schema_version") != 1:
        raise ValueError("unsupported reliability policy schema")
    return policy


def load_release_corporate_action_audit() -> VerifiedCorporateActionAudit | None:
    """Load and revalidate the independently retained audit, when configured.

    The opaque capability is deliberately recreated only through the verifier;
    JSON or environment claims alone can never satisfy the release gate.
    """
    import os

    values = {
        "reviewed_audit_path": os.environ.get("BORO_CORPORATE_ACTION_REVIEWED_AUDIT"),
        "expected_sha256": os.environ.get("BORO_CORPORATE_ACTION_AUDIT_SHA256"),
        "packet_dir": os.environ.get("BORO_CORPORATE_ACTION_PACKET_DIR"),
        "policy_path": os.environ.get("BORO_CORPORATE_ACTION_REVIEWER_POLICY"),
        "baseline_report_path": os.environ.get("BORO_CORPORATE_ACTION_BASELINE_REPORT"),
    }
    if not all(values.values()):
        return None
    try:
        return load_verified_corporate_action_audit(**values)
    except (CorporateActionReviewError, OSError, TypeError, ValueError):
        return None


def shadow_progress(
    started_at: str | datetime,
    reconciled_through: str | datetime,
    metrics: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    release = policy["release"]
    as_of = _dt(metrics["as_of"])
    started = _dt(started_at)
    reconciled = _dt(reconciled_through)
    elapsed_days = max(0, (as_of - started).days)
    failed = []
    if elapsed_days < int(release["min_shadow_days"]):
        failed.append("SHADOW_DURATION")
    if reconciled < as_of:
        failed.append("SHADOW_NOT_RECONCILED")
    if float(metrics.get("delivery_rate", 0.0)) < float(release["min_delivery_rate"]):
        failed.append("SHADOW_DELIVERY_SLO")
    if int(metrics.get("delivery_sample_size", 0)) < int(release["min_delivery_samples"]):
        failed.append("SHADOW_SAMPLE_SIZE")
    if int(metrics.get("duplicate_signals", 0)) > int(release["max_duplicate_signals"]):
        failed.append("SHADOW_DUPLICATES")
    if int(metrics.get("unresolved_incidents", 0)) > int(release["max_unresolved_incidents"]):
        failed.append("SHADOW_INCIDENTS")
    return {
        "passed": not failed,
        "elapsed_days": elapsed_days,
        "failed_gates": failed,
    }


def evaluate_release(
    evidence: dict[str, Any],
    policy: dict[str, Any],
    *,
    corporate_action_audit: VerifiedCorporateActionAudit | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    corporate_action_audit_sha256 = verified_corporate_action_audit_sha256(
        corporate_action_audit
    )
    if corporate_action_audit_sha256 is None:
        blockers.append("CORPORATE_ACTION_REVIEW_MISSING")
    dataset = evidence.get("dataset", {})
    if dataset.get("point_in_time") is not True:
        blockers.append("DATASET_NOT_POINT_IN_TIME")
    if float(dataset.get("coverage", 0.0)) < float(policy["data"]["min_point_in_time_coverage"]):
        blockers.append("DATASET_COVERAGE")
    if len(str(dataset.get("manifest_hash", ""))) != 64:
        blockers.append("DATASET_MANIFEST_MISSING")
    if evidence.get("statistics", {}).get("passed") is not True:
        blockers.append("STATISTICAL_EVIDENCE")
    if len(str(evidence.get("statistics", {}).get("report_hash", ""))) != 64:
        blockers.append("STATISTICAL_REPORT_MISSING")
    if not str(evidence.get("strategy_version", "")).strip():
        blockers.append("STRATEGY_VERSION_MISSING")

    shadow = evidence.get("shadow", {})
    required_shadow = {"started_at", "reconciled_through"}
    if not required_shadow.issubset(shadow):
        blockers.append("SHADOW_EVIDENCE_MISSING")
    else:
        progress = shadow_progress(
            shadow["started_at"],
            shadow["reconciled_through"],
            {**shadow, "as_of": evidence["as_of"]},
            policy,
        )
        blockers.extend(progress["failed_gates"])

    as_of = _dt(evidence["as_of"])
    approvals = evidence.get("approvals", {})
    for role in policy["release"]["required_approvals"]:
        approval = approvals.get(role)
        label = role.upper()
        if not approval or approval.get("approved") is not True:
            blockers.append(f"APPROVAL_{label}_MISSING")
            continue
        if (
            not approval.get("reviewer")
            or not approval.get("evidence_uri")
            or not approval.get("valid_through")
        ):
            blockers.append(f"APPROVAL_{label}_INVALID")
            continue
        if _dt(approval["valid_through"]) < as_of:
            blockers.append(f"APPROVAL_{label}_EXPIRED")

    result = {"approved": not blockers, "blockers": blockers}
    if corporate_action_audit_sha256 is not None:
        result["corporate_action_audit_sha256"] = corporate_action_audit_sha256
    return result
