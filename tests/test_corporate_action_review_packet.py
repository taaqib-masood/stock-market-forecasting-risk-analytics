import csv
import hashlib
import json

from src.reliability.corporate_action_review_packet import (
    PACKET_MANIFEST_SCHEMA_VERSION,
    export_review_packet,
)
from src.reliability.corporate_action_reviews import build_review_rows


def test_review_packet_exports_controlled_visibility_and_factor_templates(tmp_path):
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "visibility_review_queue": [{
            "symbol": "TCS", "action_type": "DIVIDEND", "ex_date": "2024-01-31",
            "purpose": "Dividend - Rs 10 Per Share", "reason": "snapshot_retrieval",
        }],
        "factor_review_queue": [{
            "symbol": "ABC", "action_type": "RIGHTS", "ex_date": "2024-01-31",
            "purpose": "Rights 1:4 @ Premium Rs 10",
            "reason": "reviewed adjustment factor required",
        }],
    }), encoding="utf-8")

    result = export_review_packet(report, tmp_path / "packet")

    visibility = list(csv.DictReader(result["visibility_csv"].open()))
    factors = list(csv.DictReader(result["factor_csv"].open()))
    assert visibility[0]["decision"] == "PENDING"
    assert visibility[0]["evidence_sha256"] == ""
    assert visibility[0]["reviewer_id"] == ""
    assert factors[0]["adjustment_factor"] == ""
    assert factors[0]["method"] == ""
    assert result["manifest"]["queue_counts"] == {"visibility": 1, "factor": 1}


def test_review_packet_uses_stable_unique_ids_and_preserves_queue_identity(tmp_path):
    duplicate = {
        "symbol": "TCS ",
        "action_type": "DIVIDEND",
        "ex_date": "2024-01-31",
        "purpose": "Dividend - Rs 10 Per Share",
        "reason": "snapshot_retrieval",
    }
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "visibility_review_queue": [duplicate, duplicate],
        "factor_review_queue": [{
            "symbol": "ABC",
            "action_type": "RIGHTS",
            "ex_date": "2024-01-31",
            "purpose": "Rights 1:4 @ Premium Rs 10",
            "reason": "reviewed adjustment factor required",
        }],
    }), encoding="utf-8")

    result = export_review_packet(report, tmp_path / "packet")

    visibility = list(csv.DictReader(result["visibility_csv"].open()))
    factor = list(csv.DictReader(result["factor_csv"].open()))[0]
    expected_first_id = hashlib.sha256(json.dumps({
        "duplicate_occurrence": 0,
        "queue_kind": "visibility",
        "source_fields": duplicate,
    }, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    expected_second_id = hashlib.sha256(json.dumps({
        "duplicate_occurrence": 1,
        "queue_kind": "visibility",
        "source_fields": duplicate,
    }, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()

    assert [row["review_id"] for row in visibility] == [
        expected_first_id, expected_second_id,
    ]
    assert len({row["review_id"] for row in visibility}) == 2
    assert visibility[0]["symbol"] == "TCS "
    assert visibility[0]["purpose"] == duplicate["purpose"]
    assert visibility[0]["confirmed_available_at"] == ""
    assert visibility[0]["evidence_source_url"] == ""
    assert factor["confirmed_available_at"] == ""
    assert factor["evidence_source_url"] == ""


def test_review_packet_manifest_binds_templates_and_policy_contract(tmp_path):
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "visibility_review_queue": [],
        "factor_review_queue": [],
    }), encoding="utf-8")

    result = export_review_packet(report, tmp_path / "packet")
    manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))

    assert manifest == {
        "schema_version": PACKET_MANIFEST_SCHEMA_VERSION,
        "source_report_path": str(report.resolve()),
        "source_report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
        "queue_counts": {"visibility": 0, "factor": 0},
        "template_sha256": {
            "visibility": hashlib.sha256(result["visibility_csv"].read_bytes()).hexdigest(),
            "factor": hashlib.sha256(result["factor_csv"].read_bytes()).hexdigest(),
        },
        "row_identities": {
            "visibility": [row["review_id"] for row in build_review_rows("visibility", [])],
            "factor": [row["review_id"] for row in build_review_rows("factor", [])],
        },
        "reviewer_policy_contract": {
            "policy_version": "corporate-action-review-policy-v1",
            "required_keys": [
                "policy_version",
                "authorized_reviewers",
                "prohibited_reviewers",
                "allowed_evidence_hosts",
            ],
        },
    }


def test_review_packet_v2_policy_emits_v3_manifest_contract(tmp_path):
    report = tmp_path / "audit.json"
    report.write_text(json.dumps({
        "visibility_review_queue": [],
        "factor_review_queue": [],
    }), encoding="utf-8")

    result = export_review_packet(
        report,
        tmp_path / "packet",
        reviewer_policy_version="corporate-action-review-policy-v2",
    )

    contract = result["manifest"]["reviewer_policy_contract"]
    assert result["manifest"]["schema_version"] == "corporate-action-review-packet-v3"
    assert contract["policy_version"] == "corporate-action-review-policy-v2"
    assert contract["governance_directory"] == "governance"
    assert contract["required_principal_keys"] == [
        "reviewer_id", "actor_type", "scopes", "valid_from", "valid_through",
        "revoked", "independence_evidence_path", "independence_evidence_sha256",
        "governance_owner_id", "approved_at", "approval_evidence_path",
        "approval_evidence_sha256",
    ]
