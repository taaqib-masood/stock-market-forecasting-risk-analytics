import ast
import builtins
import csv
import hashlib
import importlib
import json
import math
import re
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pytest

from src.reliability.preregistration import canonical_json_bytes, sha256_json
from src.reliability.corporate_action_audit import audit_corporate_actions
from src.reliability.corporate_action_review_packet import export_review_packet
from src.reliability.nifty_tri import (
    NiftyTriAcquirer,
    _file_bytes,
    _request_body,
    build_tri_windows,
)
from src.reliability.store import ReliabilityStore


START = date(2013, 12, 1)
END = date(2019, 12, 31)
DOMAINS = (
    "calendar",
    "constituents",
    "bars",
    "corporate_actions",
    "sectors_industry",
    "suspensions",
    "delistings",
    "fundamentals",
    "halal_evidence",
    "tri",
)
MEMBER_SESSION_DOMAINS = {
    "constituents",
    "bars",
    "sectors_industry",
    "fundamentals",
    "halal_evidence",
}
EVENT_DOMAINS = {
    "corporate_actions",
    "suspensions",
    "delistings",
}
REVIEW_KINDS = ("business_reviews", "concept_reviews", "pdf_reviews", "delistings")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
UTC_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
MALFORMED_CONTENTS = [
    pytest.param(b"{", id="invalid-json"),
    pytest.param(b"\xff", id="invalid-utf8"),
    pytest.param(b"null\n", id="scalar"),
    pytest.param(b"[]\n", id="list"),
    pytest.param(b"NaN\n", id="nonfinite"),
    pytest.param(b"{}\n", id="wrong-schema"),
]
TASK_6_TYPED_COLUMNS = tuple(
    (table, column, declared_type)
    for table, columns in {
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
        "sector_classifications": {
            "symbol": "TEXT",
            "sector": "TEXT",
            "effective_from": "TEXT",
            "available_at": "TEXT",
            "manifest_hash": "TEXT",
        },
        "suspensions": {
            "symbol": "TEXT",
            "effective_from": "TEXT",
            "available_at": "TEXT",
            "manifest_hash": "TEXT",
        },
        "delistings": {
            "symbol": "TEXT",
            "effective_from": "TEXT",
            "available_at": "TEXT",
            "manifest_hash": "TEXT",
        },
        "manifests": {
            "content_hash": "TEXT",
            "source": "TEXT",
            "available_at": "TEXT",
            "metadata_json": "TEXT",
        },
    }.items()
    for column, declared_type in columns.items()
)


def _module():
    return importlib.import_module("src.reliability.experiment_preflight")


def _protocol():
    return {
        "experiment_id": "nse-halal-residual-momentum-v1",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v1",
        "periods": {
            "warmup": [START.isoformat(), "2014-12-31"],
            "scored": ["2015-01-01", END.isoformat()],
            "burned": [["2020-01-01", "2024-06-30"]],
        },
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
        "parameters": {"momentum_long": 252, "skip": 21, "atr": 14},
        "statistical_policy": {"min_observations": 504, "n_trials_floor": 7},
    }


def _v4_protocol():
    protocol = _protocol()
    protocol["experiment_id"] = "nse-halal-residual-momentum-v4"
    protocol["protocol_version"] = "pit-nifty500-next-open-v4"
    protocol["parameters"]["halal_max_age_days"] = 365
    return protocol


@lru_cache
def _sessions():
    current = START
    sessions = []
    while current <= END:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    return tuple(sessions)


def _sha256(content):
    return hashlib.sha256(content).hexdigest()


