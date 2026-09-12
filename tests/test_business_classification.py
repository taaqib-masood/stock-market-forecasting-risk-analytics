import json

from src.reliability.business_classification import (
    derive_business_classifications,
    write_business_classification_outputs,
)


def test_derivation_accepts_only_defensible_exchange_categories():
    audit = {
        "security_types": {
            "TCS": {"type": "NON_FINANCIAL_TAXONOMY", "source": "NSE_FINANCIAL_RESULT_TAXONOMY",
                    "evidence": {"isin": "INE467B01029", "instrument_name": "TCS LTD"}},
            "SBILIFE": {"type": "INSURANCE_BUSINESS", "source": "NSE_LEGAL_INSTRUMENT_NAME",
                        "evidence": {"isin": "INE123W01016", "instrument_name": "SBI LIFE INSURANCE CO LTD"}},
            "BANK": {"type": "BANKING_TAXONOMY", "source": "NSE_FINANCIAL_RESULT_TAXONOMY",
                     "evidence": {"isin": "INE000000001", "instrument_name": "BANK LTD"}},
            "IBULHSGFIN": {"type": "UNKNOWN", "source": "NO_EXPLICIT_TYPE_EVIDENCE",
                           "evidence": {"isin": "INE148I01020", "instrument_name": "INDIABULLS HSG FIN LTD"}},
            "ETF": {"type": "FUND", "source": "NSE_ISIN_OR_INSTRUMENT_NAME",
                    "evidence": {"isin": "INF000000001", "instrument_name": "ETF"}},
            "DVR": {"type": "NON_FINANCIAL_TAXONOMY", "source": "NSE",
                    "evidence": {"isin": "IN9000000001", "instrument_name": "DVR SHARE"}},
        }
    }

    result = derive_business_classifications(
        audit,
        effective_from="2024-07-05",
        available_at="2024-07-05T18:00:00Z",
        methodology_version="nse-business-v1",
    )

    assert [row["symbol"] for row in result["classifications"]] == ["SBILIFE", "TCS"]
    assert result["classifications"][0]["business_type"] == "INSURER"
    assert result["classifications"][1]["business_type"] == "NON_FINANCIAL"
    assert [row["symbol"] for row in result["review_queue"]] == ["BANK", "IBULHSGFIN"]
    assert result["specialist_review_queue"] == [{
        "symbol": "SBILIFE",
        "business_type": "INSURER",
        "required_action": "QUALIFIED_SHARIAH_INSURANCE_REVIEW",
        "evidence": {"isin": "INE123W01016", "instrument_name": "SBI LIFE INSURANCE CO LTD"},
    }]
    assert result["excluded_funds"] == ["ETF"]
    assert result["excluded_nonstandard_equities"] == ["DVR"]


def test_finance_words_in_name_do_not_bypass_primary_evidence_review():
    audit = {"security_types": {
        "MAYBEFIN": {"type": "UNKNOWN", "source": "NO_EXPLICIT_TYPE_EVIDENCE",
                     "evidence": {"instrument_name": "MAYBE HOUSING FINANCE LTD", "isin": "INE1"}}
    }}

    result = derive_business_classifications(
        audit, effective_from="2024-07-05", available_at="2024-07-05T18:00:00Z",
        methodology_version="nse-business-v1",
    )

    assert result["classifications"] == []
    assert result["review_queue"][0]["required_action"] == "PRIMARY_BUSINESS_REVIEW"


def test_derivation_reports_corporate_coverage():
    audit = {"security_types": {
        "A": {"type": "NON_FINANCIAL_TAXONOMY", "source": "NSE",
              "evidence": {"isin": "INE000000001"}},
        "B": {"type": "UNKNOWN", "source": "NSE", "evidence": {"isin": "INE000000002"}},
        "F": {"type": "FUND", "source": "NSE", "evidence": {}},
    }}

    result = derive_business_classifications(
        audit, effective_from="2024-07-05", available_at="2024-07-05T18:00:00Z",
        methodology_version="nse-business-v1",
    )

    assert result["coverage"] == {"corporate_total": 2, "classified": 1, "ratio": 0.5}


def test_writer_emits_import_csv_and_auditable_review_report(tmp_path):
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps({"security_types": {
        "A": {"type": "NON_FINANCIAL_TAXONOMY", "source": "NSE",
              "evidence": {"isin": "INE000000001"}},
        "B": {"type": "UNKNOWN", "source": "NSE", "evidence": {"isin": "INE000000002"}},
    }}))
    output = tmp_path / "business.csv"
    report = tmp_path / "report.json"

    result = write_business_classification_outputs(
        audit_path, output=output, report=report, effective_from="2024-07-05",
        available_at="2024-07-05T18:00:00Z", methodology_version="nse-business-v1",
    )

    assert output.read_text().splitlines()[0] == (
        "SYMBOL,BUSINESS_TYPE,EFFECTIVE_FROM,AVAILABLE_AT,METHODOLOGY_VERSION,REASON"
    )
    assert json.loads(report.read_text())["review_queue"][0]["symbol"] == "B"
    assert result["coverage"]["ratio"] == 0.5
