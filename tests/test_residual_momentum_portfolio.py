import ast
import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import src.reliability.experiment_preflight as experiment_preflight
import src.reliability.historical_portfolio as historical_portfolio
from src.reliability.experiment_preflight import PreflightResult, run_preflight
from src.reliability.experiment_registry import ExperimentRegistry
from src.reliability.historical_portfolio import (
    ResidualPortfolioDataError,
    run_residual_momentum_evaluation,
)
from src.reliability.preregistration import canonical_json_bytes, sha256_json
from src.reliability.store import ReliabilityStore


SOURCE_DOMAINS = (
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
REVIEW_KINDS = (
    "business_reviews",
    "concept_reviews",
    "pdf_reviews",
    "delistings",
)


def _reviewed_factor_payload(factor):
    return {
        "adjustment_factor": factor,
        "review_provenance": {
            "review_id": "reviewed-factor-fixture",
            "method": "retained primary evidence",
            "evidence_path": "evidence/reviewed-factor.json",
            "evidence_sha256": "a" * 64,
            "evidence_source_url": "https://www.nseindia.com/reviewed-factor",
            "confirmed_available_at": "2026-01-13T18:00:00Z",
            "reviewer_id": "independent-test-reviewer",
            "reviewed_at": "2026-01-14T00:00:00Z",
        },
    }


def _preflight(store, protocol, *, passed=True, claimed_reproducible=None):
    root = store.path.parent
    start = protocol["periods"]["warmup"][0]
    end = protocol["periods"]["scored"][1]
    blockers = set()
    sources, catalogue_records = experiment_preflight._sources(
        [root / "source-catalogue.jsonl"], start, end, blockers
    )
    sessions, closures, weekday_count = (
        experiment_preflight._calendar_sessions(
            sources.get("calendar"), start, end, blockers
        )
    )
    coverage, referenced_hashes = experiment_preflight._store_coverage(
        store, sessions
    )
    store_manifest_hashes = (
        experiment_preflight._bind_store_manifest_sources(
            store, referenced_hashes, sources
        )
    )
    _, review_records = experiment_preflight._reviews(
        sorted((root / "reviews").glob("*.json")),
        sources,
        start,
        end,
        len(sessions),
        blockers,
    )
    assert not blockers
    source_records = [sources[key].record for key in sorted(sources)]
    source_hashes = tuple(sorted(
        record["sha256"] for record in source_records
    ))
    catalogue_hashes = tuple(sorted(
        record["sha256"] for record in catalogue_records
    ))
    review_hashes = tuple(sorted(
        record["sha256"] for record in review_records
    ))
    aggregates = {
        "date_bounds": {
            "start": start,
            "end": end,
        },
        "calendar": {
            "weekdays": weekday_count,
            "sessions": len(sessions),
            "closures": len(closures),
        },
        "coverage": {
            **coverage,
            **{
                domain: {
                    "expected": len(sessions),
                    "observed": len(sessions),
                    "ratio": 1.0,
                }
                for domain in (
                    "calendar",
                    "corporate_actions",
                    "suspensions",
                    "delistings",
                )
            },
        },
        "hashes": {
            "protocol": sha256_json(protocol),
            "retained": tuple(
                sorted(set(source_hashes) | set(catalogue_hashes))
            ),
            "reviews": review_hashes,
        },
    }
    if claimed_reproducible is not None:
        aggregates["reproducibility_verified"] = claimed_reproducible
    manifest_payload = {
        "aggregate_coverage": coverage,
        "calendar": aggregates["calendar"],
        "catalogues": catalogue_records,
        "catalogue_hashes": catalogue_hashes,
        "closures": tuple(closure.isoformat() for closure in closures),
        "protocol_sha256": sha256_json(protocol),
        "reviews": review_records,
        "review_hashes": review_hashes,
        "schema_version": 2,
        "sessions": tuple(session.isoformat() for session in sessions),
        "source_hashes": source_hashes,
        "sources": source_records,
        "store_manifest_hashes": store_manifest_hashes,
    }
    manifest_payload["aggregate_coverage"] = aggregates["coverage"]
    return PreflightResult(
        passed=passed,
        blockers=() if passed else ("BARS",),
        aggregates=aggregates,
        dataset_manifest_sha256=(
            sha256_json(manifest_payload) if passed else None
        ),
        manifest_payload=manifest_payload if passed else None,
    )


def _install_test_provenance(
    store,
    root,
    *,
    start,
    end,
    sessions,
    closures=(),
    fixture="task6",
):
    root = Path(root)
    retained = root / "retained"
    retained.mkdir(parents=True, exist_ok=True)
    prior = (
        pd.Timestamp(start) - pd.Timedelta(days=1)
    ).date().isoformat() + "T00:00:00Z"
    reviewed_at = (
        pd.Timestamp(end) + pd.Timedelta(days=1)
    ).date().isoformat() + "T00:00:00Z"
    source_hashes = {}
    records = []
    for domain in SOURCE_DOMAINS:
        path = retained / f"{domain}.json"
        if domain == "calendar":
            payload = {
                "bounds": {"start": start, "end": end},
                "closures": [
                    pd.Timestamp(day).date().isoformat()
                    for day in closures
                ],
                "schema_version": 1,
                "sessions": [
                    pd.Timestamp(day).date().isoformat()
                    for day in sessions
                ],
            }
        elif domain == "tri":
            payload = {
                "normalized_rows": [
                    {
                        "session_date": pd.Timestamp(day).date().isoformat(),
                        "tri": 1.0,
                    }
                    for day in sessions
                ],
            }
        else:
            payload = {"domain": domain, "fixture": fixture}
        content = canonical_json_bytes(payload)
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        source_hashes[domain] = digest
        records.append({
            "available_at": prior,
            "coverage": {
                "end": end,
                "expected_sessions": len(sessions),
                "observed_sessions": len(sessions),
                "start": start,
            },
            "domain": domain,
            "path": str(path.relative_to(root)),
            "sha256": digest,
            "source_id": (
                "NIFTY INDICES" if domain == "tri" else "NSE"
            ),
            "status": "downloaded",
        })
    (root / "source-catalogue.jsonl").write_bytes(b"".join(
        canonical_json_bytes(record)
        for record in sorted(records, key=lambda item: item["domain"])
    ))
    reviews = root / "reviews"
    reviews.mkdir(parents=True, exist_ok=True)
    for kind in REVIEW_KINDS:
        (reviews / f"{kind}.json").write_bytes(canonical_json_bytes({
            "coverage": {
                "end": end,
                "expected_sessions": len(sessions),
                "observed_sessions": len(sessions),
                "start": start,
            },
            "kind": kind,
            "reviewed_at": reviewed_at,
            "source_id": "INTERNAL REVIEW",
            "source_sha256": source_hashes["halal_evidence"],
            "status": "VERIFIED",
            "unresolved_queue_count": 0,
        }))
    manifests = {
        domain: store.register_manifest(
            "NSE",
            (retained / f"{source_domain}.json").read_bytes(),
            prior,
            {"domain": source_domain},
        )
        for domain, source_domain in {
            "constituents": "constituents",
            "bars": "bars",
            "corporate_actions": "corporate_actions",
            "sectors_industry": "sectors_industry",
            "suspensions": "suspensions",
            "delistings": "delistings",
            "fundamentals": "fundamentals",
            "halal": "halal_evidence",
        }.items()
    }
    return manifests, prior


def _protocol(_registry_path=None, **overrides):
    protocol = {
        "family": "synthetic-residual",
        "periods": {
            "warmup": ["2026-01-01", "2026-01-09"],
            "scored": ["2026-01-12", "2026-02-20"],
        },
        "parameters": {
            "momentum_long": 5,
            "skip": 1,
            "selection_limit": 5,
            "correlation_lookback": 3,
            "max_correlation": 1.0,
            "volatility_lookback": 3,
            "atr": 2,
            "max_hold_sessions": 8,
            "initial_capital": 100_000,
            "liquidity_cap": 0.05,
        },
        "statistical_policy": {"n_trials_floor": 7, "bootstrap_samples": 100},
    }
    protocol.update(overrides)
    return protocol


def _create_auxiliary_tables(store):
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


def _replace_runtime_lookup_column_type(
    store,
    table,
    target_column,
):
    rows = store.connection.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()
    definitions = [
        f'"{row["name"]}" '
        f'{"BLOB" if row["name"] == target_column else row["type"]}'
        for row in rows
    ]
    columns = ", ".join(f'"{row["name"]}"' for row in rows)
    store.connection.execute(
        f'ALTER TABLE "{table}" RENAME TO "{table}_valid"'
    )
    store.connection.execute(
        f'CREATE TABLE "{table}" ({", ".join(definitions)})'
    )
    store.connection.execute(
        f'INSERT INTO "{table}" ({columns}) '
        f'SELECT {columns} FROM "{table}_valid"'
    )
    store.connection.commit()


def _add_runtime_sector_alias(store):
    store.connection.execute(
        """
        CREATE TABLE sectors_industry (
            symbol TEXT,
            sector TEXT,
            effective_from TEXT,
            available_at TEXT,
            manifest_hash TEXT
        )
        """
    )
    store.connection.execute(
        """
        INSERT INTO sectors_industry
        SELECT symbol, sector, effective_from, available_at, manifest_hash
        FROM sector_classifications
        """
    )
    store.connection.commit()


def _mutate_runtime_lookup_schema(store, scenario):
    if scenario == "multiple_sector_tables":
        _add_runtime_sector_alias(store)
        return
    if scenario == "malformed_first_sector_with_valid_alias":
        _replace_runtime_lookup_column_type(
            store,
            "sector_classifications",
            "effective_from",
        )
        _add_runtime_sector_alias(store)
        return
    if scenario in {"dual_sector_dates", "wrong_typed_sector_dates"}:
        table = "sector_classifications"
    elif scenario.endswith("suspension_dates"):
        table = "suspensions"
    else:
        table = "delistings"
    store.connection.execute(
        f"ALTER TABLE {table} ADD COLUMN session_date TEXT"
    )
    store.connection.execute(
        f"UPDATE {table} SET session_date = effective_from"
    )
    store.connection.commit()
    if scenario.startswith("wrong_typed"):
        _replace_runtime_lookup_column_type(
            store,
            table,
            "effective_from",
        )


def _seed_store(tmp_path, *, missing=None):
    store = ReliabilityStore(tmp_path / "portfolio.db")
    _create_auxiliary_tables(store)
    registry_path = tmp_path / "registry.jsonl"
    registry_path.write_text("", encoding="utf-8")
    sessions = pd.bdate_range("2026-01-01", "2026-02-20")
    protocol = _protocol(registry_path)
    manifests, prior = _install_test_provenance(
        store,
        tmp_path,
        start=protocol["periods"]["warmup"][0],
        end=protocol["periods"]["scored"][1],
        sessions=sessions,
        fixture="portfolio",
    )
    tri = pd.Series(
        [1000 + position * 2 for position in range(len(sessions))], index=sessions, dtype=float
    )
    symbols = ("GAP", "INTRA", "HOLD", "FORCED", "RANK", "EXTRA")
    for symbol in symbols:
        store.put_membership(
            symbol, "2025-12-31", prior, manifests["constituents"]
        )
        store.put_fundamental(
            symbol,
            "2025-12-31",
            prior,
            manifests["fundamentals"],
            0.1,
            0.01,
        )
        if not (missing == "halal" and symbol == "GAP"):
            store.put_halal_classification(
                symbol,
                "2025-12-31",
                "GREEN",
                True,
                "synthetic-v1",
                prior,
                manifests["halal"],
            )
        if not (missing == "sector" and symbol == "GAP"):
            store.connection.execute(
                "INSERT INTO sector_classifications VALUES (?, ?, ?, ?, ?)",
                (
                    symbol,
                    "TECH" if symbol != "RANK" else "HEALTH",
                    "2025-12-31",
                    prior,
                    manifests["sectors_industry"],
                ),
            )
        for position, day in enumerate(sessions):
            close = 100 + position * 1.5
            if symbol == "RANK" and position < 14:
                close = 120 + position * 3
            if symbol == "RANK" and position >= 14:
                close = 153 - (position - 14) * 0.05
            if symbol == "INTRA" and position < 13:
                close = 110 + position * 2.5
            if symbol == "EXTRA":
                close = 85 + position * 1.5
            open_ = close - 0.5
            high, low = close + 1, close - 1
            if symbol == "GAP" and position == 13:
                open_, high, low, close = 80, 82, 79, 81
            if symbol == "INTRA" and position == 13:
                open_, high, low, close = 140, 141, 75, 140
            if missing == "next_open" and symbol == "GAP" and position == 12:
                continue
            store.put_bar(
                symbol, day.date().isoformat(), open_, open_, open_, open_, 10_000,
                f"{day.date().isoformat()}T03:45:00Z", manifests["bars"],
            )
            store.put_bar(
                symbol, day.date().isoformat(), open_, high, low, close, 10_000,
                f"{day.date().isoformat()}T10:00:00Z", manifests["bars"],
            )

    if missing != "halal":
        store.put_halal_classification(
            "FORCED",
            "2026-01-20",
            "RED",
            False,
            "synthetic-v1",
            "2026-01-20T18:00:00Z",
            manifests["halal"],
        )
    if missing != "corporate_action":
        store.put_corporate_action(
            "HOLD", "SPLIT", "2026-01-16", {
                **_reviewed_factor_payload(0.25),
                "purpose": "Face Value Split From Rs 10 Per Share To Rs 5 Per Share",
            },
            "2026-01-15T18:00:00Z", manifests["corporate_actions"],
        )
    else:
        store.put_corporate_action(
            "HOLD", "SPLIT", "2026-01-16", {"purpose": "unquantified"},
            "2026-01-15T18:00:00Z", manifests["corporate_actions"],
        )
    store.connection.execute(
        "INSERT INTO suspensions VALUES (?, ?, ?, ?)",
        (
            "FORCED",
            "2026-01-20",
            "2026-01-19T18:00:00Z",
            manifests["suspensions"],
        ),
    )
    store.connection.execute(
        "INSERT INTO delistings VALUES (?, ?, ?, ?)",
        (
            "FORCED",
            "2026-02-01",
            "2026-02-01T18:00:00Z",
            manifests["delistings"],
        ),
    )
    store.connection.commit()
    if missing == "benchmark":
        tri = tri.drop(pd.Timestamp("2026-01-20"))
    return store, protocol, tri, registry_path


def test_rejects_preflight_without_passing_hash(tmp_path):
    store, protocol, tri, registry_path = _seed_store(tmp_path)
    preflight = replace(
        _preflight(store, protocol),
        dataset_manifest_sha256=None,
    )

    with pytest.raises(ResidualPortfolioDataError, match="PREFLIGHT_DATASET"):
        run_residual_momentum_evaluation(
            store, protocol=protocol, benchmark_tri=tri,
            preflight=preflight, registry=ExperimentRegistry(registry_path),
            effective_n_trials=7,
        )


def test_requires_bound_hashes_and_an_explicit_read_only_registry(tmp_path):
    store, protocol, tri, registry_path = _seed_store(tmp_path)
    changed_protocol = {**protocol, "family": "changed-family"}

    with pytest.raises(ResidualPortfolioDataError, match="PREFLIGHT_PROTOCOL"):
        run_residual_momentum_evaluation(
            store, protocol=changed_protocol, benchmark_tri=tri,
            preflight=_preflight(store, protocol),
            registry=ExperimentRegistry(registry_path),
            effective_n_trials=7,
        )


def test_runs_weekly_point_in_time_portfolio_with_shared_cash_and_evidence(tmp_path):
    store, protocol, tri, registry_path = _seed_store(tmp_path)
    before_registry = hashlib.sha256(registry_path.read_bytes()).hexdigest()
    preflight = _preflight(store, protocol)

    report = run_residual_momentum_evaluation(
        store, protocol=protocol, benchmark_tri=tri,
        preflight=preflight,
        registry=ExperimentRegistry(registry_path),
        effective_n_trials=7,
    )

    assert report["verdict"] == "REJECTED"
    assert report["release_approved"] is False
    assert report["assumptions"]["fill_cost_bps"] == 15
    assert report["source_hashes"]["dataset_manifest"] == (
        preflight.dataset_manifest_sha256
    )
    assert report["n_trials"] >= 7
    assert report["decisions"]
    assert all(pd.Timestamp(row["decision_date"]).weekday() == 4 for row in report["decisions"])
    assert all(trade["entry_date"] > trade["decision_date"] for trade in report["trades"])
    assert all(weight <= 0.10 for row in report["decisions"] for weight in row["weights"].values())
    assert all(sum(row["weights"].values()) <= 0.80 for row in report["decisions"])
    assert report["costs"]["total"] == pytest.approx(0.0015 * report["costs"]["notional"])
    assert {"forced_exit", "intraday_stop"} <= {
        trade["exit_reason"] for trade in report["trades"]
    }
    assert report["coverage"]["sessions"] == len(tri)
    assert report["coverage"]["scored_sessions"] == len(report["portfolio"]["nav"])
    assert report["overall"]["metrics"]["observations"] == len(report["portfolio"]["nav"])
    assert any(row["retained_holding_ages"] for row in report["decisions"])
    assert report["overall"]["failed_gates"]
    assert report["regimes"]["regimes"]
    assert hashlib.sha256(registry_path.read_bytes()).hexdigest() == before_registry


@pytest.mark.parametrize(
    ("missing", "error"),
    [
        ("next_open", "PREFLIGHT_COVERAGE"),
        ("corporate_action", "MISSING_CORPORATE_ACTION_FACTOR"),
        ("halal", "PREFLIGHT_COVERAGE"),
        ("sector", "PREFLIGHT_COVERAGE"),
        ("benchmark", "MISSING_BENCHMARK_SESSION"),
    ],
)
def test_missing_point_in_time_inputs_fail_closed_with_named_error(tmp_path, missing, error):
    store, protocol, tri, registry_path = _seed_store(tmp_path, missing=missing)

    with pytest.raises(ResidualPortfolioDataError, match=error):
        run_residual_momentum_evaluation(
            store, protocol=protocol, benchmark_tri=tri,
            preflight=_preflight(store, protocol),
            registry=ExperimentRegistry(registry_path),
            effective_n_trials=7,
        )


def test_future_revisions_do_not_change_a_point_in_time_result(tmp_path):
    store, protocol, tri, registry_path = _seed_store(tmp_path)
    baseline = run_residual_momentum_evaluation(
        store, protocol=protocol, benchmark_tri=tri,
        preflight=_preflight(store, protocol),
        registry=ExperimentRegistry(registry_path),
        effective_n_trials=7,
    )
    manifest = store.register_manifest("future", b"future", "2027-01-01T18:00:00Z")
    store.put_bar("GAP", "2026-01-15", 1, 1, 1, 1, 99_999_999, "2027-01-01T18:00:00Z", manifest)
    store.put_halal_classification(
        "GAP", "2026-01-01", "RED", False, "future-v1", "2027-01-01T18:00:00Z", manifest
    )

    revised = run_residual_momentum_evaluation(
        store, protocol=protocol, benchmark_tri=tri,
        preflight=_preflight(store, protocol),
        registry=ExperimentRegistry(registry_path),
        effective_n_trials=7,
    )

    assert revised["decisions"] == baseline["decisions"]
    assert revised["trades"] == baseline["trades"]
    assert revised["portfolio"]["nav"].equals(baseline["portfolio"]["nav"])


def test_reselection_does_not_create_a_second_buy_or_reset_the_position(tmp_path):
    store, protocol, tri, registry_path = _seed_store(tmp_path)
    report = run_residual_momentum_evaluation(
        store, protocol=protocol, benchmark_tri=tri,
        preflight=_preflight(store, protocol),
        registry=ExperimentRegistry(registry_path),
        effective_n_trials=7,
    )

    buys = [event for event in report.get("ledger", []) if event["kind"] == "BUY"]
    assert buys
    assert len({(event["ticker"], event["decision_date"]) for event in buys}) == len(buys)


def _independent_sha256_json(value):
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256((encoded + "\n").encode("utf-8")).hexdigest()


def _seed_independent_ledger_store(
    tmp_path,
    *,
    close_exit_open=55.0,
    dividend_payload=None,
    predecision_traded_value_multiplier=1.0,
    post_decision_traded_value=120_000.0,
    buy_day_close=102.0,
    buy_day_intraday_stop=False,
    extra_symbols=(),
    sector_overrides=None,
    calendar_sessions=None,
    closures=(),
    extra_bar_dates=(),
    extra_bar_price=100.0,
    include_split=True,
    ledger_price_overrides=None,
    suspension_date="2026-01-19",
):
    store = ReliabilityStore(tmp_path / "independent-ledger.db")
    _create_auxiliary_tables(store)
    registry_path = tmp_path / "independent-registry.jsonl"
    registry_path.write_text("", encoding="utf-8")
    sessions = pd.DatetimeIndex(
        calendar_sessions
        if calendar_sessions is not None
        else pd.bdate_range("2026-01-01", "2026-01-23")
    )
    protocol = _protocol(
        periods={
            "warmup": ["2026-01-01", "2026-01-08"],
            "scored": ["2026-01-09", "2026-01-23"],
        }
    )
    manifests, prior = _install_test_provenance(
        store,
        tmp_path,
        start=protocol["periods"]["warmup"][0],
        end=protocol["periods"]["scored"][1],
        sessions=sessions,
        closures=closures,
        fixture="independent-ledger",
    )
    benchmark = pd.Series(
        [100.0 + position for position in range(len(sessions))],
        index=sessions,
        dtype=float,
    )
    traded_values = {
        "2026-01-01": 80_000.0 * predecision_traded_value_multiplier,
        "2026-01-02": 90_000.0 * predecision_traded_value_multiplier,
        "2026-01-05": 100_000.0 * predecision_traded_value_multiplier,
        "2026-01-06": 110_000.0 * predecision_traded_value_multiplier,
        "2026-01-07": 120_000.0 * predecision_traded_value_multiplier,
        "2026-01-08": 130_000.0 * predecision_traded_value_multiplier,
        "2026-01-09": 70_000.0 * predecision_traded_value_multiplier,
    }
    ledger_prices = {
        "2026-01-12": (
            100.0,
            max(103.0, buy_day_close + 1.0),
            80.0 if buy_day_intraday_stop else 99.0,
            buy_day_close,
        ),
        "2026-01-13": (102.0, 105.0, 101.0, 104.0),
        "2026-01-14": (50.0, 53.0, 49.0, 52.0),
        "2026-01-15": (52.0, 55.0, 51.0, 54.0),
        "2026-01-16": (54.0, 56.0, 53.0, 55.0),
        "2026-01-19": (55.0, 57.0, 54.0, 56.0),
    }
    ledger_prices.update(ledger_price_overrides or {})
    symbols = ("LEDGER", "WATCH", *extra_symbols)
    sectors = dict(sector_overrides or {})
    for symbol in symbols:
        store.put_membership(
            symbol, "2025-12-31", prior, manifests["constituents"]
        )
        store.put_fundamental(
            symbol,
            "2025-12-31",
            prior,
            manifests["fundamentals"],
            0.1,
            0.01,
        )
        store.put_halal_classification(
            symbol,
            "2025-12-31",
            "GREEN",
            True,
            "synthetic-v1",
            prior,
            manifests["halal"],
        )
        store.connection.execute(
            "INSERT INTO sector_classifications VALUES (?, ?, ?, ?, ?)",
            (
                symbol,
                sectors.get(
                    symbol,
                    "TECH" if symbol == "LEDGER" else f"SECTOR-{symbol}",
                ),
                "2025-12-31",
                prior,
                manifests["sectors_industry"],
            ),
        )
        for position, day in enumerate(sessions):
            day_text = day.date().isoformat()
            if symbol == "LEDGER":
                open_, high, low, close = ledger_prices.get(
                    day_text, (100.0, 101.0, 99.0, 100.0)
                )
                volume = traded_values.get(
                    day_text, post_decision_traded_value
                ) / close
            else:
                close = 200.0 + position
                open_, high, low = close - 1.0, close + 1.0, close - 2.0
                volume = 2_000.0
            store.put_bar(
                symbol,
                day_text,
                open_,
                open_,
                open_,
                open_,
                volume,
                f"{day_text}T03:45:00Z",
                manifests["bars"],
            )
            store.put_bar(
                symbol,
                day_text,
                (
                    close_exit_open
                    if symbol == "LEDGER" and day_text == "2026-01-19"
                    else open_
                ),
                (
                    max(high, close_exit_open, close)
                    if symbol == "LEDGER" and day_text == "2026-01-19"
                    else high
                ),
                (
                    min(low, close_exit_open, close)
                    if symbol == "LEDGER" and day_text == "2026-01-19"
                    else low
                ),
                close,
                volume,
                f"{day_text}T10:00:00Z",
                manifests["bars"],
            )

    for day in pd.DatetimeIndex(extra_bar_dates):
        day_text = day.date().isoformat()
        for symbol in symbols:
            price = extra_bar_price if symbol == "LEDGER" else 220.0
            store.put_bar(
                symbol,
                day_text,
                price,
                price,
                price,
                price,
                2_000.0,
                f"{day_text}T03:45:00Z",
                manifests["bars"],
            )
            store.put_bar(
                symbol,
                day_text,
                price,
                price + 1.0,
                price - 1.0,
                price,
                2_000.0,
                f"{day_text}T10:00:00Z",
                manifests["bars"],
            )

    if include_split:
        store.put_corporate_action(
            "LEDGER",
            "SPLIT",
            "2026-01-14",
            {
                **_reviewed_factor_payload(0.25),
                "purpose": "Face Value Split From Rs 10 Per Share To Rs 5 Per Share",
            },
            "2026-01-13T18:00:00Z",
            manifests["corporate_actions"],
        )
    store.put_corporate_action(
        "LEDGER",
        "DIVIDEND",
        "2026-01-15",
        dividend_payload
        or {"cash_amount": 1.0, "purpose": "Dividend - Rs 1 Per Share"},
        "2026-01-14T18:00:00Z",
        manifests["corporate_actions"],
    )
    if suspension_date is not None:
        store.connection.execute(
            "INSERT INTO suspensions VALUES (?, ?, ?, ?)",
            (
                "LEDGER",
                suspension_date,
                (
                    pd.Timestamp(suspension_date) - pd.Timedelta(days=1)
                ).date().isoformat() + "T18:00:00Z",
                manifests["suspensions"],
            ),
        )
    store.connection.commit()
    return store, protocol, benchmark, registry_path, manifests


def _passing_overall(strategy, benchmark, *, policy):
    return {
        "passed": True,
        "failed_gates": [],
        "metrics": {
            "observations": len(strategy),
            "annualized_excess_return": 0.12,
            "excess_return_ci_lower": 0.01,
            "excess_return_ci_upper": 0.20,
            "probability_outperformance": 0.99,
            "deflated_sharpe_probability": 0.99,
            "max_drawdown": 0.02,
        },
    }


def _passing_regimes(strategy, benchmark, regimes, policy):
    return {
        "passed": True,
        "regimes": {
            name: {
                "passed": True,
                "failed_gates": [],
                "metrics": {
                    "observations": 126,
                    "annualized_excess_return": 0.05,
                    "probability_outperformance": 0.90,
                    "max_drawdown": 0.02,
                },
            }
            for name in ("BULL", "BEAR", "SIDEWAYS")
        },
    }


def _run_independent_fixture(
    tmp_path,
    monkeypatch,
    *,
    claimed_reproducible=None,
    passing_statistics=False,
    selected=("LEDGER",),
    selection_start=None,
    weight=0.06,
    seed_kwargs=None,
):
    store, protocol, benchmark, registry_path, manifest = _seed_independent_ledger_store(
        tmp_path, **(seed_kwargs or {})
    )

    def fixed_selection(_scores, returns, **_kwargs):
        available = [symbol for symbol in selected if symbol in returns]
        if (
            selection_start is not None
            and returns.index[-1] < pd.Timestamp(selection_start)
        ):
            return []
        if returns.index[-1] < pd.Timestamp("2026-01-23"):
            return available
        return []

    monkeypatch.setattr(historical_portfolio, "select_candidates", fixed_selection)
    monkeypatch.setattr(
        historical_portfolio,
        "allocate_weights",
        lambda selected, *_args, **_kwargs: (
            {symbol: weight for symbol in selected}
        ),
    )
    if passing_statistics:
        monkeypatch.setattr(
            historical_portfolio, "evaluate_outperformance", _passing_overall
        )
        monkeypatch.setattr(
            historical_portfolio, "_pit_regimes", _passing_regimes
        )
    bound_preflight = _preflight(
        store,
        protocol,
        claimed_reproducible=claimed_reproducible,
    )
    report = run_residual_momentum_evaluation(
        store,
        protocol=protocol,
        benchmark_tri=benchmark,
        preflight=bound_preflight,
        registry=ExperimentRegistry(registry_path),
        effective_n_trials=7,
    )
    return report, protocol, benchmark, manifest, bound_preflight


def _real_acceptance_protocol():
    return {
        "experiment_id": "nse-halal-residual-momentum-v1",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v1",
        "periods": {
            "warmup": ["2013-12-01", "2014-12-31"],
            "scored": ["2015-01-01", "2019-12-31"],
            "burned": [["2020-01-01", "2024-06-30"]],
        },
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
        "parameters": {
            "momentum_long": 252,
            "skip": 21,
            "selection_limit": 10,
            "correlation_lookback": 63,
            "max_correlation": 0.80,
            "volatility_lookback": 63,
            "atr": 14,
            "max_hold_sessions": 20,
            "initial_capital": 100_000,
            "liquidity_cap": 0.05,
        },
        "statistical_policy": {
            "n_trials_floor": 7,
            "bootstrap_samples": 100,
        },
    }


def _seed_real_acceptance_composition(tmp_path):
    protocol = _real_acceptance_protocol()
    sessions = pd.bdate_range("2013-12-01", "2019-12-31")
    retained = tmp_path / "retained"
    retained.mkdir(parents=True)
    symbols = tuple(f"REAL{number:02d}" for number in range(10))
    member_sessions = [
        {
            "session_date": day.date().isoformat(),
            "symbol": symbol,
        }
        for day in sessions
        for symbol in symbols
    ]
    domains = (
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
    source_hashes = {}
    source_records = []
    for domain in domains:
        path = retained / f"{domain}.json"
        if domain == "calendar":
            payload = {
                "bounds": {"start": "2013-12-01", "end": "2019-12-31"},
                "closures": [],
                "schema_version": 1,
                "sessions": [
                    day.date().isoformat() for day in sessions
                ],
            }
        elif domain == "tri":
            payload = {
                "normalized_rows": [
                    {
                        "session_date": day.date().isoformat(),
                        "tri": 1.0,
                    }
                    for day in sessions
                ],
            }
        elif domain in {
            "constituents",
            "bars",
            "sectors_industry",
            "fundamentals",
            "halal_evidence",
        }:
            payload = {
                "bounds": {
                    "start": "2013-12-01",
                    "end": "2019-12-31",
                },
                "domain": domain,
                "member_sessions": member_sessions,
                "schema_version": 1,
            }
        else:
            payload = {
                "bounds": {
                    "start": "2013-12-01",
                    "end": "2019-12-31",
                },
                "domain": domain,
                "rows": [],
                "schema_version": 1,
            }
        content = canonical_json_bytes(payload)
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        source_hashes[domain] = digest
        source_records.append({
            "available_at": "2013-11-30T00:00:00Z",
            "coverage": {
                "end": "2019-12-31",
                "expected_sessions": len(sessions),
                "observed_sessions": len(sessions),
                "start": "2013-12-01",
            },
            "domain": domain,
            "path": str(path.relative_to(tmp_path)),
            "sha256": digest,
            "source_id": (
                "NIFTY INDICES" if domain == "tri" else "NSE"
            ),
            "status": "downloaded",
        })
    catalogue = tmp_path / "source-catalogue.jsonl"
    catalogue.write_bytes(b"".join(
        canonical_json_bytes(record)
        for record in sorted(source_records, key=lambda item: item["domain"])
    ))
    review_paths = []
    for kind in (
        "business_reviews",
        "concept_reviews",
        "pdf_reviews",
        "delistings",
    ):
        path = tmp_path / "reviews" / f"{kind}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes({
            "coverage": {
                "end": "2019-12-31",
                "expected_sessions": len(sessions),
                "observed_sessions": len(sessions),
                "start": "2013-12-01",
            },
            "kind": kind,
            "reviewed_at": "2020-01-02T00:00:00Z",
            "source_id": "INTERNAL REVIEW",
            "source_sha256": source_hashes["halal_evidence"],
            "status": "VERIFIED",
            "unresolved_queue_count": 0,
        }))
        review_paths.append(path)

    store = ReliabilityStore(tmp_path / "real-composition.db")
    _create_auxiliary_tables(store)
    manifests = {
        domain: store.register_manifest(
            "NSE",
            (retained / f"{source_domain}.json").read_bytes(),
            "2013-11-30T00:00:00Z",
            {"domain": source_domain},
        )
        for domain, source_domain in {
            "constituents": "constituents",
            "bars": "bars",
            "corporate_actions": "corporate_actions",
            "sectors_industry": "sectors_industry",
            "suspensions": "suspensions",
            "delistings": "delistings",
            "fundamentals": "fundamentals",
            "halal": "halal_evidence",
        }.items()
    }
    for number, symbol in enumerate(symbols):
        store.put_membership(
            symbol,
            "2013-12-01",
            "2013-11-30T00:00:00Z",
            manifests["constituents"],
        )
        store.put_fundamental(
            symbol,
            "2013-11-30",
            "2013-11-30T00:00:00Z",
            manifests["fundamentals"],
            0.10,
            0.01,
        )
        for revision in pd.date_range(
            "2013-11-30",
            "2019-12-31",
            freq="180D",
        ):
            store.put_halal_classification(
                symbol,
                revision.date().isoformat(),
                "GREEN",
                True,
                "real-composition-v1",
                f"{revision.date().isoformat()}T00:00:00Z",
                manifests["halal"],
            )
        store.connection.execute(
            "INSERT INTO sector_classifications VALUES (?, ?, ?, ?, ?)",
            (
                symbol,
                f"SECTOR-{number % 4}",
                "2013-11-30",
                "2013-11-30T00:00:00Z",
                manifests["sectors_industry"],
            ),
        )

    prices = {symbol: 100.0 for symbol in symbols}
    bar_rows = []
    for position, day in enumerate(sessions):
        day_text = day.date().isoformat()
        for number, symbol in enumerate(symbols):
            walsh_sign = (
                1.0
                if ((position % 32) & (number + 1)).bit_count() % 2 == 0
                else -1.0
            )
            daily_return = (
                -0.00002 + 0.00001 * walsh_sign
                if number == 0
                else 0.004 + 0.001 * walsh_sign
            )
            prices[symbol] *= 1.0 + daily_return
            price = prices[symbol]
            volume = 10_000_000.0 / price
            bar_rows.extend((
                {
                    "symbol": symbol,
                    "session_date": day_text,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": volume,
                    "available_at": f"{day_text}T03:45:00Z",
                },
                {
                    "symbol": symbol,
                    "session_date": day_text,
                    "open": price,
                    "high": price * 1.0005,
                    "low": price * 0.9995,
                    "close": price,
                    "volume": volume,
                    "available_at": f"{day_text}T10:00:00Z",
                },
            ))
    store.put_bars(bar_rows, manifests["bars"])
    store.connection.commit()

    benchmark_values = []
    benchmark_level = 100.0
    for day in sessions:
        if day.year == 2015:
            benchmark_return = 0.0002
        elif day.year in (2016, 2019):
            benchmark_return = -0.0004
        else:
            benchmark_return = 0.0
        benchmark_level *= 1.0 + benchmark_return
        benchmark_values.append(benchmark_level)
    benchmark = pd.Series(
        benchmark_values,
        index=sessions,
        dtype=float,
        name="NIFTY 50 TRI GROSS",
    )
    preflight = run_preflight(
        store,
        protocol,
        source_catalogues=[catalogue],
        review_reports=review_paths,
    )
    registry_path = tmp_path / "registry.jsonl"
    registry_path.write_text("", encoding="utf-8")
    return store, protocol, benchmark, preflight, registry_path