def _write_json(path, payload, *, canonical=False):
    content = canonical_json_bytes(payload) if canonical else (
        json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return _sha256(content)


def _catalogue(
    tmp_path,
    *,
    omit=None,
    one_session=False,
    placeholder_domain=None,
    extra_source_symbol=None,
):
    retained_root = tmp_path / "retained"
    sessions = _sessions()
    closures = []
    if one_session:
        sessions = sessions[:1]
        closures = [day.isoformat() for day in _sessions()[1:]]
    calendar_payload = {
        "bounds": {"start": START.isoformat(), "end": END.isoformat()},
        "closures": closures,
        "schema_version": 1,
        "sessions": [day.isoformat() for day in sessions],
    }
    sources = {}
    records = []
    for domain in DOMAINS:
        if domain == omit:
            continue
        path = retained_root / f"{domain}.json"
        if domain == "calendar":
            digest = _write_json(path, calendar_payload, canonical=True)
        elif domain == "tri":
            digest = _write_json(path, {
                "normalized_rows": [
                    {"session_date": day.isoformat(), "tri": 1.0} for day in sessions
                ],
            })
        elif domain == placeholder_domain:
            digest = _write_json(
                path,
                {"domain": domain},
                canonical=True,
            )
        elif domain in MEMBER_SESSION_DOMAINS:
            symbols = ["SYNTH"]
            if extra_source_symbol is not None:
                symbols.append(extra_source_symbol)
            digest = _write_json(path, {
                "bounds": {
                    "start": START.isoformat(),
                    "end": END.isoformat(),
                },
                "domain": domain,
                "member_sessions": [
                    {
                        "session_date": day.isoformat(),
                        "symbol": symbol,
                    }
                    for day in sessions
                    for symbol in symbols
                ],
                "schema_version": 1,
            }, canonical=True)
        elif domain in EVENT_DOMAINS:
            digest = _write_json(path, {
                "bounds": {
                    "start": START.isoformat(),
                    "end": END.isoformat(),
                },
                "domain": domain,
                "rows": [],
                "schema_version": 1,
            }, canonical=True)
        else:
            raise AssertionError(f"unhandled source domain: {domain}")
        sources[domain] = digest
        records.append({
            "available_at": "2013-11-30T00:00:00Z",
            "coverage": {
                "end": END.isoformat(),
                "expected_sessions": len(sessions),
                "observed_sessions": len(sessions),
                "start": START.isoformat(),
            },
            "domain": domain,
            "path": str(path.relative_to(tmp_path)),
            "sha256": digest,
            "source_id": "NIFTY INDICES" if domain == "tri" else "NSE",
            "status": "downloaded",
        })
    catalogue = tmp_path / "source-catalogue.jsonl"
    catalogue.write_bytes(b"".join(
        canonical_json_bytes(record) for record in sorted(records, key=lambda item: item["domain"])
    ))
    return catalogue, sources, tuple(sessions)


def _reviews(tmp_path, sources, *, omit=None, unresolved=False):
    paths = []
    for kind in REVIEW_KINDS:
        if kind == omit:
            continue
        path = tmp_path / "reviews" / f"{kind}.json"
        _write_json(path, {
            "coverage": {
                "end": END.isoformat(),
                "expected_sessions": len(_sessions()),
                "observed_sessions": len(_sessions()),
                "start": START.isoformat(),
            },
            "kind": kind,
            "reviewed_at": "2020-01-02T00:00:00Z",
            "source_id": "INTERNAL REVIEW",
            "source_sha256": sources.get("halal_evidence", "0" * 64),
            "status": "VERIFIED",
            "unresolved_queue_count": 1 if unresolved and kind == "business_reviews" else 0,
        }, canonical=True)
        paths.append(path)
    return paths


def _store(tmp_path, *, missing_bar=False, missing_fundamental=False, missing_halal=False):
    store = ReliabilityStore(tmp_path / "reliability.db")
    retained = tmp_path / "retained"
    store.connection.executescript(
        """
        CREATE TABLE sector_classifications (
            symbol TEXT NOT NULL,
            sector TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            available_at TEXT NOT NULL,
            manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash)
        );
        CREATE TABLE suspensions (
            symbol TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            available_at TEXT NOT NULL,
            manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash)
        );
        CREATE TABLE delistings (
            symbol TEXT NOT NULL,
            effective_from TEXT NOT NULL,
            available_at TEXT NOT NULL,
            manifest_hash TEXT NOT NULL REFERENCES manifests(content_hash)
        );
        """
    )

    def retained_manifest(domain):
        path = retained / f"{domain}.json"
        if path.exists():
            return store.register_manifest(
                "NSE",
                path.read_bytes(),
                "2013-11-30T00:00:00Z",
                {"domain": domain},
            )
        return store.register_manifest(
            "NSE",
            b"synthetic",
            "2013-11-30T00:00:00Z",
            {"domain": domain},
        )

    manifests = {
        "constituents": retained_manifest("constituents"),
        "bars": retained_manifest("bars"),
        "corporate_actions": retained_manifest("corporate_actions"),
        "sectors_industry": retained_manifest("sectors_industry"),
        "suspensions": retained_manifest("suspensions"),
        "delistings": retained_manifest("delistings"),
        "fundamentals": retained_manifest("fundamentals"),
        "halal": retained_manifest("halal_evidence"),
    }
    prior = "2013-11-30T00:00:00Z"
    store.put_membership(
        "SYNTH", START.isoformat(), prior, manifests["constituents"]
    )
    rows = []
    for session in _sessions():
        if missing_bar and session == _sessions()[-1]:
            continue
        rows.append({
            "symbol": "SYNTH",
            "session_date": session.isoformat(),
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
            "available_at": prior,
        })
    store.put_bars(rows, manifests["bars"])
    if not missing_fundamental:
        store.put_fundamental(
            "SYNTH", prior, prior, manifests["fundamentals"], 0.1, 0.1
        )
    if not missing_halal:
        store.put_halal_classification(
            "SYNTH", prior, "GREEN", True, "v1", prior, manifests["halal"]
        )
    store.connection.execute(
        "INSERT INTO sector_classifications VALUES (?, ?, ?, ?, ?)",
        (
            "SYNTH",
            "TECH",
            f"{START.isoformat()}T00:00:00+00:00",
            "2013-11-30T00:00:00+00:00",
            manifests["sectors_industry"],
        ),
    )
    store.connection.commit()
    return store


def _run(tmp_path, **kwargs):
    catalogue, sources, _ = _catalogue(tmp_path, omit=kwargs.pop("omit_source", None))
    store = _store(
        tmp_path,
        missing_bar=kwargs.pop("missing_bar", False),
        missing_fundamental=kwargs.pop("missing_fundamental", False),
        missing_halal=kwargs.pop("missing_halal", False),
    )
    return _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources, **kwargs),
    )


