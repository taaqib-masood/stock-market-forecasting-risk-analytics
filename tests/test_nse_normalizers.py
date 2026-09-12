import json
import csv

import pytest

from src.reliability.nse_normalizers import (
    normalize_bhavcopy,
    normalize_bhavcopy_exclusions,
    normalize_corporate_actions,
    normalize_corporate_actions_snapshot,
    reconcile_corporate_action_announcements,
    normalize_financial_result_index,
    normalize_financials,
    normalize_business_classifications,
    normalize_membership_snapshots,
)


def test_business_classifications_preserve_point_in_time_lineage(tmp_path):
    path = tmp_path / "business.csv"
    _csv(path, ["SYMBOL", "BUSINESS_TYPE", "EFFECTIVE_FROM", "AVAILABLE_AT",
                "METHODOLOGY_VERSION", "REASON"], [{
        "SYMBOL": "IBULHSGFIN", "BUSINESS_TYPE": "CONVENTIONAL_NBFC",
        "EFFECTIVE_FROM": "2024-01-01", "AVAILABLE_AT": "2024-06-01T10:00:00Z",
        "METHODOLOGY_VERSION": "business-v1", "REASON": "housing finance lender",
    }])

    rows = normalize_business_classifications(path)

    assert rows == [{
        "symbol": "IBULHSGFIN", "business_type": "CONVENTIONAL_NBFC",
        "effective_from": "2024-01-01", "available_at": "2024-06-01T10:00:00Z",
        "methodology_version": "business-v1", "reason": "housing finance lender",
    }]


