import hashlib
import importlib
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from threading import Event, Thread
import pytest

import src.reliability.experiment_registry as registry_module
import src.reliability.residual_momentum_experiment as experiment_module
from src.reliability.experiment_preflight import PreflightResult
from src.reliability.experiment_registry import ExperimentRegistry
from src.reliability.nifty_tri import (
    NiftyTriAcquirer,
    TriWindow,
    _file_bytes,
    _request_body,
    build_tri_windows,
)
from src.reliability.preregistration import (
    V7_SOURCE_KEYS,
    build_preregistered_event,
    canonical_json_bytes,
    sha256_json,
)
from src.reliability.residual_momentum_experiment import (
    ExperimentCommandError,
    _source_hashes,
    main,
)


def test_source_snapshot_retries_transient_empty_regular_file_reads(monkeypatch):
    relative_path = "src/reliability/residual_momentum.py"
    path = Path(relative_path)
    original_read = experiment_module.os.read
    empty_returned = False

    def transient_empty_read(descriptor, size):
        nonlocal empty_returned
        if not empty_returned:
            empty_returned = True
            return b""
        return original_read(descriptor, size)

    monkeypatch.setattr(experiment_module.os, "read", transient_empty_read)

    snapshot = experiment_module._read_source_snapshot(relative_path)

    assert snapshot.size == path.stat().st_size
    assert snapshot.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_source_identity_ignores_metadata_timestamp_drift():
    base = {
        "st_dev": 1, "st_ino": 2, "st_mode": 0o100644,
        "st_size": 12,
    }
    first = SimpleNamespace(**base, st_mtime_ns=34, st_ctime_ns=100)
    second = SimpleNamespace(**base, st_mtime_ns=56, st_ctime_ns=200)

    assert experiment_module._source_identity(first) == experiment_module._source_identity(second)


def _protocol():
    return {
        "experiment_id": "nse-halal-residual-momentum-v7",
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


def _seed_registry(path):
    registry = ExperimentRegistry(path)
    for number in range(6):
        registry.register({
            "experiment_id": f"legacy-{number}",
            "family": "nse-swing-2020-2024",
            "strategy_version": "legacy-v1",
            "protocol_version": "legacy-v1",
            "report_sha256": f"{number + 1:064x}",
            "verdict": "REJECTED",
        })
    return registry


def _paths(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "evidence"
    registry = tmp_path / "experiments.jsonl"
    source = tmp_path / "strategy.py"
    source.write_text("RULE = 'sealed'\n", encoding="utf-8")
    _seed_registry(registry)
    return root, registry, source


def _preregister(tmp_path):
    root, registry, source = _paths(tmp_path)
    assert main([
        "preregister", "--root", str(root), "--registry", str(registry),
        "--created-at", "2026-07-13T00:00:00Z",
    ]) == 0
    return root, registry, source


def _passing_preflight():
    manifest_payload = {
        "schema_version": 2,
        "protocol_sha256": sha256_json(_protocol()),
        "sources": [],
        "source_hashes": [],
        "catalogues": [],
        "catalogue_hashes": [],
        "reviews": [],
        "review_hashes": [],
        "store_manifest_hashes": {},
        "sessions": ["2015-01-01"],
        "closures": [],
        "aggregate_coverage": {},
        "calendar": {"weekdays": 1, "sessions": 1, "closures": 0},
    }
    return PreflightResult(
        passed=True,
        blockers=(),
        aggregates={"calendar": manifest_payload["calendar"]},
        dataset_manifest_sha256=sha256_json(manifest_payload),
        manifest_payload=manifest_payload,
    )


def _write_preflight(root, result=None):
    result = result or _passing_preflight()
    path = root / "preflight" / "nse-halal-residual-momentum-v7.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes({
        "passed": result.passed,
        "blockers": list(result.blockers),
        "aggregates": result.aggregates,
        "dataset_manifest_sha256": result.dataset_manifest_sha256,
        "manifest_payload": result.manifest_payload,
    }))
    return path


def _write_tri_component(acquirer, window, *, session_date=None):
    session_date = session_date or window.start
    path = acquirer._path(window)
    raw_path = acquirer._raw_path(window)
    raw_payload = [{
        "Date": session_date.strftime("%d %b %Y"),
        "Index Name": "NIFTY 50",
        "TotalReturnsIndex": "100.0",
    }]
    raw_response = canonical_json_bytes(raw_payload)
    normalized = [{
        "session_date": session_date.isoformat(),
        "tri": 100.0,
    }]
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
    return path