def _complete_corporate_action_review_artifacts(tmp_path):
    source_dir = tmp_path / "corporate-action-sources"
    records = []
    month = date(2019, 1, 1)
    while month <= date(2024, 6, 1):
        next_month = date(
            month.year + (month.month == 12),
            month.month % 12 + 1,
            1,
        )
        month_end = next_month - timedelta(days=1)
        snapshot = source_dir / f"actions-{month:%Y-%m}.json"
        payload = []
        if month == date(2019, 1, 1):
            payload = [{
                "symbol": "TCS",
                "series": "EQ",
                "subject": "Rights 1:4 @ Premium Rs 10",
                "exDate": "03-Jan-2019",
                "recDate": "03-Jan-2019",
                "caBroadcastDate": "01-Jan-2019 10:00:00",
            }]
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(payload), encoding="utf-8")
        records.append({
            "kind": "corporate_actions",
            "status": "downloaded",
            "path": str(snapshot),
            "sha256": _sha256(snapshot.read_bytes()),
            "available_at": "2019-01-01T00:00:00Z",
            "params": {
                "from_date": month.strftime("%d-%m-%Y"),
                "to_date": month_end.strftime("%d-%m-%Y"),
            },
        })
        month = next_month
    catalogue = tmp_path / "corporate-action-source-catalogue.jsonl"
    catalogue.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    baseline = audit_corporate_actions(
        catalogue,
        start="2019-01-01",
        end="2024-06-30",
    )
    baseline_path = tmp_path / "corporate-action-baseline.json"
    baseline_path.write_bytes(canonical_json_bytes(baseline))
    packet_dir = tmp_path / "corporate-action-review-packet"
    exported = export_review_packet(baseline_path, packet_dir)
    evidence = packet_dir / "evidence" / "nse-notice.txt"
    evidence.parent.mkdir()
    evidence.write_bytes(b"NSE primary corporate action notice\n")
    with exported["factor_csv"].open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames
        rows = list(reader)
    rows[0].update({
        "decision": "APPROVED",
        "evidence_path": "evidence/nse-notice.txt",
        "evidence_sha256": _sha256(evidence.read_bytes()),
        "evidence_source_url": "https://www.nseindia.com/corporates/corporateActions",
        "reviewer_id": "independent-reviewer",
        "reviewed_at": "2024-01-02T12:00:00Z",
        "confirmed_available_at": "2019-01-01T10:00:00Z",
        "adjustment_factor": "0.75",
        "method": "Rights theoretical ex-price formula using notice terms.",
        "notes": "Primary exchange notice retained.",
    })
    with exported["factor_csv"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    policy_path = tmp_path / "corporate-action-reviewer-policy.json"
    policy_path.write_text(json.dumps({
        "policy_version": "corporate-action-review-policy-v1",
        "authorized_reviewers": ["independent-reviewer"],
        "prohibited_reviewers": ["issuer-employee"],
        "allowed_evidence_hosts": ["www.nseindia.com"],
    }), encoding="utf-8")
    reviewed = audit_corporate_actions(
        catalogue,
        start="2019-01-01",
        end="2024-06-30",
        review_packet_dir=packet_dir,
        reviewer_policy_path=policy_path,
        baseline_report_path=baseline_path,
    )
    reviewed_path = tmp_path / "corporate-action-reviewed.json"
    reviewed_path.write_bytes(canonical_json_bytes(reviewed))
    return {
        "audit_path": reviewed_path,
        "audit_sha256": _sha256(reviewed_path.read_bytes()),
        "packet_dir": packet_dir,
        "factor_csv": exported["factor_csv"],
        "evidence_path": evidence,
        "policy_path": policy_path,
        "baseline_path": baseline_path,
    }


def _rewrite_source(catalogue, domain, content):
    root = catalogue.parent
    records = [json.loads(line) for line in catalogue.read_text().splitlines()]
    record = next(item for item in records if item["domain"] == domain)
    artifact = root / record["path"]
    artifact.write_bytes(content)
    record["sha256"] = _sha256(content)
    catalogue.write_bytes(b"".join(canonical_json_bytes(item) for item in records))


def _assert_named_stable_blocker(run, blocker):
    first = run()
    second = run()
    assert first.passed is second.passed is False
    assert first.dataset_manifest_sha256 is second.dataset_manifest_sha256 is None
    assert first.blockers == second.blockers
    assert blocker in first.blockers


def _assert_aggregate_schema(value):
    assert set(value) == {"calendar", "coverage", "date_bounds", "hashes"}
    assert value["date_bounds"] == {"start": START.isoformat(), "end": END.isoformat()}
    assert set(value["calendar"]) == {"closures", "sessions", "weekdays"}
    assert all(isinstance(value["calendar"][key], int) and value["calendar"][key] >= 0
               for key in value["calendar"])
    assert set(value["coverage"]) == {
        "bars", "calendar", "corporate_actions", "constituents", "delistings",
        "fundamentals", "halal", "sectors_industry", "suspensions",
    }
    for aggregate in value["coverage"].values():
        assert set(aggregate) == {"expected", "observed", "ratio"}
        assert isinstance(aggregate["expected"], int) and aggregate["expected"] >= 0
        assert isinstance(aggregate["observed"], int) and aggregate["observed"] >= 0
        assert isinstance(aggregate["ratio"], float) and math.isfinite(aggregate["ratio"])
        assert 0.0 <= aggregate["ratio"] <= 1.0
    assert set(value["hashes"]) == {"protocol", "retained", "reviews"}
    assert SHA256.fullmatch(value["hashes"]["protocol"])
    for key in ("retained", "reviews"):
        assert isinstance(value["hashes"][key], tuple)
        assert all(SHA256.fullmatch(digest) for digest in value["hashes"][key])


def _replace_with_partial_typed_table(
    store,
    table,
    target_column,
    mutation,
):
    rows = store.connection.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()
    definitions = []
    retained_columns = []
    for row in rows:
        if mutation == "missing" and row["name"] == target_column:
            continue
        retained_columns.append(row["name"])
        declared_type = (
            "BLOB"
            if mutation == "wrong_type" and row["name"] == target_column
            else row["type"]
        )
        definitions.append(f'"{row["name"]}" {declared_type}')
    store.connection.execute(
        f'ALTER TABLE "{table}" RENAME TO "{table}_complete"'
    )
    store.connection.execute(
        f'CREATE TABLE "{table}" ({", ".join(definitions)})'
    )
    quoted_columns = ", ".join(
        f'"{column}"' for column in retained_columns
    )
    store.connection.execute(
        f'INSERT INTO "{table}" ({quoted_columns}) '
        f'SELECT {quoted_columns} FROM "{table}_complete"'
    )
    store.connection.commit()


def _add_sector_alias(store, table="sectors_industry"):
    store.connection.execute(
        f"""
        CREATE TABLE {table} (
            symbol TEXT,
            sector TEXT,
            effective_from TEXT,
            available_at TEXT,
            manifest_hash TEXT
        )
        """
    )
    store.connection.execute(
        f"""
        INSERT INTO {table}
        SELECT symbol, sector, effective_from, available_at, manifest_hash
        FROM sector_classifications
        """
    )
    store.connection.commit()


def _add_session_date_variant(store, table):
    store.connection.execute(
        f"ALTER TABLE {table} ADD COLUMN session_date TEXT"
    )
    store.connection.execute(
        f"UPDATE {table} SET session_date = effective_from"
    )
    store.connection.commit()


def _mutate_lookup_schema(store, scenario):
    if scenario == "multiple_sector_tables":
        _add_sector_alias(store)
        return
    if scenario == "malformed_first_sector_with_valid_alias":
        _replace_with_partial_typed_table(
            store,
            "sector_classifications",
            "effective_from",
            "wrong_type",
        )
        _add_sector_alias(store)
        return
    if scenario in {"dual_sector_dates", "wrong_typed_sector_dates"}:
        _add_session_date_variant(store, "sector_classifications")
        if scenario.startswith("wrong_typed"):
            _replace_with_partial_typed_table(
                store,
                "sector_classifications",
                "effective_from",
                "wrong_type",
            )
        return
    table = (
        "suspensions"
        if scenario.endswith("suspension_dates")
        else "delistings"
    )
    _add_session_date_variant(store, table)
    if scenario.startswith("wrong_typed"):
        _replace_with_partial_typed_table(
            store,
            table,
            "effective_from",
            "wrong_type",
        )


def test_preflight_accepts_complete_canonical_synthetic_calendar(tmp_path):
    result = _run(tmp_path)

    assert result.passed is True
    assert result.dataset_manifest_sha256 is not None
    _assert_aggregate_schema(result.aggregates)
    with pytest.raises(TypeError):
        result.aggregates["calendar"] = {}


def test_v4_preflight_requires_explicit_corporate_action_review_inputs(tmp_path):
    store = ReliabilityStore(tmp_path / "store.db")
    protocol = _protocol()
    protocol["experiment_id"] = "nse-halal-residual-momentum-v4"
    protocol["protocol_version"] = "pit-nifty500-next-open-v4"
    protocol["parameters"]["halal_max_age_days"] = 365

    result = _module().run_preflight(
        store,
        protocol,
        source_catalogues=[],
        review_reports=[],
    )

    assert "CORPORATE_ACTION_REVIEW" in result.blockers


def test_v4_preflight_binds_complete_corporate_action_review_and_detects_drift(
    tmp_path,
):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    review = _complete_corporate_action_review_artifacts(tmp_path)
    protocol = _v4_protocol()

    result = _module().run_preflight(
        store,
        protocol,
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
        corporate_action_audit_path=review["audit_path"],
        corporate_action_audit_sha256=review["audit_sha256"],
        corporate_action_packet_dir=review["packet_dir"],
        corporate_action_policy_path=review["policy_path"],
        corporate_action_baseline_path=review["baseline_path"],
    )

    assert result.passed is True
    assert result.manifest_payload["corporate_action_review"] == {
        "schema_version": "corporate-action-review-binding-v1",
        "audit_path": str(review["audit_path"].resolve()),
        "audit_sha256": review["audit_sha256"],
        "packet_dir": str(review["packet_dir"].resolve()),
        "packet_manifest_path": str(
            (review["packet_dir"] / "manifest.json").resolve()
        ),
        "packet_manifest_sha256": _sha256(
            (review["packet_dir"] / "manifest.json").read_bytes()
        ),
        "policy_path": str(review["policy_path"].resolve()),
        "reviewer_policy_sha256": _sha256(review["policy_path"].read_bytes()),
        "baseline_path": str(review["baseline_path"].resolve()),
        "baseline_report_sha256": _sha256(review["baseline_path"].read_bytes()),
    }
    assert result.aggregates["hashes"]["corporate_action_review"] == _module().sha256_json(
        result.manifest_payload["corporate_action_review"]
    )
    _module().verify_preflight_binding(store, protocol, result)


@pytest.mark.parametrize(
    "artifact",
    ("audit", "packet_manifest", "factor_csv", "evidence", "policy", "baseline"),
)
def test_v4_preflight_rejects_every_corporate_action_artifact_drift(
    tmp_path,
    artifact,
):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    review = _complete_corporate_action_review_artifacts(tmp_path)
    protocol = _v4_protocol()
    result = _module().run_preflight(
        store,
        protocol,
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
        corporate_action_audit_path=review["audit_path"],
        corporate_action_audit_sha256=review["audit_sha256"],
        corporate_action_packet_dir=review["packet_dir"],
        corporate_action_policy_path=review["policy_path"],
        corporate_action_baseline_path=review["baseline_path"],
    )
    targets = {
        "audit": review["audit_path"],
        "packet_manifest": review["packet_dir"] / "manifest.json",
        "factor_csv": review["factor_csv"],
        "evidence": review["evidence_path"],
        "policy": review["policy_path"],
        "baseline": review["baseline_path"],
    }
    target = targets[artifact]
    target.write_bytes(target.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="CORPORATE_ACTION_REVIEW"):
        _module().verify_preflight_binding(store, protocol, result)


@pytest.mark.parametrize(
    "domain",
    sorted(MEMBER_SESSION_DOMAINS | EVENT_DOMAINS),
)
def test_placeholder_domain_artifacts_fail_closed(tmp_path, domain):
    catalogue, sources, _ = _catalogue(
        tmp_path,
        placeholder_domain=domain,
    )
    result = _module().run_preflight(
        _store(tmp_path),
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
    )

    assert result.passed is False
    assert result.dataset_manifest_sha256 is None
    assert "SOURCE_STORE_ROWS" in result.blockers


def test_source_universe_missing_from_store_fails_closed(tmp_path):
    catalogue, sources, _ = _catalogue(
        tmp_path,
        extra_source_symbol="MISSING",
    )
    result = _module().run_preflight(
        _store(tmp_path),
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
    )

    assert result.passed is False
    assert result.dataset_manifest_sha256 is None
    assert "SOURCE_STORE_ROWS" in result.blockers


def test_preflight_sources_accept_canonical_tri_acquisition_catalogue(
    tmp_path,
):
    acquirer = NiftyTriAcquirer(tmp_path, retries=1)
    for position, window in enumerate(
        build_tri_windows(START, END)
    ):
        day = window.start
        raw_payload = [{
            "Date": day.strftime("%d %b %Y"),
            "Index Name": "NIFTY 50",
            "TotalReturnsIndex": str(100 + position),
        }]
        raw_response = canonical_json_bytes(raw_payload)
        normalized = [{
            "session_date": day.isoformat(),
            "tri": float(100 + position),
        }]
        path = acquirer._path(window)
        raw_path = acquirer._raw_path(window)
        artifact = acquirer._artifact(
            window,
            _request_body(window),
            raw_payload,
            normalized,
            raw_path=raw_path,
            raw_response=raw_response,
            status_code=200,
            content_type="application/json",
            retrieved_at="2026-07-24T18:30:00Z",
        )
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(raw_response)
        path.write_bytes(_file_bytes(artifact))
        acquirer._catalogue({
            **artifact,
            "status": "downloaded",
            "path": path,
            "raw_path": raw_path,
        })
    merged = acquirer.merge_retained(START, END)
    blockers = set()

    sources, catalogues = _module()._sources(
        [acquirer.catalogue],
        START.isoformat(),
        END.isoformat(),
        blockers,
    )

    assert sources["tri"].artifact == merged.resolve()
    assert "SOURCE_CATALOGUES" not in blockers
    assert "TRI" not in blockers
    assert catalogues[0]["source_domains"] == ("tri",)


def test_manifest_payload_is_immutable_complete_and_recomputable(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    reports = _reviews(tmp_path, sources)

    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=reports,
    )

    assert result.passed is True
    assert result.manifest_payload is not None
    assert sha256_json(result.manifest_payload) == result.dataset_manifest_sha256
    assert set(result.manifest_payload) == {
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
    assert result.manifest_payload["schema_version"] == 2
    assert result.manifest_payload["source_hashes"] == tuple(
        sorted(sources.values())
    )
    assert result.manifest_payload["catalogue_hashes"] == (
        _sha256(catalogue.read_bytes()),
    )
    assert result.manifest_payload["review_hashes"] == tuple(
        sorted(_sha256(path.read_bytes()) for path in reports)
    )
    assert result.manifest_payload["catalogues"] == ({
        "available_at": "2013-11-30T00:00:00Z",
        "bounds": {"start": START.isoformat(), "end": END.isoformat()},
        "domain": "source_catalogue",
        "path": str(catalogue.resolve()),
        "sha256": _sha256(catalogue.read_bytes()),
        "source_domains": tuple(sorted(DOMAINS)),
    },)
    assert {
        record["kind"] for record in result.manifest_payload["reviews"]
    } == set(REVIEW_KINDS)
    assert all(
        set(record) == {
            "available_at", "bounds", "kind", "path", "sha256"
        }
        and Path(record["path"]).is_absolute()
        for record in result.manifest_payload["reviews"]
    )
    assert result.manifest_payload["store_manifest_hashes"] == {
        "bars": (sources["bars"],),
        "corporate_actions": (sources["corporate_actions"],),
        "constituents": (sources["constituents"],),
        "delistings": (sources["delistings"],),
        "fundamentals": (sources["fundamentals"],),
        "halal": (sources["halal_evidence"],),
        "sectors_industry": (sources["sectors_industry"],),
        "suspensions": (sources["suspensions"],),
    }
    with pytest.raises(TypeError):
        result.manifest_payload["store_manifest_hashes"]["bars"] = ()


def test_verify_preflight_binding_recomputes_protocol_manifest_and_store(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
    )

    verified = _module().verify_preflight_binding(store, _protocol(), result)

    assert verified["dataset_manifest_sha256"] == result.dataset_manifest_sha256
    assert verified["store_manifest_hashes"] == result.manifest_payload[
        "store_manifest_hashes"
    ]

    changed_protocol = deepcopy(_protocol())
    changed_protocol["parameters"]["skip"] = 20
    with pytest.raises(ValueError, match="PREFLIGHT_PROTOCOL"):
        _module().verify_preflight_binding(store, changed_protocol, result)

    changed_hash = replace(result, dataset_manifest_sha256="f" * 64)
    with pytest.raises(ValueError, match="PREFLIGHT_MANIFEST"):
        _module().verify_preflight_binding(store, _protocol(), changed_hash)

    unrelated = store.register_manifest(
        "unrelated", b"unrelated", "2013-11-30T00:00:00Z"
    )
    store.connection.execute(
        "UPDATE bars SET manifest_hash = ? WHERE rowid = (SELECT MIN(rowid) FROM bars)",
        (unrelated,),
    )
    store.connection.commit()
    with pytest.raises(ValueError, match="PREFLIGHT_STORE_MANIFESTS"):
        _module().verify_preflight_binding(store, _protocol(), result)


def test_self_consistent_unrelated_store_claim_cannot_verify(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
    )
    payload = json.loads(json.dumps(result.manifest_payload))
    payload["store_manifest_hashes"]["bars"] = ["e" * 64]
    forged = replace(
        result,
        manifest_payload=payload,
        dataset_manifest_sha256=sha256_json(payload),
    )

    with pytest.raises(ValueError, match="PREFLIGHT_STORE_MANIFESTS"):
        _module().verify_preflight_binding(store, _protocol(), forged)


def test_binding_requires_every_source_domain_even_when_payload_is_rehashed(
    tmp_path,
):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
    )
    payload = json.loads(json.dumps(result.manifest_payload))
    omitted = next(
        record
        for record in payload["sources"]
        if record["domain"] == "corporate_actions"
    )
    payload["sources"].remove(omitted)
    payload["source_hashes"].remove(omitted["sha256"])
    aggregates = json.loads(json.dumps(result.aggregates))
    aggregates["hashes"]["retained"].remove(omitted["sha256"])
    forged = replace(
        result,
        aggregates=aggregates,
        manifest_payload=payload,
        dataset_manifest_sha256=sha256_json(payload),
    )

    with pytest.raises(ValueError, match="PREFLIGHT_SOURCE_HASHES"):
        _module().verify_preflight_binding(store, _protocol(), forged)


@pytest.mark.parametrize(
    ("domain", "mutation"),
    [
        (
            "corporate_actions",
            "INSERT INTO corporate_actions VALUES "
            "('SYNTH', 'DIVIDEND', '2015-01-02T00:00:00+00:00', "
            "'{\"cash_amount\": 1.0}', '2015-01-01T00:00:00+00:00', ?)",
        ),
        (
            "sectors_industry",
            "UPDATE sector_classifications SET manifest_hash = ?",
        ),
        (
            "suspensions",
            "INSERT INTO suspensions VALUES "
            "('SYNTH', '2015-01-02T00:00:00+00:00', "
            "'2015-01-01T00:00:00+00:00', ?)",
        ),
        (
            "delistings",
            "INSERT INTO delistings VALUES "
            "('SYNTH', '2019-12-31T00:00:00+00:00', "
            "'2019-12-30T00:00:00+00:00', ?)",
        ),
    ],
)
def test_binding_rejects_result_affecting_typed_table_manifest_mismatch(
    tmp_path, domain, mutation
):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
    )
    unrelated = store.register_manifest(
        "NSE",
        f"unrelated-{domain}".encode(),
        "2013-11-30T00:00:00Z",
        {"domain": domain},
    )
    store.connection.execute(mutation, (unrelated,))
    store.connection.commit()

    with pytest.raises(ValueError, match="PREFLIGHT_STORE_MANIFESTS"):
        _module().verify_preflight_binding(store, _protocol(), result)


