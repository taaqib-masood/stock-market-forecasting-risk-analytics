import hashlib
import json
import sys

import pytest

from src.reliability import compliance_audit
from src.reliability.compliance_audit import audit_release_evidence
from tests.corporate_action_test_support import issue_reviewed_factor_chain


EXPECTED_CLI_BLOCKERS = [
    "CORPORATE_ACTION_REVIEW_MISSING",
    "DATASET_NOT_POINT_IN_TIME",
    "DATASET_COVERAGE",
    "STATISTICAL_EVIDENCE",
    "SHADOW_EVIDENCE_MISSING",
    "APPROVAL_QUANTITATIVE_MISSING",
    "APPROVAL_SHARIAH_MISSING",
    "APPROVAL_LEGAL_MISSING",
]
CANONICAL_REJECTED_AUDIT_SHA256 = (
    "92086b8fc49a9d686756286deb1008f06da501ec946af955d36f99163ea83400"
)


def test_compliance_audit_emits_machine_readable_blockers_and_hashes(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "schema_version": 1,
        "data": {"min_point_in_time_coverage": 1.0},
        "release": {"min_shadow_days": 180, "min_delivery_rate": 0.995,
                    "min_delivery_samples": 100, "max_duplicate_signals": 0,
                    "max_unresolved_incidents": 0,
                    "required_approvals": ["quantitative", "shariah", "legal"]},
    }))
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({
        "as_of": "2026-07-12T00:00:00Z",
        "dataset": {"point_in_time": False, "coverage": 0.0, "manifest_hash": "a" * 64},
        "statistics": {"passed": False, "report_hash": "b" * 64},
        "strategy_version": "rule-v1",
        "approvals": {},
    }))

    result = audit_release_evidence(evidence, policy)

    assert result["approved"] is False
    assert "DATASET_NOT_POINT_IN_TIME" in result["blockers"]
    assert "STATISTICAL_EVIDENCE" in result["blockers"]
    assert "CORPORATE_ACTION_REVIEW_MISSING" in result["blockers"]
    assert len(result["evidence_sha256"]) == 64
    assert len(result["policy_sha256"]) == 64


def test_compliance_audit_propagates_explicit_verified_audit(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({
        "schema_version": 1,
        "data": {"min_point_in_time_coverage": 1.0},
        "release": {"min_shadow_days": 180, "min_delivery_rate": 0.995,
                    "min_delivery_samples": 100, "max_duplicate_signals": 0,
                    "max_unresolved_incidents": 0,
                    "required_approvals": []},
    }))
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({
        "as_of": "2026-07-12T00:00:00Z",
        "dataset": {"point_in_time": True, "coverage": 1.0, "manifest_hash": "a" * 64},
        "statistics": {"passed": True, "report_hash": "b" * 64},
        "strategy_version": "rule-v1",
        "shadow": {
            "started_at": "2026-01-01T00:00:00Z",
            "reconciled_through": "2026-07-12T00:00:00Z",
            "delivery_rate": 1.0,
            "delivery_sample_size": 100,
            "duplicate_signals": 0,
            "unresolved_incidents": 0,
        },
    }))
    capability = issue_reviewed_factor_chain(tmp_path).audit_capability

    result = audit_release_evidence(
        evidence,
        policy,
        corporate_action_audit=capability,
    )

    assert result["approved"] is True
    assert result["blockers"] == []
    assert len(result["corporate_action_audit_sha256"]) == 64


def test_cli_rejected_audit_is_fail_closed_deterministic_and_authority_free(
    tmp_path, monkeypatch, capsys,
):
    fixture = "data/reliability/current-release-evidence.json"
    first_output = tmp_path / "first-audit.json"
    second_output = tmp_path / "second-audit.json"
    observed_authority = []
    real_audit = compliance_audit.audit_release_evidence

    def observe_audit(evidence_path, policy_path, *, corporate_action_audit=None):
        observed_authority.append(corporate_action_audit)
        return real_audit(
            evidence_path,
            policy_path,
            corporate_action_audit=corporate_action_audit,
        )

    monkeypatch.setattr(compliance_audit, "audit_release_evidence", observe_audit)
    for output in (first_output, second_output):
        monkeypatch.setattr(
            sys,
            "argv",
            ["compliance_audit", fixture, "--output", str(output)],
        )
        with pytest.raises(SystemExit) as raised:
            compliance_audit.main()
        assert raised.value.code == 2
        capsys.readouterr()

    assert observed_authority == [None, None]
    first_bytes = first_output.read_bytes()
    second_bytes = second_output.read_bytes()
    assert first_bytes == second_bytes
    assert hashlib.sha256(first_bytes).hexdigest() == CANONICAL_REJECTED_AUDIT_SHA256

    result = json.loads(first_bytes)
    assert result["approved"] is False
    assert result["blockers"] == EXPECTED_CLI_BLOCKERS
    assert "corporate_action_audit" not in result
    assert "corporate_action_audit_sha256" not in result
    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "VerifiedCorporateActionAudit",
        "reviewed_audit_path",
        "packet_dir",
        "baseline_report_path",
        "review_artifact_binding",
        "governance_owner_id",
        "revalidation_sources",
        "registry",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "authority_flag",
    [
        "--corporate-action-packet",
        "--corporate-action-audit",
        "--corporate-action-policy",
        "--corporate-action-audit-sha256",
    ],
)
def test_cli_rejects_corporate_action_authority_flags(
    authority_flag, monkeypatch, capsys,
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compliance_audit",
            "data/reliability/current-release-evidence.json",
            authority_flag,
            "untrusted-input",
        ],
    )

    with pytest.raises(SystemExit) as raised:
        compliance_audit.main()

    assert raised.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