def test_real_preflight_and_real_statistics_compose_to_accepted_verdict(tmp_path):
    store, protocol, benchmark, preflight, registry_path = (
        _seed_real_acceptance_composition(tmp_path)
    )
    assert preflight.passed is True

    report = run_residual_momentum_evaluation(
        store,
        protocol=protocol,
        benchmark_tri=benchmark,
        preflight=preflight,
        registry=ExperimentRegistry(registry_path),
        effective_n_trials=7,
    )

    daily = report["exposure"]["daily"]
    orders = [
        event
        for event in report["ledger"]
        if event["kind"] in {"BUY", "SELL"}
    ]
    independent_gate_inputs = {
        "max_open_gross": max(row["open_gross_exposure"] for row in daily),
        "max_open_security": max(row["open_max_security"] for row in daily),
        "max_open_sector": max(row["open_max_sector"] for row in daily),
        "max_close_gross": max(row["gross_exposure"] for row in daily),
        "max_close_security": max(row["max_security"] for row in daily),
        "max_close_sector": max(row["max_sector"] for row in daily),
        "max_correlation": max(
            decision["max_pairwise_correlation"]
            for decision in report["decisions"]
        ),
        "max_participation": max(
            order["notional"] / (order["liquidity_notional"] / 0.05)
            for order in orders
        ),
    }

    assert report["verdict"] == "ACCEPTED"
    assert report["release_approved"] is False
    assert report["failed_gates"] == []
    assert report["overall"]["passed"] is True
    assert all(
        result["passed"] for result in report["regimes"]["regimes"].values()
    )
    assert all(
        result["metrics"]["observations"] >= 126
        for result in report["regimes"]["regimes"].values()
    )
    assert report["rejected_orders"] == []
    assert report["source_hashes"]["dataset_manifest"] == (
        preflight.dataset_manifest_sha256
    )
    assert all(report["verification"].values())
    for field, value in independent_gate_inputs.items():
        assert report["exposure"][field] == pytest.approx(value)
    assert max(
        independent_gate_inputs["max_open_gross"],
        independent_gate_inputs["max_close_gross"],
    ) <= 0.80
    assert max(
        independent_gate_inputs["max_open_security"],
        independent_gate_inputs["max_close_security"],
    ) <= 0.10
    assert max(
        independent_gate_inputs["max_open_sector"],
        independent_gate_inputs["max_close_sector"],
    ) <= 0.30
    assert independent_gate_inputs["max_correlation"] <= 0.80
    assert independent_gate_inputs["max_participation"] <= 0.05


