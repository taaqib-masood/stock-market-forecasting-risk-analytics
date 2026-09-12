import csv
import copy
import gc
import hashlib
import json
import os
import pickle
import weakref

import pytest

import src.reliability.corporate_action_reviews as corporate_action_reviews
from src.reliability.corporate_action_review_packet import export_review_packet
from src.reliability.corporate_action_reviews import (
    CorporateActionReviewError,
    ReviewedFactorOverrides,
    VerifiedCorporateActionAudit,
    build_review_rows,
    is_verified_corporate_action_audit,
    is_verified_reviewed_factor_overrides,
    load_verified_corporate_action_audit,
    validate_review_packet,
    verified_corporate_action_audit_sha256,
)
from src.reliability.preregistration import canonical_json_bytes
from tests.corporate_action_test_support import issue_reviewed_factor_chain


VISIBILITY_QUEUE = [{
    "symbol": "TCS",
    "action_type": "DIVIDEND",
    "ex_date": "2024-01-31",
    "purpose": "Dividend - Rs 10 Per Share",
    "reason": "snapshot_retrieval",
}]
FACTOR_QUEUE = [{
    "symbol": "ABC",
    "action_type": "RIGHTS",
    "ex_date": "2024-01-31",
    "purpose": "Rights 1:4 @ Premium Rs 10",
    "reason": "reviewed adjustment factor required",
}]


