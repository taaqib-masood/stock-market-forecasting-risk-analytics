import csv
import json

from src.reliability.security_types import analyze_filing_gaps, classify_security_types


def _csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["TckrSymb", "SctySrs", "FinInstrmNm",
                                                       "ISIN", "ElgbltyNrmlMkt", "DelFlg"])
        writer.writeheader()
        writer.writerows(rows)


def test_security_types_use_filing_taxonomy_and_explicit_fund_evidence(tmp_path):
    security = tmp_path / "security.csv"
    _csv(security, [
        {"TckrSymb": "BANK", "SctySrs": "EQ", "FinInstrmNm": "A BANK LTD",
         "ISIN": "INE000A01001", "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "FIN", "SctySrs": "EQ", "FinInstrmNm": "FINANCE LTD",
         "ISIN": "INE000A01002", "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "CORP", "SctySrs": "EQ", "FinInstrmNm": "STEEL LTD",
         "ISIN": "INE000A01003", "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "ETF", "SctySrs": "EQ", "FinInstrmNm": "AXIS MF - AXIS GOLD ETF",
         "ISIN": "INF000A01004", "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "MYSTERY", "SctySrs": "EQ", "FinInstrmNm": "MYSTERY LTD",
         "ISIN": "INE000A01005", "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "NCD", "SctySrs": "EQ", "FinInstrmNm": "SECURED NCD 8.4%",
         "ISIN": "INE000A07005", "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
        {"TckrSymb": "INS", "SctySrs": "EQ", "FinInstrmNm": "EXAMPLE LIFE INS CO LTD",
         "ISIN": "INE000A01006", "ElgbltyNrmlMkt": "1", "DelFlg": "N"},
    ])
    filings = tmp_path / "filings.json"
    filings.write_text(json.dumps([
        {"symbol": "BANK", "bank": "B"}, {"symbol": "FIN", "bank": "F"},
        {"symbol": "CORP", "bank": "N"},
    ]))

    result = classify_security_types(security, [filings])

    assert result["BANK"]["type"] == "BANKING_TAXONOMY"
    assert result["FIN"]["type"] == "FINANCIAL_TAXONOMY"
    assert result["CORP"]["type"] == "NON_FINANCIAL_TAXONOMY"
    assert result["ETF"]["type"] == "FUND"
    assert result["MYSTERY"]["type"] == "UNKNOWN"
    assert result["NCD"]["type"] == "DEBT_INSTRUMENT"
    assert result["INS"]["type"] == "INSURANCE_BUSINESS"


def test_gap_analysis_separates_funds_later_filings_and_missing_metadata():
    coverage = {"no_point_in_time_filing": ["ETF", "LATER", "NONE"]}
    types = {
        "ETF": {"type": "FUND"}, "LATER": {"type": "NON_FINANCIAL_TAXONOMY"},
        "NONE": {"type": "UNKNOWN"},
    }

    result = analyze_filing_gaps(coverage, types, later_filing_symbols={"LATER"})

    assert result["reasons"] == {
        "FUND_NOT_CORPORATE_FILER": ["ETF"],
        "FILING_ONLY_AFTER_CUTOFF": ["LATER"],
        "NO_NSE_FILING_METADATA": ["NONE"],
    }