def test_independent_ledger_reconstructs_every_cash_share_fee_and_return(tmp_path, monkeypatch):
    report, protocol, benchmark, store_manifest, expected_preflight = _run_independent_fixture(
        tmp_path, monkeypatch
    )

    expected_ledger = [
        {
            "kind": "BUY",
            "date": "2026-01-12",
            "ticker": "LEDGER",
            "decision_date": "2026-01-09",
            "price": 100.0,
            "shares": 50.0,
            "fee": 7.5,
            "notional": 5_000.0,
            "stop": 95.0,
            "sector": "TECH",
            "liquidity_notional": 5_000.0,
            "participation": 0.05,
            "cash": 94_992.5,
        },
        {
            "kind": "ACTION",
            "date": "2026-01-14",
            "ticker": "LEDGER",
            "action_type": "SPLIT",
            "factor": 0.5,
            "shares_before": 50.0,
            "shares_after": 100.0,
            "stop_before": 95.0,
            "stop_after": 47.5,
            "entry_price_before": 100.0,
            "entry_price_after": 50.0,
            "cost_basis_before": 100.0,
            "cost_basis_after": 50.0,
            "cash": 94_992.5,
        },
        {
            "kind": "DIVIDEND",
            "date": "2026-01-15",
            "ticker": "LEDGER",
            "shares": 100.0,
            "cash_amount_per_share": 1.0,
            "amount": 100.0,
            "cash": 95_092.5,
        },
        {
            "kind": "SELL",
            "date": "2026-01-19",
            "ticker": "LEDGER",
            "decision_date": "2026-01-09",
            "entry_date": "2026-01-12",
            "exit_reason": "forced_exit",
            "price": 55.0,
            "shares": 100.0,
            "notional": 5_500.0,
            "fee": 8.25,
            "liquidity_notional": 6_000.0,
            "participation": 5_500.0 / 120_000.0,
            "cash": 100_584.25,
        },
    ]
    expected_nav = {
        pd.Timestamp("2026-01-09"): 100_000.0,
        pd.Timestamp("2026-01-12"): 100_092.5,
        pd.Timestamp("2026-01-13"): 100_192.5,
        pd.Timestamp("2026-01-14"): 100_192.5,
        pd.Timestamp("2026-01-15"): 100_492.5,
        pd.Timestamp("2026-01-16"): 100_592.5,
        pd.Timestamp("2026-01-19"): 100_584.25,
        pd.Timestamp("2026-01-20"): 100_584.25,
        pd.Timestamp("2026-01-21"): 100_584.25,
        pd.Timestamp("2026-01-22"): 100_584.25,
        pd.Timestamp("2026-01-23"): 100_584.25,
    }
    expected_first_strategy_return = 0.0
    expected_first_benchmark_return = 106.0 / 105.0 - 1.0

    assert report["verdict"] == "REJECTED"
    assert report["release_approved"] is False
    assert report["verification"] == {
        "data_coverage_verified": True,
        "source_hashes_verified": True,
        "review_queue_verified": True,
        "order_queue_verified": True,
        "reproducibility_verified": True,
    }
    assert report["ledger"] == expected_ledger
    assert report["portfolio"]["initial_cash"] == 100_000.0
    assert report["portfolio"]["cash"] == 100_584.25
    assert report["portfolio"]["final_nav"] == 100_584.25
    assert report["portfolio"]["open_positions"] == {}
    assert report["portfolio"]["nav"].to_dict() == expected_nav
    assert report["costs"] == {"notional": 10_500.0, "total": 15.75}
    assert report["turnover"] == 0.105
    daily = {
        row["date"].date().isoformat(): row
        for row in report["exposure"]["daily"]
    }
    assert {
        key: daily["2026-01-12"][key]
        for key in (
            "starting_cash",
            "open_nav",
            "post_trade_open_nav",
            "open_position_values",
            "closing_cash",
            "position_values",
            "nav",
        )
    } == {
        "starting_cash": 100_000.0,
        "open_nav": 100_000.0,
        "post_trade_open_nav": 99_992.5,
        "open_position_values": {"LEDGER": 5_000.0},
        "closing_cash": 94_992.5,
        "position_values": {"LEDGER": 5_100.0},
        "nav": 100_092.5,
    }
    assert daily["2026-01-12"]["open_gross_exposure"] == pytest.approx(
        5_000.0 / 99_992.5
    )
    assert daily["2026-01-12"]["open_max_security"] == pytest.approx(
        5_000.0 / 99_992.5
    )
    assert daily["2026-01-12"]["open_max_sector"] == pytest.approx(
        5_000.0 / 99_992.5
    )
    assert {
        key: daily["2026-01-15"][key]
        for key in (
            "starting_cash",
            "open_nav",
            "closing_cash",
            "position_values",
            "nav",
        )
    } == {
        "starting_cash": 94_992.5,
        "open_nav": 100_292.5,
        "closing_cash": 95_092.5,
        "position_values": {"LEDGER": 5_400.0},
        "nav": 100_492.5,
    }
    assert {
        key: daily["2026-01-19"][key]
        for key in (
            "starting_cash",
            "open_nav",
            "closing_cash",
            "position_values",
            "nav",
        )
    } == {
        "starting_cash": 95_092.5,
        "open_nav": 100_584.25,
        "closing_cash": 100_584.25,
        "position_values": {},
        "nav": 100_584.25,
    }
    assert report["portfolio"]["returns"].iloc[0] == pytest.approx(
        expected_first_strategy_return
    )
    assert report["benchmark_returns"].iloc[0] == pytest.approx(
        expected_first_benchmark_return
    )
    assert report["exposure"]["max_gross"] == pytest.approx(
        5_500.0 / 100_592.5
    )
    assert report["exposure"]["max_security"] == pytest.approx(
        5_500.0 / 100_592.5
    )
    assert report["exposure"]["max_sector"] == pytest.approx(
        5_500.0 / 100_592.5
    )
    assert report["exposure"]["max_correlation"] == 0.0
    assert report["exposure"]["max_participation"] == 0.05
    assert report["source_hashes"]["dataset_manifest"] == (
        expected_preflight.dataset_manifest_sha256
    )
    assert report["source_hashes"]["sources"] == list(
        expected_preflight.manifest_payload["source_hashes"]
    )
    assert report["source_hashes"]["catalogues"] == list(
        expected_preflight.manifest_payload["catalogue_hashes"]
    )
    assert report["source_hashes"]["retained"] == list(
        expected_preflight.aggregates["hashes"]["retained"]
    )
    assert report["source_hashes"]["reviews"] == list(
        expected_preflight.manifest_payload["review_hashes"]
    )
    assert report["source_hashes"]["store_manifests"] == {
        domain: list(hashes)
        for domain, hashes in expected_preflight.manifest_payload[
            "store_manifest_hashes"
        ].items()
    }
    assert report["reproducibility"]["input_manifest"]["protocol_sha256"] == (
        _independent_sha256_json(protocol)
    )
    assert report["reproducibility"]["input_manifest"][
        "benchmark_input_sha256"
    ] == _independent_sha256_json(
        [
            {"date": day.date().isoformat(), "value": float(value)}
            for day, value in benchmark.items()
        ]
    )
    assert report["reproducibility"]["input_manifest"][
        "store_manifest_sha256s"
    ] == sorted(store_manifest.values())
    assert report["reproducibility"]["first_report_core_sha256"] == report[
        "reproducibility"
    ]["second_report_core_sha256"]
    assert report["report_core_sha256"] == report["reproducibility"][
        "first_report_core_sha256"
    ]