def _replace_rows(path, update):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    update(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _rewrite_header(path, fields):
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def completed_packet(tmp_path):
    report_path = tmp_path / "audit.json"
    report_path.write_text(json.dumps({
        "visibility_review_queue": VISIBILITY_QUEUE,
        "factor_review_queue": FACTOR_QUEUE,
    }), encoding="utf-8")
    packet_dir = tmp_path / "packet"
    exported = export_review_packet(report_path, packet_dir)
    evidence_dir = packet_dir / "evidence"
    evidence_dir.mkdir()
    evidence = evidence_dir / "nse-notice.txt"
    evidence.write_bytes(b"NSE primary corporate action notice\n")
    evidence_sha256 = hashlib.sha256(evidence.read_bytes()).hexdigest()
    common = {
        "evidence_path": "evidence/nse-notice.txt",
        "evidence_sha256": evidence_sha256,
        "evidence_source_url": "https://www.nseindia.com/corporates/corporateActions",
        "reviewer_id": "independent-reviewer",
        "reviewed_at": "2024-01-30T12:30:00Z",
        "notes": "Primary exchange notice retained.",
    }
    _replace_rows(exported["visibility_csv"], lambda rows: rows[0].update({
        **common,
        "decision": "CONFIRMED",
        "confirmed_available_at": "2024-01-30T12:00:00Z",
    }))
    _replace_rows(exported["factor_csv"], lambda rows: rows[0].update({
        **common,
        "decision": "APPROVED",
        "confirmed_available_at": "2024-01-30T12:00:00Z",
        "adjustment_factor": "0.75",
        "method": "Rights theoretical ex-price formula using notice terms.",
    }))
    policy_path = tmp_path / "reviewer-policy.json"
    policy_path.write_text(json.dumps({
        "policy_version": "corporate-action-review-policy-v1",
        "authorized_reviewers": ["independent-reviewer"],
        "prohibited_reviewers": ["issuer-employee"],
        "allowed_evidence_hosts": ["www.nseindia.com"],
    }), encoding="utf-8")
    return {
        "packet_dir": packet_dir,
        "visibility_csv": exported["visibility_csv"],
        "factor_csv": exported["factor_csv"],
        "policy_path": policy_path,
        "source_report_path": report_path,
    }


def _validate(packet):
    return validate_review_packet(
        packet["packet_dir"],
        visibility_queue=VISIBILITY_QUEUE,
        factor_queue=FACTOR_QUEUE,
        policy_path=packet["policy_path"],
        baseline_report_path=packet["source_report_path"],
    )


def _write_v2_policy(packet, **principal_update):
    governance_dir = packet["packet_dir"] / "governance"
    governance_dir.mkdir(exist_ok=True)
    attestation = governance_dir / "reviewer-attestation.pdf"
    approval = governance_dir / "owner-approval.pdf"
    attestation.write_bytes(b"Independent reviewer attestation\n")
    approval.write_bytes(b"Governance owner approval\n")
    principal = {
        "reviewer_id": "independent-reviewer",
        "actor_type": "HUMAN",
        "scopes": ["visibility", "factor"],
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_through": "2027-01-01T00:00:00Z",
        "revoked": False,
        "independence_evidence_path": "governance/reviewer-attestation.pdf",
        "independence_evidence_sha256": hashlib.sha256(attestation.read_bytes()).hexdigest(),
        "governance_owner_id": "owner-001",
        "approved_at": "2026-01-01T00:00:00Z",
        "approval_evidence_path": "governance/owner-approval.pdf",
        "approval_evidence_sha256": hashlib.sha256(approval.read_bytes()).hexdigest(),
    }
    principal.update(principal_update)
    policy = {
        "policy_version": "corporate-action-review-policy-v2",
        "authorized_reviewers": [principal],
        "prohibited_reviewers": ["codex", "taaqib-masood"],
        "prohibited_actor_types": ["AI", "SERVICE_ACCOUNT"],
        "allowed_evidence_hosts": ["www.nseindia.com"],
    }
    packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")
    manifest_path = packet["packet_dir"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "corporate-action-review-packet-v3"
    manifest["reviewer_policy_contract"] = {
        "policy_version": "corporate-action-review-policy-v2",
        "required_keys": [
            "policy_version", "authorized_reviewers", "prohibited_reviewers",
            "prohibited_actor_types", "allowed_evidence_hosts",
        ],
        "required_principal_keys": [
            "reviewer_id", "actor_type", "scopes", "valid_from", "valid_through",
            "revoked", "independence_evidence_path", "independence_evidence_sha256",
            "governance_owner_id", "approved_at", "approval_evidence_path",
            "approval_evidence_sha256",
        ],
        "governance_directory": "governance",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _replace_rows(packet["visibility_csv"], lambda rows: rows[0].update({
        "reviewed_at": "2026-01-02T12:30:00Z",
    }))
    _replace_rows(packet["factor_csv"], lambda rows: rows[0].update({
        "reviewed_at": "2026-01-02T12:30:00Z",
    }))
    return policy


def test_verifier_accepts_independently_authorized_visibility_and_factor(completed_packet):
    result = _validate(completed_packet)
    visibility_id = build_review_rows("visibility", VISIBILITY_QUEUE)[0]["review_id"]
    factor_id = build_review_rows("factor", FACTOR_QUEUE)[0]["review_id"]

    assert result["accepted_visibility"][visibility_id]["decision"] == "CONFIRMED"
    assert result["accepted_factors"][factor_id]["adjustment_factor"] == "0.75"
    assert result["visibility_decisions"][visibility_id]["decision"] == "CONFIRMED"
    assert result["factor_decisions"][factor_id]["decision"] == "APPROVED"
    assert result["counts"] == {
        "visibility": {"accepted": 1, "pending": 0, "rejected": 0},
        "factor": {"accepted": 1, "pending": 0, "rejected": 0},
    }


def test_verifier_binds_manifest_to_the_expected_baseline_and_current_templates(
    completed_packet,
):
    result = validate_review_packet(
        completed_packet["packet_dir"],
        visibility_queue=VISIBILITY_QUEUE,
        factor_queue=FACTOR_QUEUE,
        policy_path=completed_packet["policy_path"],
        baseline_report_path=completed_packet["source_report_path"],
    )

    assert set(result["accepted_factors"]) == {
        build_review_rows("factor", FACTOR_QUEUE)[0]["review_id"],
    }
    manifest_path = completed_packet["packet_dir"] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_report_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CorporateActionReviewError, match="manifest"):
        validate_review_packet(
            completed_packet["packet_dir"],
            visibility_queue=VISIBILITY_QUEUE,
            factor_queue=FACTOR_QUEUE,
            policy_path=completed_packet["policy_path"],
            baseline_report_path=completed_packet["source_report_path"],
        )


@pytest.mark.parametrize("filename,field,value", [
    ("visibility_csv", "symbol", "INFY"),
    ("factor_csv", "purpose", "Changed rights terms"),
])
def test_verifier_rejects_mutated_immutable_fields(completed_packet, filename, field, value):
    _replace_rows(completed_packet[filename], lambda rows: rows[0].update({field: value}))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_verifier_rejects_invalid_and_duplicate_review_ids(completed_packet):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "review_id": "not-a-packet-identity",
    }))
    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)

    report_path = completed_packet["packet_dir"].parent / "audit.json"
    exported = export_review_packet(report_path, completed_packet["packet_dir"])
    _replace_rows(exported["visibility_csv"], lambda rows: rows.append(rows[0].copy()))
    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("fields", [
    [
        "review_id", "symbol", "action_type", "ex_date", "purpose", "reason",
        "confirmed_available_at", "decision", "evidence_path", "evidence_sha256",
        "evidence_source_url", "reviewer_id", "reviewed_at", "notes", "unknown",
    ],
    [
        "review_id", "symbol", "action_type", "ex_date", "purpose", "reason",
        "decision", "evidence_path", "evidence_sha256", "evidence_source_url",
        "reviewer_id", "reviewed_at", "notes",
    ],
])
def test_verifier_rejects_unknown_or_missing_columns(completed_packet, fields):
    _rewrite_header(completed_packet["visibility_csv"], fields)

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("policy_update", [
    {"authorized_reviewers": ["someone-else"]},
    {"prohibited_reviewers": ["independent-reviewer"]},
])
def test_verifier_rejects_unauthorized_or_prohibited_reviewer(
    completed_packet, policy_update,
):
    policy = json.loads(completed_packet["policy_path"].read_text(encoding="utf-8"))
    policy.update(policy_update)
    completed_packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("policy_update", [
    {"policy_version": ""},
    {"prohibited_reviewers": []},
    {"allowed_evidence_hosts": []},
])
def test_verifier_rejects_incomplete_policy_contract(completed_packet, policy_update):
    policy = json.loads(completed_packet["policy_path"].read_text(encoding="utf-8"))
    policy.update(policy_update)
    completed_packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_empty_authorization_policy_is_valid_but_cannot_accept(completed_packet):
    policy = json.loads(completed_packet["policy_path"].read_text(encoding="utf-8"))
    policy["authorized_reviewers"] = []
    completed_packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_empty_authorization_policy_allows_pending_rows(completed_packet):
    policy = json.loads(completed_packet["policy_path"].read_text(encoding="utf-8"))
    policy["authorized_reviewers"] = []
    completed_packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "decision": "PENDING",
    }))
    _replace_rows(completed_packet["factor_csv"], lambda rows: rows[0].update({
        "decision": "PENDING",
    }))

    result = _validate(completed_packet)

    assert result["accepted_visibility"] == {}
    assert result["accepted_factors"] == {}
    visibility_id = build_review_rows("visibility", VISIBILITY_QUEUE)[0]["review_id"]
    factor_id = build_review_rows("factor", FACTOR_QUEUE)[0]["review_id"]
    assert result["visibility_decisions"][visibility_id]["decision"] == "PENDING"
    assert result["factor_decisions"][factor_id]["decision"] == "PENDING"
    assert result["counts"] == {
        "visibility": {"accepted": 0, "pending": 1, "rejected": 0},
        "factor": {"accepted": 0, "pending": 1, "rejected": 0},
    }


