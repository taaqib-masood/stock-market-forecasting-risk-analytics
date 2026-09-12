import csv
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

import src.reliability.corporate_action_evidence_index as evidence_index_module
from src.reliability.corporate_action_evidence_index import (
    EvidenceIndexError,
    build_evidence_index,
    write_evidence_index,
)
from src.reliability.corporate_action_review_packet import export_review_packet
from src.reliability.corporate_action_reviews import build_review_rows
from src.reliability.preregistration import canonical_json_bytes


def _source_record(path: Path, *, kind: str, start: str, end: str) -> dict:
    content = path.read_bytes()
    return {
        "available_at": "2026-07-12T14:39:35Z",
        "bytes": len(content),
        "kind": kind,
        "params": {
            "from_date": start,
            "index": "equities",
            "to_date": end,
        },
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "status": "downloaded",
    }


def _write_catalogue(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in records),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path, *, duplicate_action: bool = False) -> dict:
    tmp_path.mkdir(parents=True, exist_ok=True)
    action_rows = [{
        "symbol": "ACME",
        "series": "EQ",
        "subject": "Interim Dividend - Rs 5 Per Share",
        "exDate": "15-Jan-2024",
        "recDate": "16-Jan-2024",
    }]
    if duplicate_action:
        action_rows.append(dict(action_rows[0]))
    announcement_rows = [{
        "symbol": "ACME",
        "an_dt": "12-Jan-2024 10:30:00",
        "sort_date": "2024-01-12 10:30:00",
        "desc": "Dividend",
        "subject": "Interim Dividend - Rs 5 Per Share",
        "attchmntText": "Interim Dividend - Rs 5 Per Share",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/acme.pdf",
        "seq_id": "123",
    }]
    actions_path = tmp_path / "actions.json"
    announcements_path = tmp_path / "announcements.json"
    actions_path.write_text(json.dumps(action_rows), encoding="utf-8")
    announcements_path.write_text(json.dumps(announcement_rows), encoding="utf-8")
    records = [
        _source_record(
            actions_path,
            kind="corporate_actions",
            start="01-01-2024",
            end="31-01-2024",
        ),
        _source_record(
            announcements_path,
            kind="corporate_announcements",
            start="01-01-2024",
            end="31-01-2024",
        ),
    ]
    catalogue_path = tmp_path / "source-catalogue.jsonl"
    _write_catalogue(catalogue_path, records)

    queue_row = {
        "symbol": "ACME",
        "action_type": "DIVIDEND",
        "ex_date": "2024-01-15",
        "purpose": "Interim Dividend - Rs 5 Per Share",
        "reason": "snapshot_retrieval",
    }
    visibility_queue = [dict(queue_row) for _ in action_rows]
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_bytes(canonical_json_bytes({
        "visibility_review_queue": visibility_queue,
        "factor_review_queue": [],
    }))
    packet_dir = tmp_path / "packet"
    export_review_packet(baseline_path, packet_dir)
    return {
        "actions_path": actions_path,
        "announcements_path": announcements_path,
        "action_sha256": records[0]["sha256"],
        "announcement_sha256": records[1]["sha256"],
        "catalogue_path": catalogue_path,
        "catalogue_records": records,
        "baseline_path": baseline_path,
        "packet_dir": packet_dir,
        "visibility_queue": visibility_queue,
    }


def _build(fixture: dict) -> list[dict[str, object]]:
    return build_evidence_index(
        catalogue_path=fixture["catalogue_path"],
        baseline_report_path=fixture["baseline_path"],
        packet_dir=fixture["packet_dir"],
    )