def test_zero_row_state_snapshots_are_bound_to_canonical_store_manifests(
    tmp_path,
):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
    )

    assert result.passed is True
    for domain in ("corporate_actions", "suspensions", "delistings"):
        assert result.manifest_payload["store_manifest_hashes"][domain] == (
            sources[domain],
        )
        assert store.connection.execute(
            f"SELECT COUNT(*) AS count FROM {domain}"
        ).fetchone()["count"] == 0


def test_binding_fails_closed_when_required_typed_table_disappears(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=_reviews(tmp_path, sources),
    )
    store.connection.execute("DROP TABLE suspensions")
    store.connection.commit()

    with pytest.raises(ValueError, match="PREFLIGHT_STORE_MANIFESTS"):
        _module().verify_preflight_binding(store, _protocol(), result)


@pytest.mark.parametrize(
    ("table", "column", "declared_type"),
    TASK_6_TYPED_COLUMNS,
)
@pytest.mark.parametrize("mutation", ("missing", "wrong_type"))
def test_every_task_6_typed_column_fails_closed_before_simulation(
    tmp_path,
    table,
    column,
    declared_type,
    mutation,
):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    reports = _reviews(tmp_path, sources)
    passing = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=reports,
    )
    assert passing.passed is True
    schema_rows = store.connection.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()
    assert next(
        row["type"].upper()
        for row in schema_rows
        if row["name"] == column
    ) == declared_type

    _replace_with_partial_typed_table(
        store,
        table,
        column,
        mutation,
    )
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=reports,
    )

    assert result.passed is False
    assert result.dataset_manifest_sha256 is None
    assert "STORE_MANIFESTS" in result.blockers
    with pytest.raises(ValueError, match="PREFLIGHT_STORE_MANIFESTS"):
        _module().verify_preflight_binding(
            store,
            _protocol(),
            passing,
        )