def _write_tri(root, *, catalogue=True):
    start = date(2013, 12, 1)
    end = date(2019, 12, 31)
    acquirer = NiftyTriAcquirer(root, retries=1)
    for window in build_tri_windows(start, end):
        session_date = (
            date(2015, 1, 1)
            if window.start <= date(2015, 1, 1) <= window.end
            else window.start
        )
        _write_tri_component(
            acquirer,
            window,
            session_date=session_date,
        )
    path = acquirer.merge_retained(start, end)
    if not catalogue:
        lines = acquirer.catalogue.read_bytes().splitlines(
            keepends=True
        )
        acquirer.catalogue.write_bytes(b"".join(lines[:-1]))
    return path


def _write_single_window_tri(root):
    acquirer = NiftyTriAcquirer(root, retries=1)
    window = TriWindow(date(2015, 1, 1), date(2015, 1, 1))
    return _write_tri_component(acquirer, window)


def _write_fabricated_tri(root):
    path = root / "tri.json"
    path.write_bytes(canonical_json_bytes({
        "normalized_rows": [{"session_date": "2015-01-01", "tri": 100.0}],
    }))
    return path


def _unexpected_network(*_args, **_kwargs):
    raise AssertionError("network access is not allowed")


def _unexpected_evaluation(*_args, **_kwargs):
    raise AssertionError("evaluation is not allowed")


def test_preregister_does_not_acquire_or_evaluate(monkeypatch, tmp_path):
    root, registry, source = _paths(tmp_path)
    monkeypatch.setattr("requests.Session.post", _unexpected_network)
    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation",
        _unexpected_evaluation,
    )

    assert main([
        "preregister", "--root", str(root), "--registry", str(registry),
        "--created-at", "2026-07-13T00:00:00Z",
    ]) == 0

    artifact = root / "preregistrations" / "nse-halal-residual-momentum-v7.json"
    assert artifact.read_bytes() == canonical_json_bytes(json.loads(artifact.read_text()))
    assert ExperimentRegistry(registry).state("nse-halal-residual-momentum-v7") == "PREREGISTERED"
    assert not (root / "attempts").exists()
    assert not (root / "preflight").exists()
    assert not (root / "reports").exists()


def test_v7_preregister_preserves_v6_semantics_and_seals_evaluation_sources(
    tmp_path,
):
    root, registry, _ = _paths(tmp_path)

    assert main([
        "preregister", "--root", str(root), "--registry", str(registry),
        "--created-at", "2026-07-24T18:30:00Z",
    ]) == 0

    artifacts = list((root / "preregistrations").glob("*.json"))
    assert len(artifacts) == 1
    event = json.loads(artifacts[0].read_text())
    assert event["protocol"] == _protocol()
    assert event["supersedes"] == {
        "experiment_id": "nse-halal-residual-momentum-v6",
        "preregistration_sha256": "21efd568affe40c7139d38bd5a4fc258de1146df817acadaefa1042cb3d5c6b8",
        "reason": (
            "v6 source seal predates canonical review authority and activation "
            "binding hardening; v7 seals the corrected fail-closed boundary"
        ),
    }
    assert list(event["source_hashes"]) == [
        "src/reliability/adjusted_prices.py",
        "src/reliability/corporate_action_audit.py",
        "src/reliability/corporate_action_review_packet.py",
        "src/reliability/corporate_action_reviews.py",
        "src/reliability/experiment_preflight.py",
        "src/reliability/experiment_registry.py",
        "src/reliability/historical_portfolio.py",
        "src/reliability/nifty_tri.py",
        "src/reliability/nse_normalizers.py",
        "src/reliability/preregistration.py",
        "src/reliability/residual_momentum.py",
        "src/reliability/residual_momentum_experiment.py",
        "src/reliability/statistics.py",
        "src/reliability/store.py",
    ]
    assert event["validation_values_opened"] is False


def test_v7_preregister_is_idempotent_and_creates_no_downstream_artifacts(
    tmp_path,
):
    root, registry, _ = _paths(tmp_path)
    command = [
        "preregister", "--root", str(root), "--registry", str(registry),
        "--created-at", "2026-07-29T00:00:00Z",
    ]

    assert main(command) == 0
    artifact = (
        root / "preregistrations" / "nse-halal-residual-momentum-v7.json"
    )
    original_bytes = artifact.read_bytes()
    original_registry = registry.read_bytes()

    assert main(command) == 0
    assert artifact.read_bytes() == original_bytes
    assert registry.read_bytes() == original_registry
    events = ExperimentRegistry(registry).events(
        "nse-halal-residual-momentum-v7"
    )
    assert [event["record_type"] for event in events] == ["PREREGISTERED"]

    forbidden = {
        "preflight", "tri", "attempt", "report", "result", "evaluation", "holdout"
    }
    assert not [
        path
        for path in root.rglob("*")
        if path.is_file()
        and "nse-halal-residual-momentum-v7" in path.name
        and any(marker in str(path).lower() for marker in forbidden)
    ]