def _mutate_csv(path: Path, mutator) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    mutator(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_build_evidence_index_binds_review_and_retained_source_identity(tmp_path):
    fixture = _fixture(tmp_path)
    rows = _build(fixture)

    assert len(rows) == 1
    record = rows[0]
    packet_row = build_review_rows("visibility", fixture["visibility_queue"])[0]
    assert record["review_id"] == packet_row["review_id"]
    assert record["queue_kind"] == "visibility"
    assert record["action_source"]["sha256"] == fixture["action_sha256"]
    assert record["announcement_candidates"][0]["seq_id"] == "123"
    assert (
        record["announcement_candidates"][0]["snapshot_sha256"]
        == fixture["announcement_sha256"]
    )
    assert record["candidate_resolution"] == "AMBIGUOUS_REVIEW_REQUIRED"
    assert "canonical_decision" not in record
    assert "audit_authority" not in record


@pytest.mark.parametrize("drift", ["sha256", "length"])
def test_build_rejects_source_integrity_drift(tmp_path, drift):
    fixture = _fixture(tmp_path)
    if drift == "sha256":
        fixture["actions_path"].write_bytes(b"[]")
    else:
        records = fixture["catalogue_records"]
        records[0]["bytes"] += 1
        _write_catalogue(fixture["catalogue_path"], records)
    output = tmp_path / "index.jsonl"

    with pytest.raises(EvidenceIndexError, match="integrity"):
        write_evidence_index(_build(fixture), output)

    assert not output.exists()


@pytest.mark.parametrize("drifted", [False, True])
def test_build_rejects_duplicate_eligible_catalogue_records_before_skipping_them(
    tmp_path,
    drifted,
):
    fixture = _fixture(tmp_path)
    duplicate = copy.deepcopy(fixture["catalogue_records"][0])
    if drifted:
        duplicate["sha256"] = "0" * 64
    _write_catalogue(
        fixture["catalogue_path"],
        [duplicate, *fixture["catalogue_records"]],
    )

    with pytest.raises(EvidenceIndexError, match="duplicate eligible source"):
        _build(fixture)


def test_build_rejects_semantically_duplicate_mixed_date_ranges(tmp_path):
    fixture = _fixture(tmp_path)
    duplicate = copy.deepcopy(fixture["catalogue_records"][0])
    duplicate["params"]["from_date"] = "2024-01-01"
    duplicate["params"]["to_date"] = "2024-01-31"
    _write_catalogue(
        fixture["catalogue_path"],
        [duplicate, *fixture["catalogue_records"]],
    )

    with pytest.raises(EvidenceIndexError, match="duplicate eligible source"):
        _build(fixture)


def test_build_rejects_duplicate_packet_review_ids(tmp_path):
    fixture = _fixture(tmp_path, duplicate_action=True)
    reviews = fixture["packet_dir"] / "visibility-reviews.csv"
    _mutate_csv(reviews, lambda rows: rows[1].update(review_id=rows[0]["review_id"]))
    output = tmp_path / "index.jsonl"

    with pytest.raises(EvidenceIndexError, match="duplicate review ID"):
        write_evidence_index(_build(fixture), output)

    assert not output.exists()


def test_build_rejects_packet_identity_mutation(tmp_path):
    fixture = _fixture(tmp_path)
    reviews = fixture["packet_dir"] / "visibility-reviews.csv"
    _mutate_csv(reviews, lambda rows: rows[0].update(symbol="OTHER"))
    output = tmp_path / "index.jsonl"

    with pytest.raises(EvidenceIndexError, match="packet identity"):
        write_evidence_index(_build(fixture), output)

    assert not output.exists()


def test_build_rejects_malformed_relevant_announcement_timestamp(tmp_path):
    fixture = _fixture(tmp_path)
    rows = json.loads(fixture["announcements_path"].read_text(encoding="utf-8"))
    rows[0]["an_dt"] = "not-a-timestamp"
    fixture["announcements_path"].write_text(json.dumps(rows), encoding="utf-8")
    fixture["catalogue_records"][1] = _source_record(
        fixture["announcements_path"],
        kind="corporate_announcements",
        start="01-01-2024",
        end="31-01-2024",
    )
    _write_catalogue(fixture["catalogue_path"], fixture["catalogue_records"])
    output = tmp_path / "index.jsonl"

    with pytest.raises(EvidenceIndexError, match="announcement timestamp"):
        write_evidence_index(_build(fixture), output)

    assert not output.exists()


def test_build_rejects_missing_retained_source(tmp_path):
    fixture = _fixture(tmp_path)
    fixture["actions_path"].unlink()
    output = tmp_path / "index.jsonl"

    with pytest.raises(EvidenceIndexError, match="retained source"):
        write_evidence_index(_build(fixture), output)

    assert not output.exists()


def test_candidate_matching_retains_all_compatible_candidates(tmp_path):
    fixture = _fixture(tmp_path)
    rows = json.loads(fixture["announcements_path"].read_text(encoding="utf-8"))
    rows.extend([
        {**rows[0], "seq_id": "124", "an_dt": "14-Jan-2024 09:00:00"},
        {**rows[0], "seq_id": "wrong-symbol", "symbol": "OTHER"},
        {**rows[0], "seq_id": "late", "an_dt": "15-Jan-2024 09:15:00"},
        {**rows[0], "seq_id": "wrong-type", "desc": "Board Meeting",
         "subject": "Board Meeting", "attchmntText": "Board Meeting"},
    ])
    fixture["announcements_path"].write_text(json.dumps(rows), encoding="utf-8")
    fixture["catalogue_records"][1] = _source_record(
        fixture["announcements_path"],
        kind="corporate_announcements",
        start="01-01-2024",
        end="31-01-2024",
    )
    _write_catalogue(fixture["catalogue_path"], fixture["catalogue_records"])

    candidates = _build(fixture)[0]["announcement_candidates"]

    assert [candidate["seq_id"] for candidate in candidates] == ["123", "124"]
    assert all(candidate["ambiguity_reason"] == "CANDIDATE_NOT_CANONICAL" for candidate in candidates)


def test_candidate_snapshot_must_intersect_bounded_action_window(tmp_path):
    fixture = _fixture(tmp_path)
    record = fixture["catalogue_records"][1]
    record["params"] = {"from_date": "01-01-2023", "to_date": "31-01-2023"}
    _write_catalogue(fixture["catalogue_path"], fixture["catalogue_records"])

    assert _build(fixture)[0]["announcement_candidates"] == []


def test_same_action_can_bind_visibility_and_factor_queue_rows(tmp_path):
    fixture = _fixture(tmp_path)
    factor_row = {
        **fixture["visibility_queue"][0],
        "reason": "reviewed adjustment factor required",
    }
    fixture["baseline_path"].write_bytes(canonical_json_bytes({
        "visibility_review_queue": fixture["visibility_queue"],
        "factor_review_queue": [factor_row],
    }))
    export_review_packet(fixture["baseline_path"], fixture["packet_dir"])

    rows = _build(fixture)

    assert [row["queue_kind"] for row in rows] == ["visibility", "factor"]
    assert rows[0]["action_source"] == rows[1]["action_source"]
    assert rows[0]["review_id"] != rows[1]["review_id"]


def test_write_evidence_index_emits_atomic_canonical_jsonl(tmp_path):
    fixture = _fixture(tmp_path)
    rows = _build(fixture)
    output = tmp_path / "nested" / "index.jsonl"
    output.parent.mkdir()

    result = write_evidence_index(rows, output)

    expected = b"".join(canonical_json_bytes(row) for row in rows)
    assert output.read_bytes() == expected
    assert result == {
        "schema_version": "corporate-action-evidence-index-v1",
        "row_count": 1,
        "sha256": hashlib.sha256(expected).hexdigest(),
    }
    assert not output.with_name(output.name + ".part").exists()


def test_write_evidence_index_fails_closed_when_part_exists(tmp_path):
    output = tmp_path / "index.jsonl"
    part = output.with_name(output.name + ".part")
    part.write_text("occupied", encoding="utf-8")

    with pytest.raises(EvidenceIndexError, match="temporary output"):
        write_evidence_index([], output)

    assert not output.exists()
    assert part.read_text(encoding="utf-8") == "occupied"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row.update(proposal_only=False), "proposal_only"),
        (lambda row: row.update(schema_version="untrusted-v2"), "schema version"),
        (
            lambda row: row["announcement_candidates"][0].update(
                decision="APPROVED",
            ),
            "audit authority",
        ),
    ],
)
def test_write_rejects_invalid_or_authoritative_proposal_rows(
    tmp_path,
    mutation,
    message,
):
    rows = copy.deepcopy(_build(_fixture(tmp_path)))
    mutation(rows[0])
    output = tmp_path / "index.jsonl"

    with pytest.raises(EvidenceIndexError, match=message):
        write_evidence_index(rows, output)

    assert not output.exists()