@pytest.mark.parametrize(
    "scenario",
    (
        "multiple_sector_tables",
        "malformed_first_sector_with_valid_alias",
        "dual_sector_dates",
        "wrong_typed_sector_dates",
        "dual_suspension_dates",
        "dual_delisting_dates",
        "wrong_typed_suspension_dates",
        "wrong_typed_delisting_dates",
    ),
)
def test_ambiguous_or_wrong_typed_lookup_schema_fails_closed(
    tmp_path,
    scenario,
):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    reports = _reviews(tmp_path, sources)
    passing = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=reports,
    )
    assert passing.passed is True

    _mutate_lookup_schema(store, scenario)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=reports,
    )

    assert result.passed is False
    assert result.dataset_manifest_sha256 is None
    assert "STORE_MANIFESTS" in result.blockers
    with pytest.raises(ValueError, match="PREFLIGHT_STORE_MANIFESTS"):
        _module().verify_preflight_binding(
            store,
            _protocol(),
            passing,
        )


@pytest.mark.parametrize("artifact", ("catalogue", "review"))
def test_binding_rereads_canonical_catalogue_and_review_artifact_bytes(
    tmp_path, artifact
):
    catalogue, sources, _ = _catalogue(tmp_path)
    reports = _reviews(tmp_path, sources)
    store = _store(tmp_path)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=reports,
    )
    target = catalogue if artifact == "catalogue" else reports[0]
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(
        ValueError,
        match=(
            "PREFLIGHT_CATALOGUES"
            if artifact == "catalogue"
            else "PREFLIGHT_REVIEWS"
        ),
    ):
        _module().verify_preflight_binding(store, _protocol(), result)