def test_close_revision_open_cannot_change_existing_position_exit_cash_or_nav(
    tmp_path, monkeypatch
):
    baseline, *_ = _run_independent_fixture(
        tmp_path / "baseline", monkeypatch
    )
    revised, *_ = _run_independent_fixture(
        tmp_path / "revised",
        monkeypatch,
        seed_kwargs={"close_exit_open": 1.0},
    )
    baseline_sell = next(
        event for event in baseline["ledger"] if event["kind"] == "SELL"
    )
    revised_sell = next(
        event for event in revised["ledger"] if event["kind"] == "SELL"
    )

    assert baseline_sell == revised_sell
    assert revised_sell["exit_reason"] == "forced_exit"
    assert revised_sell["price"] == 55.0
    assert revised["portfolio"]["cash"] == baseline["portfolio"]["cash"]
    assert revised["portfolio"]["final_nav"] == baseline["portfolio"][
        "final_nav"
    ]


@pytest.mark.parametrize(
    "extra_bar_date",
    (pd.Timestamp("2026-01-10"), pd.Timestamp("2026-01-24")),
    ids=("weekend-inside-period", "post-period-terminal-week"),
)
def test_unbound_extra_bar_dates_cannot_change_simulation_or_decisions(
    tmp_path, monkeypatch, extra_bar_date
):
    baseline, *_ = _run_independent_fixture(
        tmp_path / "baseline-calendar", monkeypatch
    )
    poisoned, *_ = _run_independent_fixture(
        tmp_path / "poisoned-calendar",
        monkeypatch,
        seed_kwargs={"extra_bar_dates": (extra_bar_date,)},
    )

    assert poisoned["decisions"] == baseline["decisions"]
    assert poisoned["ledger"] == baseline["ledger"]
    assert poisoned["portfolio"]["nav"].equals(
        baseline["portfolio"]["nav"]
    )


