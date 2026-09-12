"""Build and assess normalized point-in-time bundles from retained NSE files."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.reliability.nse_normalizers import (
    normalize_bhavcopy,
    normalize_bhavcopy_exclusions,
    normalize_business_classifications,
    normalize_corporate_actions,
    normalize_financials,
    normalize_membership_snapshots,
)


def _dt(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        text = value.replace("Z", "+00:00")
        if len(text) == 10:
            text += "T00:00:00+00:00"
        parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: str | date | datetime) -> str:
    return _dt(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _source_record(path: str | Path, kind: str) -> dict[str, str]:
    source = Path(path)
    return {
        "kind": kind,
        "filename": source.name,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }


def build_nse_bundle(
    *,
    security_snapshots: list[dict[str, Any]],
    bhavcopies: list[dict[str, Any]],
    corporate_actions: list[dict[str, Any]],
    financials: list[str | Path],
    business_classifications: list[str | Path],
    output: str | Path | None = None,
) -> dict[str, Any]:
    if not security_snapshots:
        raise ValueError("at least one security snapshot is required")
    timestamps = [item["available_at"] for item in security_snapshots]
    timestamps += [item["available_at"] for item in bhavcopies]
    timestamps += [item["available_at"] for item in corporate_actions]
    source_files = [
        _source_record(item["path"], "security_snapshot") for item in security_snapshots
    ]
    source_files += [_source_record(item["path"], "bhavcopy") for item in bhavcopies]
    source_files += [
        _source_record(item["path"], "corporate_actions") for item in corporate_actions
    ]
    source_files += [_source_record(path, "financials") for path in financials]
    source_files += [
        _source_record(path, "business_classifications") for path in business_classifications
    ]

    bars = []
    excluded_bar_series = []
    for item in bhavcopies:
        bars.extend(normalize_bhavcopy(item["path"], available_at=item["available_at"]))
        excluded_bar_series.extend(normalize_bhavcopy_exclusions(item["path"]))
    actions = []
    for item in corporate_actions:
        actions.extend(normalize_corporate_actions(item["path"], available_at=item["available_at"]))
    fundamental_rows = []
    for path in financials:
        rows = normalize_financials(path)
        fundamental_rows.extend(rows)
        timestamps.extend(row["available_at"] for row in rows)
    business_rows = []
    for path in business_classifications:
        rows = normalize_business_classifications(path)
        business_rows.extend(rows)
        timestamps.extend(row["available_at"] for row in rows)

    bundle = {
        "source": "nse-primary-source-bundle",
        "available_at": _iso(max(_dt(value) for value in timestamps)),
        "metadata": {
            "source_files": source_files,
            "membership_snapshot_count": len(security_snapshots),
            "excluded_bar_series": excluded_bar_series,
        },
        "memberships": normalize_membership_snapshots(security_snapshots),
        "bars": bars,
        "corporate_actions": actions,
        "business_classifications": business_rows,
        "fundamentals": fundamental_rows,
    }
    if output is not None:
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    return bundle


def assess_bundle(
    bundle: dict[str, Any],
    *,
    as_of: str | date | datetime,
    max_price_age_days: int = 7,
    max_fundamental_age_days: int = 200,
) -> dict[str, Any]:
    point = _dt(as_of)
    revisions: dict[tuple[str, str], dict[str, Any]] = {}
    for row in bundle.get("memberships", []):
        if _dt(row["available_at"]) > point:
            continue
        key = (row["symbol"], row["valid_from"])
        if key not in revisions or _dt(row["available_at"]) > _dt(revisions[key]["available_at"]):
            revisions[key] = row
    current = sorted({
        row["symbol"] for row in revisions.values()
        if _dt(row["valid_from"]) <= point
        and (not row.get("valid_to") or _dt(row["valid_to"]) > point)
    })

    latest_bars: dict[str, dict[str, Any]] = {}
    for row in bundle.get("bars", []):
        if _dt(row["session_date"]) > point or _dt(row["available_at"]) > point:
            continue
        symbol = row["symbol"]
        if symbol not in latest_bars or _dt(row["session_date"]) > _dt(latest_bars[symbol]["session_date"]):
            latest_bars[symbol] = row
    latest_fundamentals: dict[str, dict[str, Any]] = {}
    for row in bundle.get("fundamentals", []):
        if _dt(row["effective_from"]) > point or _dt(row["available_at"]) > point:
            continue
        symbol = row["symbol"]
        if symbol not in latest_fundamentals or _dt(row["available_at"]) > _dt(latest_fundamentals[symbol]["available_at"]):
            latest_fundamentals[symbol] = row
    latest_business: dict[str, dict[str, Any]] = {}
    for row in bundle.get("business_classifications", []):
        if _dt(row["effective_from"]) > point or _dt(row["available_at"]) > point:
            continue
        symbol = row["symbol"]
        if symbol not in latest_business or _dt(row["available_at"]) > _dt(latest_business[symbol]["available_at"]):
            latest_business[symbol] = row

    missing_prices = []
    missing_fundamentals = []
    missing_business = []
    for symbol in current:
        bar = latest_bars.get(symbol)
        if bar is None or (point - _dt(bar["session_date"])).days > max_price_age_days:
            missing_prices.append(symbol)
        fundamental = latest_fundamentals.get(symbol)
        if (
            fundamental is None
            or (point - _dt(fundamental["available_at"])).days > max_fundamental_age_days
            or fundamental.get("debt_to_assets") is None
            or fundamental.get("interest_income_ratio") is None
        ):
            missing_fundamentals.append(symbol)
        business = latest_business.get(symbol)
        if business is None or business.get("business_type") in (None, "", "UNKNOWN"):
            missing_business.append(symbol)
    blockers = []
    if not current:
        blockers.append("UNIVERSE_EMPTY")
    if missing_prices:
        blockers.append("PRICE_COVERAGE")
    if missing_fundamentals:
        blockers.append("FUNDAMENTAL_COVERAGE")
    if missing_business:
        blockers.append("BUSINESS_COVERAGE")
    excluded_series: dict[str, str] = {}
    for row in bundle.get("metadata", {}).get("excluded_bar_series", []):
        if _dt(row["session_date"]) <= point:
            excluded_series[row["symbol"]] = row["series"]
    price_gap_reasons = {
        symbol: (
            f"ALTERNATE_SERIES_{excluded_series[symbol]}"
            if symbol in excluded_series else "NO_RETAINED_BAR"
        )
        for symbol in missing_prices
    }
    denominator = len(current)
    return {
        "ready": not blockers,
        "blockers": blockers,
        "current_members": denominator,
        "price_coverage": (denominator - len(missing_prices)) / denominator if denominator else 0.0,
        "fundamental_coverage": (
            (denominator - len(missing_fundamentals)) / denominator if denominator else 0.0
        ),
        "business_coverage": (
            (denominator - len(missing_business)) / denominator if denominator else 0.0
        ),
        "missing_prices": missing_prices,
        "price_gap_reasons": price_gap_reasons,
        "missing_fundamentals": missing_fundamentals,
        "missing_business_classifications": missing_business,
    }