def test_binding_rereads_and_revalidates_tri_semantics(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path)
    store = _store(tmp_path)
    reports = _reviews(tmp_path, sources)
    result = _module().run_preflight(
        store,
        _protocol(),
        source_catalogues=[catalogue],
        review_reports=reports,
    )
    payload = json.loads(json.dumps(result.manifest_payload))
    payload["store_manifest_hashes"] = {
        domain: tuple(hashes)
        for domain, hashes in payload["store_manifest_hashes"].items()
    }
    aggregates = json.loads(json.dumps(result.aggregates))
    tri_record = next(
        record
        for record in payload["sources"]
        if record["domain"] == "tri"
    )
    tri_path = tmp_path / tri_record["path"]
    invalid_tri = canonical_json_bytes({"normalized_rows": []})
    tri_path.write_bytes(invalid_tri)
    old_tri_hash = tri_record["sha256"]
    tri_record["sha256"] = _sha256(invalid_tri)

    catalogue_records = [
        json.loads(line)
        for line in catalogue.read_text().splitlines()
    ]
    next(
        record
        for record in catalogue_records
        if record["domain"] == "tri"
    )["sha256"] = tri_record["sha256"]
    catalogue.write_bytes(b"".join(
        canonical_json_bytes(record)
        for record in catalogue_records
    ))
    old_catalogue_hash = payload["catalogue_hashes"][0]
    new_catalogue_hash = _sha256(catalogue.read_bytes())
    payload["source_hashes"] = sorted(
        record["sha256"] for record in payload["sources"]
    )
    payload["catalogues"][0]["sha256"] = new_catalogue_hash
    payload["catalogue_hashes"] = [new_catalogue_hash]
    aggregates["hashes"]["retained"] = sorted(
        (
            set(aggregates["hashes"]["retained"])
            - {old_tri_hash, old_catalogue_hash}
        )
        | {tri_record["sha256"], new_catalogue_hash}
    )
    forged = replace(
        result,
        aggregates=aggregates,
        manifest_payload=payload,
        dataset_manifest_sha256=sha256_json(payload),
    )

    with pytest.raises(ValueError, match="PREFLIGHT_TRI"):
        _module().verify_preflight_binding(
            store,
            _protocol(),
            forged,
        )


