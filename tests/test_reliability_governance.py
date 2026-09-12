import copy
import pickle
from datetime import datetime, timezone

import pytest

from src.reliability.corporate_action_reviews import (
    CorporateActionReviewError,
    VerifiedCorporateActionAudit,
)
from src.reliability import governance
from src.reliability.governance import evaluate_release, load_policy, shadow_progress
from tests.corporate_action_test_support import issue_reviewed_factor_chain


AS_OF = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _approval(role):
    return {
        "approved": True,
        "reviewer": f"named-{role}-reviewer",
        "evidence_uri": f"reviews/{role}-2026.pdf",
        "valid_through": "2027-01-01T00:00:00Z",
    }


def _passing_evidence():
    return {
        "as_of": AS_OF,
        "dataset": {"point_in_time": True, "coverage": 1.0, "manifest_hash": "a" * 64},
        "statistics": {"passed": True, "report_hash": "b" * 64},
        "strategy_version": "rule-v2.0.0",
        "shadow": {
            "started_at": "2025-12-01T00:00:00Z",
            "reconciled_through": "2026-07-01T00:00:00Z",
            "delivery_rate": 0.999,
            "delivery_sample_size": 250,
            "duplicate_signals": 0,
            "unresolved_incidents": 0,
        },
        "approvals": {
            "quantitative": _approval("quantitative"),
            "shariah": _approval("shariah"),
            "legal": _approval("legal"),
        },
    }


def test_repository_policy_loads_with_required_external_reviews():
    policy = load_policy("config/reliability-policy.json")

    assert policy["release"]["min_shadow_days"] == 180
    assert set(policy["release"]["required_approvals"]) == {
        "quantitative", "shariah", "legal"
    }


def test_complete_evidence_requires_verified_corporate_action_audit():
    result = evaluate_release(_passing_evidence(), load_policy("config/reliability-policy.json"))

    assert result == {
        "approved": False,
        "blockers": ["CORPORATE_ACTION_REVIEW_MISSING"],
    }


def test_complete_evidence_passes_only_with_issued_corporate_action_audit(tmp_path):
    capability = issue_reviewed_factor_chain(tmp_path).audit_capability

    result = evaluate_release(
        _passing_evidence(),
        load_policy("config/reliability-policy.json"),
        corporate_action_audit=capability,
    )

    assert result["approved"] is True
    assert result["blockers"] == []
    assert len(result["corporate_action_audit_sha256"]) == 64
    assert set(result) == {
        "approved", "blockers", "corporate_action_audit_sha256",
    }


def test_release_consumes_corporate_action_authority_once(monkeypatch):
    supplied_authority = object()
    consumed = []

    def consume_once(value):
        consumed.append(value)
        return "c" * 64

    monkeypatch.setattr(
        governance,
        "verified_corporate_action_audit_sha256",
        consume_once,
    )

    result = evaluate_release(
        _passing_evidence(),
        load_policy("config/reliability-policy.json"),
        corporate_action_audit=supplied_authority,
    )

    assert consumed == [supplied_authority]
    assert result["corporate_action_audit_sha256"] == "c" * 64


def test_forged_corporate_action_audit_fails_closed(tmp_path):
    invalid = object.__new__(VerifiedCorporateActionAudit)

    result = evaluate_release(
        _passing_evidence(),
        load_policy("config/reliability-policy.json"),
        corporate_action_audit=invalid,
    )

    assert result == {
        "approved": False,
        "blockers": ["CORPORATE_ACTION_REVIEW_MISSING"],
    }


@pytest.mark.parametrize("copy_operation", [copy.copy, copy.deepcopy])
def test_copied_corporate_action_audits_cannot_be_created(tmp_path, copy_operation):
    capability = issue_reviewed_factor_chain(tmp_path).audit_capability

    with pytest.raises(CorporateActionReviewError):
        copy_operation(capability)


def test_deserialized_corporate_action_audit_fails_closed(tmp_path):
    capability = issue_reviewed_factor_chain(tmp_path).audit_capability

    with pytest.raises(CorporateActionReviewError):
        pickle.loads(pickle.dumps(capability))


def test_source_drift_invalidates_corporate_action_audit_at_release_time(tmp_path):
    chain = issue_reviewed_factor_chain(tmp_path)
    chain.reviewed_path.write_text("{}", encoding="utf-8")

    result = evaluate_release(
        _passing_evidence(),
        load_policy("config/reliability-policy.json"),
        corporate_action_audit=chain.audit_capability,
    )

    assert result == {
        "approved": False,
        "blockers": ["CORPORATE_ACTION_REVIEW_MISSING"],
    }


def test_missing_reviews_block_release():
    evidence = _passing_evidence()
    evidence["approvals"] = {}

    result = evaluate_release(evidence, load_policy("config/reliability-policy.json"))

    assert result["approved"] is False
    assert set(result["blockers"]) >= {
        "APPROVAL_QUANTITATIVE_MISSING",
        "APPROVAL_SHARIAH_MISSING",
        "APPROVAL_LEGAL_MISSING",
    }


def test_expired_external_review_blocks_release():
    evidence = _passing_evidence()
    evidence["approvals"]["legal"]["valid_through"] = "2026-06-01T00:00:00Z"

    result = evaluate_release(evidence, load_policy("config/reliability-policy.json"))

    assert "APPROVAL_LEGAL_EXPIRED" in result["blockers"]


def test_shadow_gate_requires_duration_reconciliation_and_delivery_slo():
    result = shadow_progress(
        started_at="2026-06-01T00:00:00Z",
        reconciled_through="2026-06-20T00:00:00Z",
        metrics={
            "as_of": AS_OF,
            "delivery_rate": 0.99,
            "delivery_sample_size": 10,
            "duplicate_signals": 1,
            "unresolved_incidents": 1,
        },
        policy=load_policy("config/reliability-policy.json"),
    )

    assert result["passed"] is False
    assert set(result["failed_gates"]) >= {
        "SHADOW_DURATION", "SHADOW_NOT_RECONCILED", "SHADOW_DELIVERY_SLO",
        "SHADOW_SAMPLE_SIZE", "SHADOW_DUPLICATES", "SHADOW_INCIDENTS",
    }


def test_malformed_approval_fails_closed_instead_of_crashing():
    evidence = _passing_evidence()
    evidence["approvals"]["legal"].pop("valid_through")

    result = evaluate_release(evidence, load_policy("config/reliability-policy.json"))

    assert result["approved"] is False
    assert "APPROVAL_LEGAL_INVALID" in result["blockers"]
