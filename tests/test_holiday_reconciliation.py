import hashlib
import json

from src.reliability.holiday_reconciliation import reconcile_holiday_gaps


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _source(tmp_path, *, dates, url="https://archives.nseindia.com/content/circulars/CMTR1.pdf"):
    document = tmp_path / "CMTR1.pdf"
    document.write_bytes(b"official NSE circular")
    return {
        "source_id": "NSE/CMTR/1",
        "url": url,
        "path": str(document),
        "sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
        "segment": "capital_market",
        "holiday_dates": dates,
    }


def test_reconciliation_verifies_every_gap_against_retained_official_evidence(tmp_path):
    review = tmp_path / "review.json"
    manifest = tmp_path / "manifest.json"
    _write_json(review, {"missing_report_dates": ["2024-01-26", "2024-03-08"]})
    _write_json(manifest, {"sources": [_source(tmp_path, dates=["2024-01-26", "2024-03-08"])]})

    result = reconcile_holiday_gaps(review, manifest)

    assert result["complete"] is True
    assert result["status"] == "VERIFIED"
    assert result["counts"] == {"gaps": 2, "confirmed_holidays": 2, "unresolved": 0}
    assert result["confirmed_holidays"]["2024-01-26"] == ["NSE/CMTR/1"]


def test_reconciliation_fails_closed_on_missing_or_changed_evidence(tmp_path):
    review = tmp_path / "review.json"
    manifest = tmp_path / "manifest.json"
    _write_json(review, {"missing_report_dates": ["2024-01-26", "2024-03-08"]})
    source = _source(tmp_path, dates=["2024-01-26"])
    source["sha256"] = "0" * 64
    _write_json(manifest, {"sources": [source]})

    result = reconcile_holiday_gaps(review, manifest)

    assert result["complete"] is False
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["unresolved_dates"] == ["2024-01-26", "2024-03-08"]
    assert result["invalid_sources"][0]["reason"] == "SHA256_MISMATCH"


def test_reconciliation_rejects_non_nse_or_non_capital_market_sources(tmp_path):
    review = tmp_path / "review.json"
    manifest = tmp_path / "manifest.json"
    _write_json(review, {"missing_report_dates": ["2024-01-26"]})
    source = _source(
        tmp_path,
        dates=["2024-01-26"],
        url="https://broker.example/holiday-list.pdf",
    )
    _write_json(manifest, {"sources": [source]})

    result = reconcile_holiday_gaps(review, manifest)

    assert result["complete"] is False
    assert result["unresolved_dates"] == ["2024-01-26"]
    assert result["invalid_sources"][0]["reason"] == "UNOFFICIAL_SOURCE"