def test_v7_preregister_rejects_conflicting_canonical_artifact(tmp_path):
    root, registry, _ = _paths(tmp_path)
    artifact = (
        root / "preregistrations" / "nse-halal-residual-momentum-v7.json"
    )
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(canonical_json_bytes({"conflict": True}))
    before = registry.read_bytes()

    with pytest.raises(
        ExperimentCommandError,
        match="immutable preregistration artifact",
    ):
        main([
            "preregister", "--root", str(root), "--registry", str(registry),
            "--created-at", "2026-07-29T00:00:00Z",
        ])

    assert registry.read_bytes() == before


def test_v7_preregister_rejects_conflicting_registry_event_before_writing(
    tmp_path,
):
    root, registry, _ = _paths(tmp_path)
    artifact = (
        root / "preregistrations" / "nse-halal-residual-momentum-v7.json"
    )
    assert main([
        "preregister", "--root", str(root), "--registry", str(registry),
        "--created-at", "2026-07-29T00:00:00Z",
    ]) == 0
    artifact.unlink()
    before = registry.read_bytes()

    with pytest.raises(ExperimentCommandError, match="immutable"):
        main([
            "preregister", "--root", str(root), "--registry", str(registry),
            "--created-at", "2026-07-29T00:00:01Z",
        ])

    assert registry.read_bytes() == before
    assert not artifact.exists()


def test_v7_preregistration_transaction_holds_registry_lock_through_commit(
    tmp_path,
):
    root, registry_path, _ = _paths(tmp_path)
    registry = ExperimentRegistry(registry_path)
    artifact = (
        root / "preregistrations" / "nse-halal-residual-momentum-v7.json"
    )
    event = build_preregistered_event(
        _protocol(),
        record_id="pre-v7-transaction",
        created_at="2026-07-29T00:00:00Z",
        source_hashes=_source_hashes(None),
        prior_trial_count=6,
    )
    probe = "\n".join([
        "import fcntl, sys",
        f"handle = open({str(registry_path)!r}, 'a+b')",
        "try:",
        "    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)",
        "except BlockingIOError:",
        "    raise SystemExit(0)",
        "raise SystemExit(1)",
    ])

    with registry.preregistration_transaction() as transaction:
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        transaction.commit_preregistration(
            event,
            artifact,
            canonical_json_bytes(event),
        )

    assert artifact.read_bytes() == canonical_json_bytes(event)
    assert registry.events("nse-halal-residual-momentum-v7") == [event]


def test_v7_preregister_seals_sources_after_waiting_for_registry_lock(
    monkeypatch,
    tmp_path,
):
    root, registry_path, _ = _paths(tmp_path)
    source_root = tmp_path / "sealed-sources"
    for number, name in enumerate(V7_SOURCE_KEYS):
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"VALUE = {number}\n", encoding="utf-8")
    changed_source = source_root / V7_SOURCE_KEYS[0]
    old_hash = hashlib.sha256(changed_source.read_bytes()).hexdigest()
    _temporary_source_seal(monkeypatch, source_root, V7_SOURCE_KEYS)

    original_transaction = ExperimentRegistry.preregistration_transaction
    lock_attempted = Event()

    @contextmanager
    def signal_lock_attempt(self):
        lock_attempted.set()
        with original_transaction(self) as transaction:
            yield transaction

    monkeypatch.setattr(
        ExperimentRegistry,
        "preregistration_transaction",
        signal_lock_attempt,
    )

    outcome = {}

    def preregister() -> None:
        try:
            outcome["result"] = main([
                "preregister", "--root", str(root), "--registry", str(registry_path),
                "--created-at", "2026-07-29T00:00:00Z",
            ])
        except BaseException as exc:
            outcome["error"] = exc

    registry = ExperimentRegistry(registry_path)
    with original_transaction(registry):
        worker = Thread(target=preregister)
        worker.start()
        assert lock_attempted.wait(timeout=2)
        changed_source.write_text("VALUE = 'changed'\n", encoding="utf-8")

    worker.join(timeout=5)
    assert not worker.is_alive()
    assert "error" not in outcome
    assert outcome["result"] == 0

    event = ExperimentRegistry(registry_path).events(
        "nse-halal-residual-momentum-v7"
    )[0]
    changed_hash = hashlib.sha256(changed_source.read_bytes()).hexdigest()
    assert changed_hash != old_hash
    assert event["source_hashes"][V7_SOURCE_KEYS[0]] == changed_hash


