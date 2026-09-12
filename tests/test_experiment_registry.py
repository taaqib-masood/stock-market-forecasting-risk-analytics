import json
import subprocess
import sys
from contextlib import contextmanager

import pytest

from src.reliability.experiment_registry import ExperimentRegistry, ExperimentRegistryError
from src.reliability.preregistration import (
    V4_SOURCE_KEYS,
    V5_SOURCE_KEYS,
    V6_SOURCE_KEYS,
    V7_SOURCE_KEYS,
    build_preregistered_event,
    sha256_json,
)


def _record(experiment_id="exp-1", report_hash="a" * 64):
    return {
        "experiment_id": experiment_id,
        "family": "nse-swing-2020-2024",
        "strategy_version": "rule-v1",
        "protocol_version": "dynamic-v1",
        "report_sha256": report_hash,
        "verdict": "REJECTED",
    }


def _protocol():
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
        "parameters": {"momentum_long": 252, "skip": 21, "atr": 14},
        "statistical_policy": {"min_observations": 504, "n_trials_floor": 7},
    }


def _v4_protocol():
    return {
        "experiment_id": "nse-halal-residual-momentum-v4",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v4",
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


def _v5_protocol():
    return {
        **_v4_protocol(),
        "experiment_id": "nse-halal-residual-momentum-v5",
        "protocol_version": "pit-nifty500-next-open-v5",
    }


def _v6_protocol():
    return {
        **_v5_protocol(),
        "experiment_id": "nse-halal-residual-momentum-v6",
        "protocol_version": "pit-nifty500-next-open-v6",
    }


def _v7_protocol():
    return {
        **_v6_protocol(),
        "experiment_id": "nse-halal-residual-momentum-v7",
        "protocol_version": "pit-nifty500-next-open-v7",
    }


def test_fresh_registry_process_accepts_v4_without_experiment_import(tmp_path):
    registry_path = tmp_path / "experiments.jsonl"
    protocol = json.dumps(_v4_protocol())
    source_hashes = json.dumps({key: "a" * 64 for key in V4_SOURCE_KEYS})
    code = "\n".join([
        "import json",
        "from src.reliability.experiment_registry import ExperimentRegistry",
        "from src.reliability.preregistration import build_preregistered_event",
        f"registry = ExperimentRegistry({str(registry_path)!r})",
        "for number in range(6):",
        "    registry.register({'experiment_id': f'legacy-{number}', 'family': 'nse-swing-2020-2024', 'strategy_version': 'legacy-v1', 'protocol_version': 'legacy-v1', 'report_sha256': f'{number + 1:064x}', 'verdict': 'REJECTED'})",
        f"protocol = json.loads({protocol!r})",
        f"event = build_preregistered_event(protocol, record_id='pre-v4', created_at='2026-07-13T00:00:00Z', source_hashes=json.loads({source_hashes!r}), prior_trial_count=6)",
        "registry.append_event(event)",
        "assert registry.state('nse-halal-residual-momentum-v4') == 'PREREGISTERED'",
    ])

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr


def _preregistered_event(
    record_id="pre-001",
    created_at="2026-07-13T00:00:00Z",
    prior_trial_count=6,
):
    return build_preregistered_event(
        _protocol(),
        record_id=record_id,
        created_at=created_at,
        source_hashes={"src/reliability/residual_momentum.py": "a" * 64},
        prior_trial_count=prior_trial_count,
    )


def _v4_preregistered_event():
    return build_preregistered_event(
        _v4_protocol(),
        record_id="pre-v4",
        created_at="2026-07-13T00:00:00Z",
        source_hashes={key: "a" * 64 for key in V4_SOURCE_KEYS},
        prior_trial_count=6,
    )


def _v5_preregistered_event():
    return build_preregistered_event(
        _v5_protocol(),
        record_id="pre-v5",
        created_at="2026-07-27T00:00:00Z",
        source_hashes={key: "a" * 64 for key in V5_SOURCE_KEYS},
        prior_trial_count=6,
    )


def _v6_preregistered_event():
    return build_preregistered_event(
        _v6_protocol(),
        record_id="pre-v6",
        created_at="2026-07-28T00:00:00Z",
        source_hashes={key: "a" * 64 for key in V6_SOURCE_KEYS},
        prior_trial_count=6,
    )


def _v7_preregistered_event():
    event = build_preregistered_event(
        _v7_protocol(),
        record_id="pre-v7",
        created_at="2026-07-29T00:00:00Z",
        source_hashes={key: "a" * 64 for key in V7_SOURCE_KEYS},
        prior_trial_count=6,
    )
    event.setdefault("supersedes", {
        "experiment_id": "nse-halal-residual-momentum-v6",
        "preregistration_sha256": (
            "21efd568affe40c7139d38bd5a4fc258de1146df817acadaefa1042cb3d5c6b8"
        ),
        "reason": (
            "v6 source seal predates canonical review authority and activation "
            "binding hardening; v7 seals the corrected fail-closed boundary"
        ),
    })
    return event


def _started_event(preregistered):
    return {
        "record_id": "start-001",
        "record_type": "EVALUATION_STARTED",
        "experiment_id": preregistered["protocol"]["experiment_id"],
        "created_at": "2026-07-13T00:01:00Z",
        "preregistration_sha256": sha256_json(preregistered),
        "dataset_manifest_sha256": "b" * 64,
        "input_manifest_sha256": "c" * 64,
        "effective_n_trials": preregistered["effective_n_trials"],
    }


def _evaluated_event(preregistered, verdict="REJECTED"):
    return {
        "record_id": "done-001",
        "record_type": "EVALUATED",
        "experiment_id": preregistered["protocol"]["experiment_id"],
        "created_at": "2026-07-13T00:02:00Z",
        "preregistration_sha256": sha256_json(preregistered),
        "dataset_manifest_sha256": "b" * 64,
        "input_manifest_sha256": "c" * 64,
        "report_sha256": "d" * 64,
        "code_sha256": "e" * 64,
        "environment_manifest_sha256": "f" * 64,
        "metrics": {"observations": 504},
        "failed_gates": ["DEFLATED_SHARPE"],
        "verdict": verdict,
    }


def _seed_legacy_trials(registry, count=6):
    for number in range(count):
        registry.register(_record(f"legacy-{number}", f"{number + 1:064x}"))


def _lifecycle_registry(tmp_path):
    registry = ExperimentRegistry(tmp_path / "experiments.jsonl")
    _seed_legacy_trials(registry)
    return registry


def test_registry_is_idempotent_and_counts_distinct_family_trials(tmp_path):
    registry = ExperimentRegistry(tmp_path / "experiments.jsonl")

    registry.register(_record())
    registry.register(_record())
    registry.register(_record("exp-2", "b" * 64))

    assert registry.trial_count("nse-swing-2020-2024") == 2
    assert len((tmp_path / "experiments.jsonl").read_text().splitlines()) == 2


def test_registry_rejects_mutation_of_existing_experiment(tmp_path):
    registry = ExperimentRegistry(tmp_path / "experiments.jsonl")
    registry.register(_record())

    with pytest.raises(ExperimentRegistryError, match="immutable"):
        registry.register(_record(report_hash="b" * 64))


def test_registry_rejects_invalid_report_hash(tmp_path):
    with pytest.raises(ExperimentRegistryError, match="SHA-256"):
        ExperimentRegistry(tmp_path / "experiments.jsonl").register(
            _record(report_hash="short")
        )


def test_register_preserves_legacy_json_wire_format(tmp_path):
    path = tmp_path / "experiments.jsonl"
    record = _record()

    ExperimentRegistry(path).register(record)

    assert path.read_text(encoding="utf-8") == json.dumps(record, sort_keys=True) + "\n"


def test_registry_enforces_preregister_start_evaluate_order(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    pre = _preregistered_event()
    start = _started_event(pre)
    done = _evaluated_event(pre)

    with pytest.raises(ExperimentRegistryError, match="PREREGISTERED"):
        registry.append_event(start)
    registry.append_event(pre)
    registry.append_event(start)
    registry.append_event(done)

    assert registry.state(pre["protocol"]["experiment_id"]) == "REJECTED"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda hashes: {key: value for key, value in hashes.items() if key != V4_SOURCE_KEYS[0]},
        lambda hashes: {**hashes, "src/reliability/fake.py": "b" * 64},
        lambda hashes: {
            **{key: value for key, value in hashes.items() if key != V4_SOURCE_KEYS[0]},
            "src/reliability/renamed_adjusted_prices.py": "a" * 64,
        },
    ),
    ids=("missing", "extra", "renamed"),
)
def test_registry_rejects_v4_source_key_drift(tmp_path, mutate):
    registry = _lifecycle_registry(tmp_path)
    event = _v4_preregistered_event()
    event["source_hashes"] = mutate(event["source_hashes"])

    with pytest.raises(ExperimentRegistryError, match="exact v4 source key set"):
        registry.append_event(event)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda hashes: {
            key: value
            for key, value in hashes.items()
            if key != V5_SOURCE_KEYS[0]
        },
        lambda hashes: {**hashes, "src/reliability/fake.py": "b" * 64},
        lambda hashes: {
            **{
                key: value
                for key, value in hashes.items()
                if key != V5_SOURCE_KEYS[0]
            },
            "src/reliability/renamed_adjusted_prices.py": "a" * 64,
        },
    ),
    ids=("missing", "extra", "renamed"),
)
def test_registry_rejects_v5_source_key_drift(tmp_path, mutate):
    registry = _lifecycle_registry(tmp_path)
    event = _v5_preregistered_event()
    event["source_hashes"] = mutate(event["source_hashes"])

    with pytest.raises(ExperimentRegistryError, match="exact v5 source key set"):
        registry.append_event(event)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda hashes: {
            key: value
            for key, value in hashes.items()
            if key != V6_SOURCE_KEYS[0]
        },
        lambda hashes: {**hashes, "src/reliability/fake.py": "b" * 64},
    ),
    ids=("missing", "extra"),
)
def test_registry_rejects_v6_source_key_drift(tmp_path, mutate):
    registry = _lifecycle_registry(tmp_path)
    event = _v6_preregistered_event()
    event["source_hashes"] = mutate(event["source_hashes"])

    with pytest.raises(ExperimentRegistryError, match="exact v6 source key set"):
        registry.append_event(event)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda hashes: {
            key: value
            for key, value in hashes.items()
            if key != V7_SOURCE_KEYS[0]
        },
        lambda hashes: {**hashes, "src/reliability/fake.py": "b" * 64},
        lambda hashes: {
            **{
                key: value
                for key, value in hashes.items()
                if key != V7_SOURCE_KEYS[0]
            },
            "src/reliability/renamed_adjusted_prices.py": "a" * 64,
        },
    ),
    ids=("missing", "extra", "renamed"),
)
def test_registry_rejects_v7_source_key_drift(tmp_path, mutate):
    registry = _lifecycle_registry(tmp_path)
    event = _v7_preregistered_event()
    event["source_hashes"] = mutate(event["source_hashes"])

    with pytest.raises(ExperimentRegistryError, match="exact v7 source key set"):
        registry.append_event(event)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prior_trial_count", 7),
        ("effective_n_trials", 8),
        ("validation_values_opened", True),
    ],
)
def test_registry_rejects_v7_trial_accounting_mutation(tmp_path, field, value):
    registry = _lifecycle_registry(tmp_path)
    event = _v7_preregistered_event()
    event[field] = value

    with pytest.raises(ExperimentRegistryError):
        registry.append_event(event)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda event: event.pop("supersedes"),
        lambda event: event["supersedes"].update({"reason": "altered"}),
        lambda event: event["supersedes"].update({"extra": "not allowed"}),
    ),
    ids=("missing", "altered", "extra"),
)
def test_registry_rejects_v7_supersession_drift(tmp_path, mutate):
    registry = _lifecycle_registry(tmp_path)
    event = _v7_preregistered_event()
    mutate(event)

    with pytest.raises(ExperimentRegistryError, match="supersession"):
        registry.append_event(event)


