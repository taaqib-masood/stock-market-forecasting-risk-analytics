"""Fail-closed reconciliation for facts manually reviewed from filing PDFs."""

from __future__ import annotations

import re
from copy import deepcopy


REQUIRED_FACTS = ("total_assets", "total_debt", "total_revenue", "interest_income")


class PdfEvidenceError(ValueError):
    """Raised when PDF review records cannot be trusted or reconciled."""


def build_pdf_review(
    *,
    symbol: str,
    period_end: str,
    available_at: str,
    source_sha256: str,
    source_file: str,
    reviewer: str,
    unit: str,
    facts: dict,
    page_references: dict,
    candidates: dict | None = None,
) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise PdfEvidenceError("source_sha256 must be a lowercase SHA-256 digest")
    if not reviewer.strip():
        raise PdfEvidenceError("reviewer is required")
    unknown = set(facts) - set(REQUIRED_FACTS)
    if unknown:
        raise PdfEvidenceError(f"unknown facts: {', '.join(sorted(unknown))}")
    complete_facts = {name: facts.get(name) for name in REQUIRED_FACTS}
    return {
        "schema_version": 1,
        "status": "single_review",
        "tradeable": False,
        "symbol": symbol.upper(),
        "period_end": period_end,
        "available_at": available_at,
        "source_sha256": source_sha256,
        "source_file": source_file,
        "reviewer": reviewer.strip(),
        "unit": unit,
        "facts": deepcopy(complete_facts),
        "page_references": deepcopy(page_references),
        "candidates": deepcopy(candidates or {}),
    }


def reconcile_pdf_reviews(first: dict, second: dict, *, policy: dict) -> dict:
    if first.get("reviewer") == second.get("reviewer"):
        raise PdfEvidenceError("reconciliation requires independent reviewers")
    authorized = set(policy.get("authorized_data_reviewers", []))
    reviewers = {first.get("reviewer"), second.get("reviewer")}
    unauthorized = sorted(reviewer for reviewer in reviewers if reviewer not in authorized)
    if unauthorized:
        raise PdfEvidenceError(f"unauthorized reviewer: {', '.join(unauthorized)}")
    if not policy.get("policy_version"):
        raise PdfEvidenceError("reconciliation requires a versioned policy")
    for field in ("symbol", "period_end", "available_at", "source_sha256", "unit"):
        if first.get(field) != second.get(field):
            raise PdfEvidenceError(f"review disagreement: {field}")

    facts = {}
    for name in REQUIRED_FACTS:
        first_value = first.get("facts", {}).get(name)
        second_value = second.get("facts", {}).get(name)
        if first_value != second_value:
            raise PdfEvidenceError(f"fact disagreement: {name}")
        facts[name] = first_value

    missing = sorted(name for name, value in facts.items() if value is None)
    complete = not missing and facts["total_assets"] != 0 and facts["total_revenue"] != 0
    result = {
        "schema_version": 1,
        "status": "reconciled" if complete else "incomplete",
        "tradeable": complete,
        "symbol": first["symbol"],
        "period_end": first["period_end"],
        "effective_from": first["available_at"][:10],
        "available_at": first["available_at"],
        "source_sha256": first["source_sha256"],
        "unit": first["unit"],
        "reviewers": [first["reviewer"], second["reviewer"]],
        "policy_version": policy["policy_version"],
        "missing_facts": missing,
        "debt_to_assets": None,
        "interest_income_ratio": None,
        "payload": {**facts, "source_file": first.get("source_file")},
    }
    if complete:
        result["debt_to_assets"] = facts["total_debt"] / facts["total_assets"]
        result["interest_income_ratio"] = abs(facts["interest_income"]) / facts["total_revenue"]
    return result