def test_v7_preregistration_transaction_rolls_back_partial_registry_write(
    monkeypatch,
    tmp_path,
):
    root, registry, _ = _paths(tmp_path)
    artifact = (
        root / "preregistrations" / "nse-halal-residual-momentum-v7.json"
    )
    registry_before = registry.read_bytes()

    def fail_after_partial_write(_self, handle, encoded):
        handle.seek(0, os.SEEK_END)
        handle.write(encoded[:17])
        handle.flush()
        raise OSError("injected partial append failure")

    monkeypatch.setattr(
        ExperimentRegistry,
        "_append_locked",
        fail_after_partial_write,
        raising=False,
    )

    with pytest.raises(ExperimentCommandError, match="transaction"):
        main([
            "preregister", "--root", str(root), "--registry", str(registry),
            "--created-at", "2026-07-29T00:00:00Z",
        ])

    assert registry.read_bytes() == registry_before
    assert not artifact.exists()
    assert not list(artifact.parent.glob("*.part"))


def test_v7_preregistration_transaction_leaves_no_state_on_artifact_replace_failure(
    monkeypatch,
    tmp_path,
):
    root, registry, _ = _paths(tmp_path)
    artifact = (
        root / "preregistrations" / "nse-halal-residual-momentum-v7.json"
    )
    registry_before = registry.read_bytes()
    original_replace = registry_module.os.replace

    def fail_artifact_replace(source, destination):
        if Path(source).name == artifact.name + ".part":
            raise OSError("injected artifact replace failure")
        return original_replace(source, destination)

    monkeypatch.setattr(registry_module.os, "replace", fail_artifact_replace)

    with pytest.raises(ExperimentCommandError, match="transaction"):
        main([
            "preregister", "--root", str(root), "--registry", str(registry),
            "--created-at", "2026-07-29T00:00:00Z",
        ])

    assert registry.read_bytes() == registry_before
    assert not artifact.exists()
    assert not list(artifact.parent.glob("*.part"))


def test_source_seal_rejects_incomplete_dataless_placeholder_read(monkeypatch):
    original_read = experiment_module.os.read

    def incomplete_read(descriptor, size):
        if size > 0:
            return b""
        return original_read(descriptor, size)

    monkeypatch.setattr(experiment_module.os, "read", incomplete_read)

    with pytest.raises(ExperimentCommandError, match="completely and stably"):
        _source_hashes(None)


def _temporary_source_seal(monkeypatch, root, names):
    monkeypatch.setattr(experiment_module, "_PROJECT_ROOT", root)
    monkeypatch.setattr(experiment_module, "_DEFAULT_SOURCES", tuple(names))


def test_source_seal_rejects_symlink_and_nonregular_files(monkeypatch, tmp_path):
    target = tmp_path / "target.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    link = tmp_path / "link.py"
    link.symlink_to(target)
    _temporary_source_seal(monkeypatch, tmp_path, ("link.py",))

    with pytest.raises(ExperimentCommandError, match="regular non-symlink"):
        _source_hashes(None)

    fifo = tmp_path / "source.fifo"
    os.mkfifo(fifo)
    _temporary_source_seal(monkeypatch, tmp_path, ("source.fifo",))

    with pytest.raises(ExperimentCommandError, match="regular non-symlink"):
        _source_hashes(None)


def test_source_seal_second_pass_detects_same_size_mtime_atomic_replacement(
    monkeypatch,
    tmp_path,
):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_bytes(b"AAAA")
    second.write_bytes(b"BBBB")
    original_times = first.stat()
    _temporary_source_seal(monkeypatch, tmp_path, ("first.py", "second.py"))
    original_reader = experiment_module._read_source_snapshot
    reads = 0

    def replace_after_first_pass(name):
        nonlocal reads
        snapshot = original_reader(name)
        reads += 1
        if reads == 2:
            replacement = tmp_path / "replacement.py"
            replacement.write_bytes(b"CCCC")
            os.utime(
                replacement,
                ns=(original_times.st_atime_ns, original_times.st_mtime_ns),
            )
            os.replace(replacement, first)
        return snapshot

    monkeypatch.setattr(
        experiment_module,
        "_read_source_snapshot",
        replace_after_first_pass,
        raising=False,
    )

    with pytest.raises(ExperimentCommandError, match="changed between source passes"):
        experiment_module._sealed_source_hashes(None)