@pytest.mark.parametrize("evidence_path", ["../nse-notice.txt", "/tmp/nse-notice.txt"])
def test_verifier_rejects_evidence_path_traversal(completed_packet, evidence_path):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "evidence_path": evidence_path,
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_verifier_rejects_lexical_evidence_path_traversal(completed_packet):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "evidence_path": "evidence/../evidence/nse-notice.txt",
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_verifier_rejects_symlinked_evidence(completed_packet):
    evidence = completed_packet["packet_dir"] / "evidence" / "nse-notice.txt"
    linked = completed_packet["packet_dir"] / "evidence" / "linked-notice.txt"
    linked.symlink_to(evidence)
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "evidence_path": "evidence/linked-notice.txt",
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_verifier_rejects_wrong_evidence_sha256(completed_packet):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "evidence_sha256": "0" * 64,
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_verifier_rejects_unterminated_quoted_csv_field(completed_packet):
    path = completed_packet["visibility_csv"]
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Primary exchange notice retained.", '"unterminated',
        ),
        encoding="utf-8",
    )

    with pytest.raises(CorporateActionReviewError, match="malformed CSV"):
        _validate(completed_packet)


@pytest.mark.parametrize("url", [
    "http://www.nseindia.com/corporates/corporateActions",
    "https://untrusted.example/corporates/corporateActions",
    "https://www.nseindia.com:not-a-port/corporateActions",
    "https://[www.nseindia.com/corporateActions",
])
def test_verifier_rejects_non_https_or_disallowed_evidence_host(completed_packet, url):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "evidence_source_url": url,
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("field,value", [
    ("reviewed_at", "2024-01-30 12:30:00+00:00"),
    ("reviewed_at", "2999-01-30T12:30:00Z"),
    ("confirmed_available_at", "2024-01-30T13:00:00Z"),
    ("confirmed_available_at", "2024-01-31T03:45:00Z"),
])
def test_verifier_rejects_malformed_future_or_invalid_visibility_times(
    completed_packet, field, value,
):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        field: value,
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("value", [
    "",
    "2999-01-30T12:00:00Z",
    "2024-01-30T13:00:00Z",
    "2024-01-31T03:45:00Z",
])
def test_verifier_applies_availability_time_gates_to_factors(completed_packet, value):
    _replace_rows(completed_packet["factor_csv"], lambda rows: rows[0].update({
        "confirmed_available_at": value,
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("filename,decision", [
    ("visibility_csv", "APPROVED"),
    ("factor_csv", "CONFIRMED"),
])
def test_verifier_rejects_unknown_decision_vocabulary(completed_packet, filename, decision):
    _replace_rows(completed_packet[filename], lambda rows: rows[0].update({
        "decision": decision,
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("decision", ["AI_PROPOSED", "UNRECOGNIZED"])
def test_verifier_rejects_unsupported_canonical_decisions(completed_packet, decision):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "decision": decision,
    }))

    with pytest.raises(
        CorporateActionReviewError,
        match="^review decision is unsupported$",
    ):
        _validate(completed_packet)


@pytest.mark.parametrize("field,value", [
    ("adjustment_factor", "0"),
    ("adjustment_factor", "1.01"),
    ("adjustment_factor", "NaN"),
    ("method", ""),
])
def test_verifier_rejects_invalid_factor_bounds_or_method(completed_packet, field, value):
    _replace_rows(completed_packet["factor_csv"], lambda rows: rows[0].update({
        field: value,
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("filename,field", [
    ("visibility_csv", "evidence_path"),
    ("visibility_csv", "evidence_sha256"),
    ("visibility_csv", "evidence_source_url"),
    ("visibility_csv", "reviewer_id"),
    ("visibility_csv", "reviewed_at"),
    ("visibility_csv", "confirmed_available_at"),
    ("factor_csv", "evidence_path"),
    ("factor_csv", "evidence_sha256"),
    ("factor_csv", "evidence_source_url"),
    ("factor_csv", "reviewer_id"),
    ("factor_csv", "reviewed_at"),
    ("factor_csv", "confirmed_available_at"),
])
def test_verifier_rejects_completed_decisions_missing_required_fields(
    completed_packet, filename, field,
):
    _replace_rows(completed_packet[filename], lambda rows: rows[0].update({field: ""}))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


@pytest.mark.parametrize("field", [
    "evidence_path",
    "evidence_sha256",
    "evidence_source_url",
    "reviewer_id",
    "reviewed_at",
    "confirmed_available_at",
    "notes",
])
def test_verifier_rejects_rejected_decisions_missing_authority_or_rationale(
    completed_packet, field,
):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "decision": "REJECTED",
        field: "",
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_verifier_rejects_rejected_decision_with_unauthorized_reviewer(completed_packet):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "decision": "REJECTED",
        "reviewer_id": "someone-else",
    }))

    with pytest.raises(CorporateActionReviewError, match="reviewer is not authorized"):
        _validate(completed_packet)


def test_verifier_counts_pending_and_rejected_rows_without_accepting_them(completed_packet):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "decision": "PENDING",
        "evidence_path": "",
        "evidence_sha256": "",
        "evidence_source_url": "",
        "reviewer_id": "",
        "reviewed_at": "",
        "confirmed_available_at": "",
    }))
    _replace_rows(completed_packet["factor_csv"], lambda rows: rows[0].update({
        "decision": "REJECTED",
        "adjustment_factor": "",
        "method": "",
    }))

    result = _validate(completed_packet)

    assert result["accepted_visibility"] == {}
    assert result["accepted_factors"] == {}
    visibility_id = build_review_rows("visibility", VISIBILITY_QUEUE)[0]["review_id"]
    factor_id = build_review_rows("factor", FACTOR_QUEUE)[0]["review_id"]
    assert result["visibility_decisions"][visibility_id]["decision"] == "PENDING"
    assert result["factor_decisions"][factor_id]["decision"] == "REJECTED"
    assert result["counts"] == {
        "visibility": {"accepted": 0, "pending": 1, "rejected": 0},
        "factor": {"accepted": 0, "pending": 0, "rejected": 1},
    }


