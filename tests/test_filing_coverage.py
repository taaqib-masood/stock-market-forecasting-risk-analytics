import json
import csv

from src.reliability.filing_coverage import (
    execute_download_manifest,
    plan_filing_coverage,
    write_download_manifest,
    write_download_manifest_batches,
    summarize_fact_files,
)


def test_fact_summary_counts_direct_and_candidate_concepts(tmp_path):
    path = tmp_path / "facts.json"
    path.write_text(json.dumps([
        {"symbol": "A", "debt_to_assets": 0.1, "interest_income_ratio": None,
         "payload": {"total_revenue": 100, "interest_income_candidates": {
             "AdjustmentsForInterestIncome": [-2]}}},
        {"symbol": "B", "debt_to_assets": None, "interest_income_ratio": 0.01,
         "payload": {"total_revenue": 200, "interest_income_candidates": {}}},
    ]))

    result = summarize_fact_files([path])

    assert result == {
        "rows": 2, "debt_to_assets": 1, "direct_interest_income_ratio": 1,
        "annual_revenue": 2, "halal_complete": 0,
        "candidate_concepts": {"AdjustmentsForInterestIncome": 1},
    }


def test_full_manifest_batching_is_deterministic_and_bounded(tmp_path):
    selected = [{
        "symbol": f"S{i:03d}", "period_end": "2024-03-31",
        "available_at": "2024-05-01T00:00:00Z",
        "xbrl_url": f"https://nsearchives.nseindia.com/corporate/xbrl/S{i:03d}.xml",
    } for i in range(205)]

    result = write_download_manifest_batches(
        {"as_of": "2024-07-05T23:59:59Z", "selected": selected},
        tmp_path / "batches", batch_size=100,
    )

    assert result["documents"] == 205
    assert result["batches"] == 3
    assert [item["count"] for item in result["batch_index"]] == [100, 100, 5]
    assert all(len(item["sha256"]) == 64 for item in result["batch_index"])
    last = json.loads((tmp_path / "batches" / "xbrl-batch-003.json").read_text())
    assert [row["symbol"] for row in last["documents"]] == ["S200", "S201", "S202", "S203", "S204"]
from src.reliability.xbrl import XbrlResult


def test_point_in_time_filing_plan_excludes_future_and_selects_best_revision(tmp_path):
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({
        "memberships": [
            {"symbol": "TCS", "valid_from": "2024-01-01", "available_at": "2024-01-01T03:00:00Z"},
            {"symbol": "INFY", "valid_from": "2024-01-01", "available_at": "2024-01-01T03:00:00Z"},
            {"symbol": "OLD", "valid_from": "2024-01-01", "valid_to": "2024-06-01",
             "available_at": "2024-06-01T03:00:00Z"},
        ]
    }))
    index = tmp_path / "results.json"
    index.write_text(json.dumps([
        {"symbol": "TCS", "fromDate": "01-Apr-2023", "toDate": "31-Mar-2024",
         "filingDate": "20-Apr-2024 10:00", "consolidated": "Non-Consolidated",
         "audited": "Audited", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/TCS-S.xml"},
        {"symbol": "TCS", "fromDate": "01-Apr-2023", "toDate": "31-Mar-2024",
         "filingDate": "20-Apr-2024 11:00", "consolidated": "Consolidated",
         "audited": "Audited", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/TCS-C.xml"},
        {"symbol": "TCS", "fromDate": "01-Apr-2024", "toDate": "30-Jun-2024",
         "filingDate": "12-Jul-2024 10:00", "consolidated": "Consolidated",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/FUTURE.xml"},
        {"symbol": "INFY", "fromDate": "01-Apr-2023", "toDate": "31-Mar-2024",
         "filingDate": "25-Apr-2024 10:00", "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/-"},
    ]))

    result = plan_filing_coverage(bundle, [index], as_of="2024-07-05T23:59:59Z")

    assert result["counts"] == {
        "eligible_symbols": 2, "selected_xbrl": 1, "metadata_without_xbrl": 1,
        "no_point_in_time_filing": 0,
    }
    assert result["selected"][0]["symbol"] == "TCS"
    assert result["selected"][0]["xbrl_url"].endswith("TCS-C.xml")
    assert result["metadata_without_xbrl"] == ["INFY"]


def test_download_manifest_is_deduplicated_and_explicitly_bounded(tmp_path):
    plan = {
        "selected": [
            {"symbol": "TCS", "period_end": "2024-03-31", "available_at": "2024-04-20T05:30:00Z",
             "xbrl_url": "https://nsearchives.nseindia.com/corporate/xbrl/SAME.xml"},
            {"symbol": "INFY", "period_end": "2024-03-31", "available_at": "2024-04-25T05:30:00Z",
             "xbrl_url": "https://nsearchives.nseindia.com/corporate/xbrl/SAME.xml"},
        ]
    }
    output = tmp_path / "manifest.json"

    result = write_download_manifest(plan, output, limit=1)

    assert result["selected"] == 1
    assert result["remaining"] == 1
    assert len(json.loads(output.read_text())["documents"]) == 1


def test_filing_plan_matches_changed_symbol_by_isin_and_preserves_source_symbol(tmp_path):
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"memberships": [{
        "symbol": "ZOMATO", "valid_from": "2024-01-01", "available_at": "2024-01-01T03:00:00Z"
    }]}))
    security = tmp_path / "security.csv"
    with security.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["TckrSymb", "ISIN"])
        writer.writeheader()
        writer.writerow({"TckrSymb": "ZOMATO", "ISIN": "INE758T01015"})
    index = tmp_path / "index.json"
    index.write_text(json.dumps([{
        "symbol": "ETERNAL", "isin": "INE758T01015", "fromDate": "01-Apr-2023",
        "toDate": "31-Mar-2024", "filingDate": "20-May-2024 10:00",
        "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/ETERNAL.xml",
    }]))

    result = plan_filing_coverage(
        bundle, [index], as_of="2024-07-05T23:59:59Z", security_master=security
    )

    assert result["counts"]["selected_xbrl"] == 1
    assert result["selected"][0]["symbol"] == "ZOMATO"
    assert result["selected"][0]["source_symbol"] == "ETERNAL"
    assert result["selected"][0]["match_method"] == "ISIN"


def test_execute_manifest_reports_concept_completeness(tmp_path):
    xml = tmp_path / "facts.xml"
    xml.write_text('''<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:i="x">
      <context id="c"><period><instant>2024-03-31</instant></period></context>
      <i:Assets contextRef="c">100</i:Assets><i:Borrowings contextRef="c">20</i:Borrowings>
      <i:Revenue contextRef="c">80</i:Revenue></xbrl>''')
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"documents": [{
        "symbol": "TCS", "period_end": "2024-03-31",
        "available_at": "2024-04-20T10:00:00Z",
        "xbrl_url": "https://nsearchives.nseindia.com/corporate/xbrl/TCS.xml",
    }]}))

    class FakeAcquirer:
        def acquire(self, url):
            return XbrlResult("downloaded", url, xml, "abc", xml.stat().st_size,
                               "2024-04-20T10:00:00Z")

    report = execute_download_manifest(
        manifest, tmp_path / "output.json", acquirer=FakeAcquirer(), delay_seconds=0
    )

    assert report["downloaded"] == 1
    assert report["concept_coverage"]["debt_to_assets"] == 1
    assert report["concept_coverage"]["interest_income_ratio"] == 0
    assert report["halal_complete"] == 0
    assert report["missing_concepts"]["interest_income_ratio"] == ["TCS"]