def test_source_seal_second_pass_detects_earlier_file_drift(
    monkeypatch,
    tmp_path,
):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    _temporary_source_seal(monkeypatch, tmp_path, ("first.py", "second.py"))
    original_reader = experiment_module._read_source_snapshot
    reads = 0

    def drift_after_first_pass(name):
        nonlocal reads
        snapshot = original_reader(name)
        reads += 1
        if reads == 2:
            first.write_bytes(b"drift")
        return snapshot

    monkeypatch.setattr(
        experiment_module,
        "_read_source_snapshot",
        drift_after_first_pass,
        raising=False,
    )

    with pytest.raises(ExperimentCommandError, match="changed between source passes"):
        experiment_module._sealed_source_hashes(None)


def test_preflight_is_aggregate_only_and_does_not_import_strategy_calculations(
    monkeypatch, tmp_path
):
    root, registry, _ = _preregister(tmp_path)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.run_preflight",
        lambda *_args, **_kwargs: _passing_preflight(),
    )
    assert main([
        "preflight", "--root", str(root), "--registry", str(registry),
        "--store", str(tmp_path / "store.db"),
    ]) == 0

    artifact = root / "preflight" / "nse-halal-residual-momentum-v7.json"
    payload = json.loads(artifact.read_text())
    assert payload["passed"] is True
    assert set(payload) == {
        "aggregates", "blockers", "dataset_manifest_sha256", "manifest_payload", "passed"
    }


def test_preflight_in_fresh_interpreter_does_not_import_strategy_calculations(tmp_path):
    root, registry, _ = _preregister(tmp_path)
    code = "\n".join([
        "import sys",
        "from src.reliability.residual_momentum_experiment import main",
        f"assert main(['preflight', '--root', {str(root)!r}, '--registry', {str(registry)!r}, '--store', {str(tmp_path / 'store.db')!r}]) == 0",
        "assert 'src.reliability.historical_portfolio' not in sys.modules",
        "assert 'src.reliability.residual_momentum' not in sys.modules",
    ])
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path.cwd(), capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr


def test_preregister_and_recovery_work_in_fresh_interpreters(
    monkeypatch, tmp_path
):
    root, registry_path, _ = _paths(tmp_path)
    preregister = "\n".join([
        "from src.reliability.residual_momentum_experiment import main",
        f"assert main(['preregister', '--root', {str(root)!r}, '--registry', {str(registry_path)!r}, '--created-at', '2026-07-13T00:00:00Z']) == 0",
    ])
    preregistration = subprocess.run(
        [sys.executable, "-c", preregister],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    assert preregistration.returncode == 0, preregistration.stderr

    preflight = _passing_preflight()
    _write_preflight(root, preflight)
    tri = _write_tri(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {
            "dataset_manifest_sha256": preflight.dataset_manifest_sha256,
        },
    )
    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupted")),
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry_path),
            "--store", str(tmp_path / "store.db"), "--tri", str(tri),
        ])

    recover = "\n".join([
        "from src.reliability import historical_portfolio",
        "from src.reliability import residual_momentum_experiment as experiment",
        "from src.reliability.experiment_registry import ExperimentRegistry",
        f"experiment.verify_preflight_binding = lambda *_args: {{'dataset_manifest_sha256': {preflight.dataset_manifest_sha256!r}}}",
        "historical_portfolio.run_residual_momentum_evaluation = lambda *_args, **_kwargs: {'verdict': 'REJECTED', 'metrics': {}, 'failed_gates': [], 'reproducibility': {'input_manifest': {}}}",
        f"assert experiment.main(['evaluate', '--root', {str(root)!r}, '--registry', {str(registry_path)!r}, '--store', {str(tmp_path / 'store.db')!r}, '--tri', {str(tri)!r}]) == 0",
        f"assert ExperimentRegistry({str(registry_path)!r}).state('nse-halal-residual-momentum-v7') == 'REJECTED'",
    ])
    recovery = subprocess.run(
        [sys.executable, "-c", recover],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert recovery.returncode == 0, recovery.stderr


def test_preregister_rejects_non_source_path_without_opening_it(tmp_path):
    root, registry, source = _paths(tmp_path)
    source.write_text("holdout values", encoding="utf-8")

    with pytest.raises(ExperimentCommandError, match="approved source"):
        main([
            "preregister", "--root", str(root), "--registry", str(registry),
            "--source", str(source), "--created-at", "2026-07-13T00:00:00Z",
        ])

    assert not (root / "preregistrations").exists()


def test_acquire_tri_requires_existing_preregistration(tmp_path):
    with pytest.raises(ExperimentCommandError, match="preregistration"):
        main([
            "acquire-tri", "--root", str(tmp_path),
            "--start", "2015-01-01", "--end", "2015-01-01",
        ])


def test_acquire_tri_retains_one_merged_full_period_manifest(
    monkeypatch,
    tmp_path,
):
    root, registry, _ = _preregister(tmp_path)
    acquired = []
    merged = []
    monkeypatch.setattr(
        NiftyTriAcquirer,
        "acquire",
        lambda _self, window: acquired.append(window),
    )
    monkeypatch.setattr(
        NiftyTriAcquirer,
        "merge_retained",
        lambda _self, start, end: merged.append((start, end)),
    )

    assert main([
        "acquire-tri",
        "--root", str(root),
        "--registry", str(registry),
        "--start", "2013-12-01",
        "--end", "2019-12-31",
    ]) == 0

    assert acquired == build_tri_windows(
        date(2013, 12, 1),
        date(2019, 12, 31),
    )
    assert merged == [(
        date(2013, 12, 1),
        date(2019, 12, 31),
    )]


def test_evaluate_refuses_missing_or_failed_preflight(tmp_path):
    root, registry, _ = _preregister(tmp_path)
    with pytest.raises(ExperimentCommandError, match="preflight"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry),
            "--store", str(tmp_path / "store.db"), "--tri", str(_write_tri(root)),
        ])