def test_append_event_holds_one_lock_across_read_validate_and_append(
    tmp_path,
    monkeypatch,
):
    registry = _lifecycle_registry(tmp_path)
    retained_rows = registry._raw_rows()
    held = False
    transitions = []

    @contextmanager
    def locked_transaction():
        nonlocal held
        assert held is False
        held = True
        transitions.append("locked")
        try:
            yield
        finally:
            transitions.append("unlocked")
            held = False

    def read_rows():
        assert held is True
        transitions.append("read")
        return retained_rows

    def append(_event):
        assert held is True
        transitions.append("append")

    monkeypatch.setattr(
        registry,
        "_locked_transaction",
        locked_transaction,
        raising=False,
    )
    monkeypatch.setattr(registry, "_raw_rows", read_rows)
    monkeypatch.setattr(registry, "_append", append)

    registry.append_event(_preregistered_event())

    assert transitions == ["locked", "read", "append", "unlocked"]


def test_registry_rejects_second_evaluation_start(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    pre = _preregistered_event()
    registry.append_event(pre)
    registry.append_event(_started_event(pre))

    with pytest.raises(ExperimentRegistryError, match="one evaluation"):
        registry.append_event({**_started_event(pre), "record_id": "start-2"})


def test_legacy_rejections_count_toward_new_family_trial_penalty(tmp_path):
    registry = ExperimentRegistry(tmp_path / "experiments.jsonl")

    _seed_legacy_trials(registry)

    assert registry.relevant_trial_count("nse-halal-swing") == 6


def test_relevant_trial_count_only_consumes_started_lifecycle_attempts(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    registry.append_event(preregistered)

    assert registry.relevant_trial_count("nse-halal-swing") == 6

    registry.append_event(_started_event(preregistered))
    assert registry.relevant_trial_count("nse-halal-swing") == 7


def test_registry_binds_preregistration_count_to_actual_prior_attempts(tmp_path):
    registry = _lifecycle_registry(tmp_path)

    with pytest.raises(ExperimentRegistryError, match="prior_trial_count must equal 6"):
        registry.append_event(_preregistered_event(prior_trial_count=7))


@pytest.mark.parametrize(
    ("prior_trial_count", "effective_n_trials"),
    [(6, 7), (7, 8)],
)
def test_registry_validates_effective_trials_against_actual_history(
    tmp_path, prior_trial_count, effective_n_trials
):
    registry = ExperimentRegistry(tmp_path / "experiments.jsonl")
    _seed_legacy_trials(registry, count=prior_trial_count)
    preregistered = _preregistered_event(
        prior_trial_count=prior_trial_count
    )
    preregistered["effective_n_trials"] = effective_n_trials

    registry.append_event(preregistered)

    assert registry.events()[-1]["effective_n_trials"] == effective_n_trials


def test_registry_counts_started_attempts_when_validating_preregistration(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    registry.append_event(preregistered)
    registry.append_event(_started_event(preregistered))
    stale_preregistration = _preregistered_event(
        record_id="pre-002",
        created_at="2026-07-13T00:02:00Z",
        prior_trial_count=6,
    )

    with pytest.raises(ExperimentRegistryError, match="prior_trial_count must equal 7"):
        registry.append_event(stale_preregistration)


def test_lifecycle_replay_is_idempotent_for_each_event_type(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    started = _started_event(preregistered)
    evaluated = _evaluated_event(preregistered)

    for event in (preregistered, preregistered, started, started, evaluated, evaluated):
        registry.append_event(event)

    record_ids = [event["record_id"] for event in registry.events() if "record_id" in event]
    assert record_ids == ["pre-001", "start-001", "done-001"]


def test_registry_rejects_corrupt_json(tmp_path):
    path = tmp_path / "experiments.jsonl"
    path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(ExperimentRegistryError, match="invalid registry JSON"):
        ExperimentRegistry(path).events()


def test_registry_rejects_duplicate_record_id_with_different_content(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    registry.append_event(preregistered)

    with pytest.raises(ExperimentRegistryError, match="record IDs are immutable"):
        registry.append_event({**preregistered, "created_at": "2026-07-13T00:01:00Z"})


def test_registry_rejects_preregistration_hash_mismatch(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    registry.append_event(preregistered)
    start = _started_event(preregistered)

    with pytest.raises(ExperimentRegistryError, match="preregistration hash"):
        registry.append_event({**start, "preregistration_sha256": "0" * 64})


def test_registry_rejects_evaluation_without_start(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    registry.append_event(preregistered)

    with pytest.raises(ExperimentRegistryError, match="EVALUATION_STARTED"):
        registry.append_event(_evaluated_event(preregistered))


def test_registry_rejects_timestamp_reversal(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    registry.append_event(preregistered)
    start = _started_event(preregistered)
    start["created_at"] = "2026-07-12T23:59:59Z"

    with pytest.raises(ExperimentRegistryError, match="timestamps"):
        registry.append_event(start)


def test_invalid_evaluation_consumes_the_attempt(tmp_path):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    registry.append_event(preregistered)
    registry.append_event(_started_event(preregistered))
    registry.append_event(_evaluated_event(preregistered, verdict="INVALID"))

    assert registry.state(preregistered["protocol"]["experiment_id"]) == "INVALID"
    with pytest.raises(ExperimentRegistryError, match="one evaluation"):
        registry.append_event(
            {
                **_started_event(preregistered),
                "record_id": "start-2",
                "created_at": "2026-07-13T00:03:00Z",
            }
        )


@pytest.mark.parametrize(
    "field", ["dataset_manifest_sha256", "input_manifest_sha256"]
)
def test_recovery_can_only_finish_the_exact_started_input_set(tmp_path, field):
    registry = _lifecycle_registry(tmp_path)
    preregistered = _preregistered_event()
    registry.append_event(preregistered)
    registry.append_event(_started_event(preregistered))

    with pytest.raises(ExperimentRegistryError, match="started input"):
        registry.append_event(
            {**_evaluated_event(preregistered), field: "0" * 64}
        )