def _csv(path, fieldnames, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_membership_snapshots_emit_delisting_correction(tmp_path):
    first = tmp_path / "security-20240101.csv"
    second = tmp_path / "security-20240201.csv"
    _csv(first, ["TckrSymb", "SctySrs"], [
        {"TckrSymb": "KEEP", "SctySrs": "EQ"},
        {"TckrSymb": "DELISTED", "SctySrs": "EQ"},
        {"TckrSymb": "ETF", "SctySrs": "BE"},
    ])
    _csv(second, ["SYMBOL", "SERIES"], [{"SYMBOL": "KEEP", "SERIES": "EQ"}])

    rows = normalize_membership_snapshots([
        {"path": first, "snapshot_date": "2024-01-01", "available_at": "2024-01-01T03:00:00Z"},
        {"path": second, "snapshot_date": "2024-02-01", "available_at": "2024-02-01T03:00:00Z"},
    ])

    assert {tuple(sorted(row.items())) for row in rows} == {
        tuple(sorted({"symbol": "KEEP", "valid_from": "2024-01-01",
                      "available_at": "2024-01-01T03:00:00Z"}.items())),
        tuple(sorted({"symbol": "DELISTED", "valid_from": "2024-01-01",
                      "available_at": "2024-01-01T03:00:00Z"}.items())),
        tuple(sorted({"symbol": "DELISTED", "valid_from": "2024-01-01",
                      "valid_to": "2024-02-01",
                      "available_at": "2024-02-01T03:00:00Z"}.items())),
    }


def test_mii_security_snapshot_excludes_deleted_ineligible_and_test_symbols(tmp_path):
    path = tmp_path / "security.csv"
    fields = ["TckrSymb", "SctySrs", "FinInstrmNm", "ISIN", "ElgbltyNrmlMkt", "DelFlg"]
    _csv(path, fields, [
        {"TckrSymb": "TCS", "SctySrs": "EQ", "ISIN": "INE467B01029",
         "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "MERGED", "SctySrs": "EQ", "ISIN": "INE001A01036",
         "ElgbltyNrmlMkt": "0", "DelFlg": "Y"},
        {"TckrSymb": "011NSETEST", "SctySrs": "EQ", "ISIN": "DUMMYSAN005",
         "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "BOND", "SctySrs": "N3", "ISIN": "INE338I07099",
         "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "GOLDETF", "SctySrs": "EQ", "ISIN": "INF000000001",
         "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "NCD", "SctySrs": "EQ", "FinInstrmNm": "SECURED NCD 8.4%",
         "ISIN": "INE148I07LL3",
         "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
    ])

    rows = normalize_membership_snapshots([{
        "path": path, "snapshot_date": "2024-07-05", "available_at": "2024-07-05T03:00:00Z"
    }])

    assert [row["symbol"] for row in rows] == ["TCS"]


def test_udiff_bhavcopy_aliases_are_normalized(tmp_path):
    path = tmp_path / "bhav.csv"
    _csv(path, ["TckrSymb", "TradDt", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol"], [{
        "TckrSymb": "RELIANCE", "TradDt": "28-Jun-2024", "OpnPric": "3000",
        "HghPric": "3030", "LwPric": "2980", "ClsPric": "3020", "TtlTradgVol": "1000000",
    }])

    rows = normalize_bhavcopy(path, available_at="2024-06-28T18:00:00Z")

    assert rows == [{
        "symbol": "RELIANCE", "session_date": "2024-06-28", "open": 3000.0,
        "high": 3030.0, "low": 2980.0, "close": 3020.0, "volume": 1000000.0,
        "available_at": "2024-06-28T18:00:00Z",
    }]


def test_bhavcopy_excludes_non_equity_series(tmp_path):
    path = tmp_path / "bhav.csv"
    fields = ["SYMBOL", "SERIES", "TIMESTAMP", "OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY"]
    _csv(path, fields, [
        {"SYMBOL": "TCS", "SERIES": "EQ", "TIMESTAMP": "05-JUL-2024", "OPEN": 100,
         "HIGH": 102, "LOW": 99, "CLOSE": 101, "TOTTRDQTY": 1000},
        {"SYMBOL": "BOND", "SERIES": "N3", "TIMESTAMP": "05-JUL-2024", "OPEN": 990,
         "HIGH": 990, "LOW": 990, "CLOSE": 990, "TOTTRDQTY": 50},
    ])

    rows = normalize_bhavcopy(path, available_at="2024-07-05T18:00:00Z")

    assert [row["symbol"] for row in rows] == ["TCS"]
    assert normalize_bhavcopy_exclusions(path) == [{
        "symbol": "BOND", "series": "N3", "session_date": "2024-07-05"
    }]


def test_official_corporate_action_columns_are_normalized(tmp_path):
    path = tmp_path / "actions.csv"
    _csv(path, ["SYMBOL", "SERIES", "PURPOSE", "EX-DATE", "RECORD DATE"], [{
        "SYMBOL": "BSE", "SERIES": "EQ", "PURPOSE": "Bonus 2:1",
        "EX-DATE": "23-May-2025", "RECORD DATE": "23-May-2025",
    }])

    rows = normalize_corporate_actions(path, available_at="2025-05-01T12:00:00Z")

    assert rows[0]["action_type"] == "BONUS"
    assert rows[0]["ex_date"] == "2025-05-23"
    assert rows[0]["payload"]["purpose"] == "Bonus 2:1"


def test_corporate_action_api_snapshot_uses_retrieval_time_when_broadcast_is_absent(tmp_path):
    path = tmp_path / "actions.json"
    path.write_text(json.dumps([{
        "symbol": "RELIANCE", "series": "EQ", "subject": "Bonus 1:1", "faceVal": "10",
        "exDate": "28-Oct-2024", "recDate": "28-Oct-2024", "caBroadcastDate": None,
    }]))

    rows = normalize_corporate_actions_snapshot(path, available_at="2026-07-11T10:00:00Z")

    assert rows[0]["action_type"] == "BONUS"
    assert rows[0]["available_at"] == "2026-07-11T10:00:00Z"
    assert rows[0]["payload"]["availability_source"] == "snapshot_retrieval"
    assert rows[0]["payload"]["face_value"] == 10.0


def test_corporate_action_reconciliation_uses_matching_announcement_timestamp(tmp_path):
    actions = tmp_path / "actions.json"
    announcements = tmp_path / "announcements.json"
    actions.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Dividend - Rs 10 Per Share",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]))
    announcements.write_text(json.dumps([{
        "symbol": "TCS", "desc": "Record Date",
        "attchmntText": "Record date for the purpose of Dividend is 31-Jan-2024.",
        "an_dt": "15-Jan-2024 10:30:00",
    }]))

    rows = reconcile_corporate_action_announcements(
        actions, announcements, available_at="2026-07-12T00:00:00Z"
    )

    assert rows[0]["available_at"] == "2024-01-15T05:00:00Z"
    assert rows[0]["payload"]["availability_source"] == "matched_announcement"


def test_corporate_action_reconciliation_does_not_guess_ambiguous_match(tmp_path):
    actions = tmp_path / "actions.json"
    announcements = tmp_path / "announcements.json"
    actions.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Dividend - Rs 10 Per Share",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]))
    candidate = {
        "symbol": "TCS", "desc": "Record Date",
        "attchmntText": "Record date for the purpose of Dividend is 31-Jan-2024.",
        "an_dt": "15-Jan-2024 10:30:00",
    }
    announcements.write_text(json.dumps([candidate, {**candidate, "an_dt": "16-Jan-2024 10:30:00"}]))

    rows = reconcile_corporate_action_announcements(
        actions, announcements, available_at="2026-07-12T00:00:00Z"
    )

    assert rows[0]["available_at"] == "2026-07-12T00:00:00Z"
    assert rows[0]["payload"]["availability_source"] == "ambiguous_announcement"


def test_corporate_action_reconciliation_matches_exact_declared_dividend_amount(tmp_path):
    actions = tmp_path / "actions.json"
    announcements = tmp_path / "announcements.json"
    actions.write_text(json.dumps([{
        "symbol": "IIFL", "series": "EQ", "subject": "Interim Dividend - Rs 4 Per Share",
        "exDate": "25-Jan-2024", "recDate": "25-Jan-2024", "caBroadcastDate": None,
    }]))
    announcements.write_text(json.dumps([{
        "symbol": "IIFL", "desc": "Dividend",
        "attchmntText": "Board declared Interim Dividend of Rs. 4 per equity share.",
        "an_dt": "17-Jan-2024 16:12:06",
    }]))

    rows = reconcile_corporate_action_announcements(
        actions, announcements, available_at="2026-07-12T00:00:00Z"
    )

    assert rows[0]["payload"]["availability_source"] == "matched_announcement"


def test_corporate_action_reconciliation_matches_prose_date_without_leading_zero(tmp_path):
    actions = tmp_path / "actions.json"
    announcements = tmp_path / "announcements.json"
    actions.write_text(json.dumps([{
        "symbol": "CONCOR", "series": "EQ", "subject": "Bonus 1:4",
        "exDate": "04-Feb-2019", "recDate": "05-Feb-2019", "caBroadcastDate": None,
    }]))
    announcements.write_text(json.dumps([{
        "symbol": "CONCOR", "desc": "Record Date",
        "attchmntText": "Record Date as February 5, 2019 for Bonus equity shares.",
        "an_dt": "23-Jan-2019 19:06:00",
    }]))

    rows = reconcile_corporate_action_announcements(
        actions, announcements, available_at="2026-07-12T00:00:00Z"
    )

    assert rows[0]["payload"]["availability_source"] == "matched_announcement"


def test_corporate_action_reconciliation_matches_dividend_amount_without_currency_prefix(tmp_path):
    actions = tmp_path / "actions.json"
    announcements = tmp_path / "announcements.json"
    actions.write_text(json.dumps([{
        "symbol": "ACC", "series": "EQ", "subject": "Dividend - Rs 14 Per Share",
        "exDate": "05-Mar-2019", "recDate": "-", "caBroadcastDate": None,
    }]))
    announcements.write_text(json.dumps([{
        "symbol": "ACC", "desc": "Dividend",
        "attchmntText": "Board recommended Final Dividend of 14 per equity share.",
        "an_dt": "05-Feb-2019 13:54:00",
    }]))

    rows = reconcile_corporate_action_announcements(
        actions, announcements, available_at="2026-07-12T00:00:00Z"
    )

    assert rows[0]["payload"]["availability_source"] == "matched_announcement"


def test_economic_only_match_uses_latest_qualifying_announcement_date(tmp_path):
    actions = tmp_path / "actions.json"
    announcements = tmp_path / "announcements.json"
    actions.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Dividend - Rs 10 Per Share",
        "exDate": "31-Jan-2024", "recDate": "-", "caBroadcastDate": None,
    }]))
    announcements.write_text(json.dumps([
        {"symbol": "TCS", "desc": "Dividend", "attchmntText": "Dividend of Rs 10 per share.",
         "an_dt": "01-Dec-2023 10:00:00"},
        {"symbol": "TCS", "desc": "Dividend", "attchmntText": "Dividend of Rs 10 per share.",
         "an_dt": "15-Jan-2024 10:00:00"},
    ]))

    rows = reconcile_corporate_action_announcements(
        actions, announcements, available_at="2026-07-12T00:00:00Z"
    )

    assert rows[0]["available_at"] == "2024-01-15T04:30:00Z"


