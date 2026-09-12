"""Conservative business-category derivation from retained NSE evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


_ACCEPTED = {
    "NON_FINANCIAL_TAXONOMY": "NON_FINANCIAL",
    "INSURANCE_BUSINESS": "INSURER",
}


def derive_business_classifications(
    audit: dict[str, Any],
    *,
    effective_from: str,
    available_at: str,
    methodology_version: str,
) -> dict[str, Any]:
    classifications = []
    review_queue = []
    excluded_funds = []
    excluded_nonstandard = []
    specialist_review_queue = []
    corporate_total = 0

    for symbol, record in sorted(audit.get("security_types", {}).items()):
        source_type = record.get("type", "UNKNOWN")
        evidence = record.get("evidence", {})
        if source_type == "FUND":
            excluded_funds.append(symbol)
            continue
        if not str(evidence.get("isin", "")).upper().startswith("INE"):
            excluded_nonstandard.append(symbol)
            continue
        corporate_total += 1
        business_type = _ACCEPTED.get(source_type)
        if business_type:
            classifications.append({
                "symbol": symbol,
                "business_type": business_type,
                "effective_from": effective_from,
                "available_at": available_at,
                "methodology_version": methodology_version,
                "reason": (
                    f"{record.get('source', 'UNKNOWN')}: "
                    f"{evidence.get('instrument_name', symbol)}"
                ),
            })
            if business_type == "INSURER":
                specialist_review_queue.append({
                    "symbol": symbol,
                    "business_type": business_type,
                    "required_action": "QUALIFIED_SHARIAH_INSURANCE_REVIEW",
                    "evidence": evidence,
                })
            continue
        review_queue.append({
            "symbol": symbol,
            "source_type": source_type,
            "source": record.get("source", "UNKNOWN"),
            "evidence": evidence,
            "required_action": "PRIMARY_BUSINESS_REVIEW",
        })

    classified = len(classifications)
    return {
        "classifications": classifications,
        "review_queue": review_queue,
        "excluded_funds": excluded_funds,
        "excluded_nonstandard_equities": excluded_nonstandard,
        "specialist_review_queue": specialist_review_queue,
        "coverage": {
            "corporate_total": corporate_total,
            "classified": classified,
            "ratio": classified / corporate_total if corporate_total else 0.0,
        },
    }


def write_business_classification_outputs(
    audit_path: str | Path,
    *,
    output: str | Path,
    report: str | Path,
    effective_from: str,
    available_at: str,
    methodology_version: str,
) -> dict[str, Any]:
    audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
    result = derive_business_classifications(
        audit,
        effective_from=effective_from,
        available_at=available_at,
        methodology_version=methodology_version,
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["SYMBOL", "BUSINESS_TYPE", "EFFECTIVE_FROM", "AVAILABLE_AT",
              "METHODOLOGY_VERSION", "REASON"]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in result["classifications"]:
            writer.writerow({field: row[field.lower()] for field in fields})
    report_path = Path(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result