def test_declared_holiday_bar_cannot_replace_shortened_week_decision(
    tmp_path, monkeypatch
):
    bound_sessions = pd.bdate_range("2026-01-01", "2026-01-22")
    seed = {
        "calendar_sessions": bound_sessions,
        "closures": (pd.Timestamp("2026-01-23"),),
    }
    baseline, *_ = _run_independent_fixture(
        tmp_path / "holiday-baseline",
        monkeypatch,
        seed_kwargs=seed,
    )
    poisoned, *_ = _run_independent_fixture(
        tmp_path / "holiday-poisoned",
        monkeypatch,
        seed_kwargs={
            **seed,
            "extra_bar_dates": (pd.Timestamp("2026-01-23"),),
        },
    )

    assert baseline["decisions"][-1]["decision_date"] == "2026-01-22"
    assert poisoned["decisions"] == baseline["decisions"]
    assert poisoned["rejected_orders"] == baseline["rejected_orders"]


def test_unbound_closure_bar_before_purpose_dividend_cannot_affect_values(
    tmp_path, monkeypatch
):
    bound_sessions = pd.bdate_range("2026-01-01", "2026-01-23").difference(
        pd.DatetimeIndex(["2026-01-14"])
    )
    common = {
        "calendar_sessions": bound_sessions,
        "closures": (pd.Timestamp("2026-01-14"),),
        "dividend_payload": {
            "purpose": "Dividend - Rs 1 Per Share",
        },
        "include_split": False,
        "ledger_price_overrides": {
            "2026-01-15": (104.0, 106.0, 103.0, 105.0),
            "2026-01-16": (105.0, 107.0, 104.0, 106.0),
            "2026-01-19": (106.0, 108.0, 105.0, 107.0),
            "2026-01-20": (107.0, 109.0, 106.0, 108.0),
            "2026-01-21": (108.0, 110.0, 107.0, 109.0),
            "2026-01-22": (109.0, 111.0, 108.0, 110.0),
            "2026-01-23": (110.0, 112.0, 109.0, 111.0),
        },
        "suspension_date": None,
    }
    actual_compute_scores = historical_portfolio.compute_scores
    captured_scores = []

    def capture_scores(*args, **kwargs):
        scores = actual_compute_scores(*args, **kwargs)
        captured_scores.append(scores.copy())
        return scores

    monkeypatch.setattr(
        historical_portfolio,
        "compute_scores",
        capture_scores,
    )
    baseline, *_ = _run_independent_fixture(
        tmp_path / "dividend-baseline",
        monkeypatch,
        selection_start="2026-01-16",
        seed_kwargs=common,
    )
    baseline_scores = [scores.copy() for scores in captured_scores]
    captured_scores.clear()
    poisoned, *_ = _run_independent_fixture(
        tmp_path / "dividend-poisoned",
        monkeypatch,
        selection_start="2026-01-16",
        seed_kwargs={
            **common,
            "extra_bar_dates": (pd.Timestamp("2026-01-14"),),
            "extra_bar_price": 50.0,
        },
    )
    poisoned_scores = [scores.copy() for scores in captured_scores]
    baseline_buy = next(
        event for event in baseline["ledger"] if event["kind"] == "BUY"
    )
    poisoned_buy = next(
        event for event in poisoned["ledger"] if event["kind"] == "BUY"
    )

    assert len(baseline_scores) == len(poisoned_scores) > 0
    for expected, actual in zip(baseline_scores, poisoned_scores):
        pd.testing.assert_series_equal(actual, expected)
    assert poisoned["decisions"] == baseline["decisions"]
    assert poisoned_buy["stop"] == baseline_buy["stop"]
    assert poisoned["ledger"] == baseline["ledger"]
    assert poisoned["portfolio"]["nav"].equals(
        baseline["portfolio"]["nav"]
    )