def test_dividend_percentage_matches_cash_amount_using_retained_face_value(tmp_path):
    actions = tmp_path / "actions.json"
    announcements = tmp_path / "announcements.json"
    actions.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ", "subject": "Dividend - Re 1 Per Share",
        "faceVal": "2", "exDate": "31-Jan-2024", "recDate": "-",
        "caBroadcastDate": None,
    }]))
    announcements.write_text(json.dumps([{
        "symbol": "TCS", "desc": "Dividend",
        "attchmntText": "Board recommended a dividend of 50% per equity share.",
        "an_dt": "15-Jan-2024 10:00:00",
    }]))

    rows = reconcile_corporate_action_announcements(
        actions, announcements, available_at="2026-07-12T00:00:00Z"
    )

    assert rows[0]["payload"]["availability_source"] == "matched_announcement"


def test_sub_division_announcement_is_treated_as_split(tmp_path):
    actions = tmp_path / "actions.json"
    announcements = tmp_path / "announcements.json"
    actions.write_text(json.dumps([{
        "symbol": "TCS", "series": "EQ",
        "subject": "Face Value Split (Sub-Division) - From Rs 10 Per Share To Rs 2 Per Share",
        "exDate": "31-Jan-2024", "recDate": "31-Jan-2024", "caBroadcastDate": None,
    }]))
    announcements.write_text(json.dumps([{
        "symbol": "TCS", "desc": "Sub-Division of Equity Shares",
        "attchmntText": "Record date for sub-division is January 31, 2024.",
        "an_dt": "15-Jan-2024 10:00:00",
    }]))

    rows = reconcile_corporate_action_announcements(
        actions, announcements, available_at="2026-07-12T00:00:00Z"
    )

    assert rows[0]["payload"]["availability_source"] == "matched_announcement"