def test_write_file_fsync_failure_preserves_destination(tmp_path, monkeypatch):
    rows = _build(_fixture(tmp_path))
    output = tmp_path / "index.jsonl"
    output.write_bytes(b"prior\n")

    def fail_file_fsync(_descriptor):
        raise OSError("file fsync failed")

    monkeypatch.setattr(evidence_index_module.os, "fsync", fail_file_fsync)

    with pytest.raises(EvidenceIndexError, match="before destination replacement"):
        write_evidence_index(rows, output)

    assert output.read_bytes() == b"prior\n"
    assert not output.with_name(output.name + ".part").exists()


def test_write_replace_failure_preserves_destination(tmp_path, monkeypatch):
    rows = _build(_fixture(tmp_path))
    output = tmp_path / "index.jsonl"
    output.write_bytes(b"prior\n")

    def fail_replace(_source, _destination):
        raise OSError("replace failed")

    monkeypatch.setattr(evidence_index_module.os, "replace", fail_replace)

    with pytest.raises(EvidenceIndexError, match="before destination replacement"):
        write_evidence_index(rows, output)

    assert output.read_bytes() == b"prior\n"
    assert not output.with_name(output.name + ".part").exists()


def test_write_parent_fsync_failure_reports_replaced_but_uncertain_durability(
    tmp_path,
    monkeypatch,
):
    rows = _build(_fixture(tmp_path))
    expected = b"".join(canonical_json_bytes(row) for row in rows)
    output = tmp_path / "index.jsonl"
    output.write_bytes(b"prior\n")
    real_fsync = os.fsync
    calls = 0

    def fail_parent_fsync(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("parent fsync failed")
        real_fsync(descriptor)

    monkeypatch.setattr(evidence_index_module.os, "fsync", fail_parent_fsync)

    with pytest.raises(
        EvidenceIndexError,
        match="destination was replaced.*durability is uncertain",
    ):
        write_evidence_index(rows, output)

    assert output.read_bytes() == expected
    assert not output.with_name(output.name + ".part").exists()


def test_catalogue_relative_sources_and_output_are_location_independent(
    tmp_path,
    monkeypatch,
):
    fixtures = [_fixture(tmp_path / location) for location in ("one", "two")]
    for fixture in fixtures:
        for record in fixture["catalogue_records"]:
            record["path"] = Path(record["path"]).name
        _write_catalogue(fixture["catalogue_path"], fixture["catalogue_records"])
    monkeypatch.chdir(tmp_path.parent)

    first = _build(fixtures[0])
    second = _build(fixtures[1])

    assert first == second
    assert first[0]["action_source"]["path"] == "actions.json"
    assert first[0]["announcement_candidates"][0]["snapshot_path"] == (
        "announcements.json"
    )