def test_weekly_decisions_require_bound_proof_that_terminal_week_is_complete():
    partial = [
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-06"),
    ]
    holiday_shortened = [
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-06"),
        pd.Timestamp("2026-01-07"),
        pd.Timestamp("2026-01-08"),
    ]

    assert historical_portfolio._residual_weekly_decisions(
        partial,
        [],
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-06"),
    ) == set()
    assert historical_portfolio._residual_weekly_decisions(
        holiday_shortened,
        [pd.Timestamp("2026-01-09")],
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-09"),
    ) == {pd.Timestamp("2026-01-08")}


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
def test_runtime_rejects_ambiguous_or_wrong_typed_lookup_schema(
    tmp_path,
    scenario,
):
    store, _protocol_value, _benchmark, _registry, _manifests = (
        _seed_independent_ledger_store(tmp_path)
    )
    _mutate_runtime_lookup_schema(store, scenario)

    with pytest.raises(
        ResidualPortfolioDataError,
        match="PREFLIGHT_STORE_MANIFESTS",
    ):
        if "sector" in scenario:
            historical_portfolio._residual_sector(
                store,
                "LEDGER",
                "2026-01-15T10:00:00Z",
            )
        else:
            table = (
                "suspensions"
                if "suspension" in scenario
                else "delistings"
            )
            historical_portfolio._residual_event_active(
                store,
                table,
                "LEDGER",
                "2026-01-19T03:45:00Z",
            )