def test_evaluate_rejects_fabricated_or_uncatalogued_tri_before_start(
    monkeypatch, tmp_path
):
    root, registry, _ = _preregister(tmp_path)
    _write_preflight(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {"dataset_manifest_sha256": _passing_preflight().dataset_manifest_sha256},
    )

    with pytest.raises(ExperimentCommandError, match="retained TRI"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry),
            "--store", str(tmp_path / "store.db"),
            "--tri", str(_write_fabricated_tri(root)),
        ])
    assert ExperimentRegistry(registry).state("nse-halal-residual-momentum-v7") == "PREREGISTERED"

    with pytest.raises(ExperimentCommandError, match="catalogue"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry),
            "--store", str(tmp_path / "store.db"),
            "--tri", str(_write_tri(root, catalogue=False)),
        ])
    assert ExperimentRegistry(registry).state("nse-halal-residual-momentum-v7") == "PREREGISTERED"

    _write_preflight(root, PreflightResult(False, ("BARS",), {}, None, None))
    with pytest.raises(ExperimentCommandError, match="preflight"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry),
            "--store", str(tmp_path / "store.db"), "--tri", str(_write_tri(root)),
        ])


def test_evaluate_rejects_catalogued_single_window_without_full_protocol_coverage(
    monkeypatch, tmp_path
):
    root, registry, _ = _preregister(tmp_path)
    _write_preflight(root)
    tri = _write_single_window_tri(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {
            "dataset_manifest_sha256": (
                _passing_preflight().dataset_manifest_sha256
            ),
            "sessions": ("2015-01-01",),
        },
    )
    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation",
        lambda *_args, **_kwargs: {
            "verdict": "REJECTED",
            "metrics": {},
            "failed_gates": ["FIXTURE"],
        },
    )

    with pytest.raises(
        ExperimentCommandError,
        match="merged|coverage",
    ):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry),
            "--store", str(tmp_path / "store.db"), "--tri", str(tri),
        ])

    assert ExperimentRegistry(registry).state(
        "nse-halal-residual-momentum-v7"
    ) == "PREREGISTERED"


def test_evaluate_rejects_merged_tri_missing_a_preflight_session(
    monkeypatch,
    tmp_path,
):
    root, registry, _ = _preregister(tmp_path)
    _write_preflight(root)
    tri = _write_tri(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {
            "dataset_manifest_sha256": (
                _passing_preflight().dataset_manifest_sha256
            ),
            "sessions": ("2015-01-01", "2015-01-02"),
        },
    )

    with pytest.raises(ExperimentCommandError, match="coverage"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry),
            "--store", str(tmp_path / "store.db"), "--tri", str(tri),
        ])

    assert ExperimentRegistry(registry).state(
        "nse-halal-residual-momentum-v7"
    ) == "PREREGISTERED"


