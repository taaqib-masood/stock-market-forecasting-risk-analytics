import csv
import json

from src.reliability.nse_bundle import assess_bundle, build_nse_bundle


def _csv(path, fieldnames, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _sources(tmp_path, include_financial=True):
    security = tmp_path / "security.csv"
    bhav = tmp_path / "bhav.csv"
    actions = tmp_path / "actions.csv"
    financials = tmp_path / "financials.csv"
    business = tmp_path / "business.csv"
    _csv(security, ["SYMBOL", "SERIES"], [{"SYMBOL": "TCS", "SERIES": "EQ"}])
    _csv(bhav, ["SYMBOL", "TIMESTAMP", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY"], [{
        "SYMBOL": "TCS", "TIMESTAMP": "2024-07-01", "OPEN": 100, "HIGH": 102,
        "LOW": 99, "CLOSE": 101, "TOTTRDQTY": 1000,
    }])
    _csv(actions, ["SYMBOL", "PURPOSE", "EX-DATE"], [])
    _csv(business, ["SYMBOL", "BUSINESS_TYPE", "EFFECTIVE_FROM", "AVAILABLE_AT",
                    "METHODOLOGY_VERSION", "REASON"], [{
        "SYMBOL": "TCS", "BUSINESS_TYPE": "NON_FINANCIAL",
        "EFFECTIVE_FROM": "2024-01-01", "AVAILABLE_AT": "2024-06-30T12:00:00Z",
        "METHODOLOGY_VERSION": "business-v1", "REASON": "software services",
    }])
    if include_financial:
        _csv(financials, ["SYMBOL", "PERIOD_END", "FILING_DATE", "TOTAL_DEBT",
                          "TOTAL_ASSETS", "INTEREST_INCOME", "TOTAL_REVENUE"], [{
            "SYMBOL": "TCS", "PERIOD_END": "2024-03-31", "FILING_DATE": "2024-06-30",
            "TOTAL_DEBT": 10, "TOTAL_ASSETS": 100, "INTEREST_INCOME": 1,
            "TOTAL_REVENUE": 100,
        }])
    return security, bhav, actions, financials, business


def test_bundle_builder_retains_hashes_for_every_source_file(tmp_path):
    security, bhav, actions, financials, business = _sources(tmp_path)

    bundle = build_nse_bundle(
        security_snapshots=[{"path": security, "snapshot_date": "2024-07-01",
                             "available_at": "2024-07-01T03:00:00Z"}],
        bhavcopies=[{"path": bhav, "available_at": "2024-07-01T18:00:00Z"}],
        corporate_actions=[{"path": actions, "available_at": "2024-07-01T12:00:00Z"}],
        financials=[financials],
        business_classifications=[business],
    )

    assert bundle["source"] == "nse-primary-source-bundle"
    assert len(bundle["metadata"]["source_files"]) == 5
    assert all(len(item["sha256"]) == 64 for item in bundle["metadata"]["source_files"])
    assert bundle["available_at"] == "2024-07-01T18:00:00Z"


def test_bundle_can_be_written_as_importer_compatible_json(tmp_path):
    security, bhav, actions, financials, business = _sources(tmp_path)
    output = tmp_path / "bundle.json"

    bundle = build_nse_bundle(
        security_snapshots=[{"path": security, "snapshot_date": "2024-07-01",
                             "available_at": "2024-07-01T03:00:00Z"}],
        bhavcopies=[{"path": bhav, "available_at": "2024-07-01T18:00:00Z"}],
        corporate_actions=[{"path": actions, "available_at": "2024-07-01T12:00:00Z"}],
        financials=[financials],
        business_classifications=[business],
        output=output,
    )

    assert json.loads(output.read_text()) == bundle


def test_quality_report_blocks_current_member_without_fundamentals(tmp_path):
    security, bhav, actions, _financials, business = _sources(tmp_path, include_financial=False)
    bundle = build_nse_bundle(
        security_snapshots=[{"path": security, "snapshot_date": "2024-07-01",
                             "available_at": "2024-07-01T03:00:00Z"}],
        bhavcopies=[{"path": bhav, "available_at": "2024-07-01T18:00:00Z"}],
        corporate_actions=[{"path": actions, "available_at": "2024-07-01T12:00:00Z"}],
        financials=[],
        business_classifications=[business],
    )

    report = assess_bundle(bundle, as_of="2024-07-02")

    assert report["ready"] is False
    assert report["missing_fundamentals"] == ["TCS"]
    assert "FUNDAMENTAL_COVERAGE" in report["blockers"]


def test_quality_report_passes_complete_current_snapshot(tmp_path):
    security, bhav, actions, financials, business = _sources(tmp_path)
    bundle = build_nse_bundle(
        security_snapshots=[{"path": security, "snapshot_date": "2024-07-01",
                             "available_at": "2024-07-01T03:00:00Z"}],
        bhavcopies=[{"path": bhav, "available_at": "2024-07-01T18:00:00Z"}],
        corporate_actions=[{"path": actions, "available_at": "2024-07-01T12:00:00Z"}],
        financials=[financials],
        business_classifications=[business],
    )

    report = assess_bundle(bundle, as_of="2024-07-02")

    assert report["ready"] is True
    assert report["current_members"] == 1
    assert report["price_coverage"] == 1.0
    assert report["fundamental_coverage"] == 1.0


def test_quality_report_blocks_missing_business_classification(tmp_path):
    security, bhav, actions, financials, _business = _sources(tmp_path)
    bundle = build_nse_bundle(
        security_snapshots=[{"path": security, "snapshot_date": "2024-07-01",
                             "available_at": "2024-07-01T03:00:00Z"}],
        bhavcopies=[{"path": bhav, "available_at": "2024-07-01T18:00:00Z"}],
        corporate_actions=[{"path": actions, "available_at": "2024-07-01T12:00:00Z"}],
        financials=[financials],
        business_classifications=[],
    )

    report = assess_bundle(bundle, as_of="2024-07-02")

    assert report["business_coverage"] == 0.0
    assert report["missing_business_classifications"] == ["TCS"]
    assert "BUSINESS_COVERAGE" in report["blockers"]


def test_price_gaps_distinguish_alternate_series_from_no_bar():
    bundle = {
        "memberships": [
            {"symbol": "BEONLY", "valid_from": "2024-01-01", "available_at": "2024-01-01T00:00:00Z"},
            {"symbol": "SUSPENDED", "valid_from": "2024-01-01", "available_at": "2024-01-01T00:00:00Z"},
        ],
        "bars": [],
        "fundamentals": [],
        "business_classifications": [],
        "metadata": {"excluded_bar_series": [
            {"symbol": "BEONLY", "series": "BE", "session_date": "2024-07-05"}
        ]},
    }

    report = assess_bundle(bundle, as_of="2024-07-05")

    assert report["price_gap_reasons"] == {
        "BEONLY": "ALTERNATE_SERIES_BE",
        "SUSPENDED": "NO_RETAINED_BAR",
    }
