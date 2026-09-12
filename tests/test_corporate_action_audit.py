import csv
import hashlib
import json
import sys

import pytest

import src.reliability.corporate_action_audit as corporate_action_audit
from src.reliability.corporate_action_audit import audit_corporate_actions, main
from src.reliability.corporate_action_review_packet import export_review_packet
from src.reliability.corporate_action_reviews import (
    CorporateActionReviewError,
    load_reviewed_factor_overrides,
)
from src.reliability.preregistration import canonical_json_bytes


def _catalogue(path, snapshot, *, available_at="2024-02-01T00:00:00Z"):
    record = {
        "kind": "corporate_actions",
        "status": "downloaded",
        "path": str(snapshot),
        "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "available_at": available_at,
        "params": {"from_date": "01-01-2024", "to_date": "31-01-2024"},
    }
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


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


def _review_packet(tmp_path, report):
    tmp_path.mkdir(parents=True, exist_ok=True)
    report_path = tmp_path / "audit-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    packet_dir = tmp_path / "packet"
    exported = export_review_packet(report_path, packet_dir)
    evidence_dir = packet_dir / "evidence"
    evidence_dir.mkdir()
    evidence = evidence_dir / "nse-notice.txt"
    evidence.write_bytes(b"NSE primary corporate action notice\n")
    policy_path = tmp_path / "reviewer-policy.json"
    policy_path.write_text(json.dumps({
        "policy_version": "corporate-action-review-policy-v1",
        "authorized_reviewers": ["independent-reviewer"],
        "prohibited_reviewers": ["issuer-employee"],
        "allowed_evidence_hosts": ["www.nseindia.com"],
    }), encoding="utf-8")
    return {
        "packet_dir": packet_dir,
        "policy_path": policy_path,
        "source_report_path": report_path,
        "visibility_csv": exported["visibility_csv"],
        "factor_csv": exported["factor_csv"],
        "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
    }


def _complete_visibility(packet, *, symbol, decision="CONFIRMED"):
    _replace_rows(packet["visibility_csv"], lambda rows: [
        row.update({
            "decision": decision,
            "evidence_path": "evidence/nse-notice.txt",
            "evidence_sha256": packet["evidence_sha256"],
            "evidence_source_url": "https://www.nseindia.com/corporates/corporateActions",
            "reviewer_id": "independent-reviewer",
            "reviewed_at": "2024-01-30T12:30:00Z",
            "confirmed_available_at": "2024-01-30T12:00:00Z",
            "notes": "Primary exchange notice retained.",
        }) for row in rows if row["symbol"] == symbol
    ])


def _complete_factor(packet, *, symbol, decision="APPROVED"):
    _replace_rows(packet["factor_csv"], lambda rows: [
        row.update({
            "decision": decision,
            "evidence_path": "evidence/nse-notice.txt",
            "evidence_sha256": packet["evidence_sha256"],
            "evidence_source_url": "https://www.nseindia.com/corporates/corporateActions",
            "reviewer_id": "independent-reviewer",
            "reviewed_at": "2024-01-30T12:30:00Z",
            "confirmed_available_at": "2024-01-30T12:00:00Z",
            "adjustment_factor": "0.75",
            "method": "Rights theoretical ex-price formula using notice terms.",
            "notes": "Primary exchange notice retained.",
        }) for row in rows if row["symbol"] == symbol
    ])


def test_audit_accepts_complete_hash_verified_exchange_timestamps(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
        "caBroadcastDate": "15-Jan-2024 10:00:00",
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)

    result = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")

    assert result["complete"] is True
    assert result["counts"]["covered_months"] == 1
    assert result["counts"]["point_in_time_price_actions"] == 1


def test_audit_fails_closed_on_missing_months_and_retrieval_only_timestamps(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
        "caBroadcastDate": None,
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)

    result = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-02-29")

    assert result["complete"] is False
    assert result["missing_months"] == ["2024-02"]
    assert result["counts"]["retrieval_only_price_actions"] == 1
    assert set(result["blockers"]) == {"MISSING_MONTHS", "NON_POINT_IN_TIME_ACTIONS"}
    assert result["visibility_review_queue"] == [{
        "symbol": "TCS", "action_type": "BONUS", "ex_date": "2024-01-31",
        "purpose": "Bonus 1:1", "reason": "snapshot_retrieval",
    }]