def test_policy_v2_accepts_human_reviewer_with_retained_governance_evidence(
    completed_packet,
):
    _write_v2_policy(completed_packet)

    assert _validate(completed_packet)["counts"] == {
        "visibility": {"accepted": 1, "pending": 0, "rejected": 0},
        "factor": {"accepted": 1, "pending": 0, "rejected": 0},
    }


@pytest.mark.parametrize("principal_update", [
    {"actor_type": "AI"},
    {"actor_type": "SERVICE_ACCOUNT"},
    {"valid_through": "2026-01-01T00:00:00Z"},
    {"revoked": True},
    {"scopes": ["visibility"]},
    {"independence_evidence_sha256": "0" * 64},
    {"approval_evidence_sha256": "0" * 64},
    {"reviewer_id": "codex"},
])
def test_policy_v2_rejects_prohibited_or_invalid_authority(
    completed_packet, principal_update,
):
    _write_v2_policy(completed_packet, **principal_update)
    if principal_update.get("reviewer_id") == "codex":
        _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
            "reviewer_id": "codex",
        }))
        _replace_rows(completed_packet["factor_csv"], lambda rows: rows[0].update({
            "reviewer_id": "codex",
        }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_policy_v2_rejects_missing_governance_evidence(completed_packet):
    _write_v2_policy(completed_packet)
    (completed_packet["packet_dir"] / "governance" / "owner-approval.pdf").unlink()

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_policy_v2_rejects_missing_factor_scope(completed_packet):
    _write_v2_policy(completed_packet, scopes=["visibility"])
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "decision": "PENDING",
    }))

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_rejected_factor_requires_v2_governance_authority(completed_packet):
    _write_v2_policy(completed_packet)
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "decision": "PENDING",
    }))
    _replace_rows(completed_packet["factor_csv"], lambda rows: rows[0].update({
        "decision": "REJECTED",
        "adjustment_factor": "",
        "method": "",
    }))
    (completed_packet["packet_dir"] / "governance" / "reviewer-attestation.pdf").unlink()

    with pytest.raises(CorporateActionReviewError):
        _validate(completed_packet)