def test_evaluate_starts_before_evaluator_and_writes_canonical_report_atomically(
    monkeypatch, tmp_path
):
    root, registry_path, _ = _preregister(tmp_path)
    _write_preflight(root)
    tri = _write_tri(root)
    registry = ExperimentRegistry(registry_path)
    observed = []

    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {"dataset_manifest_sha256": _passing_preflight().dataset_manifest_sha256},
    )

    def evaluate(*_args, **kwargs):
        observed.append((
            registry.state("nse-halal-residual-momentum-v7"),
            kwargs.get("effective_n_trials"),
        ))
        return {
            "verdict": "REJECTED",
            "metrics": {"observations": 1},
            "failed_gates": ["FIXTURE"],
            "reproducibility": {"input_manifest": {}},
        }

    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation", evaluate,
    )

    assert main([
        "evaluate", "--root", str(root), "--registry", str(registry_path),
        "--store", str(tmp_path / "store.db"), "--tri", str(tri),
    ]) == 0

    assert observed == [("EVALUATION_STARTED", 7)]
    started = ExperimentRegistry(registry_path).events()[-2]
    assert started["effective_n_trials"] == 7
    attempt = json.loads(
        (
            root / "attempts" / "nse-halal-residual-momentum-v7.json"
        ).read_text()
    )
    assert attempt["input_manifest"]["effective_n_trials"] == 7
    report = root / "reports" / "nse-halal-residual-momentum-v7.json"
    assert report.read_bytes() == canonical_json_bytes(json.loads(report.read_text()))
    assert not list(report.parent.glob("*.part"))
    completed = ExperimentRegistry(registry_path).events()[-1]
    assert completed["record_type"] == "EVALUATED"
    assert completed["report_sha256"] == hashlib.sha256(report.read_bytes()).hexdigest()


def test_evaluator_exception_consumes_attempt_and_second_start_is_rejected(
    monkeypatch, tmp_path
):
    root, registry_path, _ = _preregister(tmp_path)
    _write_preflight(root)
    tri = _write_tri(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {"dataset_manifest_sha256": _passing_preflight().dataset_manifest_sha256},
    )
    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupted")),
    )

    with pytest.raises(RuntimeError, match="interrupted"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry_path),
            "--store", str(tmp_path / "store.db"), "--tri", str(tri),
        ])

    assert ExperimentRegistry(registry_path).state("nse-halal-residual-momentum-v7") == "EVALUATION_STARTED"
    assert main([
        "evaluate", "--root", str(root), "--registry", str(registry_path),
        "--store", str(tmp_path / "other.db"), "--tri", str(tri),
    ]) == 0
    assert ExperimentRegistry(registry_path).state("nse-halal-residual-momentum-v7") == "INVALID"


def test_exact_input_recovery_completes_started_attempt(
    monkeypatch, tmp_path
):
    root, registry_path, source = _preregister(tmp_path)
    _write_preflight(root)
    tri = _write_tri(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {"dataset_manifest_sha256": _passing_preflight().dataset_manifest_sha256},
    )
    calls = []

    def fail_once(*_args, **_kwargs):
        calls.append("first")
        raise RuntimeError("interrupted")

    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation", fail_once,
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry_path),
            "--store", str(tmp_path / "store.db"), "--tri", str(tri),
        ])

    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation",
        lambda *_args, **_kwargs: {
            "verdict": "REJECTED", "metrics": {}, "failed_gates": [],
            "reproducibility": {"input_manifest": {}},
        },
    )
    assert main([
        "evaluate", "--root", str(root), "--registry", str(registry_path),
        "--store", str(tmp_path / "store.db"), "--tri", str(tri),
    ]) == 0
    assert ExperimentRegistry(registry_path).state("nse-halal-residual-momentum-v7") == "REJECTED"


def test_recovery_refuses_forged_report_until_evaluator_reproduces_it(
    monkeypatch, tmp_path
):
    root, registry_path, _ = _preregister(tmp_path)
    _write_preflight(root)
    tri = _write_tri(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {"dataset_manifest_sha256": _passing_preflight().dataset_manifest_sha256},
    )
    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupted")),
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry_path),
            "--store", str(tmp_path / "store.db"), "--tri", str(tri),
        ])

    attempt = json.loads((root / "attempts" / "nse-halal-residual-momentum-v7.json").read_text())
    forged = {
        "verdict": "ACCEPTED",
        "metrics": {},
        "failed_gates": [],
        "release_approved": False,
        "command_input_manifest": attempt["input_manifest"],
        "command_input_manifest_sha256": attempt["input_manifest_sha256"],
    }
    report = root / "reports" / "nse-halal-residual-momentum-v7.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(canonical_json_bytes(forged))
    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation",
        lambda *_args, **_kwargs: {
            "verdict": "REJECTED", "metrics": {}, "failed_gates": [],
            "reproducibility": {"input_manifest": {}},
        },
    )

    with pytest.raises(ExperimentCommandError, match="reproduce"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry_path),
            "--store", str(tmp_path / "store.db"), "--tri", str(tri),
        ])
    assert ExperimentRegistry(registry_path).state("nse-halal-residual-momentum-v7") == "EVALUATION_STARTED"


