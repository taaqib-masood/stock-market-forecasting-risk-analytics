import csv
import json

from src.reliability.nse_pipeline import apply_generation_blockers, run_config


def _csv(path, fields, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_pipeline_config_builds_bundle_and_quality_report(tmp_path):
    _csv(tmp_path / "security.csv", ["SYMBOL", "SERIES"], [{"SYMBOL": "TCS", "SERIES": "EQ"}])
    _csv(tmp_path / "bhav.csv", ["SYMBOL", "TIMESTAMP", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY"], [{
        "SYMBOL": "TCS", "TIMESTAMP": "2024-07-01", "OPEN": 100, "HIGH": 102,
        "LOW": 99, "CLOSE": 101, "TOTTRDQTY": 1000,
    }])
    _csv(tmp_path / "actions.csv", ["SYMBOL", "PURPOSE", "EX-DATE"], [])
    _csv(tmp_path / "financials.csv", ["SYMBOL", "PERIOD_END", "FILING_DATE", "TOTAL_DEBT",
                                            "TOTAL_ASSETS", "INTEREST_INCOME", "TOTAL_REVENUE"], [{
        "SYMBOL": "TCS", "PERIOD_END": "2024-03-31", "FILING_DATE": "2024-06-30",
        "TOTAL_DEBT": 10, "TOTAL_ASSETS": 100, "INTEREST_INCOME": 1, "TOTAL_REVENUE": 100,
    }])
    _csv(tmp_path / "business.csv", ["SYMBOL", "BUSINESS_TYPE", "EFFECTIVE_FROM",
                                        "AVAILABLE_AT", "METHODOLOGY_VERSION", "REASON"], [{
        "SYMBOL": "TCS", "BUSINESS_TYPE": "NON_FINANCIAL",
        "EFFECTIVE_FROM": "2024-01-01", "AVAILABLE_AT": "2024-06-30T12:00:00Z",
        "METHODOLOGY_VERSION": "business-v1", "REASON": "software services",
    }])
    config = {
        "as_of": "2024-07-02",
        "output": "bundle.json",
        "quality_report": "quality.json",
        "security_snapshots": [{"path": "security.csv", "snapshot_date": "2024-07-01",
                                  "available_at": "2024-07-01T03:00:00Z"}],
        "bhavcopies": [{"path": "bhav.csv", "available_at": "2024-07-01T18:00:00Z"}],
        "corporate_actions": [{"path": "actions.csv", "available_at": "2024-07-01T12:00:00Z"}],
        "financials": ["financials.csv"],
        "business_classifications": ["business.csv"],
    }
    config_path = tmp_path / "sources.json"
    config_path.write_text(json.dumps(config))

    result = run_config(config_path)

    assert result["quality"]["ready"] is True
    assert (tmp_path / "bundle.json").exists()
    assert json.loads((tmp_path / "quality.json").read_text())["ready"] is True


def test_pipeline_preserves_external_source_blockers(tmp_path):
    quality = {"ready": True, "blockers": []}

    result = apply_generation_blockers(
        quality, ["CORPORATE_ACTION_POINT_IN_TIME_SOURCE"]
    )

    assert result["ready"] is False
    assert result["blockers"] == ["CORPORATE_ACTION_POINT_IN_TIME_SOURCE"]