def test_policy_v2_rejects_unsupported_policy_version(completed_packet):
    _write_v2_policy(completed_packet)
    policy = json.loads(completed_packet["policy_path"].read_text(encoding="utf-8"))
    policy["policy_version"] = "corporate-action-review-policy-v99"
    completed_packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(CorporateActionReviewError, match="unsupported"):
        _validate(completed_packet)


def test_policy_v2_rejects_reviewer_as_its_own_governance_owner(completed_packet):
    _write_v2_policy(completed_packet, governance_owner_id="independent-reviewer")

    with pytest.raises(CorporateActionReviewError, match="governance owner"):
        _validate(completed_packet)


def test_policy_v2_rejects_prohibited_governance_owner(completed_packet):
    _write_v2_policy(completed_packet, governance_owner_id="codex")

    with pytest.raises(CorporateActionReviewError, match="governance owner"):
        _validate(completed_packet)


def test_policy_v2_rejects_owner_approval_after_review(completed_packet):
    _write_v2_policy(completed_packet, approved_at="2026-01-03T00:00:00Z")

    with pytest.raises(CorporateActionReviewError, match="approval"):
        _validate(completed_packet)


@pytest.mark.parametrize("field,value", [
    ("valid_from", None),
    ("valid_through", 123),
])
def test_policy_v2_rejects_malformed_validity_types_with_domain_error(
    completed_packet, field, value,
):
    _write_v2_policy(completed_packet, **{field: value})

    with pytest.raises(CorporateActionReviewError, match=field):
        _validate(completed_packet)


@pytest.mark.parametrize("reviewed_at,valid_through", [
    ("2026-01-01T00:00:00Z", "2026-01-03T00:00:00Z"),
    ("2026-01-03T00:00:00Z", "2026-01-03T00:00:00Z"),
])
def test_policy_v2_accepts_inclusive_authorization_validity_boundaries(
    completed_packet, reviewed_at, valid_through,
):
    _write_v2_policy(completed_packet, valid_through=valid_through)
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "reviewed_at": reviewed_at,
    }))
    _replace_rows(completed_packet["factor_csv"], lambda rows: rows[0].update({
        "reviewed_at": reviewed_at,
    }))

    assert _validate(completed_packet)["counts"]["factor"]["accepted"] == 1


def test_policy_v2_rejects_governance_path_traversal(completed_packet):
    _write_v2_policy(completed_packet)
    policy = json.loads(completed_packet["policy_path"].read_text(encoding="utf-8"))
    policy["authorized_reviewers"][0]["independence_evidence_path"] = (
        "governance/../governance/reviewer-attestation.pdf"
    )
    completed_packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(CorporateActionReviewError, match="governance evidence path"):
        _validate(completed_packet)


def test_policy_v2_rejects_symlinked_governance_evidence(completed_packet):
    _write_v2_policy(completed_packet)
    evidence = completed_packet["packet_dir"] / "governance" / "reviewer-attestation.pdf"
    outside = completed_packet["packet_dir"].parent / "outside-attestation.pdf"
    outside.write_bytes(evidence.read_bytes())
    evidence.unlink()
    evidence.symlink_to(outside)

    with pytest.raises(CorporateActionReviewError, match="governance evidence"):
        _validate(completed_packet)


@pytest.mark.parametrize("reviewer_id", [
    " independent-reviewer ",
    "Independent-Reviewer",
])
def test_policy_v2_rejects_noncanonical_reviewer_ids(completed_packet, reviewer_id):
    _write_v2_policy(completed_packet, reviewer_id=reviewer_id)

    with pytest.raises(CorporateActionReviewError, match="reviewer ID"):
        _validate(completed_packet)


