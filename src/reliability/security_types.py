"""Evidence-backed NSE security taxonomy and filing-gap analysis."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


FILING_TYPES = {
    "B": "BANKING_TAXONOMY",
    "F": "FINANCIAL_TAXONOMY",
    "N": "NON_FINANCIAL_TAXONOMY",
}


def classify_security_types(
    security_path: str | Path,
    filing_index_paths: list[str | Path],
) -> dict[str, dict]:
    filing_flags: dict[str, set[str]] = {}
    for path in filing_index_paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError(f"{path}: filing index must contain a list")
        for row in rows:
            if not isinstance(row, dict) or not row.get("symbol"):
                continue
            flag = str(row.get("bank") or "").strip().upper()
            if flag in FILING_TYPES:
                filing_flags.setdefault(str(row["symbol"]).upper(), set()).add(flag)

    output = {}
    with Path(security_path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            symbol = (row.get("TckrSymb") or row.get("SYMBOL") or "").strip().upper()
            if not symbol or not _active_equity(row):
                continue
            name = (row.get("FinInstrmNm") or "").strip()
            isin = (row.get("ISIN") or "").strip().upper()
            flags = filing_flags.get(symbol, set())
            evidence = {"instrument_name": name, "isin": isin,
                        "filing_taxonomy_flags": sorted(flags)}
            if _explicit_debt(name):
                security_type = "DEBT_INSTRUMENT"
                source = "NSE_INSTRUMENT_NAME"
            elif _explicit_insurance(name):
                security_type = "INSURANCE_BUSINESS"
                source = "NSE_LEGAL_INSTRUMENT_NAME"
            elif len(flags) == 1:
                flag = next(iter(flags))
                security_type = FILING_TYPES[flag]
                source = "NSE_FINANCIAL_RESULT_TAXONOMY"
            elif len(flags) > 1:
                security_type = "UNKNOWN"
                source = "CONFLICTING_NSE_TAXONOMY"
            elif _explicit_fund(isin, name):
                security_type = "FUND"
                source = "NSE_ISIN_OR_INSTRUMENT_NAME"
            else:
                security_type = "UNKNOWN"
                source = "NO_EXPLICIT_TYPE_EVIDENCE"
            output[symbol] = {"type": security_type, "source": source, "evidence": evidence}
    return output


def filing_symbols(index_paths: list[str | Path]) -> set[str]:
    symbols = set()
    for path in index_paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = payload.get("data", []) if isinstance(payload, dict) else payload
        if isinstance(rows, list):
            symbols.update(str(row.get("symbol", "")).upper() for row in rows if isinstance(row, dict))
    symbols.discard("")
    return symbols


def analyze_filing_gaps(
    coverage_plan: dict,
    security_types: dict[str, dict],
    *,
    later_filing_symbols: set[str],
) -> dict:
    reasons = {
        "FUND_NOT_CORPORATE_FILER": [],
        "DEBT_INSTRUMENT_NOT_EQUITY": [],
        "INSURANCE_BUSINESS_REVIEW": [],
        "FILING_ONLY_AFTER_CUTOFF": [],
        "NO_NSE_FILING_METADATA": [],
        "NO_POINT_IN_TIME_FILING": [],
    }
    for symbol in sorted(coverage_plan.get("no_point_in_time_filing", [])):
        security_type = security_types.get(symbol, {}).get("type", "UNKNOWN")
        if security_type == "FUND":
            reason = "FUND_NOT_CORPORATE_FILER"
        elif security_type == "DEBT_INSTRUMENT":
            reason = "DEBT_INSTRUMENT_NOT_EQUITY"
        elif security_type == "INSURANCE_BUSINESS":
            reason = "INSURANCE_BUSINESS_REVIEW"
        elif symbol in later_filing_symbols:
            reason = "FILING_ONLY_AFTER_CUTOFF"
        elif security_type == "UNKNOWN":
            reason = "NO_NSE_FILING_METADATA"
        else:
            reason = "NO_POINT_IN_TIME_FILING"
        reasons[reason].append(symbol)
    reasons = {reason: symbols for reason, symbols in reasons.items() if symbols}
    return {"gap_count": sum(len(symbols) for symbols in reasons.values()),
            "counts": {reason: len(symbols) for reason, symbols in reasons.items()},
            "reasons": reasons}


def _active_equity(row: dict[str, str]) -> bool:
    series = (row.get("SctySrs") or row.get("SERIES") or "").strip().upper()
    if series and series != "EQ":
        return False
    if "ElgbltyNrmlMkt" in row and (row.get("ElgbltyNrmlMkt") or "").strip() != "1":
        return False
    if (row.get("DelFlg") or "").strip().upper() == "Y":
        return False
    isin = (row.get("ISIN") or "").strip().upper()
    return not isin or (isin.startswith("IN") and not isin.startswith("DUMMY"))


def _explicit_fund(isin: str, name: str) -> bool:
    if isin.startswith("INF"):
        return True
    normalized = f" {name.upper()} "
    return bool(re.search(r"\bETF\b|\bAMC\s*-|\bMUTUAL FUND\b", normalized))


def _explicit_debt(name: str) -> bool:
    return bool(re.search(r"\bNCD\b|\bDEBENTURE", name.upper()))


def _explicit_insurance(name: str) -> bool:
    return bool(re.search(r"\bINSURANCE\b|\bINS\b|\bINSURA\b|\bASSU\b|\bGIC\b", name.upper()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify NSE security types and filing gaps")
    parser.add_argument("security_master")
    parser.add_argument("coverage_plan")
    parser.add_argument("--index", action="append", default=[])
    parser.add_argument("--later-index", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    types = classify_security_types(args.security_master, args.index + args.later_index)
    coverage = json.loads(Path(args.coverage_plan).read_text(encoding="utf-8"))
    gaps = analyze_filing_gaps(coverage, types,
                               later_filing_symbols=filing_symbols(args.later_index))
    payload = {"type_counts": dict(sorted(Counter(row["type"] for row in types.values()).items())),
               "security_types": types, "filing_gaps": gaps}
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(destination), "type_counts": payload["type_counts"],
                      "filing_gap_counts": gaps["counts"]}, indent=2))


if __name__ == "__main__":
    main()