def test_one_day_five_year_calendar_fails_even_with_explicit_closures(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path, one_session=True)
    result = _module().run_preflight(
        _store(tmp_path), _protocol(), source_catalogues=[catalogue], review_reports=_reviews(tmp_path, sources)
    )

    assert result.passed is False
    assert result.dataset_manifest_sha256 is None
    assert "CALENDAR" in result.blockers


def test_calendar_omission_fails_closed(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path)
    records = [json.loads(line) for line in catalogue.read_text().splitlines()]
    calendar = next(record for record in records if record["domain"] == "calendar")
    path = tmp_path / calendar["path"]
    payload = json.loads(path.read_text())
    payload["sessions"].pop()
    calendar["sha256"] = _write_json(path, payload, canonical=True)
    catalogue.write_bytes(b"".join(canonical_json_bytes(record) for record in records))

    result = _module().run_preflight(
        _store(tmp_path), _protocol(), source_catalogues=[catalogue], review_reports=_reviews(tmp_path, sources)
    )

    assert result.passed is False
    assert "CALENDAR" in result.blockers


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_required_retained_domain_blocks_when_missing(tmp_path, domain):
    result = _run(tmp_path, omit_source=domain)

    assert result.passed is False
    assert result.dataset_manifest_sha256 is None
    assert domain.upper() in result.blockers


@pytest.mark.parametrize(
    ("kwargs", "blocker"),
    [
        ({"missing_bar": True}, "BARS"),
        ({"missing_fundamental": True}, "FUNDAMENTALS"),
        ({"missing_halal": True}, "HALAL"),
    ],
)
def test_as_of_coverage_requires_every_active_member_session(tmp_path, kwargs, blocker):
    result = _run(tmp_path, **kwargs)

    assert result.passed is False
    assert result.dataset_manifest_sha256 is None
    assert blocker in result.blockers


def test_complete_zero_action_store_passes_with_retained_action_snapshots(tmp_path):
    result = _run(tmp_path)

    assert result.passed is True
    assert result.aggregates["coverage"]["corporate_actions"]["ratio"] == 1.0


def test_review_source_hash_must_link_to_verified_retained_artifact(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path)
    reports = _reviews(tmp_path, sources)
    payload = json.loads(reports[0].read_text())
    payload["source_sha256"] = "f" * 64
    _write_json(reports[0], payload, canonical=True)

    result = _module().run_preflight(
        _store(tmp_path), _protocol(), source_catalogues=[catalogue], review_reports=reports
    )

    assert result.passed is False
    assert "BUSINESS_REVIEWS" in result.blockers


def test_provenance_requires_canonical_utc_and_retained_root(tmp_path):
    catalogue, sources, _ = _catalogue(tmp_path)
    records = [json.loads(line) for line in catalogue.read_text().splitlines()]
    records[0]["available_at"] = "2013-11-30T00:00:00+00:00"
    records[1]["path"] = str((tmp_path / "outside.json").resolve())
    (tmp_path / "outside.json").write_bytes(b"{}")
    catalogue.write_bytes(b"".join(canonical_json_bytes(record) for record in records))

    result = _module().run_preflight(
        _store(tmp_path), _protocol(), source_catalogues=[catalogue], review_reports=_reviews(tmp_path, sources)
    )

    assert result.passed is False
    assert {records[0]["domain"].upper(), records[1]["domain"].upper()} <= set(result.blockers)


def test_every_valid_material_provenance_change_changes_manifest(tmp_path):
    first = _run(tmp_path / "first")
    catalogue, sources, _ = _catalogue(tmp_path / "changed")
    records = [json.loads(line) for line in catalogue.read_text().splitlines()]
    next(
        record for record in records if record["domain"] == "calendar"
    )["available_at"] = "2013-11-29T00:00:00Z"
    catalogue.write_bytes(b"".join(canonical_json_bytes(record) for record in records))
    reports = _reviews(tmp_path / "changed", sources)
    payload = json.loads(reports[0].read_text())
    payload["reviewed_at"] = "2020-01-03T00:00:00Z"
    _write_json(reports[0], payload, canonical=True)
    changed = _module().run_preflight(
        _store(tmp_path / "changed"), _protocol(), source_catalogues=[catalogue], review_reports=reports
    )

    assert first.passed is changed.passed is True
    assert first.dataset_manifest_sha256 != changed.dataset_manifest_sha256


