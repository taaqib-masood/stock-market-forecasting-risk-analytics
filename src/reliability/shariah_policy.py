"""Versioned, fail-closed policy for Shariah accounting and business routing."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


DECISION_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
RIBA_BUSINESSES = {"CONVENTIONAL_BANK", "CONVENTIONAL_NBFC", "CONVENTIONAL_LENDER"}


class ShariahPolicyError(ValueError):
    """Raised when a policy cannot provide auditable, fail-closed behavior."""


def load_shariah_policy(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        policy = json.load(handle)
    if policy.get("schema_version") != 1 or not policy.get("policy_version"):
        raise ShariahPolicyError("unsupported or unversioned Shariah policy")
    for decision in policy.get("decisions", {}).values():
        if decision.get("status") not in DECISION_STATUSES:
            raise ShariahPolicyError("unsupported decision status")
    return policy


def apply_accounting_policy(review: dict, policy: dict) -> dict:
    result = deepcopy(review)
    result.setdefault("facts", {})
    applications = []
    for decision_id, decision in policy.get("decisions", {}).items():
        status = decision.get("status")
        if status not in DECISION_STATUSES:
            raise ShariahPolicyError("unsupported decision status")
        if status != "APPROVED":
            continue
        required = ("approved_by", "evidence_uri", "effective_from")
        if any(not decision.get(field) for field in required):
            raise ShariahPolicyError(f"approved decision {decision_id} lacks approval metadata")
        source = decision.get("source_candidate")
        target = decision.get("target_fact")
        candidate = result.get("candidates", {}).get(source)
        if not source or not target or not candidate or candidate.get("value") is None:
            continue
        if result["facts"].get(target) is not None:
            continue
        result["facts"][target] = candidate["value"]
        applications.append({
            "decision_id": decision_id,
            "policy_version": policy["policy_version"],
            "approved_by": decision["approved_by"],
            "evidence_uri": decision["evidence_uri"],
            "effective_from": decision["effective_from"],
            "source_candidate": source,
            "target_fact": target,
        })
    result["policy_applications"] = applications
    return result


def route_business_screen(business_type: str | None) -> dict:
    normalized = business_type.strip().upper() if business_type else None
    if normalized in RIBA_BUSINESSES:
        return {"route": "EXCLUDED_RIBA_BUSINESS", "tradeable": False}
    if normalized == "INSURER":
        return {"route": "SPECIALIST_REVIEW", "tradeable": False}
    if normalized == "NON_FINANCIAL":
        return {"route": "RATIO_SCREEN", "tradeable": None}
    return {"route": "UNKNOWN_BUSINESS", "tradeable": False}


def build_policy_review_queue(reviews: list[dict], policy: dict) -> list[dict]:
    queue = []
    for review in reviews:
        missing = sorted(name for name, value in review.get("facts", {}).items() if value is None)
        candidates = sorted(review.get("candidates", {}))
        pending = sorted(
            decision_id
            for decision_id, decision in policy.get("decisions", {}).items()
            if decision.get("status") == "PENDING"
            and decision.get("target_fact") in missing
            and decision.get("source_candidate") in candidates
        )
        if missing:
            queue.append({
                "symbol": review.get("symbol"),
                "missing_facts": missing,
                "available_candidates": candidates,
                "pending_decisions": pending,
            })
    return queue