@pytest.mark.parametrize("governance_owner_id", [
    "codex",
    "CODEX",
    " codex ",
    "AI",
    "ai",
    "SERVICE_ACCOUNT",
])
def test_policy_v2_rejects_owner_aliases_and_actor_sentinels(
    completed_packet, governance_owner_id,
):
    _write_v2_policy(completed_packet, governance_owner_id=governance_owner_id)

    with pytest.raises(CorporateActionReviewError, match="governance owner"):
        _validate(completed_packet)


def test_policy_v2_rejects_noncanonical_completed_reviewer_id(completed_packet):
    _write_v2_policy(completed_packet)
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "reviewer_id": " independent-reviewer ",
    }))

    with pytest.raises(CorporateActionReviewError, match="reviewer ID"):
        _validate(completed_packet)


def test_policy_v2_accepts_distinct_canonical_governance_owner(completed_packet):
    _write_v2_policy(completed_packet, governance_owner_id="owner-001")

    assert _validate(completed_packet)["counts"]["visibility"]["accepted"] == 1


@pytest.mark.parametrize("scopes", [
    [[]],
    [None],
    [1],
    [""],
    [" visibility "],
    ["unknown"],
])
def test_policy_v2_rejects_malformed_scopes_with_domain_error(
    completed_packet, scopes,
):
    _write_v2_policy(completed_packet, scopes=scopes)

    with pytest.raises(CorporateActionReviewError, match="scopes"):
        _validate(completed_packet)


@pytest.mark.parametrize("field,value", [
    ("prohibited_reviewers", [None]),
    ("prohibited_reviewers", [" codex "]),
    ("prohibited_actor_types", [None]),
    ("prohibited_actor_types", [" ai "]),
    ("allowed_evidence_hosts", [None]),
])
def test_policy_v2_rejects_malformed_top_level_lists_with_domain_error(
    completed_packet, field, value,
):
    _write_v2_policy(completed_packet)
    policy = json.loads(completed_packet["policy_path"].read_text(encoding="utf-8"))
    policy[field] = value
    completed_packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(CorporateActionReviewError, match=field):
        _validate(completed_packet)


def test_policy_v2_rejects_governance_fifo_without_blocking(completed_packet):
    _write_v2_policy(completed_packet)
    fifo = completed_packet["packet_dir"] / "governance" / "reviewer-fifo"
    os.mkfifo(fifo)
    try:
        policy = json.loads(completed_packet["policy_path"].read_text(encoding="utf-8"))
        principal = policy["authorized_reviewers"][0]
        principal["independence_evidence_path"] = "governance/reviewer-fifo"
        principal["independence_evidence_sha256"] = "0" * 64
        completed_packet["policy_path"].write_text(json.dumps(policy), encoding="utf-8")

        with pytest.raises(CorporateActionReviewError, match="governance evidence"):
            _validate(completed_packet)
    finally:
        fifo.unlink(missing_ok=True)


def test_verified_corporate_action_audit_cannot_be_constructed_or_forged():
    with pytest.raises(CorporateActionReviewError, match="verified audit"):
        VerifiedCorporateActionAudit()

    forged = object.__new__(VerifiedCorporateActionAudit)
    object.__setattr__(forged, "_audit_sha256", "a" * 64)
    object.__setattr__(forged, "_artifact_binding", {})
    object.__setattr__(forged, "_complete", True)
    object.__setattr__(forged, "_unresolved_visibility", 0)
    object.__setattr__(forged, "_unresolved_factors", 0)

    class LookalikeAudit:
        audit_sha256 = "a" * 64
        artifact_binding = {}
        complete = True
        unresolved_visibility = 0
        unresolved_factors = 0

    assert is_verified_corporate_action_audit(forged) is False
    assert is_verified_corporate_action_audit(LookalikeAudit()) is False
    assert is_verified_corporate_action_audit(object()) is False


def test_verified_corporate_action_audit_is_issued_after_full_revalidation(
    tmp_path,
):
    chain = issue_reviewed_factor_chain(tmp_path)
    capability = chain.audit_capability
    expected_sha256 = hashlib.sha256(
        canonical_json_bytes(chain.reviewed_report)
    ).hexdigest()
    expected_binding = chain.reviewed_report["review_artifact_binding"]

    assert is_verified_corporate_action_audit(capability) is True
    assert verified_corporate_action_audit_sha256(capability) == expected_sha256
    assert capability.audit_sha256 == expected_sha256
    assert capability.complete is True
    assert capability.unresolved_visibility == 0
    assert capability.unresolved_factors == 0
    assert capability.artifact_binding == expected_binding
    with pytest.raises(TypeError, match="immutable"):
        capability.complete = False