def test_runtime_rejects_stale_halal_classification(tmp_path):
    store, protocol, _benchmark, _registry, _manifests = (
        _seed_independent_ledger_store(tmp_path)
    )

    with pytest.raises(
        ResidualPortfolioDataError,
        match="STALE_HALAL:LEDGER",
    ):
        historical_portfolio._residual_eligible(
            store,
            "LEDGER",
            "2027-01-01T00:00:00Z",
            protocol["parameters"],
        )


def test_runtime_rejects_conflicting_top_halal_revisions(tmp_path):
    store, protocol, _benchmark, _registry, manifests = (
        _seed_independent_ledger_store(tmp_path)
    )
    store.put_halal_classification(
        "LEDGER",
        "2025-12-31",
        "RED",
        False,
        "synthetic-v2",
        "2025-12-31T00:00:00Z",
        manifests["halal"],
        reason="conflicting retained revision",
    )

    with pytest.raises(
        ResidualPortfolioDataError,
        match="CONFLICTING_HALAL:LEDGER",
    ):
        historical_portfolio._residual_eligible(
            store,
            "LEDGER",
            "2026-01-15T10:00:00Z",
            protocol["parameters"],
        )


def test_sell_participation_breach_rejects_through_full_verdict(
    tmp_path, monkeypatch
):
    report, *_ = _run_independent_fixture(
        tmp_path,
        monkeypatch,
        passing_statistics=True,
        seed_kwargs={"post_decision_traded_value": 50_000.0},
    )
    buys = [
        event["participation"]
        for event in report["ledger"]
        if event["kind"] == "BUY"
    ]
    sells = [
        event["participation"]
        for event in report["ledger"]
        if event["kind"] == "SELL"
    ]

    assert max(buys) <= 0.05
    assert max(sells) > 0.05
    assert report["exposure"]["max_buy_participation"] <= 0.05
    assert report["exposure"]["max_sell_participation"] > 0.05
    assert "order_participation" in report["failed_gates"]
    assert report["verdict"] == "REJECTED"


def test_open_exposure_breach_survives_same_day_intraday_exit_in_verdict(
    tmp_path, monkeypatch
):
    report, *_ = _run_independent_fixture(
        tmp_path,
        monkeypatch,
        passing_statistics=True,
        weight=0.20,
        seed_kwargs={
            "buy_day_intraday_stop": True,
            "predecision_traded_value_multiplier": 5.0,
            "post_decision_traded_value": 500_000.0,
        },
    )

    assert report["exposure"]["max_open_security"] > 0.10
    assert report["exposure"]["max_close_security"] == 0.0
    assert "realized_security" in report["failed_gates"]
    assert report["verdict"] == "REJECTED"


def test_open_gross_breach_rejects_through_full_verdict(
    tmp_path, monkeypatch
):
    symbols = tuple(f"GROSS{number}" for number in range(8))
    monkeypatch.setattr(
        historical_portfolio,
        "_selected_pairwise_correlation",
        lambda _returns, _selected, *, lookback: 0.0,
    )
    report, *_ = _run_independent_fixture(
        tmp_path,
        monkeypatch,
        passing_statistics=True,
        selected=("LEDGER", *symbols),
        weight=0.09,
        seed_kwargs={
            "extra_symbols": symbols,
            "predecision_traded_value_multiplier": 5.0,
        },
    )

    assert report["exposure"]["max_open_gross"] > 0.80
    assert "realized_gross" in report["failed_gates"]
    assert report["verdict"] == "REJECTED"


def test_open_sector_breach_rejects_through_full_verdict(
    tmp_path, monkeypatch
):
    symbols = ("SECTOR1", "SECTOR2", "SECTOR3")
    selected = ("LEDGER", *symbols)
    monkeypatch.setattr(
        historical_portfolio,
        "_selected_pairwise_correlation",
        lambda _returns, _selected, *, lookback: 0.0,
    )
    report, *_ = _run_independent_fixture(
        tmp_path,
        monkeypatch,
        passing_statistics=True,
        selected=selected,
        weight=0.08,
        seed_kwargs={
            "extra_symbols": symbols,
            "predecision_traded_value_multiplier": 5.0,
            "sector_overrides": {
                symbol: "ONE-SECTOR" for symbol in selected
            },
        },
    )

    assert report["exposure"]["max_open_sector"] > 0.30
    assert report["exposure"]["max_open_security"] < 0.10
    assert report["exposure"]["max_open_gross"] < 0.80
    assert "realized_sector" in report["failed_gates"]
    assert report["verdict"] == "REJECTED"


def test_close_exposure_breach_is_separate_from_compliant_open_exposure(
    tmp_path, monkeypatch
):
    report, *_ = _run_independent_fixture(
        tmp_path,
        monkeypatch,
        passing_statistics=True,
        weight=0.09,
        seed_kwargs={
            "buy_day_close": 200.0,
            "predecision_traded_value_multiplier": 5.0,
            "post_decision_traded_value": 500_000.0,
        },
    )

    assert report["exposure"]["max_open_security"] < 0.10
    assert report["exposure"]["max_close_security"] > 0.10
    assert "realized_security" in report["failed_gates"]
    assert report["verdict"] == "REJECTED"


def test_selected_correlation_uses_only_frozen_trailing_lookback():
    first = pd.Series([0.01, -0.01] * 20, dtype=float)
    trailing = pd.Series([0.01, -0.01] * 31 + [0.01], dtype=float)
    left = pd.concat([first, trailing], ignore_index=True)
    right = pd.concat([-first, trailing], ignore_index=True)
    returns = pd.DataFrame({"LEFT": left, "RIGHT": right})

    realized = historical_portfolio._selected_pairwise_correlation(
        returns, ["LEFT", "RIGHT"], lookback=63
    )

    assert returns.corr().loc["LEFT", "RIGHT"] < 0.80
    assert realized == pytest.approx(1.0)


def test_trailing_correlation_breach_rejects_through_full_verdict(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        historical_portfolio,
        "_selected_pairwise_correlation",
        lambda _returns, _selected, *, lookback: 0.81,
    )
    report, *_ = _run_independent_fixture(
        tmp_path,
        monkeypatch,
        passing_statistics=True,
        selected=("LEDGER", "WATCH"),
        weight=0.04,
    )

    assert report["exposure"]["max_correlation"] == 0.81
    assert "selected_correlation" in report["failed_gates"]
    assert report["verdict"] == "REJECTED"


@pytest.mark.parametrize(
    ("payload", "expected_amount_per_share"),
    [
        ({"cash_amount": 1.0}, 1.0),
        (
            {
                **_reviewed_factor_payload(0.98),
                "purpose": "Dividend - Rs 1 Per Share",
            },
            1.0,
        ),
        ({"purpose": "Dividend - Rs 1 Per Share"}, 1.0),
        (
            {
                **_reviewed_factor_payload(0.98),
                "purpose": "Dividend - Rs 1 Per Share",
            },
            1.0,
        ),
    ],
)
def test_dividend_canonical_forms_credit_reconstructable_cash(
    tmp_path, monkeypatch, payload, expected_amount_per_share
):
    report, *_ = _run_independent_fixture(
        tmp_path,
        monkeypatch,
        seed_kwargs={"dividend_payload": payload},
    )
    dividend = next(
        event for event in report["ledger"] if event["kind"] == "DIVIDEND"
    )

    assert dividend["shares"] == 100.0
    assert dividend["cash_amount_per_share"] == pytest.approx(
        expected_amount_per_share
    )
    assert dividend["amount"] == pytest.approx(
        100.0 * expected_amount_per_share
    )