def test_recovery_input_drift_writes_invalid_report_beside_existing_report(
    monkeypatch, tmp_path
):
    root, registry_path, _ = _preregister(tmp_path)
    _write_preflight(root)
    tri = _write_tri(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {"dataset_manifest_sha256": _passing_preflight().dataset_manifest_sha256},
    )
    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("interrupted")),
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry_path),
            "--store", str(tmp_path / "store.db"), "--tri", str(tri),
        ])

    attempt = json.loads((root / "attempts" / "nse-halal-residual-momentum-v7.json").read_text())
    report = root / "reports" / "nse-halal-residual-momentum-v7.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(canonical_json_bytes({
        "verdict": "REJECTED",
        "metrics": {},
        "failed_gates": [],
        "release_approved": False,
        "command_input_manifest": attempt["input_manifest"],
        "command_input_manifest_sha256": attempt["input_manifest_sha256"],
    }))
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment._environment_manifest",
        lambda: {"runtime": "changed"},
    )

    assert main([
        "evaluate", "--root", str(root), "--registry", str(registry_path),
        "--store", str(tmp_path / "store.db"), "--tri", str(tri),
    ]) == 0
    assert ExperimentRegistry(registry_path).state("nse-halal-residual-momentum-v7") == "INVALID"
    assert report.exists()
    assert (root / "reports" / "nse-halal-residual-momentum-v7.invalid.json").exists()

@pytest.mark.parametrize("changed_input", ["code", "protocol", "dataset", "environment"])
def test_changed_recovery_input_is_invalid_without_rerunning(
    monkeypatch, tmp_path, changed_input
):
    root, registry_path, source = _preregister(tmp_path / changed_input)
    _write_preflight(root)
    tri = _write_tri(root)
    monkeypatch.setattr(
        "src.reliability.residual_momentum_experiment.verify_preflight_binding",
        lambda *_args: {"dataset_manifest_sha256": _passing_preflight().dataset_manifest_sha256},
    )
    calls = []

    def interrupted(*_args, **_kwargs):
        calls.append("evaluator")
        raise RuntimeError("interrupted")

    monkeypatch.setattr(
        "src.reliability.historical_portfolio.run_residual_momentum_evaluation", interrupted,
    )
    store_path = tmp_path / f"{changed_input}.db"
    recovery_store_path = store_path
    with pytest.raises(RuntimeError, match="interrupted"):
        main([
            "evaluate", "--root", str(root), "--registry", str(registry_path),
            "--store", str(store_path), "--tri", str(tri),
        ])
    if changed_input == "code":
        monkeypatch.setattr(
            "src.reliability.residual_momentum_experiment._current_source_hashes",
            lambda stored: {**stored, next(iter(stored)): "f" * 64},
        )
    elif changed_input == "protocol":
        preregistration = root / "preregistrations" / "nse-halal-residual-momentum-v7.json"
        payload = json.loads(preregistration.read_text())
        payload["protocol"]["parameters"]["skip"] = 20
        preregistration.write_bytes(canonical_json_bytes(payload))
    elif changed_input == "dataset":
        recovery_store_path = tmp_path / "changed-dataset.db"
    else:
        monkeypatch.setattr(
            "src.reliability.residual_momentum_experiment._environment_manifest",
            lambda: {"runtime": "changed"},
        )

    assert main([
        "evaluate", "--root", str(root), "--registry", str(registry_path),
        "--store", str(recovery_store_path), "--tri", str(tri),
    ]) == 0
    completed = ExperimentRegistry(registry_path).events()[-1]
    assert completed["verdict"] == "INVALID"
    assert calls == ["evaluator"]
    assert {
        "code": "SOURCE_HASHES",
        "protocol": "PROTOCOL",
        "dataset": "DATASET",
        "environment": "ENVIRONMENT",
    }[changed_input] in completed["failed_gates"]
