"""Explicit, sealed commands for the residual-momentum experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from .experiment_preflight import (
    PreflightResult,
    run_preflight,
    verify_preflight_binding,
)
from .experiment_registry import ExperimentRegistry, ExperimentRegistryError
from .preregistration import (
    V7_SOURCE_KEYS,
    build_preregistered_event,
    canonical_json_bytes,
    sha256_json,
)
from .store import ReliabilityStore


EXPERIMENT_ID = "nse-halal-residual-momentum-v7"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REGISTRY = _PROJECT_ROOT / "data/reliability/experiment-registry.jsonl"
_DEFAULT_SOURCES = V7_SOURCE_KEYS


class ExperimentCommandError(RuntimeError):
    """Raised when a sealed experiment command cannot safely proceed."""


def _protocol() -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v7",
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
            "atr": 14,
            "halal_max_age_days": 365,
        },
        "statistical_policy": {"min_observations": 504, "n_trials_floor": 7},
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_canonical(path: Path, value: object) -> bytes:
    encoded = canonical_json_bytes(_jsonable(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    if temporary.exists():
        raise ExperimentCommandError(f"incomplete temporary artifact exists: {temporary}")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return encoded


def _read_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
        value = json.loads(encoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentCommandError(f"invalid {label} artifact: {path}") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != encoded:
        raise ExperimentCommandError(f"{label} artifact is not canonical: {path}")
    return value


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict"):
        try:
            if hasattr(value, "columns"):
                return _jsonable(value.to_dict(orient="records"))
            return _jsonable(value.to_dict())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return _jsonable(value.item())
        except ValueError:
            pass
    return value


def _artifact_path(root: Path, kind: str) -> Path:
    return root / kind / f"{EXPERIMENT_ID}.json"


@dataclass(frozen=True)
class _SourceSnapshot:
    device: int
    inode: int
    mode: int
    size: int
    sha256: str


def _validate_requested_sources(paths: list[str] | None) -> None:
    approved = {
        str((_PROJECT_ROOT / name).resolve()): name
        for name in _DEFAULT_SOURCES
    }
    for name in paths or []:
        try:
            resolved = str(Path(name).resolve(strict=True))
        except OSError as exc:
            raise ExperimentCommandError(f"missing approved source file: {name}") from exc
        if resolved not in approved:
            raise ExperimentCommandError(f"source is not an approved source file: {name}")


def _source_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
    )


def _read_source_snapshot(name: str) -> _SourceSnapshot:
    path = _PROJECT_ROOT / name
    required_flags = ("O_NOFOLLOW", "O_NONBLOCK")
    if not all(hasattr(os, flag) for flag in required_flags):
        raise ExperimentCommandError(
            "source sealing requires no-follow nonblocking descriptor support"
        )
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ExperimentCommandError(
            f"source must be a regular non-symlink file: {name}"
        ) from exc

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ExperimentCommandError(
                f"source must be a regular non-symlink file: {name}"
            )
        digest = hashlib.sha256()
        byte_count = 0
        empty_reads = 0
        while byte_count < before.st_size:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                empty_reads += 1
                if empty_reads >= 3:
                    break
                continue
            empty_reads = 0
            digest.update(chunk)
            byte_count += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)

    if (
        _source_identity(before) != _source_identity(after)
        or byte_count != before.st_size
    ):
        raise ExperimentCommandError(
            f"source file was not read completely and stably: {name}"
        )
    return _SourceSnapshot(
        device=after.st_dev,
        inode=after.st_ino,
        mode=after.st_mode,
        size=after.st_size,
        sha256=digest.hexdigest(),
    )


def _source_snapshots(paths: list[str] | None) -> dict[str, _SourceSnapshot]:
    _validate_requested_sources(paths)
    snapshots = {}
    for name in _DEFAULT_SOURCES:
        snapshots[name] = _read_source_snapshot(name)
    return dict(sorted(snapshots.items()))


def _source_hashes(paths: list[str] | None) -> dict[str, str]:
    return {
        name: snapshot.sha256
        for name, snapshot in _source_snapshots(paths).items()
    }


def _sealed_source_hashes(paths: list[str] | None) -> dict[str, str]:
    first = _source_snapshots(paths)
    second = _source_snapshots(paths)
    if first != second:
        raise ExperimentCommandError(
            "source files changed between source passes"
        )
    return {
        name: snapshot.sha256
        for name, snapshot in second.items()
    }


def _current_source_hashes(stored: Mapping[str, object]) -> dict[str, str]:
    if set(stored) != set(_DEFAULT_SOURCES):
        raise ExperimentCommandError("stored source keys do not match the v7 source seal")
    for name in stored:
        if not isinstance(name, str):
            raise ExperimentCommandError("invalid named source file")
    return _sealed_source_hashes(None)


def _environment_manifest() -> dict[str, object]:
    packages = {}
    for package in ("numpy", "pandas", "scipy"):
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = "NOT_INSTALLED"
    return {
        "implementation": platform.python_implementation(),
        "packages": packages,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


def _load_preregistration(root: Path, registry: ExperimentRegistry) -> tuple[dict, dict]:
    artifact = _artifact_path(root, "preregistrations")
    if not artifact.exists():
        raise ExperimentCommandError("missing preregistration artifact")
    event = _read_canonical(artifact, "preregistration")
    events = registry.events(EXPERIMENT_ID)
    if not events or events[0].get("record_type") != "PREREGISTERED":
        raise ExperimentCommandError("missing preregistration registry evidence")
    registered = events[0]
    protocol = event.get("protocol")
    if not isinstance(protocol, dict):
        raise ExperimentCommandError("invalid preregistration protocol")
    return event, registered


def _preflight_from_payload(payload: dict) -> PreflightResult:
    required = {
        "passed", "blockers", "aggregates", "dataset_manifest_sha256", "manifest_payload"
    }
    if set(payload) != required or not isinstance(payload["passed"], bool):
        raise ExperimentCommandError("invalid preflight artifact")
    if not isinstance(payload["blockers"], list) or not all(
        isinstance(item, str) for item in payload["blockers"]
    ):
        raise ExperimentCommandError("invalid preflight blockers")
    if not isinstance(payload["aggregates"], dict):
        raise ExperimentCommandError("invalid preflight aggregates")
    return PreflightResult(
        passed=payload["passed"],
        blockers=tuple(payload["blockers"]),
        aggregates=payload["aggregates"],
        dataset_manifest_sha256=payload["dataset_manifest_sha256"],
        manifest_payload=payload["manifest_payload"],
    )


def _load_preflight(root: Path) -> PreflightResult:
    artifact = _artifact_path(root, "preflight")
    if not artifact.exists():
        raise ExperimentCommandError("missing preflight artifact")
    result = _preflight_from_payload(_read_canonical(artifact, "preflight"))
    if not result.passed or result.blockers or not result.dataset_manifest_sha256:
        raise ExperimentCommandError("preflight did not pass")
    return result


def _catalogued_tri(acquirer, artifact: Mapping[str, object], path: Path) -> bool:
    try:
        records = [json.loads(line) for line in acquirer.catalogue.read_text(
            encoding="utf-8"
        ).splitlines() if line]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    expected = {
        "available_at": artifact["retrieved_at"],
        "kind": artifact["kind"],
        "window": artifact["window"],
        "url": artifact["url"],
        "request": artifact["request"],
        "path": str(path),
        "raw_sha256": artifact["raw_sha256"],
        "normalized_sha256": artifact["normalized_sha256"],
        "raw_bytes": artifact["raw_bytes"],
        "raw_response_path": artifact["raw_response_path"],
        "status_code": artifact["status_code"],
        "content_type": artifact["content_type"],
    }
    return any(
        isinstance(record, dict)
        and record.get("status") in {"downloaded", "cached"}
        and all(record.get(key) == value for key, value in expected.items())
        for record in records
    )


def _load_tri(
    root: Path,
    path: Path,
    *,
    protocol: Mapping[str, object],
    required_sessions: object,
):
    try:
        import pandas as pd
        from .nifty_tri import (
            NiftyTriAcquirer,
            NiftyTriError,
            validate_tri_session_coverage,
        )
    except ImportError as exc:
        raise ExperimentCommandError("pandas is required for evaluation") from exc
    try:
        start = date.fromisoformat(
            protocol["periods"]["warmup"][0]
        )
        end = date.fromisoformat(protocol["periods"]["scored"][1])
        acquirer = NiftyTriAcquirer(root)
        artifact = acquirer.load_merged(
            path,
            start=start,
            end=end,
        )
        rows = artifact["normalized_rows"]
        validate_tri_session_coverage(rows, required_sessions)
    except (
        KeyError,
        TypeError,
        ValueError,
        NiftyTriError,
        ExperimentCommandError,
    ) as exc:
        raise ExperimentCommandError(
            f"invalid retained TRI merged artifact or coverage: {exc}"
        ) from exc
    rows = artifact["normalized_rows"]
    index = pd.DatetimeIndex([row["session_date"] for row in rows])
    values = [float(row["tri"]) for row in rows]
    return pd.Series(values, index=index, dtype=float)


def _input_manifest(
    *,
    preregistration_sha256: str,
    protocol: dict,
    source_hashes: dict[str, str],
    preflight: PreflightResult,
    binding: Mapping[str, object],
    tri_path: Path,
    store_path: Path,
    effective_n_trials: int,
) -> dict[str, object]:
    environment = _environment_manifest()
    return {
        "schema_version": 2,
        "preregistration_sha256": preregistration_sha256,
        "protocol_sha256": sha256_json(protocol),
        "source_hashes": source_hashes,
        "dataset_manifest_sha256": preflight.dataset_manifest_sha256,
        "preflight_binding_sha256": sha256_json(_jsonable(dict(binding))),
        "tri_sha256": _sha256_bytes(tri_path.read_bytes()),
        "store_path": str(store_path.resolve()),
        "effective_n_trials": effective_n_trials,
        "environment_manifest": environment,
        "environment_manifest_sha256": sha256_json(environment),
    }


def _attempt_path(root: Path) -> Path:
    return _artifact_path(root, "attempts")


def _report_path(root: Path) -> Path:
    return _artifact_path(root, "reports")


def _invalid_report_path(root: Path) -> Path:
    return _report_path(root).with_name(f"{EXPERIMENT_ID}.invalid.json")


def _started_event(
    preregistration_sha256: str,
    dataset_manifest_sha256: str,
    input_manifest_sha256: str,
    effective_n_trials: int,
) -> dict[str, object]:
    return {
        "record_id": f"start-{input_manifest_sha256[:24]}",
        "record_type": "EVALUATION_STARTED",
        "experiment_id": EXPERIMENT_ID,
        "created_at": _utc_now(),
        "preregistration_sha256": preregistration_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "input_manifest_sha256": input_manifest_sha256,
        "effective_n_trials": effective_n_trials,
    }


def _evaluation_event(
    *,
    preregistration_sha256: str,
    dataset_manifest_sha256: str,
    input_manifest_sha256: str,
    report_sha256: str,
    input_manifest: Mapping[str, object],
    metrics: Mapping[str, object],
    failed_gates: list[str],
    verdict: str,
) -> dict[str, object]:
    return {
        "record_id": f"evaluated-{report_sha256[:24]}",
        "record_type": "EVALUATED",
        "experiment_id": EXPERIMENT_ID,
        "created_at": _utc_now(),
        "preregistration_sha256": preregistration_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "input_manifest_sha256": input_manifest_sha256,
        "report_sha256": report_sha256,
        "code_sha256": sha256_json(input_manifest["source_hashes"]),
        "environment_manifest_sha256": input_manifest["environment_manifest_sha256"],
        "metrics": dict(metrics),
        "failed_gates": sorted(set(failed_gates)),
        "verdict": verdict,
    }


def _write_report(
    root: Path,
    report: Mapping[str, object],
    input_manifest: Mapping[str, object],
    *,
    path: Path | None = None,
    mismatch_error: str = "immutable report already exists with different contents",
) -> tuple[Path, bytes]:
    payload = {
        **dict(report),
        "release_approved": False,
        "command_input_manifest": dict(input_manifest),
        "command_input_manifest_sha256": sha256_json(input_manifest),
    }
    path = path or _report_path(root)
    if path.exists():
        existing = path.read_bytes()
        if existing != canonical_json_bytes(_jsonable(payload)):
            raise ExperimentCommandError(mismatch_error)
        return path, existing
    return path, _write_canonical(path, payload)


def _invalid_report(
    root: Path,
    *,
    input_manifest: Mapping[str, object],
    failed_gates: list[str],
) -> tuple[Path, bytes]:
    return _write_report(root, {
        "verdict": "INVALID",
        "metrics": {},
        "failed_gates": sorted(set(failed_gates)),
        "reason": "retained evaluation inputs changed before recovery",
    }, input_manifest, path=_invalid_report_path(root))


def _changed_gates(previous: Mapping[str, object], current: Mapping[str, object]) -> list[str]:
    gates = []
    if previous.get("protocol_sha256") != current.get("protocol_sha256"):
        gates.append("PROTOCOL")
    if previous.get("effective_n_trials") != current.get(
        "effective_n_trials"
    ):
        gates.append("PROTOCOL")
    if previous.get("source_hashes") != current.get("source_hashes"):
        gates.append("SOURCE_HASHES")
    if previous.get("environment_manifest_sha256") != current.get("environment_manifest_sha256"):
        gates.append("ENVIRONMENT")
    if any(
        previous.get(field) != current.get(field)
        for field in (
            "dataset_manifest_sha256", "preflight_binding_sha256", "tri_sha256", "store_path"
        )
    ):
        gates.append("DATASET")
    return gates or ["INPUT_MANIFEST"]


def _record_invalid(
    root: Path,
    registry: ExperimentRegistry,
    started: Mapping[str, object],
    preregistration_sha256: str,
    input_manifest: Mapping[str, object],
    failed_gates: list[str],
) -> None:
    _, report_bytes = _invalid_report(
        root, input_manifest=input_manifest, failed_gates=failed_gates
    )
    registry.append_event(_evaluation_event(
        preregistration_sha256=preregistration_sha256,
        dataset_manifest_sha256=started["dataset_manifest_sha256"],
        input_manifest_sha256=started["input_manifest_sha256"],
        report_sha256=_sha256_bytes(report_bytes),
        input_manifest=input_manifest,
        metrics={},
        failed_gates=failed_gates,
        verdict="INVALID",
    ))


def _preregister(args: argparse.Namespace) -> int:
    root = Path(args.root)
    registry = ExperimentRegistry(args.registry)
    protocol = _protocol()
    artifact = _artifact_path(root, "preregistrations")
    try:
        with registry.preregistration_transaction() as transaction:
            retained = transaction.read_artifact(artifact)
            existing_events = transaction.events(EXPERIMENT_ID)
            if args.created_at:
                created_at = args.created_at
            elif retained is not None:
                created_at = retained.get("created_at")
            elif len(existing_events) == 1:
                created_at = existing_events[0].get("created_at")
            else:
                created_at = _utc_now()
            sources = _sealed_source_hashes(args.source)
            event = build_preregistered_event(
                protocol,
                record_id=f"preregistered-{sha256_json(protocol)[:24]}",
                created_at=created_at,
                source_hashes=sources,
                prior_trial_count=transaction.relevant_trial_count(
                    protocol["family"]
                ),
            )
            transaction.commit_preregistration(
                event,
                artifact,
                canonical_json_bytes(event),
            )
    except ExperimentRegistryError as exc:
        raise ExperimentCommandError(str(exc)) from exc
    return 0


def _preflight(args: argparse.Namespace) -> int:
    root = Path(args.root)
    registry = ExperimentRegistry(args.registry)
    event, registered = _load_preregistration(root, registry)
    if sha256_json(event) != sha256_json(registered):
        raise ExperimentCommandError("preregistration artifact does not match registry")
    store = ReliabilityStore(args.store)
    try:
        catalogues = [Path(path) for path in args.source_catalogue]
        reviews = [Path(path) for path in args.review_report]
        result = run_preflight(
            store,
            event["protocol"],
            source_catalogues=catalogues,
            review_reports=reviews,
            corporate_action_audit_path=(
                Path(args.corporate_action_audit)
                if args.corporate_action_audit else None
            ),
            corporate_action_audit_sha256=args.corporate_action_audit_sha256,
            corporate_action_packet_dir=(
                Path(args.corporate_action_packet_dir)
                if args.corporate_action_packet_dir else None
            ),
            corporate_action_policy_path=(
                Path(args.corporate_action_policy)
                if args.corporate_action_policy else None
            ),
            corporate_action_baseline_path=(
                Path(args.corporate_action_baseline)
                if args.corporate_action_baseline else None
            ),
        )
    finally:
        store.close()
    payload = {
        "passed": result.passed,
        "blockers": list(result.blockers),
        "aggregates": result.aggregates,
        "dataset_manifest_sha256": result.dataset_manifest_sha256,
        "manifest_payload": result.manifest_payload,
    }
    _write_canonical(_artifact_path(root, "preflight"), payload)
    return 0


def _acquire_tri(args: argparse.Namespace) -> int:
    root = Path(args.root)
    event, _ = _load_preregistration(
        root,
        ExperimentRegistry(args.registry),
    )
    try:
        from .nifty_tri import NiftyTriAcquirer, TriWindow, build_tri_windows
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except (ImportError, ValueError) as exc:
        raise ExperimentCommandError("invalid TRI acquisition window") from exc
    expected_start = date.fromisoformat(
        event["protocol"]["periods"]["warmup"][0]
    )
    expected_end = date.fromisoformat(
        event["protocol"]["periods"]["scored"][1]
    )
    if (start, end) != (expected_start, expected_end):
        raise ExperimentCommandError(
            "TRI acquisition must cover the full warmup and scored periods"
        )
    acquirer = NiftyTriAcquirer(root)
    for window in build_tri_windows(start, end):
        acquirer.acquire(TriWindow(window.start, window.end))
    acquirer.merge_retained(start, end)
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    registry = ExperimentRegistry(args.registry)
    event, registered = _load_preregistration(root, registry)
    protocol = event.get("protocol")
    if not isinstance(protocol, dict):
        raise ExperimentCommandError("invalid preregistration protocol")
    preregistration_sha256 = sha256_json(registered)
    effective_n_trials = registered.get("effective_n_trials")
    if (
        isinstance(effective_n_trials, bool)
        or not isinstance(effective_n_trials, int)
        or effective_n_trials < 7
    ):
        raise ExperimentCommandError(
            "preregistration effective_n_trials is invalid"
        )
    state = registry.state(EXPERIMENT_ID)
    if state in {"ACCEPTED", "REJECTED", "INVALID"}:
        raise ExperimentCommandError("evaluation has already completed")

    preflight = _load_preflight(root)
    store = ReliabilityStore(args.store)
    try:
        try:
            binding = verify_preflight_binding(store, protocol, preflight)
        except ValueError as exc:
            if state == "EVALUATION_STARTED":
                started = registry.events(EXPERIMENT_ID)[-1]
                fallback = {
                    "source_hashes": _current_source_hashes(registered["source_hashes"]),
                    "environment_manifest_sha256": sha256_json(_environment_manifest()),
                    "effective_n_trials": effective_n_trials,
                }
                _record_invalid(
                    root, registry, started, preregistration_sha256, fallback, ["DATASET"]
                )
                return 0
            raise ExperimentCommandError("preflight binding verification failed") from exc

        if binding.get("dataset_manifest_sha256") != preflight.dataset_manifest_sha256:
            raise ExperimentCommandError("preflight binding has changed dataset manifest")
        source_hashes = _current_source_hashes(registered["source_hashes"])
        required_sessions = binding.get(
            "sessions",
            (
                preflight.manifest_payload.get("sessions", ())
                if isinstance(preflight.manifest_payload, Mapping)
                else ()
            ),
        )
        benchmark_tri = _load_tri(
            root,
            Path(args.tri),
            protocol=protocol,
            required_sessions=required_sessions,
        )
        current = _input_manifest(
            preregistration_sha256=preregistration_sha256,
            protocol=protocol,
            source_hashes=source_hashes,
            preflight=preflight,
            binding=binding,
            tri_path=Path(args.tri),
            store_path=Path(args.store),
            effective_n_trials=effective_n_trials,
        )
        input_sha256 = sha256_json(current)

        if state == "PREREGISTERED":
            if sha256_json(event) != preregistration_sha256:
                raise ExperimentCommandError("preregistration artifact does not match registry")
            if source_hashes != registered["source_hashes"]:
                raise ExperimentCommandError("named source hashes do not match preregistration")
            attempt = {
                "preregistration_sha256": preregistration_sha256,
                "dataset_manifest_sha256": preflight.dataset_manifest_sha256,
                "input_manifest_sha256": input_sha256,
                "input_manifest": current,
            }
            _write_canonical(_attempt_path(root), attempt)
            started = _started_event(
                preregistration_sha256,
                preflight.dataset_manifest_sha256,
                input_sha256,
                effective_n_trials,
            )
            registry.append_event(started)
        elif state == "EVALUATION_STARTED":
            started = registry.events(EXPERIMENT_ID)[-1]
            attempt = _read_canonical(_attempt_path(root), "evaluation attempt")
            previous = attempt.get("input_manifest")
            if not isinstance(previous, dict):
                raise ExperimentCommandError("invalid retained evaluation attempt")
            if (
                attempt.get("input_manifest_sha256") != sha256_json(previous)
                or started.get("input_manifest_sha256") != sha256_json(previous)
                or started.get("preregistration_sha256") != preregistration_sha256
            ):
                _record_invalid(root, registry, started, preregistration_sha256, current, ["INPUT_MANIFEST"])
                return 0
            if previous != current:
                _record_invalid(root, registry, started, preregistration_sha256, current, _changed_gates(previous, current))
                return 0
            report_path = _report_path(root)
            if report_path.exists():
                report = _read_canonical(report_path, "report")
                if (
                    report.get("command_input_manifest") != current
                    or report.get("command_input_manifest_sha256") != input_sha256
                ):
                    raise ExperimentCommandError("retained report input manifest is invalid")
        else:
            raise ExperimentCommandError("evaluation requires preregistration")

        from .historical_portfolio import run_residual_momentum_evaluation
        report = run_residual_momentum_evaluation(
            store,
            protocol=protocol,
            benchmark_tri=benchmark_tri,
            preflight=preflight,
            registry=registry,
            effective_n_trials=effective_n_trials,
        )
        if not isinstance(report, Mapping):
            raise ExperimentCommandError("evaluator returned an invalid report")
        verdict = report.get("verdict")
        if verdict not in {"ACCEPTED", "REJECTED", "INVALID"}:
            raise ExperimentCommandError("evaluator report has an invalid verdict")
        metrics = report.get("metrics")
        failed_gates = report.get("failed_gates")
        if not isinstance(metrics, Mapping) or not isinstance(failed_gates, list):
            raise ExperimentCommandError("evaluator report is missing evidence fields")
        _, report_bytes = _write_report(
            root,
            report,
            current,
            mismatch_error="retained report does not reproduce evaluator output",
        )
        registry.append_event(_evaluation_event(
            preregistration_sha256=preregistration_sha256,
            dataset_manifest_sha256=started["dataset_manifest_sha256"],
            input_manifest_sha256=started["input_manifest_sha256"],
            report_sha256=_sha256_bytes(report_bytes),
            input_manifest=current,
            metrics=metrics,
            failed_gates=failed_gates,
            verdict=verdict,
        ))
        return 0
    except ExperimentRegistryError as exc:
        raise ExperimentCommandError(str(exc)) from exc
    finally:
        store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="residual-momentum-experiment")
    commands = parser.add_subparsers(dest="command", required=True)

    preregister = commands.add_parser("preregister")
    preregister.add_argument("--root", required=True)
    preregister.add_argument("--registry", default=str(_DEFAULT_REGISTRY))
    preregister.add_argument("--source", action="append")
    preregister.add_argument("--created-at")
    preregister.set_defaults(handler=_preregister)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--root", required=True)
    preflight.add_argument("--registry", default=str(_DEFAULT_REGISTRY))
    preflight.add_argument("--store", required=True)
    preflight.add_argument("--source-catalogue", action="append", default=[])
    preflight.add_argument("--review-report", action="append", default=[])
    preflight.add_argument("--corporate-action-audit")
    preflight.add_argument("--corporate-action-audit-sha256")
    preflight.add_argument("--corporate-action-packet-dir")
    preflight.add_argument("--corporate-action-policy")
    preflight.add_argument("--corporate-action-baseline")
    preflight.set_defaults(handler=_preflight)

    acquire = commands.add_parser("acquire-tri")
    acquire.add_argument("--root", required=True)
    acquire.add_argument("--registry", default=str(_DEFAULT_REGISTRY))
    acquire.add_argument("--start", required=True)
    acquire.add_argument("--end", required=True)
    acquire.set_defaults(handler=_acquire_tri)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--root", required=True)
    evaluate.add_argument("--registry", default=str(_DEFAULT_REGISTRY))
    evaluate.add_argument("--store", required=True)
    evaluate.add_argument("--tri", required=True)
    evaluate.set_defaults(handler=_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return args.handler(args)


def _cli() -> int:
    try:
        return main()
    except ExperimentCommandError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
