import csv
import hashlib
import json

from src.reliability.business_review_packet import export_business_review_packet


def test_export_business_review_packet_binds_queues_to_source_report(tmp_path):
    report = {
        "review_queue": [{
            "symbol": "BANK",
            "source_type": "BANKING_TAXONOMY",
            "source": "NSE_XBRL",
            "required_action": "PRIMARY_BUSINESS_REVIEW",
            "evidence": {"isin": "INE000000001", "instrument_name": "BANK LTD"},
        }],
        "specialist_review_queue": [{
            "symbol": "LIFE",
            "business_type": "INSURER",
            "required_action": "QUALIFIED_SHARIAH_INSURANCE_REVIEW",
            "evidence": {"isin": "INE000000002", "instrument_name": "LIFE LTD"},
        }],
    }
    report_path = tmp_path / "business-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    result = export_business_review_packet(report_path, tmp_path / "reviews")

    primary = list(csv.DictReader(result["primary_business_csv"].open()))
    insurers = list(csv.DictReader(result["insurer_csv"].open()))
    manifest = json.loads(result["manifest_path"].read_text())
    assert primary[0]["decision"] == "PENDING"
    assert primary[0]["proposed_business_type"] == ""
    assert primary[0]["isin"] == "INE000000001"
    assert insurers[0]["decision"] == "PENDING"
    assert insurers[0]["shariah_route"] == ""
    assert manifest["primary_business_rows"] == 1
    assert manifest["insurer_rows"] == 1
    assert manifest["source_report_sha256"] == hashlib.sha256(
        report_path.read_bytes()
    ).hexdigest()
    assert manifest["primary_business_csv_sha256"] == hashlib.sha256(
        result["primary_business_csv"].read_bytes()
    ).hexdigest()
    assert manifest["insurer_csv_sha256"] == hashlib.sha256(
        result["insurer_csv"].read_bytes()
    ).hexdigest()
    assert "qualified Shariah reviewer" in manifest["acceptance"]["insurer"]
