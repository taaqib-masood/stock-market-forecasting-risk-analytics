import json
from datetime import date

from src.reliability.backfill_config import build_pipeline_config


def _append(path, record):
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def test_build_pipeline_config_selects_retained_prices_and_latest_security_snapshot(tmp_path):
    catalogue = tmp_path / "source-catalogue.jsonl"
    security = tmp_path / "security.csv"
    security.write_text("SYMBOL,SERIES\nTCS,EQ\n")
    old_security = tmp_path / "old-security.csv"
    old_security.write_text("SYMBOL,SERIES\nOLD,EQ\n")
    bhav = tmp_path / "bhav.csv"
    bhav.write_text("SYMBOL,SERIES\nTCS,EQ\n")
    _append(catalogue, {"kind": "security_master", "session_date": "2024-07-01",
                        "status": "downloaded", "extracted_paths": [str(old_security)]})
    _append(catalogue, {"kind": "security_master", "session_date": "2024-07-05",
                        "status": "downloaded", "extracted_paths": [str(security)]})
    _append(catalogue, {"kind": "bhavcopy", "session_date": "2024-07-05",
                        "status": "downloaded", "extracted_paths": [str(bhav)]})

    config = build_pipeline_config(catalogue, date(2024, 7, 1), date(2024, 7, 5))

    assert config["as_of"] == "2024-07-05T23:59:59Z"
    assert len(config["security_snapshots"]) == 1
    assert config["security_snapshots"][0]["snapshot_date"] == "2024-07-05"
    assert config["bhavcopies"][0]["path"] == str(bhav.resolve())
    assert config["financials"] == []


def test_build_pipeline_config_reports_absent_required_sources(tmp_path):
    config = build_pipeline_config(
        tmp_path / "missing.jsonl", date(2024, 7, 1), date(2024, 7, 5)
    )

    assert set(config["generation_blockers"]) == {"SECURITY_SNAPSHOT_ABSENT", "BHAVCOPY_ABSENT"}