@pytest.mark.parametrize(
    ("field", "failing_value", "failed_gate"),
    [
        ("max_gross", 0.8000001, "realized_gross"),
        ("max_security", 0.1000001, "realized_security"),
        ("max_sector", 0.3000001, "realized_sector"),
        ("max_correlation", 0.8000001, "selected_correlation"),
        ("max_participation", 0.0500001, "order_participation"),
        ("data_coverage_verified", False, "data_coverage"),
        ("source_hashes_verified", False, "source_hashes"),
        ("review_queue_verified", False, "review_queue"),
        ("order_queue_verified", False, "order_queue"),
        ("reproducibility_verified", False, "reproducibility"),
    ],
)
def test_each_realized_and_evidence_gate_fails_independently(
    field, failing_value, failed_gate
):
    exposure = {
        "max_gross": 0.80,
        "max_security": 0.10,
        "max_sector": 0.30,
        "max_correlation": 0.80,
        "max_participation": 0.05,
    }
    verification = {
        "data_coverage_verified": True,
        "source_hashes_verified": True,
        "review_queue_verified": True,
        "order_queue_verified": True,
        "reproducibility_verified": True,
    }
    if field in exposure:
        exposure[field] = failing_value
    else:
        verification[field] = failing_value

    assert historical_portfolio._realized_gate_failures(
        exposure, verification
    ) == [failed_gate]


def test_internal_byte_mismatch_rejects_caller_claimed_reproducibility(
    tmp_path, monkeypatch
):
    original = historical_portfolio._canonical_report_core_bytes
    calls = 0

    def mismatched_bytes(report_core):
        nonlocal calls
        calls += 1
        encoded = original(report_core)
        return encoded if calls == 1 else encoded + b"mismatch"

    monkeypatch.setattr(
        historical_portfolio, "_canonical_report_core_bytes", mismatched_bytes
    )
    report, _protocol_value, _benchmark, _manifest, _preflight_result = (
        _run_independent_fixture(
            tmp_path, monkeypatch, claimed_reproducible=True
        )
    )

    assert calls == 2
    assert report["verification"]["reproducibility_verified"] is False
    assert "reproducibility" in report["failed_gates"]
    assert report["verdict"] == "REJECTED"
    assert report["release_approved"] is False


def test_evaluator_uses_preregistered_trial_count_after_start(
    tmp_path,
    monkeypatch,
):
    registry = ExperimentRegistry(tmp_path / "registry.jsonl")
    monkeypatch.setattr(
        registry,
        "relevant_trial_count",
        lambda _family: 7,
    )
    evidence = {
        "calendar_sessions": ["2015-01-01"],
        "calendar_closures": [],
        "dataset_manifest_sha256": "a" * 64,
        "preflight_aggregates_sha256": "b" * 64,
        "protocol_sha256": "c" * 64,
        "source_sha256s": [],
        "catalogue_sha256s": [],
        "retained_source_sha256s": [],
        "review_report_sha256s": [],
        "preflight_store_manifest_sha256s": {},
        "verification": {
            "data_coverage_verified": True,
            "source_hashes_verified": True,
            "review_queue_verified": True,
        },
    }
    monkeypatch.setattr(
        historical_portfolio,
        "_preflight_evidence",
        lambda *_args, **_kwargs: evidence,
    )
    monkeypatch.setattr(
        historical_portfolio,
        "_input_manifest",
        lambda *_args, **kwargs: {
            "effective_n_trials": kwargs["n_trials"],
        },
    )
    observed = []

    def run_once(*_args, **kwargs):
        observed.append(kwargs["n_trials"])
        return {
            "exposure": {
                "max_gross": 0.0,
                "max_security": 0.0,
                "max_sector": 0.0,
                "max_correlation": 0.0,
                "max_participation": 0.0,
            },
            "failed_gates": [],
            "metrics": {},
            "n_trials": kwargs["n_trials"],
            "rejected_orders": [],
        }

    monkeypatch.setattr(
        historical_portfolio,
        "_run_residual_momentum_once",
        run_once,
    )

    report = run_residual_momentum_evaluation(
        ReliabilityStore(tmp_path / "store.db"),
        protocol=_protocol(),
        benchmark_tri=pd.Series(
            [100.0],
            index=pd.DatetimeIndex(["2015-01-01"]),
        ),
        preflight=object(),
        registry=registry,
        effective_n_trials=7,
    )

    assert observed == [7, 7]
    assert report["n_trials"] == 7
    assert report["reproducibility"]["input_manifest"][
        "effective_n_trials"
    ] == 7


def test_retained_artifact_mutation_between_replays_fails_closed(
    tmp_path, monkeypatch
):
    actual_run_once = historical_portfolio._run_residual_momentum_once
    calls = 0

    def mutate_after_first_pass(*args, **kwargs):
        nonlocal calls
        result = actual_run_once(*args, **kwargs)
        calls += 1
        if calls == 1:
            review = (
                tmp_path
                / "reviews"
                / "business_reviews.json"
            )
            review.write_bytes(review.read_bytes() + b" ")
        return result

    monkeypatch.setattr(
        historical_portfolio,
        "_run_residual_momentum_once",
        mutate_after_first_pass,
    )

    with pytest.raises(
        ResidualPortfolioDataError,
        match="PREFLIGHT_REVIEWS",
    ):
        _run_independent_fixture(tmp_path, monkeypatch)

    assert calls == 1


def test_report_binds_immutable_preflight_sources_reviews_code_environment_and_store(
    tmp_path, monkeypatch
):
    report, protocol, _benchmark, _manifest, expected_preflight = _run_independent_fixture(
        tmp_path, monkeypatch
    )
    input_manifest = report["reproducibility"]["input_manifest"]

    assert input_manifest["dataset_manifest_sha256"] == (
        expected_preflight.dataset_manifest_sha256
    )
    assert input_manifest["preflight_aggregates_sha256"] == (
        _independent_sha256_json(expected_preflight.aggregates)
    )
    expected_sessions = list(
        expected_preflight.manifest_payload["sessions"]
    )
    expected_closures = list(
        expected_preflight.manifest_payload["closures"]
    )
    assert input_manifest["calendar_sessions"] == expected_sessions
    assert input_manifest["calendar_closures"] == expected_closures
    assert report["source_hashes"]["calendar_sessions"] == expected_sessions
    assert report["source_hashes"]["calendar_closures"] == expected_closures
    assert input_manifest["source_sha256s"] == list(
        expected_preflight.manifest_payload["source_hashes"]
    )
    assert input_manifest["catalogue_sha256s"] == list(
        expected_preflight.manifest_payload["catalogue_hashes"]
    )
    assert input_manifest["retained_source_sha256s"] == list(
        expected_preflight.aggregates["hashes"]["retained"]
    )
    assert input_manifest["review_report_sha256s"] == list(
        expected_preflight.manifest_payload["review_hashes"]
    )
    assert input_manifest["preflight_store_manifest_sha256s"] == {
        domain: list(hashes)
        for domain, hashes in expected_preflight.manifest_payload[
            "store_manifest_hashes"
        ].items()
    }
    assert input_manifest["effective_n_trials"] == 7
    assert len(input_manifest["registry_snapshot_sha256"]) == 64
    assert len(input_manifest["code_sha256"]) == 64
    assert {
        "src/reliability/nifty_tri.py",
        "src/reliability/residual_momentum_experiment.py",
    } <= set(input_manifest["code_manifest"])
    assert len(input_manifest["environment_manifest_sha256"]) == 64
    assert input_manifest["environment_manifest_sha256"] == (
        _independent_sha256_json(input_manifest["environment_manifest"])
    )
    assert len(input_manifest["store_snapshot_sha256"]) == 64
    assert len(input_manifest["store_manifests_sha256"]) == 64
    assert report["reproducibility"]["input_manifest_sha256"] == (
        _independent_sha256_json(input_manifest)
    )


def test_task_6_module_contains_one_current_evaluator_and_no_superseded_claim():
    source_path = Path(historical_portfolio.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    evaluator_defs = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "run_residual_momentum_evaluation"
    ]

    assert len(evaluator_defs) == 1
    assert "intentionally supersedes" not in source
