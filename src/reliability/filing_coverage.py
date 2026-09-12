"""Plan point-in-time NSE XBRL coverage for an eligible equity universe."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

from src.reliability.nse_normalizers import normalize_financial_result_index
from src.reliability.xbrl import XbrlAcquirer, parse_halal_financial_facts


def plan_filing_coverage(
    bundle_path: str | Path,
    index_paths: list[str | Path],
    *,
    as_of: str,
    security_master: str | Path | None = None,
) -> dict:
    point = _dt(as_of)
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    eligible = _eligible_symbols(bundle.get("memberships", []), point)
    symbol_isins = _security_isins(security_master, eligible) if security_master else {}
    isin_symbols: dict[str, list[str]] = {}
    for symbol, isin in symbol_isins.items():
        isin_symbols.setdefault(isin, []).append(symbol)
    grouped: dict[str, list[dict]] = {symbol: [] for symbol in eligible}
    for path in index_paths:
        for filing in normalize_financial_result_index(path):
            source_symbol = filing["symbol"]
            if source_symbol in grouped:
                target_symbol = source_symbol
                match_method = "SYMBOL"
            else:
                matches = isin_symbols.get(filing.get("isin") or "", [])
                if len(matches) != 1:
                    continue
                target_symbol = matches[0]
                match_method = "ISIN"
            if target_symbol not in grouped:
                continue
            if _dt(filing["available_at"]) > point or _dt(filing["period_end"]) > point:
                continue
            grouped[target_symbol].append({**filing, "symbol": target_symbol,
                                           "source_symbol": source_symbol,
                                           "match_method": match_method})

    selected = []
    metadata_without_xbrl = []
    no_filing = []
    for symbol in sorted(eligible):
        candidates = grouped[symbol]
        usable = [filing for filing in candidates if filing.get("xbrl_url")]
        if usable:
            selected.append(max(usable, key=_filing_rank))
        elif candidates:
            metadata_without_xbrl.append(symbol)
        else:
            no_filing.append(symbol)
    counts = {
        "eligible_symbols": len(eligible),
        "selected_xbrl": len(selected),
        "metadata_without_xbrl": len(metadata_without_xbrl),
        "no_point_in_time_filing": len(no_filing),
    }
    return {
        "as_of": point.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "counts": counts,
        "coverage": len(selected) / len(eligible) if eligible else 0.0,
        "selected": selected,
        "metadata_without_xbrl": metadata_without_xbrl,
        "no_point_in_time_filing": no_filing,
        "ready": len(selected) == len(eligible) and bool(eligible),
    }


def write_download_manifest(plan: dict, output: str | Path, *, limit: int) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError("download manifest limit must be between 1 and 100")
    selected = plan.get("selected", [])
    batch = selected[:limit]
    documents = []
    seen = set()
    for filing in batch:
        if filing["xbrl_url"] in seen:
            continue
        seen.add(filing["xbrl_url"])
        documents.append({key: filing[key] for key in
                          ("symbol", "period_end", "available_at", "xbrl_url")})
    payload = {"as_of": plan.get("as_of"), "documents": documents}
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"selected": len(documents), "remaining": max(0, len(selected) - limit),
            "output": str(destination)}


def write_download_manifest_batches(
    plan: dict,
    output_dir: str | Path,
    *,
    batch_size: int = 100,
) -> dict:
    if not 1 <= batch_size <= 100:
        raise ValueError("batch size must be between 1 and 100")
    documents = []
    seen = set()
    for filing in plan.get("selected", []):
        url = filing["xbrl_url"]
        if url in seen:
            continue
        seen.add(url)
        documents.append({key: filing[key] for key in
                          ("symbol", "period_end", "available_at", "xbrl_url")})

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    batch_index = []
    for offset in range(0, len(documents), batch_size):
        number = offset // batch_size + 1
        filename = f"xbrl-batch-{number:03d}.json"
        payload = {"as_of": plan.get("as_of"), "documents": documents[offset:offset + batch_size]}
        content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        (root / filename).write_bytes(content)
        batch_index.append({
            "batch": number,
            "filename": filename,
            "count": len(payload["documents"]),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    result = {"documents": len(documents), "batches": len(batch_index),
              "batch_size": batch_size, "batch_index": batch_index}
    (root / "batch-index.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def execute_download_manifest(
    manifest_path: str | Path,
    output_path: str | Path,
    *,
    acquirer: XbrlAcquirer | None = None,
    delay_seconds: float = 2.0,
) -> dict:
    if delay_seconds < 0:
        raise ValueError("delay cannot be negative")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    documents = manifest.get("documents", [])
    if not isinstance(documents, list) or len(documents) > 100:
        raise ValueError("manifest must contain at most 100 documents")
    output_path = Path(output_path)
    acquirer = acquirer or XbrlAcquirer(output_path.parent)
    facts = []
    failures = []
    for position, document in enumerate(documents):
        required = {"symbol", "period_end", "available_at", "xbrl_url"}
        if not isinstance(document, dict) or required - set(document):
            failures.append({"document": document, "error": "invalid manifest document"})
            continue
        if position:
            time.sleep(delay_seconds)
        try:
            retained = acquirer.acquire(document["xbrl_url"])
            facts.append(parse_halal_financial_facts(
                retained.path, symbol=document["symbol"],
                period_end=document["period_end"], available_at=document["available_at"],
            ))
        except Exception as exc:
            failures.append({"symbol": document["symbol"], "url": document["xbrl_url"],
                             "error": str(exc)})
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    debt = sum(row["debt_to_assets"] is not None for row in facts)
    interest = sum(row["interest_income_ratio"] is not None for row in facts)
    complete = sum(row["debt_to_assets"] is not None and row["interest_income_ratio"] is not None
                   for row in facts)
    missing_debt = [row["symbol"] for row in facts if row["debt_to_assets"] is None]
    missing_interest = [row["symbol"] for row in facts if row["interest_income_ratio"] is None]
    return {
        "requested": len(documents), "downloaded": len(facts), "failures": failures,
        "concept_coverage": {"debt_to_assets": debt, "interest_income_ratio": interest},
        "halal_complete": complete,
        "missing_concepts": {"debt_to_assets": missing_debt,
                             "interest_income_ratio": missing_interest},
        "output": str(output_path),
    }


def summarize_fact_files(paths: list[str | Path]) -> dict:
    rows = []
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"{path}: fact file must contain a list")
        rows.extend(payload)
    candidates = Counter()
    for row in rows:
        candidates.update(row.get("payload", {}).get("interest_income_candidates", {}).keys())
    return {
        "rows": len(rows),
        "debt_to_assets": sum(row.get("debt_to_assets") is not None for row in rows),
        "direct_interest_income_ratio": sum(
            row.get("interest_income_ratio") is not None for row in rows
        ),
        "annual_revenue": sum(
            row.get("payload", {}).get("total_revenue") not in (None, 0) for row in rows
        ),
        "halal_complete": sum(
            row.get("debt_to_assets") is not None
            and row.get("interest_income_ratio") is not None
            for row in rows
        ),
        "candidate_concepts": dict(sorted(candidates.items())),
    }


def _eligible_symbols(memberships: list[dict], point: datetime) -> set[str]:
    revisions: dict[tuple[str, str], dict] = {}
    for row in memberships:
        if _dt(row["available_at"]) > point:
            continue
        key = (row["symbol"], row["valid_from"])
        if key not in revisions or _dt(row["available_at"]) > _dt(revisions[key]["available_at"]):
            revisions[key] = row
    return {
        row["symbol"] for row in revisions.values()
        if _dt(row["valid_from"]) <= point
        and (not row.get("valid_to") or _dt(row["valid_to"]) > point)
    }


def _security_isins(path: str | Path, eligible: set[str]) -> dict[str, str]:
    output = {}
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            symbol = (row.get("TckrSymb") or row.get("SYMBOL") or "").strip().upper()
            isin = (row.get("ISIN") or "").strip().upper()
            if symbol in eligible and isin:
                output[symbol] = isin
    return output


def _filing_rank(filing: dict) -> tuple:
    consolidated = filing.get("consolidated", "").strip().lower()
    audited = filing.get("audited", "").strip().lower()
    is_consolidated = consolidated == "consolidated" or (
        "consolidated" in consolidated and "non" not in consolidated
    )
    is_audited = "audited" in audited and "un-audited" not in audited and "unaudited" not in audited
    return (_dt(filing["period_end"]), is_consolidated, is_audited, _dt(filing["available_at"]))


def _dt(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    if len(text) == 10:
        text += "T00:00:00+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan point-in-time NSE filing coverage")
    parser.add_argument("bundle")
    parser.add_argument("--index", action="append", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--security-master")
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    plan = plan_filing_coverage(
        args.bundle, args.index, as_of=args.as_of, security_master=args.security_master
    )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {"plan": str(destination), **plan["counts"], "coverage": plan["coverage"]}
    if args.manifest:
        result["manifest"] = write_download_manifest(plan, args.manifest, limit=args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