def test_recursive_aggregate_allowlist_rejects_identifier_under_innocuous_key(tmp_path):
    result = _run(tmp_path)
    _assert_aggregate_schema(result.aggregates)
    leaked = json.loads(json.dumps(result.aggregates))
    leaked["calendar"]["sessions"] = "SYNTH"

    with pytest.raises(AssertionError):
        _assert_aggregate_schema(leaked)


def test_tri_validator_receives_all_canonical_calendar_sessions(tmp_path, monkeypatch):
    calls = []

    def validate(rows, sessions):
        calls.append((rows, tuple(sessions)))

    module = _module()
    monkeypatch.setattr(module.nifty_tri, "validate_tri_session_coverage", validate)
    result = _run(tmp_path)

    assert result.passed is True
    assert calls and calls[0][1] == _sessions()
    assert len(calls[0][0]) == len(_sessions())
    assert all(row["tri"] == 1.0 for row in calls[0][0])


@pytest.mark.parametrize("content", MALFORMED_CONTENTS)
def test_malformed_hash_valid_calendar_always_returns_calendar_blocker(tmp_path, content):
    catalogue, sources, _ = _catalogue(tmp_path)
    _rewrite_source(catalogue, "calendar", content)
    store = _store(tmp_path)
    reports = _reviews(tmp_path, sources)

    _assert_named_stable_blocker(
        lambda: _module().run_preflight(
            store, _protocol(), source_catalogues=[catalogue], review_reports=reports
        ),
        "CALENDAR",
    )


@pytest.mark.parametrize("content", MALFORMED_CONTENTS)
def test_malformed_hash_valid_tri_always_returns_tri_blocker(tmp_path, content):
    catalogue, sources, _ = _catalogue(tmp_path)
    _rewrite_source(catalogue, "tri", content)
    store = _store(tmp_path)
    reports = _reviews(tmp_path, sources)

    _assert_named_stable_blocker(
        lambda: _module().run_preflight(
            store, _protocol(), source_catalogues=[catalogue], review_reports=reports
        ),
        "TRI",
    )


@pytest.mark.parametrize("content", MALFORMED_CONTENTS)
def test_malformed_source_catalogue_always_returns_catalogue_blocker(tmp_path, content):
    catalogue, sources, _ = _catalogue(tmp_path)
    catalogue.write_bytes(content)
    store = _store(tmp_path)
    reports = _reviews(tmp_path, sources)

    _assert_named_stable_blocker(
        lambda: _module().run_preflight(
            store, _protocol(), source_catalogues=[catalogue], review_reports=reports
        ),
        "SOURCE_CATALOGUES",
    )


@pytest.mark.parametrize("content", MALFORMED_CONTENTS)
def test_malformed_review_always_returns_review_blocker(tmp_path, content):
    catalogue, sources, _ = _catalogue(tmp_path)
    reports = _reviews(tmp_path, sources)
    reports[0].write_bytes(content)
    store = _store(tmp_path)

    _assert_named_stable_blocker(
        lambda: _module().run_preflight(
            store, _protocol(), source_catalogues=[catalogue], review_reports=reports
        ),
        "REVIEW_REPORTS",
    )


@pytest.mark.parametrize(
    ("artifact", "content", "blocker"),
    [
        ("calendar", b'{"bounds":NaN}\n', "CALENDAR"),
        ("tri", b'{"normalized_rows":NaN}\n', "TRI"),
        ("catalogue", b'{"domain":"calendar","extra":NaN}\n', "SOURCE_CATALOGUES"),
        ("review", b'{"kind":"business_reviews","extra":NaN}\n', "REVIEW_REPORTS"),
    ],
)
def test_nonfinite_mapping_payloads_are_contained_by_artifact_boundary(
    tmp_path, artifact, content, blocker
):
    catalogue, sources, _ = _catalogue(tmp_path)
    reports = _reviews(tmp_path, sources)
    if artifact in {"calendar", "tri"}:
        _rewrite_source(catalogue, artifact, content)
    elif artifact == "catalogue":
        catalogue.write_bytes(content)
    else:
        reports[0].write_bytes(content)
    store = _store(tmp_path)

    _assert_named_stable_blocker(
        lambda: _module().run_preflight(
            store, _protocol(), source_catalogues=[catalogue], review_reports=reports
        ),
        blocker,
    )


def test_preflight_module_has_no_strategy_dependencies_or_calls(tmp_path, monkeypatch):
    path = Path("src/reliability/experiment_preflight.py")
    tree = ast.parse(path.read_text())
    forbidden_modules = {
        "src.reliability.residual_momentum",
        "src.reliability.portfolio_simulator",
        "src.reliability.historical_portfolio",
        "src.reliability.walk_forward",
    }
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imports & forbidden_modules

    guarded_callables = [
        ("src.reliability.residual_momentum", "compute_scores"),
        ("src.reliability.portfolio_simulator", "simulate_shared_portfolio"),
        ("src.reliability.historical_portfolio", "run_static_universe_diagnostic"),
        ("src.reliability.walk_forward", "evaluate_regimes"),
    ]
    for module_name, attribute in guarded_callables:
        dependency = importlib.import_module(module_name)
        monkeypatch.setattr(
            dependency,
            attribute,
            lambda *_args, **_kwargs: pytest.fail("forbidden strategy/evaluator call"),
        )

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in forbidden_modules:
            raise AssertionError(f"forbidden import: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    sys.modules.pop("src.reliability.experiment_preflight", None)
    module = importlib.import_module("src.reliability.experiment_preflight")
    catalogue, sources, _ = _catalogue(tmp_path)
    result = module.run_preflight(
        _store(tmp_path), _protocol(), source_catalogues=[catalogue], review_reports=_reviews(tmp_path, sources)
    )
    assert result.passed is True
