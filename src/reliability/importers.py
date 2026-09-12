"""Provider-neutral imports for frozen point-in-time reliability bundles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.halal_screen import GREEN, RED, YELLOW, classify
from src.reliability.shariah_policy import route_business_screen
from src.reliability.nse_normalizers import normalize_bhavcopy
from src.reliability.store import ReliabilityStore


_TIER_NAME = {GREEN: "GREEN", YELLOW: "YELLOW", RED: "RED"}


def import_bhavcopy_history(
    store: ReliabilityStore,
    paths: list[str | Path],
) -> dict[str, Any]:
    total = 0
    sessions = []
    for value in sorted(map(Path, paths)):
        rows = normalize_bhavcopy(value, available_at="2100-01-01T00:00:00Z")
        for row in rows:
            row["available_at"] = f"{row['session_date']}T18:00:00Z"
            sessions.append(row["session_date"])
        if not rows:
            continue
        content = value.read_bytes()
        manifest = store.register_manifest(
            "nse-historical-bhavcopy",
            content,
            available_at=max(row["available_at"] for row in rows),
            metadata={"filename": value.name},
        )
        store.put_bars(rows, manifest)
        total += len(rows)
    return {
        "files": len(paths),
        "bars": total,
        "first_session": min(sessions) if sessions else None,
        "last_session": max(sessions) if sessions else None,
    }


def _available(record: dict[str, Any], bundle: dict[str, Any]) -> str:
    return record.get("available_at") or bundle["available_at"]


def import_bundle(
    store: ReliabilityStore,
    path: str | Path,
    *,
    ruleset_version: str = "aaoifi-v1",
) -> dict[str, Any]:
    """Import one normalized JSON bundle and derive classifications from fundamentals."""
    source_path = Path(path)
    raw = source_path.read_bytes()
    bundle = json.loads(raw)
    if not bundle.get("source") or not bundle.get("available_at"):
        raise ValueError("bundle requires source and available_at")
    manifest_hash = store.register_manifest(
        bundle["source"],
        raw,
        available_at=bundle["available_at"],
        metadata={"filename": source_path.name, **bundle.get("metadata", {})},
    )

    for record in bundle.get("memberships", []):
        store.put_membership(
            record["symbol"], record["valid_from"], _available(record, bundle), manifest_hash,
            valid_to=record.get("valid_to"),
        )
    for record in bundle.get("bars", []):
        store.put_bar(
            record["symbol"], record["session_date"], record["open"], record["high"],
            record["low"], record["close"], record["volume"], _available(record, bundle),
            manifest_hash,
        )
    for record in bundle.get("corporate_actions", []):
        store.put_corporate_action(
            record["symbol"], record["action_type"], record["ex_date"],
            record.get("payload", {}), _available(record, bundle), manifest_hash,
        )
    for record in bundle.get("business_classifications", []):
        store.put_business_classification(
            record["symbol"],
            business_type=record["business_type"],
            effective_from=record["effective_from"],
            methodology_version=record["methodology_version"],
            available_at=_available(record, bundle),
            manifest_hash=manifest_hash,
            reason=record["reason"],
        )
    for record in bundle.get("fundamentals", []):
        available_at = _available(record, bundle)
        debt = record.get("debt_to_assets")
        interest = record.get("interest_income_ratio")
        store.put_fundamental(
            record["symbol"], record["period_end"], available_at, manifest_hash,
            debt_to_assets=debt, interest_income_ratio=interest, payload=record.get("payload"),
        )
        business_record = store.business_as_of(record["symbol"], available_at)
        business = route_business_screen(business_record.get("business_type"))
        if business["route"] == "EXCLUDED_RIBA_BUSINESS":
            tier, tradeable = "RED", False
            reasons = ["excluded: conventional riba-based primary business"]
        elif business["route"] == "SPECIALIST_REVIEW":
            tier, tradeable = "UNKNOWN", False
            reasons = ["insurer requires qualified specialist Shariah business review"]
        elif business["route"] == "UNKNOWN_BUSINESS":
            tier, tradeable = "UNKNOWN", False
            reasons = ["required point-in-time business classification is missing"]
        elif debt is None or interest is None:
            tier, tradeable = "UNKNOWN", False
            reasons = ["required point-in-time fundamental ratio is missing"]
        else:
            verdict = classify(
                debt, interest,
                is_vice=bool(record.get("is_vice", False)),
                is_riba_financial=bool(record.get("is_riba_financial", False)),
            )
            tier = _TIER_NAME[verdict["tier"]]
            tradeable = bool(verdict["tradeable"])
            reasons = verdict["reasons"]
        store.put_halal_classification(
            record["symbol"],
            effective_from=record.get("effective_from", available_at),
            tier=tier,
            tradeable=tradeable,
            ruleset_version=ruleset_version,
            available_at=available_at,
            manifest_hash=manifest_hash,
            reason="; ".join(reasons),
        )

    return {
        "manifest_hash": manifest_hash,
        "counts": {
            "memberships": len(bundle.get("memberships", [])),
            "bars": len(bundle.get("bars", [])),
            "corporate_actions": len(bundle.get("corporate_actions", [])),
            "business_classifications": len(bundle.get("business_classifications", [])),
            "fundamentals": len(bundle.get("fundamentals", [])),
            "halal_classifications": len(bundle.get("fundamentals", [])),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a normalized reliability data bundle")
    parser.add_argument("bundle", help="Path to normalized JSON bundle")
    parser.add_argument("--db", default="results/reliability.db")
    parser.add_argument("--ruleset-version", default="aaoifi-v1")
    args = parser.parse_args()
    with ReliabilityStore(args.db) as store:
        result = import_bundle(store, args.bundle, ruleset_version=args.ruleset_version)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