@pytest.mark.parametrize(("source", "policy_version", "mutate"), [
    (
        "reviewed audit bytes",
        "corporate-action-review-policy-v1",
        lambda chain: chain.reviewed_path.write_bytes(b"{}"),
    ),
    (
        "factor decision CSV",
        "corporate-action-review-policy-v1",
        lambda chain: (chain.packet_dir / "factor-reviews.csv").write_bytes(
            b"tampered decision CSV\n"
        ),
    ),
    (
        "reviewer policy",
        "corporate-action-review-policy-v1",
        lambda chain: chain.policy_path.write_bytes(b"{}"),
    ),
    (
        "governance attestation",
        "corporate-action-review-policy-v2",
        lambda chain: (chain.packet_dir / "governance" / "reviewer-attestation.pdf").write_bytes(
            b"tampered governance evidence\n"
        ),
    ),
    (
        "baseline report",
        "corporate-action-review-policy-v1",
        lambda chain: chain.baseline_path.write_bytes(b"{}"),
    ),
])
def test_verified_corporate_action_audit_revalidates_current_sources_at_use_time(
    tmp_path,
    source,
    policy_version,
    mutate,
):
    chain = issue_reviewed_factor_chain(
        tmp_path,
        name=source.replace(" ", "-"),
        reviewer_policy_version=policy_version,
    )

    mutate(chain)

    assert verified_corporate_action_audit_sha256(chain.audit_capability) is None
    assert is_verified_corporate_action_audit(chain.audit_capability) is False


def test_verified_corporate_action_audit_defensively_copies_artifact_binding(
    tmp_path,
):
    capability = issue_reviewed_factor_chain(tmp_path).audit_capability

    returned = capability.artifact_binding
    returned["schema_version"] = "forged"

    assert capability.artifact_binding["schema_version"] != "forged"


def _stored_complete_report(validation):
    return {
        "status": "VERIFIED",
        "complete": True,
        "blockers": [],
        "counts": {
            "retrieval_only_price_actions": 0,
            "unquantifiable_price_actions": 0,
            "pending_visibility_actions": 0,
            "rejected_visibility_actions": 0,
            "pending_factor_actions": 0,
            "rejected_factor_actions": 0,
            "reviewed_visibility_actions": 0,
            "reviewed_factor_actions": 0,
        },
        "visibility_review_queue": [],
        "factor_review_queue": [],
        "review_decision_snapshot": {
            "visibility": [
                validation["visibility_decisions"][review_id]
                for review_id in sorted(validation["visibility_decisions"])
            ],
            "factor": [
                validation["factor_decisions"][review_id]
                for review_id in sorted(validation["factor_decisions"])
            ],
        },
        "review_artifact_binding": validation["review_artifact_binding"],
        "reviewed_factor_overrides": [],
    }


@pytest.mark.parametrize("visibility_decision,factor_decision", [
    ("PENDING", "PENDING"),
    ("REJECTED", "PENDING"),
    ("PENDING", "REJECTED"),
])
def test_adversarial_stored_complete_audit_fails_fresh_queue_completeness(
    completed_packet,
    visibility_decision,
    factor_decision,
):
    _replace_rows(completed_packet["visibility_csv"], lambda rows: rows[0].update({
        "decision": visibility_decision,
    }))
    _replace_rows(completed_packet["factor_csv"], lambda rows: rows[0].update({
        "decision": factor_decision,
    }))
    validation = _validate(completed_packet)
    report = _stored_complete_report(validation)
    reviewed_path = completed_packet["packet_dir"].parent / "stored-complete.json"
    reviewed_path.write_bytes(canonical_json_bytes(report))

    with pytest.raises(CorporateActionReviewError, match="fresh review"):
        load_verified_corporate_action_audit(
            reviewed_path,
            expected_sha256=hashlib.sha256(reviewed_path.read_bytes()).hexdigest(),
            packet_dir=completed_packet["packet_dir"],
            policy_path=completed_packet["policy_path"],
            baseline_report_path=completed_packet["source_report_path"],
        )


def test_adversarial_capability_registries_require_exact_identity(tmp_path):
    chain = issue_reviewed_factor_chain(tmp_path)

    class EqualAudit(VerifiedCorporateActionAudit):
        def __hash__(self):
            return hash(chain.audit_capability)

        def __eq__(self, _other):
            return True

    class EqualOverrides(ReviewedFactorOverrides):
        def __hash__(self):
            return hash(chain.capability)

        def __eq__(self, _other):
            return True

    assert is_verified_corporate_action_audit(object.__new__(EqualAudit)) is False
    assert is_verified_reviewed_factor_overrides(object.__new__(EqualOverrides)) is False
    assert is_verified_corporate_action_audit(chain.capability) is False
    assert is_verified_reviewed_factor_overrides(chain.audit_capability) is False


