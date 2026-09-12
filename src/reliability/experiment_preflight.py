"""Value-blind, fail-closed dataset readiness verification."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from src.reliability import nifty_tri
from src.reliability.corporate_action_reviews import load_reviewed_factor_overrides
from src.reliability.preregistration import canonical_json_bytes, sha256_json, validate_protocol
from src.reliability.store import ReliabilityStore, _iso


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UTC_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_VALIDATION_TIME = "2026-01-01T00:00:00Z"
_MIN_SESSION_RATIO = 0.75
_CORPORATE_ACTION_REVIEW_EXPERIMENTS = {
    "nse-halal-residual-momentum-v4",
    "nse-halal-residual-momentum-v5",
    "nse-halal-residual-momentum-v6",
    "nse-halal-residual-momentum-v7",
}
_CORPORATE_ACTION_REVIEW_BINDING_VERSION = "corporate-action-review-binding-v1"
_SOURCE_IDENTITIES = {
    "calendar": {"NSE"},
    "constituents": {"NSE"},
    "bars": {"NSE"},
    "corporate_actions": {"NSE"},
    "sectors_industry": {"NSE"},
    "suspensions": {"NSE"},
    "delistings": {"NSE"},
    "fundamentals": {"NSE"},
    "halal_evidence": {"NSE"},
    "tri": {"NIFTY INDICES"},
}
_REQUIRED_REVIEWS = {"business_reviews", "concept_reviews", "pdf_reviews", "delistings"}
_REVIEW_IDENTITIES = {"INTERNAL REVIEW"}
_STORE_SOURCE_DOMAINS = {
    "bars": "bars",
    "constituents": "constituents",
    "corporate_actions": "corporate_actions",
    "delistings": "delistings",
    "fundamentals": "fundamentals",
    "halal": "halal_evidence",
    "sectors_industry": "sectors_industry",
    "suspensions": "suspensions",
}
_ZERO_ROW_STORE_DOMAINS = {
    "corporate_actions",
    "delistings",
    "suspensions",
}
_MEMBER_SESSION_SOURCE_DOMAINS = {
    "bars": "bars",
    "constituents": "constituents",
    "fundamentals": "fundamentals",
    "halal_evidence": "halal",
    "sectors_industry": "sectors_industry",
}
_EVENT_SOURCE_DOMAINS = {
    "corporate_actions": (
        "corporate_actions",
        ("symbol", "action_type", "ex_date", "available_at"),
    ),
    "delistings": (
        "delistings",
        ("symbol", "effective_from", "available_at"),
    ),
    "suspensions": (
        "suspensions",
        ("symbol", "effective_from", "available_at"),
    ),
}
_TASK_6_TYPED_SCHEMAS = {
    "memberships": {
        "symbol": "TEXT",
        "valid_from": "TEXT",
        "valid_to": "TEXT",
        "available_at": "TEXT",
        "manifest_hash": "TEXT",
    },
    "bars": {
        "symbol": "TEXT",
        "session_date": "TEXT",
        "open": "REAL",
        "high": "REAL",
        "low": "REAL",
        "close": "REAL",
        "volume": "REAL",
        "available_at": "TEXT",
        "manifest_hash": "TEXT",
    },
    "corporate_actions": {
        "symbol": "TEXT",
        "action_type": "TEXT",
        "ex_date": "TEXT",
        "payload_json": "TEXT",
        "available_at": "TEXT",
        "manifest_hash": "TEXT",
    },
    "fundamentals": {
        "symbol": "TEXT",
        "period_end": "TEXT",
        "debt_to_assets": "REAL",
        "interest_income_ratio": "REAL",
        "payload_json": "TEXT",
        "available_at": "TEXT",
        "manifest_hash": "TEXT",
    },
    "halal_classifications": {
        "symbol": "TEXT",
        "effective_from": "TEXT",
        "tier": "TEXT",
        "tradeable": "INTEGER",
        "ruleset_version": "TEXT",
        "reason": "TEXT",
        "available_at": "TEXT",
        "manifest_hash": "TEXT",
    },
    "manifests": {
        "content_hash": "TEXT",
        "source": "TEXT",
        "available_at": "TEXT",
        "metadata_json": "TEXT",
    },
}
_TASK_6_EVENT_SCHEMA = {
    "symbol": "TEXT",
    "available_at": "TEXT",
    "manifest_hash": "TEXT",
}
_TASK_6_SECTOR_SCHEMA = {
    "symbol": "TEXT",
    "sector": "TEXT",
    "available_at": "TEXT",
    "manifest_hash": "TEXT",
}
_TASK_6_SECTOR_TABLES = (
    "sector_classifications",
    "sectors_industry",
    "sectors",
)
_TASK_6_EFFECTIVE_COLUMNS = ("effective_from", "session_date")


class _FrozenDict(dict):
    """A JSON-compatible mapping that cannot be modified after construction."""

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("preflight aggregates are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class PreflightResult:
    passed: bool
    blockers: tuple[str, ...]
    aggregates: dict
    dataset_manifest_sha256: str | None
    manifest_payload: dict | None = None


@dataclass(frozen=True)
class _Source:
    record: dict
    artifact: Path


@dataclass(frozen=True)
class Task6Lookup:
    table: str
    value_column: str | None
    effective_column: str


@dataclass(frozen=True)
class Task6LookupSchema:
    sector: Task6Lookup
    suspensions: Task6Lookup
    delistings: Task6Lookup


def _declared_table_schema(
    store: ReliabilityStore,
    table: str,
) -> dict[str, str]:
    return {
        row["name"]: str(row["type"]).upper()
        for row in store.connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def _resolve_typed_lookup(
    table: str,
    schema: dict[str, str],
    required: dict[str, str],
    *,
    value_column: str | None,
) -> Task6Lookup:
    if not schema or any(
        schema.get(column) != declared_type
        for column, declared_type in required.items()
    ):
        raise ValueError(f"invalid typed lookup schema for {table}")
    effective_columns = [
        column
        for column in _TASK_6_EFFECTIVE_COLUMNS
        if column in schema
    ]
    if len(effective_columns) != 1:
        raise ValueError(f"ambiguous effective date schema for {table}")
    effective = effective_columns[0]
    if schema[effective] != "TEXT":
        raise ValueError(f"invalid effective date type for {table}")
    return Task6Lookup(
        table=table,
        value_column=value_column,
        effective_column=effective,
    )


def resolve_task6_lookup_schema(
    store: ReliabilityStore,
) -> Task6LookupSchema:
    """Resolve the only typed sector and event lookup contract Task 6 may use."""
    sector_schemas = {
        table: _declared_table_schema(store, table)
        for table in _TASK_6_SECTOR_TABLES
    }
    sector_tables = [
        table for table, schema in sector_schemas.items() if schema
    ]
    if len(sector_tables) != 1:
        raise ValueError("ambiguous sector lookup tables")
    sector_table = sector_tables[0]
    sector = _resolve_typed_lookup(
        sector_table,
        sector_schemas[sector_table],
        _TASK_6_SECTOR_SCHEMA,
        value_column="sector",
    )
    events = {
        table: _resolve_typed_lookup(
            table,
            _declared_table_schema(store, table),
            _TASK_6_EVENT_SCHEMA,
            value_column=None,
        )
        for table in ("suspensions", "delistings")
    }
    return Task6LookupSchema(
        sector=sector,
        suspensions=events["suspensions"],
        delistings=events["delistings"],
    )


def run_preflight(
    store: ReliabilityStore,
    protocol: dict,
    *,
    source_catalogues: list[Path],
    review_reports: list[Path],
    corporate_action_audit_path: Path | None = None,
    corporate_action_audit_sha256: str | None = None,
    corporate_action_packet_dir: Path | None = None,
    corporate_action_policy_path: Path | None = None,
    corporate_action_baseline_path: Path | None = None,
) -> PreflightResult:
    """Return aggregate-only eligibility using retained, hash-bound evidence."""
    blockers: set[str] = set()
    try:
        validate_protocol(protocol, now=_VALIDATION_TIME)
        protocol_hash = sha256_json(protocol)
        start = protocol["periods"]["warmup"][0]
        end = protocol["periods"]["scored"][1]
    except (KeyError, TypeError, ValueError):
        return _result(False, {"PROTOCOL"}, {}, None, None)

    sources, catalogue_records = _sources(
        source_catalogues, start, end, blockers
    )
    sessions, closures, weekday_count = _calendar_sessions(
        sources.get("calendar"), start, end, blockers
    )
    _source_coverage(sources, len(sessions), blockers)
    _validate_tri(sources.get("tri"), sessions, blockers)

    try:
        coverage, referenced_store_hashes = _store_coverage(store, sessions)
        store_manifest_hashes = _bind_store_manifest_sources(
            store, referenced_store_hashes, sources
        )
    except ValueError:
        blockers.add("STORE_MANIFESTS")
        coverage = {
            domain: _coverage(len(sessions), 0)
            for domain in (
                "bars",
                "constituents",
                "fundamentals",
                "halal",
                "sectors_industry",
            )
        }
        store_manifest_hashes = {}
    try:
        _reconcile_source_store_rows(
            store,
            protocol,
            sources,
            sessions,
        )
    except ValueError:
        blockers.add("SOURCE_STORE_ROWS")
    for domain in (
        "constituents",
        "bars",
        "fundamentals",
        "halal",
        "sectors_industry",
    ):
        if coverage[domain]["ratio"] != 1.0:
            blockers.add(domain.upper())
    for domain in (
        "calendar",
        "corporate_actions",
        "suspensions",
        "delistings",
    ):
        coverage[domain] = _source_aggregate(sources.get(domain), len(sessions))
        if coverage[domain]["ratio"] != 1.0:
            blockers.add(domain.upper())

    reviews, review_records = _reviews(
        review_reports, sources, start, end, len(sessions), blockers
    )
    corporate_action_review = None
    if protocol["experiment_id"] in _CORPORATE_ACTION_REVIEW_EXPERIMENTS:
        try:
            corporate_action_review = _corporate_action_review(
                audit_path=corporate_action_audit_path,
                audit_sha256=corporate_action_audit_sha256,
                packet_dir=corporate_action_packet_dir,
                policy_path=corporate_action_policy_path,
                baseline_path=corporate_action_baseline_path,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            blockers.add("CORPORATE_ACTION_REVIEW")
    catalogue_hashes = [
        record["sha256"] for record in catalogue_records
    ]
    review_hashes = [record["sha256"] for record in review_records]
    aggregates = {
        "date_bounds": {"start": start, "end": end},
        "calendar": {
            "weekdays": weekday_count,
            "sessions": len(sessions),
            "closures": len(closures),
        },
        "coverage": {key: coverage[key] for key in sorted(coverage)},
        "hashes": {
            "protocol": protocol_hash,
            "retained": tuple(sorted({source.record["sha256"] for source in sources.values()} | set(catalogue_hashes))),
            "reviews": tuple(sorted(review_hashes)),
        },
    }
    if protocol["experiment_id"] in _CORPORATE_ACTION_REVIEW_EXPERIMENTS:
        aggregates["hashes"]["corporate_action_review"] = (
            sha256_json(corporate_action_review)
            if corporate_action_review is not None else None
        )
    manifest_payload = None
    manifest = None
    if not blockers:
        manifest_payload = {
            "schema_version": 2,
            "protocol_sha256": protocol_hash,
            "sources": [sources[key].record for key in sorted(sources)],
            "source_hashes": sorted(
                source.record["sha256"] for source in sources.values()
            ),
            "catalogues": catalogue_records,
            "catalogue_hashes": sorted(catalogue_hashes),
            "reviews": review_records,
            "review_hashes": sorted(review_hashes),
            "store_manifest_hashes": store_manifest_hashes,
            "sessions": [session.isoformat() for session in sessions],
            "closures": [closure.isoformat() for closure in closures],
            "aggregate_coverage": aggregates["coverage"],
            "calendar": aggregates["calendar"],
        }
        if protocol["experiment_id"] in _CORPORATE_ACTION_REVIEW_EXPERIMENTS:
            manifest_payload["corporate_action_review"] = corporate_action_review
        manifest = sha256_json(manifest_payload)
    return _result(
        not blockers, blockers, aggregates, manifest, manifest_payload
    )


def _corporate_action_review(
    *,
    audit_path: Path | None,
    audit_sha256: str | None,
    packet_dir: Path | None,
    policy_path: Path | None,
    baseline_path: Path | None,
) -> dict[str, str]:
    if any(value is None for value in (
        audit_path, audit_sha256, packet_dir, policy_path, baseline_path,
    )):
        raise ValueError("corporate-action review inputs are required")
    audit_path = Path(audit_path).resolve(strict=True)
    packet_dir = Path(packet_dir).resolve(strict=True)
    policy_path = Path(policy_path).resolve(strict=True)
    baseline_path = Path(baseline_path).resolve(strict=True)
    content = audit_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != audit_sha256:
        raise ValueError("corporate-action audit hash drifted")
    report = json.loads(content)
    if (
        not isinstance(report, dict)
        or report.get("period") != {"start": "2019-01-01", "end": "2024-06-30"}
        or report.get("counts", {}).get("expected_months") != 66
        or report.get("counts", {}).get("covered_months") != 66
    ):
        raise ValueError("corporate-action audit coverage is invalid")
    overrides = load_reviewed_factor_overrides(
        audit_path,
        expected_sha256=audit_sha256,
        packet_dir=packet_dir,
        policy_path=policy_path,
        baseline_report_path=baseline_path,
    )
    verified = overrides.artifact_binding
    return {
        "schema_version": _CORPORATE_ACTION_REVIEW_BINDING_VERSION,
        "audit_path": str(audit_path),
        "audit_sha256": audit_sha256,
        "packet_dir": str(packet_dir),
        "packet_manifest_path": verified["packet_manifest_path"],
        "packet_manifest_sha256": verified["packet_manifest_sha256"],
        "policy_path": str(policy_path),
        "reviewer_policy_sha256": verified["reviewer_policy_sha256"],
        "baseline_path": str(baseline_path),
        "baseline_report_sha256": verified["baseline_report_sha256"],
    }


def _result(
    passed: bool,
    blockers: set[str],
    aggregates: dict,
    manifest: str | None,
    manifest_payload: dict | None,
) -> PreflightResult:
    return PreflightResult(
        passed=passed,
        blockers=tuple(sorted(blockers)),
        aggregates=_freeze(aggregates),
        dataset_manifest_sha256=manifest if passed else None,
        manifest_payload=(
            _freeze(manifest_payload)
            if passed and manifest_payload is not None
            else None
        ),
    )


def verify_preflight_binding(
    store: ReliabilityStore,
    protocol: dict,
    preflight: PreflightResult,
) -> dict:
    """Recompute the canonical preflight-to-store provenance binding."""
    if (
        not isinstance(preflight, PreflightResult)
        or not preflight.passed
        or preflight.blockers
    ):
        raise ValueError("PREFLIGHT_FAILED")
    if (
        not isinstance(preflight.dataset_manifest_sha256, str)
        or _SHA256.fullmatch(preflight.dataset_manifest_sha256) is None
        or not isinstance(preflight.manifest_payload, dict)
    ):
        raise ValueError("PREFLIGHT_MANIFEST")

    payload = preflight.manifest_payload
    required = {
        "aggregate_coverage",
        "calendar",
        "catalogues",
        "catalogue_hashes",
        "closures",
        "protocol_sha256",
        "reviews",
        "review_hashes",
        "schema_version",
        "sessions",
        "source_hashes",
        "sources",
        "store_manifest_hashes",
    }
    if protocol.get("experiment_id") in _CORPORATE_ACTION_REVIEW_EXPERIMENTS:
        required.add("corporate_action_review")
    if set(payload) != required or payload.get("schema_version") != 2:
        raise ValueError("PREFLIGHT_MANIFEST")
    try:
        protocol_hash = sha256_json(protocol)
        manifest_hash = sha256_json(payload)
        start = protocol["periods"]["warmup"][0]
        end = protocol["periods"]["scored"][1]
    except (TypeError, ValueError) as exc:
        raise ValueError("PREFLIGHT_MANIFEST") from exc
    except KeyError as exc:
        raise ValueError("PREFLIGHT_PROTOCOL") from exc
    if payload.get("protocol_sha256") != protocol_hash:
        raise ValueError("PREFLIGHT_PROTOCOL")
    if manifest_hash != preflight.dataset_manifest_sha256:
        raise ValueError("PREFLIGHT_MANIFEST")

    if protocol.get("experiment_id") in _CORPORATE_ACTION_REVIEW_EXPERIMENTS:
        corporate_action_review = payload.get("corporate_action_review")
        if not isinstance(corporate_action_review, dict) or set(corporate_action_review) != {
            "schema_version",
            "audit_path",
            "audit_sha256",
            "packet_dir",
            "packet_manifest_path",
            "packet_manifest_sha256",
            "policy_path",
            "reviewer_policy_sha256",
            "baseline_path",
            "baseline_report_sha256",
        } or corporate_action_review.get(
            "schema_version"
        ) != _CORPORATE_ACTION_REVIEW_BINDING_VERSION:
            raise ValueError("CORPORATE_ACTION_REVIEW")
        try:
            actual_corporate_action_review = _corporate_action_review(
                audit_path=Path(corporate_action_review["audit_path"]),
                audit_sha256=corporate_action_review["audit_sha256"],
                packet_dir=Path(corporate_action_review["packet_dir"]),
                policy_path=Path(corporate_action_review["policy_path"]),
                baseline_path=Path(corporate_action_review["baseline_path"]),
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("CORPORATE_ACTION_REVIEW") from exc
        if actual_corporate_action_review != corporate_action_review:
            raise ValueError("CORPORATE_ACTION_REVIEW")

    aggregates = preflight.aggregates
    if not isinstance(aggregates, dict):
        raise ValueError("PREFLIGHT_AGGREGATES")
    hashes = aggregates.get("hashes")
    if not isinstance(hashes, dict) or hashes.get("protocol") != protocol_hash:
        raise ValueError("PREFLIGHT_PROTOCOL")
    if (
        protocol.get("experiment_id") in _CORPORATE_ACTION_REVIEW_EXPERIMENTS
        and hashes.get("corporate_action_review")
        != sha256_json(payload["corporate_action_review"])
    ):
        raise ValueError("CORPORATE_ACTION_REVIEW")
    if (
        payload.get("aggregate_coverage") != aggregates.get("coverage")
        or payload.get("calendar") != aggregates.get("calendar")
    ):
        raise ValueError("PREFLIGHT_AGGREGATES")

    claimed_catalogues = payload.get("catalogues")
    if not isinstance(claimed_catalogues, (list, tuple)) or not claimed_catalogues:
        raise ValueError("PREFLIGHT_CATALOGUES")
    catalogue_paths = []
    for record in claimed_catalogues:
        if (
            not isinstance(record, dict)
            or set(record) != {
                "available_at",
                "bounds",
                "domain",
                "path",
                "sha256",
                "source_domains",
            }
            or record.get("domain") != "source_catalogue"
            or not isinstance(record.get("path"), str)
            or not Path(record["path"]).is_absolute()
            or not isinstance(record.get("sha256"), str)
            or _SHA256.fullmatch(record["sha256"]) is None
            or not _canonical_utc(record.get("available_at"))
            or record.get("bounds") != {"start": start, "end": end}
        ):
            raise ValueError("PREFLIGHT_CATALOGUES")
        catalogue_paths.append(Path(record["path"]))
    catalogue_blockers: set[str] = set()
    actual_sources, actual_catalogues = _sources(
        catalogue_paths, start, end, catalogue_blockers
    )
    if (
        catalogue_blockers
        or sha256_json(actual_catalogues) != sha256_json(claimed_catalogues)
    ):
        raise ValueError("PREFLIGHT_CATALOGUES")

    sources = payload.get("sources")
    if not isinstance(sources, (list, tuple)):
        raise ValueError("PREFLIGHT_SOURCE_HASHES")
    source_records = {}
    for record in sources:
        if (
            not isinstance(record, dict)
            or record.get("domain") not in _SOURCE_IDENTITIES
            or not isinstance(record.get("sha256"), str)
            or _SHA256.fullmatch(record["sha256"]) is None
            or record["domain"] in source_records
        ):
            raise ValueError("PREFLIGHT_SOURCE_HASHES")
        source_records[record["domain"]] = record
    if set(source_records) != set(_SOURCE_IDENTITIES):
        raise ValueError("PREFLIGHT_SOURCE_HASHES")
    actual_source_records = {
        domain: source.record
        for domain, source in actual_sources.items()
    }
    if source_records != actual_source_records:
        raise ValueError("PREFLIGHT_SOURCE_HASHES")
    source_hashes = tuple(sorted(
        record["sha256"] for record in source_records.values()
    ))
    catalogue_hashes = tuple(sorted(
        record["sha256"] for record in actual_catalogues
    ))
    if (
        tuple(payload.get("source_hashes", ())) != source_hashes
        or tuple(payload.get("catalogue_hashes", ())) != catalogue_hashes
        or tuple(sorted(hashes.get("retained", ())))
        != tuple(sorted(set(source_hashes) | set(catalogue_hashes)))
    ):
        raise ValueError("PREFLIGHT_SOURCE_HASHES")

    raw_sessions = payload.get("sessions")
    try:
        sessions = tuple(date.fromisoformat(value) for value in raw_sessions)
    except (TypeError, ValueError) as exc:
        raise ValueError("PREFLIGHT_SESSIONS") from exc
    raw_closures = payload.get("closures")
    try:
        closures = tuple(date.fromisoformat(value) for value in raw_closures)
    except (TypeError, ValueError) as exc:
        raise ValueError("PREFLIGHT_SESSIONS") from exc
    if (
        not sessions
        or sessions != tuple(sorted(set(sessions)))
        or closures != tuple(sorted(set(closures)))
        or set(sessions) & set(closures)
        or len(sessions) != aggregates.get("calendar", {}).get("sessions")
        or len(closures) != aggregates.get("calendar", {}).get("closures")
    ):
        raise ValueError("PREFLIGHT_SESSIONS")
    calendar_blockers: set[str] = set()
    actual_sessions, actual_closures, weekday_count = _calendar_sessions(
        actual_sources.get("calendar"), start, end, calendar_blockers
    )
    if (
        calendar_blockers
        or sessions != actual_sessions
        or closures != actual_closures
        or payload.get("calendar") != {
            "weekdays": weekday_count,
            "sessions": len(actual_sessions),
            "closures": len(actual_closures),
        }
    ):
        raise ValueError("PREFLIGHT_SESSIONS")
    tri_blockers: set[str] = set()
    _validate_tri(
        actual_sources.get("tri"),
        actual_sessions,
        tri_blockers,
    )
    if tri_blockers:
        raise ValueError("PREFLIGHT_TRI")

    claimed_reviews = payload.get("reviews")
    if not isinstance(claimed_reviews, (list, tuple)) or not claimed_reviews:
        raise ValueError("PREFLIGHT_REVIEWS")
    review_paths = []
    for record in claimed_reviews:
        if (
            not isinstance(record, dict)
            or set(record) != {
                "available_at", "bounds", "kind", "path", "sha256"
            }
            or record.get("kind") not in _REQUIRED_REVIEWS
            or not isinstance(record.get("path"), str)
            or not Path(record["path"]).is_absolute()
            or not isinstance(record.get("sha256"), str)
            or _SHA256.fullmatch(record["sha256"]) is None
            or not _canonical_utc(record.get("available_at"))
            or record.get("bounds") != {"start": start, "end": end}
        ):
            raise ValueError("PREFLIGHT_REVIEWS")
        review_paths.append(Path(record["path"]))
    review_blockers: set[str] = set()
    _, actual_reviews = _reviews(
        review_paths,
        actual_sources,
        start,
        end,
        len(sessions),
        review_blockers,
    )
    if (
        review_blockers
        or sha256_json(actual_reviews) != sha256_json(claimed_reviews)
    ):
        raise ValueError("PREFLIGHT_REVIEWS")
    review_hashes = tuple(sorted(
        record["sha256"] for record in actual_reviews
    ))
    if (
        tuple(payload.get("review_hashes", ())) != review_hashes
        or tuple(sorted(hashes.get("reviews", ()))) != review_hashes
    ):
        raise ValueError("PREFLIGHT_REVIEWS")

    try:
        actual_coverage, referenced_store_hashes = _store_coverage(
            store, sessions
        )
        actual_store_hashes = _bind_store_manifest_sources(
            store, referenced_store_hashes, actual_sources
        )
        _reconcile_source_store_rows(
            store,
            protocol,
            actual_sources,
            sessions,
        )
    except ValueError as exc:
        if "source/store row evidence" in str(exc):
            raise ValueError("PREFLIGHT_SOURCE_STORE_ROWS") from exc
        raise ValueError("PREFLIGHT_STORE_MANIFESTS") from exc
    for domain in (
        "bars",
        "constituents",
        "fundamentals",
        "halal",
        "sectors_industry",
    ):
        if actual_coverage[domain] != aggregates.get("coverage", {}).get(domain):
            raise ValueError("PREFLIGHT_COVERAGE")

    claimed_store_hashes = payload.get("store_manifest_hashes")
    if claimed_store_hashes != actual_store_hashes:
        raise ValueError("PREFLIGHT_STORE_MANIFESTS")

    return _freeze({
        "dataset_manifest_sha256": preflight.dataset_manifest_sha256,
        "protocol_sha256": protocol_hash,
        "source_hashes": source_hashes,
        "catalogue_hashes": catalogue_hashes,
        "review_hashes": review_hashes,
        "store_manifest_hashes": actual_store_hashes,
        "sessions": tuple(session.isoformat() for session in sessions),
        "closures": tuple(closure.isoformat() for closure in closures),
    })


def _sources(
    catalogue_paths: list[Path], start: str, end: str, blockers: set[str]
) -> tuple[dict[str, _Source], list[dict]]:
    sources: dict[str, _Source] = {}
    catalogue_records: list[dict] = []
    for requested in catalogue_paths:
        catalogue = Path(requested).resolve()
        try:
            content = catalogue.read_bytes()
            lines = content.splitlines(keepends=True)
        except OSError:
            blockers.add("SOURCE_CATALOGUES")
            continue
        catalogue_domains = []
        catalogue_available_at = []
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                canonical = _canonical_mapping(record)
            except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                blockers.add("SOURCE_CATALOGUES")
                continue
            if canonical is None or line != canonical:
                blockers.add("SOURCE_CATALOGUES")
                continue
            domain = record.get("domain")
            if domain is None and _valid_tri_window_catalogue_record(record):
                continue
            if domain not in _SOURCE_IDENTITIES:
                blockers.add("SOURCE_CATALOGUES")
                continue
            source = _verified_source(record, catalogue.parent, start, end)
            if source is None or domain in sources:
                blockers.add(str(domain).upper())
                continue
            sources[domain] = source
            catalogue_domains.append(domain)
            catalogue_available_at.append(record["available_at"])
        if catalogue_domains and catalogue_available_at:
            catalogue_records.append({
                "available_at": max(catalogue_available_at),
                "bounds": {"start": start, "end": end},
                "domain": "source_catalogue",
                "path": str(catalogue),
                "sha256": hashlib.sha256(content).hexdigest(),
                "source_domains": tuple(sorted(catalogue_domains)),
            })
    for domain in _SOURCE_IDENTITIES:
        if domain not in sources:
            blockers.add(domain.upper())
    return sources, sorted(
        catalogue_records, key=lambda record: record["path"]
    )


def _verified_source(record: dict, root: Path, start: str, end: str) -> _Source | None:
    domain = record.get("domain")
    coverage = record.get("coverage")
    if (
        record.get("status") not in {"downloaded", "cached", "retained"}
        or record.get("source_id") not in _SOURCE_IDENTITIES[domain]
        or not _canonical_utc(
            record.get("available_at"),
            latest=None if domain == "tri" else start,
        )
        or not isinstance(coverage, dict)
        or coverage.get("start") != start
        or coverage.get("end") != end
        or not isinstance(coverage.get("expected_sessions"), int)
        or not isinstance(coverage.get("observed_sessions"), int)
        or coverage["expected_sessions"] < 0
        or coverage["observed_sessions"] < 0
        or not isinstance(record.get("sha256"), str)
        or _SHA256.fullmatch(record["sha256"]) is None
        or not isinstance(record.get("path"), str)
    ):
        return None
    retained_root = (root / "retained").resolve()
    artifact = (root / record["path"]).resolve()
    if artifact == retained_root or retained_root not in artifact.parents:
        return None
    try:
        if not artifact.is_file() or _file_sha256(artifact) != record["sha256"]:
            return None
    except OSError:
        return None
    return _Source(record=record, artifact=artifact)


def _valid_tri_window_catalogue_record(record: dict) -> bool:
    required = {
        "available_at",
        "content_type",
        "kind",
        "normalized_sha256",
        "path",
        "raw_bytes",
        "raw_response_path",
        "raw_sha256",
        "recorded_at",
        "request",
        "status",
        "status_code",
        "url",
        "window",
    }
    return (
        set(record) == required
        and record.get("kind") == "nifty_50_tri"
        and record.get("status") in {"downloaded", "cached"}
        and _canonical_utc(record.get("available_at"))
        and _canonical_utc(record.get("recorded_at"))
        and isinstance(record.get("path"), str)
        and isinstance(record.get("raw_response_path"), str)
        and isinstance(record.get("raw_bytes"), int)
        and record["raw_bytes"] > 0
        and isinstance(record.get("status_code"), int)
        and 200 <= record["status_code"] < 300
        and all(
            isinstance(record.get(field), str)
            and _SHA256.fullmatch(record[field]) is not None
            for field in ("normalized_sha256", "raw_sha256")
        )
        and isinstance(record.get("window"), dict)
        and set(record["window"]) == {"start", "end"}
    )


def _canonical_utc(value: object, *, latest: str | None = None) -> bool:
    if not isinstance(value, str) or _UTC_Z.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        if latest is not None:
            bound = datetime.combine(date.fromisoformat(latest), time.min, tzinfo=timezone.utc)
            return parsed <= bound
    except ValueError:
        return False
    return True


def _canonical_mapping(value: object) -> bytes | None:
    if not isinstance(value, dict):
        return None
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError):
        return None


def _calendar_sessions(
    source: _Source | None, start: str, end: str, blockers: set[str]
) -> tuple[tuple[date, ...], tuple[date, ...], int]:
    expected_weekdays = _weekdays(date.fromisoformat(start), date.fromisoformat(end))
    if source is None:
        return (), (), len(expected_weekdays)
    try:
        content = source.artifact.read_bytes()
        payload = json.loads(content)
        canonical = _canonical_mapping(payload)
        if canonical is None or content != canonical:
            raise ValueError("calendar must be canonical JSON object")
        if set(payload) != {"bounds", "closures", "schema_version", "sessions"}:
            raise ValueError("calendar schema mismatch")
        if payload.get("schema_version") != 1 or payload.get("bounds") != {"start": start, "end": end}:
            raise ValueError("calendar bounds mismatch")
        sessions = _parse_sorted_dates(payload.get("sessions"))
        closures = _parse_sorted_dates(payload.get("closures"))
    except (AttributeError, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        blockers.add("CALENDAR")
        return (), (), len(expected_weekdays)
    if sessions is None or closures is None:
        blockers.add("CALENDAR")
        return (), (), len(expected_weekdays)
    session_set, closure_set, weekday_set = set(sessions), set(closures), set(expected_weekdays)
    if (
        session_set & closure_set
        or not session_set <= weekday_set
        or not closure_set <= weekday_set
        or session_set | closure_set != weekday_set
        or len(sessions) / len(expected_weekdays) < _MIN_SESSION_RATIO
    ):
        blockers.add("CALENDAR")
    return tuple(sessions), tuple(closures), len(expected_weekdays)


def _parse_sorted_dates(value: object) -> list[date] | None:
    if not isinstance(value, list):
        return None
    parsed = []
    for item in value:
        try:
            parsed.append(date.fromisoformat(item))
        except (TypeError, ValueError):
            return None
    return parsed if parsed == sorted(set(parsed)) else None


def _weekdays(start: date, end: date) -> list[date]:
    output = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return output


def _source_coverage(sources: dict[str, _Source], sessions: int, blockers: set[str]) -> None:
    for domain, source in sources.items():
        coverage = source.record["coverage"]
        if coverage["expected_sessions"] != sessions or coverage["observed_sessions"] != sessions:
            blockers.add(domain.upper())


def _validate_tri(source: _Source | None, sessions: tuple[date, ...], blockers: set[str]) -> None:
    if source is None:
        return
    try:
        payload = json.loads(source.artifact.read_bytes())
        if not isinstance(payload, dict):
            raise ValueError("TRI payload must be an object")
        raw_rows = payload.get("normalized_rows")
        if not isinstance(raw_rows, list):
            raise ValueError("normalized rows required")
        rows = []
        for row in raw_rows:
            if not isinstance(row, dict) or not isinstance(row.get("session_date"), str):
                raise ValueError("TRI row schema mismatch")
            rows.append({"session_date": row["session_date"], "tri": 1.0})
        if {row["session_date"] for row in rows} != {item.isoformat() for item in sessions}:
            raise ValueError("calendar mismatch")
        nifty_tri.validate_tri_session_coverage(rows, sessions)
    except (
        AttributeError,
        KeyError,
        OSError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        nifty_tri.NiftyTriError,
    ):
        blockers.add("TRI")


def _store_coverage(
    store: ReliabilityStore,
    sessions: tuple[date, ...],
) -> tuple[dict[str, dict], dict[str, tuple[str, ...]]]:
    names = (
        "constituents",
        "bars",
        "fundamentals",
        "halal",
        "sectors_industry",
    )
    connection = store.connection
    lookup_schema = resolve_task6_lookup_schema(store)
    table_schemas = {
        table: _declared_table_schema(store, table)
        for table in _TASK_6_TYPED_SCHEMAS
    }
    if any(
        any(table_schemas.get(table, {}).get(column) != declared_type
            for column, declared_type in required.items())
        for table, required in _TASK_6_TYPED_SCHEMAS.items()
    ):
        raise ValueError("required typed table schema is unavailable")
    if not sessions:
        return (
            {name: _coverage(0, 0) for name in names},
            {name: () for name in _STORE_SOURCE_DOMAINS},
        )
    sector_table = lookup_schema.sector.table
    sector_value = lookup_schema.sector.value_column
    sector_effective = lookup_schema.sector.effective_column
    event_effective = {
        "suspensions": lookup_schema.suspensions.effective_column,
        "delistings": lookup_schema.delistings.effective_column,
    }

    placeholders = ", ".join("(?, ?)" for _ in sessions)
    parameters: list[str] = []
    for session in sessions:
        parameters.extend((
            f"{session.isoformat()}T00:00:00+00:00",
            f"{session.isoformat()}T23:59:59+00:00",
        ))
    base = f"""
        WITH retained_sessions(session_date, as_of) AS (VALUES {placeholders}),
        active_members AS (
            SELECT retained_sessions.session_date, retained_sessions.as_of, memberships.symbol
            FROM retained_sessions
            JOIN memberships ON memberships.valid_from <= retained_sessions.session_date
             AND (memberships.valid_to IS NULL OR memberships.valid_to > retained_sessions.session_date)
             AND memberships.available_at <= retained_sessions.as_of
            GROUP BY retained_sessions.session_date, memberships.symbol
        )
    """
    row = connection.execute(
        base + """
        SELECT COUNT(*) AS expected,
               COALESCE(SUM(CASE WHEN EXISTS (
                   SELECT 1 FROM active_members member
                   WHERE member.session_date = retained_sessions.session_date
               ) THEN 1 ELSE 0 END), 0) AS observed
        FROM retained_sessions
        """, parameters,
    ).fetchone()
    result = {"constituents": _coverage(row["expected"], row["observed"])}
    manifest_hashes = {
        "constituents": tuple(
            row["manifest_hash"]
            for row in connection.execute(
                base + """
                SELECT DISTINCT memberships.manifest_hash
                FROM retained_sessions
                JOIN memberships
                  ON memberships.valid_from <= retained_sessions.session_date
                 AND (
                    memberships.valid_to IS NULL
                    OR memberships.valid_to > retained_sessions.session_date
                 )
                 AND memberships.available_at <= retained_sessions.as_of
                ORDER BY memberships.manifest_hash
                """,
                parameters,
            ).fetchall()
        )
    }
    requirements = {
        "bars": "target.symbol = active_members.symbol AND target.session_date = active_members.session_date AND target.available_at <= active_members.as_of",
        "fundamentals": "target.symbol = active_members.symbol AND target.period_end <= active_members.as_of AND target.available_at <= active_members.as_of AND target.debt_to_assets IS NOT NULL AND target.interest_income_ratio IS NOT NULL",
        "halal": "target.symbol = active_members.symbol AND target.effective_from <= active_members.as_of AND target.available_at <= active_members.as_of AND target.tradeable = 1 AND target.tier != 'UNKNOWN'",
    }
    tables = {"bars": "bars", "fundamentals": "fundamentals", "halal": "halal_classifications"}
    for name, condition in requirements.items():
        row = connection.execute(
            base + f"""
            SELECT COUNT(*) AS expected,
                   COALESCE(SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM {tables[name]} target WHERE {condition}
                   ) THEN 1 ELSE 0 END), 0) AS observed
            FROM active_members
            """, parameters,
        ).fetchone()
        result[name] = _coverage(row["expected"], row["observed"])
        manifest_hashes[name] = tuple(
            item["manifest_hash"]
            for item in connection.execute(
                base + f"""
                SELECT DISTINCT target.manifest_hash
                FROM active_members
                JOIN {tables[name]} target ON {condition}
                ORDER BY target.manifest_hash
                """,
                parameters,
            ).fetchall()
        )
    sector_condition = (
        "target.symbol = active_members.symbol "
        f"AND target.{sector_effective} <= active_members.as_of "
        "AND target.available_at <= active_members.as_of "
        f"AND TRIM(target.{sector_value}) != ''"
    )
    row = connection.execute(
        base + f"""
        SELECT COUNT(*) AS expected,
               COALESCE(SUM(CASE WHEN EXISTS (
                   SELECT 1 FROM {sector_table} target
                   WHERE {sector_condition}
               ) THEN 1 ELSE 0 END), 0) AS observed
        FROM active_members
        """,
        parameters,
    ).fetchone()
    result["sectors_industry"] = _coverage(
        row["expected"], row["observed"]
    )
    manifest_hashes["sectors_industry"] = tuple(
        item["manifest_hash"]
        for item in connection.execute(
            base + f"""
            SELECT DISTINCT target.manifest_hash
            FROM active_members
            JOIN {sector_table} target ON {sector_condition}
            ORDER BY target.manifest_hash
            """,
            parameters,
        ).fetchall()
    )
    first_session = f"{sessions[0].isoformat()}T00:00:00+00:00"
    final_as_of = f"{sessions[-1].isoformat()}T23:59:59+00:00"
    manifest_hashes["corporate_actions"] = tuple(
        row["manifest_hash"]
        for row in connection.execute(
            """
            SELECT DISTINCT manifest_hash FROM corporate_actions
            WHERE ex_date >= ? AND ex_date <= ? AND available_at <= ?
            ORDER BY manifest_hash
            """,
            (first_session, final_as_of, final_as_of),
        ).fetchall()
    )
    for table in ("suspensions", "delistings"):
        effective = event_effective[table]
        manifest_hashes[table] = tuple(
            row["manifest_hash"]
            for row in connection.execute(
                f"""
                SELECT DISTINCT manifest_hash FROM {table}
                WHERE {effective} <= ? AND available_at <= ?
                ORDER BY manifest_hash
                """,
                (final_as_of, final_as_of),
            ).fetchall()
        )
    return result, {
        key: tuple(sorted(set(manifest_hashes[key])))
        for key in sorted(manifest_hashes)
    }


def _reconcile_source_store_rows(
    store: ReliabilityStore,
    protocol: dict,
    sources: dict[str, _Source],
    sessions: tuple[date, ...],
) -> None:
    if (
        protocol.get("family") != "nse-halal-swing"
        or protocol.get("universe") != "NIFTY 500"
    ):
        return
    try:
        bounds = {
            "start": protocol["periods"]["warmup"][0],
            "end": protocol["periods"]["scored"][1],
        }
        actual_member_sessions = _store_member_sessions(store, sessions)
        for source_domain, store_domain in (
            _MEMBER_SESSION_SOURCE_DOMAINS.items()
        ):
            source = sources[source_domain]
            payload = _canonical_source_payload(source)
            if set(payload) != {
                "bounds",
                "domain",
                "member_sessions",
                "schema_version",
            }:
                raise ValueError("member-session source schema")
            if (
                payload.get("schema_version") != 1
                or payload.get("domain") != source_domain
                or payload.get("bounds") != bounds
            ):
                raise ValueError("member-session source identity")
            expected = _member_session_records(
                payload.get("member_sessions")
            )
            if expected != actual_member_sessions[store_domain]:
                raise ValueError("member-session source mismatch")

        for source_domain, (table, columns) in (
            _EVENT_SOURCE_DOMAINS.items()
        ):
            source = sources[source_domain]
            payload = _canonical_source_payload(source)
            if set(payload) != {
                "bounds",
                "domain",
                "rows",
                "schema_version",
            }:
                raise ValueError("event source schema")
            if (
                payload.get("schema_version") != 1
                or payload.get("domain") != source_domain
                or payload.get("bounds") != bounds
            ):
                raise ValueError("event source identity")
            expected_rows = _event_source_rows(
                payload.get("rows"),
                columns,
            )
            selected = ", ".join(columns)
            actual_rows = tuple(
                {column: row[column] for column in columns}
                for row in store.connection.execute(
                    f"""
                    SELECT {selected} FROM {table}
                    WHERE manifest_hash = ?
                    ORDER BY {selected}
                    """,
                    (source.record["sha256"],),
                ).fetchall()
            )
            if expected_rows != actual_rows:
                raise ValueError("event source mismatch")
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
        sqlite3.DatabaseError,
    ) as exc:
        raise ValueError(
            f"source/store row evidence is incomplete: {exc}"
        ) from exc


def _canonical_source_payload(source: _Source) -> dict:
    content = source.artifact.read_bytes()
    payload = json.loads(content)
    canonical = _canonical_mapping(payload)
    if canonical is None or canonical != content:
        raise ValueError("source row evidence must be canonical")
    return payload


def _member_session_records(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise ValueError("member_sessions must be a list")
    records = []
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != {"session_date", "symbol"}
            or not isinstance(row["symbol"], str)
            or not row["symbol"]
            or row["symbol"] != row["symbol"].upper()
        ):
            raise ValueError("invalid member-session row")
        parsed = date.fromisoformat(row["session_date"])
        if parsed.isoformat() != row["session_date"]:
            raise ValueError("noncanonical member-session date")
        records.append({
            "session_date": row["session_date"],
            "symbol": row["symbol"],
        })
    ordered = sorted(
        records,
        key=lambda row: (row["session_date"], row["symbol"]),
    )
    if records != ordered or len({
        (row["session_date"], row["symbol"])
        for row in records
    }) != len(records):
        raise ValueError("member-session rows must be sorted and unique")
    return tuple(records)


def _event_source_rows(
    value: object,
    columns: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        raise ValueError("event rows must be a list")
    rows = []
    for row in value:
        if (
            not isinstance(row, dict)
            or set(row) != set(columns)
            or any(
                not isinstance(row[column], str) or not row[column]
                for column in columns
            )
        ):
            raise ValueError("invalid event source row")
        rows.append({column: row[column] for column in columns})
    ordered = sorted(
        rows,
        key=lambda row: tuple(row[column] for column in columns),
    )
    if rows != ordered or len({
        tuple(row[column] for column in columns)
        for row in rows
    }) != len(rows):
        raise ValueError("event source rows must be sorted and unique")
    return tuple(rows)


def _store_member_sessions(
    store: ReliabilityStore,
    sessions: tuple[date, ...],
) -> dict[str, tuple[dict[str, str], ...]]:
    names = (
        "constituents",
        "bars",
        "fundamentals",
        "halal",
        "sectors_industry",
    )
    if not sessions:
        return {name: () for name in names}
    lookup_schema = resolve_task6_lookup_schema(store)
    placeholders = ", ".join("(?, ?)" for _ in sessions)
    parameters: list[str] = []
    for session in sessions:
        parameters.extend((
            f"{session.isoformat()}T00:00:00+00:00",
            f"{session.isoformat()}T23:59:59+00:00",
        ))
    base = f"""
        WITH retained_sessions(session_date, as_of) AS (
            VALUES {placeholders}
        ),
        active_members AS (
            SELECT retained_sessions.session_date,
                   retained_sessions.as_of,
                   memberships.symbol
            FROM retained_sessions
            JOIN memberships
              ON memberships.valid_from <= retained_sessions.session_date
             AND (
                memberships.valid_to IS NULL
                OR memberships.valid_to > retained_sessions.session_date
             )
             AND memberships.available_at <= retained_sessions.as_of
            GROUP BY retained_sessions.session_date, memberships.symbol
        )
    """

    def records(query: str) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "session_date": row["session_date"],
                "symbol": row["symbol"],
            }
            for row in store.connection.execute(
                base + query,
                parameters,
            ).fetchall()
        )

    output = {
        "constituents": records(
            """
            SELECT SUBSTR(session_date, 1, 10) AS session_date, symbol
            FROM active_members
            ORDER BY session_date, symbol
            """
        )
    }
    requirements = {
        "bars": (
            "bars",
            "target.symbol = active_members.symbol "
            "AND target.session_date = active_members.session_date "
            "AND target.available_at <= active_members.as_of",
        ),
        "fundamentals": (
            "fundamentals",
            "target.symbol = active_members.symbol "
            "AND target.period_end <= active_members.as_of "
            "AND target.available_at <= active_members.as_of "
            "AND target.debt_to_assets IS NOT NULL "
            "AND target.interest_income_ratio IS NOT NULL",
        ),
        "halal": (
            "halal_classifications",
            "target.symbol = active_members.symbol "
            "AND target.effective_from <= active_members.as_of "
            "AND target.available_at <= active_members.as_of "
            "AND target.tradeable = 1 AND target.tier != 'UNKNOWN'",
        ),
    }
    for name, (table, condition) in requirements.items():
        output[name] = records(
            f"""
            SELECT SUBSTR(active_members.session_date, 1, 10)
                       AS session_date,
                   active_members.symbol AS symbol
            FROM active_members
            WHERE EXISTS (
                SELECT 1 FROM {table} target WHERE {condition}
            )
            ORDER BY session_date, symbol
            """
        )
    sector = lookup_schema.sector
    output["sectors_industry"] = records(
        f"""
        SELECT SUBSTR(active_members.session_date, 1, 10)
                   AS session_date,
               active_members.symbol AS symbol
        FROM active_members
        WHERE EXISTS (
            SELECT 1 FROM {sector.table} target
            WHERE target.symbol = active_members.symbol
              AND target.{sector.effective_column}
                  <= active_members.as_of
              AND target.available_at <= active_members.as_of
              AND TRIM(target.{sector.value_column}) != ''
        )
        ORDER BY session_date, symbol
        """
    )
    return output


def _bind_store_manifest_sources(
    store: ReliabilityStore,
    referenced_hashes: dict[str, tuple[str, ...]],
    sources: dict[str, _Source],
) -> dict[str, tuple[str, ...]]:
    output = {}
    for domain, source_domain in _STORE_SOURCE_DOMAINS.items():
        source = sources.get(source_domain)
        expected = source.record["sha256"] if source is not None else None
        hashes = referenced_hashes.get(domain, ())
        if (
            expected is None
            or (
                domain not in _ZERO_ROW_STORE_DOMAINS
                and not hashes
            )
            or any(
                not isinstance(digest, str)
                or _SHA256.fullmatch(digest) is None
                or digest != expected
                for digest in hashes
            )
        ):
            raise ValueError(f"store manifest mismatch for {domain}")
        row = store.connection.execute(
            """
            SELECT source, available_at, metadata_json
            FROM manifests WHERE content_hash = ?
            """,
            (expected,),
        ).fetchone()
        try:
            metadata = json.loads(row["metadata_json"]) if row else None
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"invalid store manifest metadata for {domain}"
            ) from exc
        if (
            row is None
            or row["source"] != source.record["source_id"]
            or row["available_at"] != _iso(source.record["available_at"])
            or metadata != {"domain": source_domain}
        ):
            raise ValueError(
                f"store manifest identity mismatch for {domain}"
            )
        output[domain] = (expected,)
    return {key: output[key] for key in sorted(output)}


def _coverage(expected: int, observed: int) -> dict:
    return {
        "expected": int(expected),
        "observed": int(observed),
        "ratio": int(observed) / int(expected) if expected else 0.0,
    }


def _source_aggregate(source: _Source | None, sessions: int) -> dict:
    if source is None:
        return _coverage(sessions, 0)
    coverage = source.record["coverage"]
    return _coverage(coverage["expected_sessions"], coverage["observed_sessions"])


def _reviews(
    paths: list[Path],
    sources: dict[str, _Source],
    start: str,
    end: str,
    sessions: int,
    blockers: set[str],
) -> tuple[dict[str, dict], list[dict]]:
    reports: dict[str, dict] = {}
    artifact_records: list[dict] = []
    verified_hashes = {source.record["sha256"] for source in sources.values()}
    for requested in paths:
        path = Path(requested).resolve()
        try:
            content = path.read_bytes()
            report = json.loads(content)
            canonical = _canonical_mapping(report)
            if canonical is None or content != canonical:
                raise ValueError("review must be canonical JSON object")
            kind = report.get("kind")
            if kind not in _REQUIRED_REVIEWS:
                raise ValueError("unsupported review kind")
        except (AttributeError, KeyError, OSError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            blockers.add("REVIEW_REPORTS")
            continue
        if kind in reports:
            blockers.add(kind.upper())
            continue
        reports[kind] = report
        artifact_records.append({
            "available_at": report.get("reviewed_at"),
            "bounds": {"start": start, "end": end},
            "kind": kind,
            "path": str(path),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    for kind in _REQUIRED_REVIEWS:
        report = reports.get(kind)
        if not _valid_review(report, verified_hashes, start, end, sessions):
            blockers.add(kind.upper())
        elif _unresolved(report):
            blockers.add(f"{kind.upper()}_UNRESOLVED_QUEUE")
    return reports, sorted(
        artifact_records, key=lambda record: record["kind"]
    )


def _valid_review(report: dict | None, source_hashes: set[str], start: str, end: str, sessions: int) -> bool:
    if not isinstance(report, dict):
        return False
    coverage = report.get("coverage")
    return (
        report.get("status") == "VERIFIED"
        and report.get("source_id") in _REVIEW_IDENTITIES
        and _canonical_utc(report.get("reviewed_at"))
        and report.get("source_sha256") in source_hashes
        and isinstance(coverage, dict)
        and coverage == {
            "start": start,
            "end": end,
            "expected_sessions": sessions,
            "observed_sessions": sessions,
        }
    )


def _unresolved(report: dict) -> bool:
    count = report.get("unresolved_queue_count", 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return True
    queue_keys = ("review_queue", "specialist_review_queue", "visibility_review_queue", "factor_review_queue")
    return count > 0 or any(isinstance(report.get(key), list) and report[key] for key in queue_keys)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
