import hashlib
import json
from datetime import date

from src.reliability.backfill_audit import audit_backfill


def _record(path, **values):
    with path.open("a") as handle:
        handle.write(json.dumps(values) + "\n")


def test_backfill_audit_separates_complete_missing_failed_absent_and_holiday(tmp_path):
    catalogue = tmp_path / "source-catalogue.jsonl"
    archive = tmp_path / "one.zip"
    archive.write_bytes(b"valid")
    digest = hashlib.sha256(b"valid").hexdigest()
    _record(catalogue, kind="bhavcopy", session_date="2024-07-01", status="downloaded",
            archive_path=str(archive), sha256=digest, recorded_at="2024-07-01T18:00:00Z")
    _record(catalogue, kind="bhavcopy", session_date="2024-07-02", status="missing_report",
            recorded_at="2024-07-02T18:00:00Z")
    _record(catalogue, kind="bhavcopy", session_date="2024-07-03", status="failed",
            error="timeout", recorded_at="2024-07-03T18:00:00Z")

    result = audit_backfill(
        catalogue, "bhavcopy", date(2024, 7, 1), date(2024, 7, 5),
        holidays={date(2024, 7, 4)},
    )

    assert result["counts"] == {
        "expected": 4, "complete": 1, "missing_report": 1,
        "failed": 1, "absent": 1, "integrity_failure": 0,
    }
    assert result["complete"] is False
    assert result["sessions"]["2024-07-04"] == "holiday"
    assert result["sessions"]["2024-07-05"] == "absent"


def test_backfill_audit_detects_changed_or_deleted_retained_files(tmp_path):
    catalogue = tmp_path / "source-catalogue.jsonl"
    changed = tmp_path / "changed.gz"
    changed.write_bytes(b"changed")
    _record(catalogue, kind="security_master", session_date="2024-07-01", status="downloaded",
            archive_path=str(changed), sha256=hashlib.sha256(b"original").hexdigest())
    _record(catalogue, kind="security_master", session_date="2024-07-02", status="downloaded",
            archive_path=str(tmp_path / "deleted.gz"), sha256="deadbeef")

    result = audit_backfill(
        catalogue, "security_master", date(2024, 7, 1), date(2024, 7, 2)
    )

    assert result["counts"]["integrity_failure"] == 2
    assert result["sessions"]["2024-07-01"] == "integrity_failure"


def test_latest_catalogue_record_wins_for_retried_session(tmp_path):
    catalogue = tmp_path / "source-catalogue.jsonl"
    archive = tmp_path / "retry.zip"
    archive.write_bytes(b"ok")
    _record(catalogue, kind="bhavcopy", session_date="2024-07-01", status="failed",
            recorded_at="2024-07-01T18:00:00Z")
    _record(catalogue, kind="bhavcopy", session_date="2024-07-01", status="downloaded",
            archive_path=str(archive), sha256=hashlib.sha256(b"ok").hexdigest(),
            recorded_at="2024-07-01T18:01:00Z")

    result = audit_backfill(catalogue, "bhavcopy", date(2024, 7, 1), date(2024, 7, 1))

    assert result["complete"] is True
    assert result["counts"]["complete"] == 1