def test_audit_emits_factor_review_queue_for_rights_issue(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Rights 1:4 @ Premium Rs 10",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
        "caBroadcastDate": "15-Jan-2024 10:00:00",
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)

    result = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")

    assert result["factor_review_queue"][0]["reason"] == "reviewed adjustment factor required"
    assert result["factor_review_queue"][0]["action_type"] == "RIGHTS"


def test_audit_queues_nonautomatic_action_even_when_raw_factor_exists(
    tmp_path,
    monkeypatch,
):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text("[]", encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    monkeypatch.setattr(
        corporate_action_audit,
        "normalize_corporate_actions_snapshot_bytes",
        lambda _content, *, available_at: [{
            "symbol": "TCS",
            "action_type": "RIGHTS",
            "ex_date": "2024-01-31",
            "available_at": available_at,
            "payload": {
                "purpose": "Rights 1:4 @ Premium Rs 10",
                "availability_source": "exchange_broadcast",
                "adjustment_factor": 0.75,
            },
        }],
    )

    result = audit_corporate_actions(
        catalogue,
        start="2024-01-01",
        end="2024-01-31",
    )

    assert result["counts"]["automatic_factor_actions"] == 0
    assert result["counts"]["unquantifiable_price_actions"] == 1
    assert result["factor_review_queue"] == [{
        "symbol": "TCS",
        "action_type": "RIGHTS",
        "ex_date": "2024-01-31",
        "purpose": "Rights 1:4 @ Premium Rs 10",
        "reason": "reviewed adjustment factor required",
    }]
    assert "UNQUANTIFIABLE_ACTIONS" in result["blockers"]


def test_audit_does_not_count_actions_outside_requested_period(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
        "exDate": "01-Feb-2024", "recDate": "01-Feb-2024",
        "caBroadcastDate": None,
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)

    result = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")

    assert result["counts"]["normalized_actions"] == 0
    assert result["counts"]["retrieval_only_price_actions"] == 0


def test_audit_reconciles_paired_announcement_source(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Dividend - Rs 10 Per Share",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]), encoding="utf-8")
    announcements = tmp_path / "announcements.json"
    announcements.write_text(json.dumps([{
        "symbol": "TCS", "desc": "Record Date",
        "attchmntText": "Record date for the purpose of Dividend is 31-Jan-2024.",
        "an_dt": "15-Jan-2024 10:30:00",
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    record = {
        "kind": "corporate_announcements", "status": "downloaded",
        "path": str(announcements),
        "sha256": hashlib.sha256(announcements.read_bytes()).hexdigest(),
        "available_at": "2026-07-12T00:00:00Z",
        "params": {"from_date": "01-01-2024", "to_date": "31-01-2024"},
    }
    with catalogue.open("a") as handle:
        handle.write(json.dumps(record) + "\n")

    result = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")

    assert result["complete"] is True
    assert result["counts"]["point_in_time_price_actions"] == 1


def test_audit_matches_action_to_prior_month_announcement(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Dividend - Rs 10 Per Share",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]), encoding="utf-8")
    announcements = tmp_path / "announcements.json"
    announcements.write_text(json.dumps([{
        "symbol": "TCS", "desc": "Record Date",
        "attchmntText": "Record date for the purpose of Dividend is 31-Jan-2024.",
        "an_dt": "20-Dec-2023 10:30:00",
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    record = {
        "kind": "corporate_announcements", "status": "downloaded",
        "path": str(announcements),
        "sha256": hashlib.sha256(announcements.read_bytes()).hexdigest(),
        "available_at": "2026-07-12T00:00:00Z",
        "params": {"from_date": "01-12-2023", "to_date": "31-12-2023"},
    }
    with catalogue.open("a") as handle:
        handle.write(json.dumps(record) + "\n")

    result = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")

    assert result["counts"]["point_in_time_price_actions"] == 1
    assert "NON_POINT_IN_TIME_ACTIONS" not in result["blockers"]


def test_audit_uses_latest_catalogue_record_without_double_counting(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Dividend - Rs 10 Per Share",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
        "caBroadcastDate": "15-Jan-2024 10:00:00",
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    with catalogue.open("a") as handle:
        handle.write(catalogue.read_text())

    result = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")

    assert result["counts"]["normalized_actions"] == 1


def test_audit_hashes_and_normalizes_the_same_snapshot_bytes(tmp_path, monkeypatch):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
        "caBroadcastDate": "15-Jan-2024 10:00:00",
    }]), encoding="utf-8")
    replacement = json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Demerger",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
        "caBroadcastDate": "15-Jan-2024 10:00:00",
    }])
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    original_open = corporate_action_audit.Path.open
    reads = 0

    def swap_on_second_snapshot_read(path, *args, **kwargs):
        nonlocal reads
        mode = args[0] if args else kwargs.get("mode", "r")
        if path.resolve() == snapshot.resolve() and "r" in mode:
            reads += 1
            if reads == 2:
                with original_open(path, "w", encoding="utf-8") as handle:
                    handle.write(replacement)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(corporate_action_audit.Path, "open", swap_on_second_snapshot_read)

    result = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")

    assert reads == 1
    assert result["complete"] is True


@pytest.mark.parametrize("review_packet_dir,reviewer_policy_path", [
    ("packet", None),
    (None, "policy.json"),
])
def test_audit_requires_review_packet_and_policy_together(
    tmp_path, review_packet_dir, reviewer_policy_path,
):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text("[]", encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)

    with pytest.raises(ValueError, match="together"):
        audit_corporate_actions(
            catalogue,
            start="2024-01-01",
            end="2024-01-31",
            review_packet_dir=review_packet_dir,
            reviewer_policy_path=reviewer_policy_path,
        )


def test_cli_requires_review_packet_and_policy_before_audit_work(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "corporate_action_audit.py",
        "missing-catalogue.jsonl",
        "--start", "2024-01-01",
        "--end", "2024-01-31",
        "--review-packet-dir", "packet",
    ])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2


def test_audit_upgrades_only_exact_confirmed_visibility_without_downgrading_exchange_data(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([
        {
            "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
            "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
            "caBroadcastDate": "15-Jan-2024 10:00:00",
        },
        {
            "symbol": "INFY", "series": "EQ", "subject": "Bonus 1:1",
            "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
            "caBroadcastDate": None,
        },
    ]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    initial = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")
    packet = _review_packet(tmp_path, initial)
    _complete_visibility(packet, symbol="INFY")

    result = audit_corporate_actions(
        catalogue,
        start="2024-01-01",
        end="2024-01-31",
        review_packet_dir=packet["packet_dir"],
        reviewer_policy_path=packet["policy_path"],
            baseline_report_path=packet["source_report_path"],
    )

    assert result["counts"]["point_in_time_price_actions"] == 2
    assert result["counts"]["retrieval_only_price_actions"] == 0
    assert result["counts"]["automatic_visibility_actions"] == 1
    assert result["counts"]["reviewed_visibility_actions"] == 1
    assert result["visibility_review_queue"] == []
    assert "NON_POINT_IN_TIME_ACTIONS" not in result["blockers"]


def test_audit_applies_only_exact_approved_factor_and_retains_canonical_provenance(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([
        {
            "symbol": "TCS", "series": "EQ", "subject": "Rights 1:4 @ Premium Rs 10",
            "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
            "caBroadcastDate": "15-Jan-2024 10:00:00",
        },
        {
            "symbol": "INFY", "series": "EQ", "subject": "Rights 1:4 @ Premium Rs 10",
            "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
            "caBroadcastDate": "15-Jan-2024 10:00:00",
        },
    ]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    initial = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")
    packet = _review_packet(tmp_path, initial)
    _complete_factor(packet, symbol="TCS")

    result = audit_corporate_actions(
        catalogue,
        start="2024-01-01",
        end="2024-01-31",
        review_packet_dir=packet["packet_dir"],
        reviewer_policy_path=packet["policy_path"],
            baseline_report_path=packet["source_report_path"],
    )

    assert result["counts"]["unquantifiable_price_actions"] == 1
    assert result["counts"]["automatic_factor_actions"] == 0
    assert result["counts"]["reviewed_factor_actions"] == 1
    assert result["counts"]["pending_factor_actions"] == 1
    assert result["factor_review_queue"] == [{
        "symbol": "INFY", "action_type": "RIGHTS", "ex_date": "2024-01-31",
        "purpose": "Rights 1:4 @ Premium Rs 10",
        "reason": "reviewed adjustment factor required", "decision": "PENDING",
    }]
    override = result["reviewed_factor_overrides"][0]
    assert override["symbol"] == "TCS"
    assert override["action_type"] == "RIGHTS"
    assert override["adjustment_factor"] == 0.75
    assert override["method"] == "Rights theoretical ex-price formula using notice terms."
    assert override["evidence_sha256"] == packet["evidence_sha256"]
    assert override["reviewer_id"] == "independent-reviewer"
    assert "UNQUANTIFIABLE_ACTIONS" in result["blockers"]


def test_verified_reviewed_audit_loads_only_accepted_factor_overrides(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Rights 1:4 @ Premium Rs 10",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024",
        "caBroadcastDate": "15-Jan-2024 10:00:00",
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    baseline = audit_corporate_actions(
        catalogue, start="2024-01-01", end="2024-01-31",
    )
    packet = _review_packet(tmp_path, baseline)
    baseline_path = packet["source_report_path"]
    _complete_factor(packet, symbol="TCS")

    reviewed = audit_corporate_actions(
        catalogue,
        start="2024-01-01",
        end="2024-01-31",
        review_packet_dir=packet["packet_dir"],
        reviewer_policy_path=packet["policy_path"],
        baseline_report_path=baseline_path,
    )
    reviewed_path = tmp_path / "reviewed-audit.json"
    reviewed_path.write_bytes(canonical_json_bytes(reviewed))

    binding = load_reviewed_factor_overrides(
        reviewed_path,
        expected_sha256=hashlib.sha256(reviewed_path.read_bytes()).hexdigest(),
        packet_dir=packet["packet_dir"],
        policy_path=packet["policy_path"],
        baseline_report_path=baseline_path,
    )

    assert binding.rows == (reviewed["reviewed_factor_overrides"][0],)
    artifact_binding = binding.artifact_binding
    assert artifact_binding == reviewed["review_artifact_binding"]
    artifact_binding["factor_reviews_sha256"] = "f" * 64
    assert binding.artifact_binding == reviewed["review_artifact_binding"]


def test_audit_keeps_pending_and_rejected_visibility_decisions_as_blockers(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([
        {
            "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
            "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
        },
        {
            "symbol": "INFY", "series": "EQ", "subject": "Bonus 1:1",
            "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
        },
    ]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    initial = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")
    packet = _review_packet(tmp_path, initial)
    _complete_visibility(packet, symbol="INFY", decision="REJECTED")

    result = audit_corporate_actions(
        catalogue,
        start="2024-01-01",
        end="2024-01-31",
        review_packet_dir=packet["packet_dir"],
        reviewer_policy_path=packet["policy_path"],
            baseline_report_path=packet["source_report_path"],
    )

    assert result["counts"]["retrieval_only_price_actions"] == 2
    assert result["counts"]["pending_visibility_actions"] == 1
    assert result["counts"]["rejected_visibility_actions"] == 1
    assert result["visibility_review_queue"] == [
        {
            "symbol": "INFY", "action_type": "BONUS", "ex_date": "2024-01-31",
            "purpose": "Bonus 1:1", "reason": "snapshot_retrieval", "decision": "REJECTED",
        },
        {
            "symbol": "TCS", "action_type": "BONUS", "ex_date": "2024-01-31",
            "purpose": "Bonus 1:1", "reason": "snapshot_retrieval", "decision": "PENDING",
        },
    ]
    assert "NON_POINT_IN_TIME_ACTIONS" in result["blockers"]


def test_audit_propagates_malformed_review_packet(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    initial = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")
    packet = _review_packet(tmp_path, initial)
    _replace_rows(packet["visibility_csv"], lambda rows: rows[0].update({
        "review_id": "not-a-current-queue-identity",
    }))

    with pytest.raises(CorporateActionReviewError):
        audit_corporate_actions(
            catalogue,
            start="2024-01-01",
            end="2024-01-31",
            review_packet_dir=packet["packet_dir"],
            reviewer_policy_path=packet["policy_path"],
            baseline_report_path=packet["source_report_path"],
        )


def test_audit_fails_closed_on_duplicate_and_stale_accepted_review_rows(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    initial = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")
    packet = _review_packet(tmp_path, initial)
    _complete_visibility(packet, symbol="TCS")
    _replace_rows(packet["visibility_csv"], lambda rows: rows.append(rows[0].copy()))

    with pytest.raises(CorporateActionReviewError):
        audit_corporate_actions(
            catalogue,
            start="2024-01-01",
            end="2024-01-31",
            review_packet_dir=packet["packet_dir"],
            reviewer_policy_path=packet["policy_path"],
            baseline_report_path=packet["source_report_path"],
        )

    stale_packet = _review_packet(tmp_path / "stale", initial)
    _complete_visibility(stale_packet, symbol="TCS")
    snapshot.write_text(json.dumps([{
        "symbol": "INFY", "series": "EQ", "subject": "Bonus 1:1",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]), encoding="utf-8")
    _catalogue(catalogue, snapshot)

    with pytest.raises(CorporateActionReviewError):
        audit_corporate_actions(
            catalogue,
            start="2024-01-01",
            end="2024-01-31",
            review_packet_dir=stale_packet["packet_dir"],
            reviewer_policy_path=stale_packet["policy_path"],
            baseline_report_path=stale_packet["source_report_path"],
        )


def test_audit_fails_closed_on_conflicting_cross_queue_review_identity(tmp_path):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Rights 1:4 @ Premium Rs 10",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    initial = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")
    packet = _review_packet(tmp_path, initial)
    _complete_visibility(packet, symbol="TCS")
    _complete_factor(packet, symbol="TCS")
    with packet["visibility_csv"].open(newline="", encoding="utf-8") as handle:
        visibility_id = next(csv.DictReader(handle))["review_id"]
    _replace_rows(packet["factor_csv"], lambda rows: rows[0].update({
        "review_id": visibility_id,
    }))

    with pytest.raises(CorporateActionReviewError):
        audit_corporate_actions(
            catalogue,
            start="2024-01-01",
            end="2024-01-31",
            review_packet_dir=packet["packet_dir"],
            reviewer_policy_path=packet["policy_path"],
            baseline_report_path=packet["source_report_path"],
        )


def test_audit_uses_the_verifier_snapshot_without_a_second_visibility_packet_read(
    tmp_path, monkeypatch,
):
    snapshot = tmp_path / "actions.json"
    snapshot.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Bonus 1:1",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]), encoding="utf-8")
    catalogue = tmp_path / "source-catalogue.jsonl"
    _catalogue(catalogue, snapshot)
    initial = audit_corporate_actions(catalogue, start="2024-01-01", end="2024-01-31")
    packet = _review_packet(tmp_path, initial)
    visibility_csv = packet["visibility_csv"].resolve()
    original_open = corporate_action_audit.Path.open
    reads = 0

    def mutate_on_second_visibility_read(path, *args, **kwargs):
        nonlocal reads
        mode = args[0] if args else kwargs.get("mode", "r")
        if path.resolve() == visibility_csv and "r" in mode:
            reads += 1
            if reads == 2:
                with original_open(path, encoding="utf-8") as handle:
                    content = handle.read()
                with original_open(path, "w", encoding="utf-8") as handle:
                    handle.write(content.replace("PENDING", "UNSUPPORTED", 1))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(corporate_action_audit.Path, "open", mutate_on_second_visibility_read)

    result = audit_corporate_actions(
        catalogue,
        start="2024-01-01",
        end="2024-01-31",
        review_packet_dir=packet["packet_dir"],
        reviewer_policy_path=packet["policy_path"],
            baseline_report_path=packet["source_report_path"],
    )

    assert reads == 1
    assert result["visibility_review_queue"][0]["decision"] == "PENDING"