@pytest.mark.parametrize("capability_field", [
    "_audit_sha256",
    "_artifact_binding",
    "_complete",
    "_unresolved_visibility",
    "_unresolved_factors",
])
def test_adversarial_audit_authority_fields_cannot_be_object_setattr_mutated(
    tmp_path,
    capability_field,
):
    capability = issue_reviewed_factor_chain(tmp_path).audit_capability

    object.__setattr__(capability, capability_field, "forged")
    assert is_verified_corporate_action_audit(capability) is False


@pytest.mark.parametrize("capability_field", [
    "_audit_sha256",
    "_artifact_binding",
    "_rows",
])
def test_adversarial_factor_authority_fields_cannot_be_object_setattr_mutated(
    tmp_path,
    capability_field,
):
    capability = issue_reviewed_factor_chain(tmp_path).capability

    object.__setattr__(capability, capability_field, "forged")
    assert is_verified_reviewed_factor_overrides(capability) is False


def test_adversarial_capability_copy_pickle_subclass_and_gc_behavior(tmp_path):
    chain = issue_reviewed_factor_chain(tmp_path)
    audit_ref = weakref.ref(chain.audit_capability)
    factor_ref = weakref.ref(chain.capability)
    audit_identifier = id(chain.audit_capability)
    factor_identifier = id(chain.capability)

    for capability, verifier in (
        (chain.audit_capability, is_verified_corporate_action_audit),
        (chain.capability, is_verified_reviewed_factor_overrides),
    ):
        for copier in (copy.copy, copy.deepcopy):
            try:
                clone = copier(capability)
            except (CorporateActionReviewError, TypeError, pickle.PickleError):
                continue
            assert clone is not capability
            assert verifier(clone) is False
        with pytest.raises((CorporateActionReviewError, TypeError, pickle.PickleError)):
            pickle.loads(pickle.dumps(capability))

    capability = None
    clone = None
    del chain
    gc.collect()

    assert audit_ref() is None
    assert factor_ref() is None
    assert audit_identifier not in corporate_action_reviews._ISSUED_VERIFIED_AUDITS._entries
    assert factor_identifier not in corporate_action_reviews._ISSUED_FACTOR_OVERRIDES._entries


def test_adversarial_identity_registry_preserves_live_entry_on_stale_cleanup(
    monkeypatch,
):
    class Token:
        pass

    registry = corporate_action_reviews._IdentityCapabilityRegistry()
    monkeypatch.setattr(
        corporate_action_reviews,
        "id",
        lambda _value: 17,
        raising=False,
    )
    stale = Token()
    live = Token()
    registry.issue(stale, "stale-payload")
    registry.issue(live, "live-payload")

    del stale
    gc.collect()

    entry = registry._entries[17]
    assert entry[0]() is live
    assert entry[1] == "live-payload"


def test_adversarial_capability_bindings_are_deeply_defensive():
    binding = {"nested": {"items": ["original"]}}
    audit = corporate_action_reviews._issue_verified_corporate_action_audit(
        audit_sha256="a" * 64,
        artifact_binding=binding,
        complete=True,
        unresolved_visibility=0,
        unresolved_factors=0,
    )
    factor = corporate_action_reviews._issue_reviewed_factor_overrides(
        audit_sha256="a" * 64,
        rows=({"nested": {"items": ["original"]}},),
        artifact_binding=binding,
    )
    binding["nested"]["items"].append("mutated-input")
    audit_binding = audit.artifact_binding
    factor_binding = factor.artifact_binding
    audit_binding["nested"]["items"].append("mutated-output")
    factor_binding["nested"]["items"].append("mutated-output")
    factor_rows = factor.rows
    factor_rows[0]["nested"]["items"].append("mutated-output")

    assert audit.artifact_binding == {"nested": {"items": ["original"]}}
    assert factor.artifact_binding == {"nested": {"items": ["original"]}}
    assert factor.rows == ({"nested": {"items": ["original"]}},)


def test_adversarial_helper_rejects_mixed_reviewed_audit_versions(tmp_path):
    def mutate_reviewed_audit(path):
        report = json.loads(path.read_text(encoding="utf-8"))
        report["version_probe"] = "mutated-between-loaders"
        path.write_bytes(canonical_json_bytes(report))

    with pytest.raises(CorporateActionReviewError, match="hash-bound"):
        issue_reviewed_factor_chain(
            tmp_path,
            after_factor_loader=mutate_reviewed_audit,
        )