def test_financial_result_index_retains_filing_visibility_and_real_xbrl_links(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps([
        {"symbol": "TCS", "fromDate": "01-Apr-2024", "toDate": "30-Jun-2024",
         "filingDate": "12-Jul-2024 16:30", "broadCastDate": "12-Jul-2024 16:31:05",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/TCS.xml",
         "consolidated": "Consolidated", "audited": "Unaudited"},
        {"symbol": "BAD", "toDate": "30-Jun-2024", "filingDate": "12-Jul-2024 16:30",
         "xbrl": "https://nsearchives.nseindia.com/corporate/xbrl/-"},
    ]))

    rows = normalize_financial_result_index(path)

    assert len(rows) == 2
    assert rows[0]["available_at"] == "2024-07-12T11:01:05Z"
    assert rows[0]["period_end"] == "2024-06-30"
    assert rows[0]["xbrl_url"].endswith("/TCS.xml")
    assert rows[1]["xbrl_url"] is None


def test_filing_financials_derive_ratios_using_filing_date(tmp_path):
    path = tmp_path / "financials.csv"
    _csv(path, ["SYMBOL", "PERIOD_END", "FILING_DATE", "TOTAL_DEBT", "TOTAL_ASSETS",
                "INTEREST_INCOME", "TOTAL_REVENUE", "BUSINESS_TYPE"], [{
        "SYMBOL": "TCS", "PERIOD_END": "2024-03-31", "FILING_DATE": "2024-04-20",
        "TOTAL_DEBT": "20", "TOTAL_ASSETS": "100", "INTEREST_INCOME": "2",
        "TOTAL_REVENUE": "100", "BUSINESS_TYPE": "NON_FINANCIAL",
    }])

    rows = normalize_financials(path)

    assert rows[0]["debt_to_assets"] == 0.2
    assert rows[0]["interest_income_ratio"] == 0.02
    assert rows[0]["available_at"] == "2024-04-20T00:00:00Z"
    assert rows[0]["effective_from"] == "2024-04-20"
    assert rows[0]["business_type"] == "NON_FINANCIAL"


def test_normalized_xbrl_json_is_accepted_as_financial_input(tmp_path):
    path = tmp_path / "facts.json"
    path.write_text(json.dumps([{
        "symbol": "TCS", "period_end": "2024-03-31", "effective_from": "2024-04-20",
        "available_at": "2024-04-20T10:00:00Z", "debt_to_assets": 0.2,
        "interest_income_ratio": None, "business_type": "NON_FINANCIAL",
        "payload": {"source_file": "TCS.xml"},
    }]))

    rows = normalize_financials(path)

    assert rows[0]["symbol"] == "TCS"
    assert rows[0]["debt_to_assets"] == 0.2
    assert rows[0]["interest_income_ratio"] is None
    assert rows[0]["business_type"] == "NON_FINANCIAL"


def test_unknown_schema_fails_with_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    _csv(path, ["foo"], [{"foo": "bar"}])

    with pytest.raises(ValueError, match="missing required columns"):
        normalize_bhavcopy(path, available_at="2024-01-01T00:00:00Z")
