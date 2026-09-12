from copy import deepcopy
import json
import subprocess
import sys

import pytest

from src.reliability.preregistration import (
    V5_SOURCE_KEYS,
    V6_SOURCE_KEYS,
    V7_SOURCE_KEYS,
    build_preregistered_event,
    canonical_json_bytes,
    sha256_json,
    validate_protocol,
)


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


def _v3_protocol():
    return {
        "experiment_id": "nse-halal-residual-momentum-v3",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v3",
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


def _v4_protocol():
    protocol = _v3_protocol()
    protocol["experiment_id"] = "nse-halal-residual-momentum-v4"
    protocol["protocol_version"] = "pit-nifty500-next-open-v4"
    return protocol


def _v5_protocol():
    protocol = _v4_protocol()
    protocol["experiment_id"] = "nse-halal-residual-momentum-v5"
    protocol["protocol_version"] = "pit-nifty500-next-open-v5"
    return protocol


def _v6_protocol():
    protocol = _v5_protocol()
    protocol["experiment_id"] = "nse-halal-residual-momentum-v6"
    protocol["protocol_version"] = "pit-nifty500-next-open-v6"
    return protocol


def _v7_protocol():
    protocol = _v6_protocol()
    protocol["experiment_id"] = "nse-halal-residual-momentum-v7"
    protocol["protocol_version"] = "pit-nifty500-next-open-v7"
    return protocol


def test_v5_protocol_is_frozen_to_v4_strategy_semantics():
    protocol = _v5_protocol()
    validate_protocol(protocol, now="2026-07-27T00:00:00Z")

    changed = deepcopy(protocol)
    changed["parameters"]["momentum_long"] = 251

    with pytest.raises(ValueError, match="frozen experiment semantics"):
        validate_protocol(changed, now="2026-07-27T00:00:00Z")


def test_v6_protocol_is_frozen_to_v5_strategy_semantics():
    protocol = _v6_protocol()
    validate_protocol(protocol, now="2026-07-28T00:00:00Z")

    changed = deepcopy(protocol)
    changed["statistical_policy"]["min_observations"] = 503

    with pytest.raises(ValueError, match="frozen experiment semantics"):
        validate_protocol(changed, now="2026-07-28T00:00:00Z")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("periods", "warmup", 0), "2013-12-02"),
        (("parameters", "momentum_long"), 251),
        (("benchmark",), "NIFTY 500 TRI GROSS"),
        (("statistical_policy", "min_observations"), 503),
    ],
    ids=("periods", "parameters", "benchmark", "statistical-policy"),
)
def test_v7_protocol_is_frozen_to_v6_strategy_semantics(path, value):
    protocol = _v7_protocol()
    validate_protocol(protocol, now="2026-07-29T00:00:00Z")

    changed = deepcopy(protocol)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError, match="protocol"):
        validate_protocol(changed, now="2026-07-29T00:00:00Z")


def test_fresh_preregistration_process_accepts_only_exact_v3_protocol():
    protocol = json.dumps(_v3_protocol())
    code = "\n".join([
        "from copy import deepcopy",
        "import json",
        "from src.reliability.preregistration import validate_protocol",
        f"protocol = json.loads({protocol!r})",
        "validate_protocol(protocol, now='2026-07-13T00:00:00Z')",
        "mutations = [",
        "    (('experiment_id',), 'nse-halal-residual-momentum-v2'),",
        "    (('family',), 'other-family'),",
        "    (('strategy_version',), 'residual-momentum-v2'),",
        "    (('protocol_version',), 'pit-nifty500-next-open-v4'),",
        "    (('universe',), 'NIFTY 200'),",
        "    (('benchmark',), 'NIFTY 50'),",
        "    (('periods', 'warmup', 0), '2013-12-02'),",
        "    (('parameters', 'momentum_long'), 251),",
        "    (('parameters', 'skip'), 20),",
        "    (('parameters', 'atr'), 15),",
        "    (('parameters', 'halal_max_age_days'), 364),",
        "    (('statistical_policy', 'min_observations'), 503),",
        "    (('statistical_policy', 'n_trials_floor'), 8),",
        "    (('parameters', 'momentum_long'), 252.0),",
        "    (('parameters', 'skip'), 21.0),",
        "    (('parameters', 'atr'), 14.0),",
        "    (('parameters', 'halal_max_age_days'), 365.0),",
        "    (('statistical_policy', 'min_observations'), 504.0),",
        "    (('statistical_policy', 'n_trials_floor'), 7.0),",
        "    (('parameters', 'momentum_long'), True),",
        "    (('parameters', 'skip'), True),",
        "    (('parameters', 'atr'), True),",
        "    (('parameters', 'halal_max_age_days'), True),",
        "    (('statistical_policy', 'min_observations'), True),",
        "    (('statistical_policy', 'n_trials_floor'), True),",
        "]",
        "for path, value in mutations:",
        "    changed = deepcopy(protocol)",
        "    target = changed",
        "    for key in path[:-1]:",
        "        target = target[key]",
        "    target[path[-1]] = value",
        "    try:",
        "        validate_protocol(changed, now='2026-07-13T00:00:00Z')",
        "    except ValueError:",
        "        pass",
        "    else:",
        "        raise AssertionError(path)",
        "for path in [('parameters', 'atr'), ('statistical_policy', 'n_trials_floor')]:",
        "    changed = deepcopy(protocol)",
        "    del changed[path[0]][path[1]]",
        "    try:",
        "        validate_protocol(changed, now='2026-07-13T00:00:00Z')",
        "    except ValueError:",
        "        pass",
        "    else:",
        "        raise AssertionError(('missing', path))",
        "for path, value in [",
        "    (('parameters', 'unexpected'), 1),",
        "    (('statistical_policy', 'unexpected'), 1),",
        "    (('unexpected',), 1),",
        "]:",
        "    changed = deepcopy(protocol)",
        "    target = changed",
        "    for key in path[:-1]:",
        "        target = target[key]",
        "    target[path[-1]] = value",
        "    try:",
        "        validate_protocol(changed, now='2026-07-13T00:00:00Z')",
        "    except ValueError:",
        "        pass",
        "    else:",
        "        raise AssertionError(('extra', path))",
    ])

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr


def test_experiment_import_does_not_mutate_shared_validator_identities():
    code = "\n".join([
        "from copy import deepcopy",
        "from src.reliability import preregistration",
        "before = deepcopy(preregistration._FROZEN_IDENTITIES)",
        "import src.reliability.residual_momentum_experiment",
        "assert preregistration._FROZEN_IDENTITIES == before",
    ])

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr


def test_canonical_hash_is_order_independent_and_material_field_sensitive():
    protocol = _protocol()
    reordered = {key: protocol[key] for key in reversed(protocol)}
    assert canonical_json_bytes(protocol) == canonical_json_bytes(reordered)
    changed = deepcopy(protocol)
    changed["parameters"]["skip"] = 20
    assert sha256_json(protocol) != sha256_json(changed)


def test_protocol_rejects_scored_overlap_with_burned_period():
    protocol = _protocol()
    protocol["periods"]["scored"] = ["2024-01-01", "2024-12-31"]
    with pytest.raises(ValueError, match="burned"):
        validate_protocol(protocol, now="2026-07-13T00:00:00Z")


@pytest.mark.parametrize(
    ("prior_trial_count", "effective_n_trials"),
    [(6, 7), (7, 8)],
)
def test_preregistered_event_counts_current_trial(
    prior_trial_count, effective_n_trials
):
    event = build_preregistered_event(
        _protocol(), record_id="pre-001", created_at="2026-07-13T00:00:00Z",
        source_hashes={"src/reliability/residual_momentum.py": "a" * 64},
        prior_trial_count=prior_trial_count,
    )
    assert event["record_type"] == "PREREGISTERED"
    assert event["protocol_sha256"] == sha256_json(_protocol())
    assert event["effective_n_trials"] == effective_n_trials
    assert event["validation_values_opened"] is False


def test_canonical_json_uses_utf8_compact_json_and_trailing_newline():
    value = {"z": "caf\N{LATIN SMALL LETTER E WITH ACUTE}", "a": [1, True]}
    assert canonical_json_bytes(value) == b'{"a":[1,true],"z":"caf\xc3\xa9"}\n'


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json_bytes({"value": float("nan")})


@pytest.mark.parametrize(
    "value",
    [
        {1: "integer key"},
        {"nested": [{"valid": "key"}, {2: "integer key"}]},
    ],
)
def test_canonical_json_rejects_non_string_mapping_keys_recursively(value):
    with pytest.raises(ValueError, match="string"):
        canonical_json_bytes(value)


@pytest.mark.parametrize(
    "field",
    [
        "experiment_id",
        "family",
        "strategy_version",
        "protocol_version",
        "periods",
        "universe",
        "benchmark",
        "parameters",
        "statistical_policy",
    ],
)
def test_protocol_requires_every_top_level_field(field):
    protocol = _protocol()
    del protocol[field]
    with pytest.raises(ValueError, match=field):
        validate_protocol(protocol, now="2026-07-13T00:00:00Z")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("experiment_id", "another-experiment"),
        ("family", "another-family"),
        ("strategy_version", "residual-momentum-v2"),
        ("protocol_version", "another-protocol"),
        ("universe", "NIFTY 200"),
        ("benchmark", "NIFTY 50"),
    ],
)
def test_protocol_rejects_changes_to_frozen_identities(field, value):
    protocol = _protocol()
    protocol[field] = value
    with pytest.raises(ValueError, match=field):
        validate_protocol(protocol, now="2026-07-13T00:00:00Z")


@pytest.mark.parametrize(
    "now",
    [
        "2026-07-13T00:00:00+00:00",
        "2026-07-13 00:00:00Z",
        "2026-07-13T00:00:00z",
        "not-a-timestamp",
    ],
)
def test_protocol_requires_valid_utc_z_preregistration_timestamp(now):
    with pytest.raises(ValueError, match="UTC Z timestamp"):
        validate_protocol(_protocol(), now=now)


@pytest.mark.parametrize(
    ("period_name", "period"),
    [
        ("warmup", ["2014-12-31", "2013-12-01"]),
        ("scored", ["2019-12-31", "2015-01-01"]),
        ("warmup", ["2013-02-29", "2014-12-31"]),
        ("scored", ["2015/01/01", "2019-12-31"]),
    ],
)
def test_protocol_rejects_invalid_or_reverse_ordered_periods(period_name, period):
    protocol = _protocol()
    protocol["periods"][period_name] = period
    with pytest.raises(ValueError, match=period_name):
        validate_protocol(protocol, now="2026-07-13T00:00:00Z")


def test_protocol_rejects_warmup_that_does_not_precede_scored_period():
    protocol = _protocol()
    protocol["periods"]["warmup"] = ["2015-01-01", "2015-12-31"]
    with pytest.raises(ValueError, match="warmup"):
        validate_protocol(protocol, now="2026-07-13T00:00:00Z")


@pytest.mark.parametrize(
    ("period_name", "shifted_period"),
    [
        ("warmup", ["2013-12-02", "2014-12-31"]),
        ("scored", ["2015-01-02", "2019-12-31"]),
        ("burned", [["2020-01-02", "2024-06-30"]]),
    ],
)
def test_protocol_rejects_changes_to_frozen_periods(period_name, shifted_period):
    protocol = _protocol()
    protocol["periods"][period_name] = shifted_period
    with pytest.raises(ValueError, match=period_name):
        validate_protocol(protocol, now="2026-07-13T00:00:00Z")


def test_protocol_checks_every_burned_period_for_scored_overlap():
    protocol = _protocol()
    protocol["periods"]["burned"] = [
        ["2010-01-01", "2010-12-31"],
        ["2019-12-31", "2024-06-30"],
    ]
    with pytest.raises(ValueError, match="burned"):
        validate_protocol(protocol, now="2026-07-13T00:00:00Z")


def test_protocol_rejects_scored_period_that_has_not_fully_ended():
    with pytest.raises(ValueError, match="scored"):
        validate_protocol(_protocol(), now="2019-12-31T23:59:59Z")


@pytest.mark.parametrize(
    "source_hashes",
    [
        {},
        {"src/reliability/residual_momentum.py": "A" * 64},
        {"src/reliability/residual_momentum.py": "g" * 64},
        {"src/reliability/residual_momentum.py": "a" * 63},
    ],
)
def test_preregistered_event_requires_lowercase_sha256_source_hashes(source_hashes):
    with pytest.raises(ValueError, match="source_hashes"):
        build_preregistered_event(
            _protocol(),
            record_id="pre-001",
            created_at="2026-07-13T00:00:00Z",
            source_hashes=source_hashes,
            prior_trial_count=6,
        )


def test_v4_preregistration_requires_the_exact_frozen_source_key_set():
    with pytest.raises(ValueError, match="exact v4 source key set"):
        build_preregistered_event(
            _v4_protocol(),
            record_id="pre-v4",
            created_at="2026-07-27T00:00:00Z",
            source_hashes={"src/reliability/fake.py": "a" * 64},
            prior_trial_count=6,
        )


@pytest.mark.parametrize(
    "source_hashes",
    [
        {key: "a" * 64 for key in V5_SOURCE_KEYS[1:]},
        {
            **{key: "a" * 64 for key in V5_SOURCE_KEYS},
            "src/reliability/fake.py": "b" * 64,
        },
        {
            **{key: "a" * 64 for key in V5_SOURCE_KEYS[1:]},
            "src/reliability/renamed_adjusted_prices.py": "a" * 64,
        },
    ],
    ids=("missing", "extra", "renamed"),
)
def test_v5_preregistration_requires_the_exact_frozen_source_key_set(
    source_hashes,
):
    with pytest.raises(ValueError, match="exact v5 source key set"):
        build_preregistered_event(
            _v5_protocol(),
            record_id="pre-v5",
            created_at="2026-07-27T00:00:00Z",
            source_hashes=source_hashes,
            prior_trial_count=6,
        )


def test_v5_preregistered_event_keeps_trial_accounting_value_blind():
    event = build_preregistered_event(
        _v5_protocol(),
        record_id="pre-v5",
        created_at="2026-07-27T00:00:00Z",
        source_hashes={key: "a" * 64 for key in V5_SOURCE_KEYS},
        prior_trial_count=6,
    )

    assert event["prior_trial_count"] == 6
    assert event["effective_n_trials"] == 7
    assert event["validation_values_opened"] is False


@pytest.mark.parametrize(
    "source_hashes",
    [
        {key: "a" * 64 for key in V6_SOURCE_KEYS[1:]},
        {
            **{key: "a" * 64 for key in V6_SOURCE_KEYS},
            "src/reliability/fake.py": "b" * 64,
        },
    ],
    ids=("missing", "extra"),
)
def test_v6_preregistration_requires_the_exact_frozen_source_key_set(
    source_hashes,
):
    with pytest.raises(ValueError, match="exact v6 source key set"):
        build_preregistered_event(
            _v6_protocol(),
            record_id="pre-v6",
            created_at="2026-07-28T00:00:00Z",
            source_hashes=source_hashes,
            prior_trial_count=7,
        )


def test_v6_preregistered_event_keeps_trial_accounting_value_blind():
    event = build_preregistered_event(
        _v6_protocol(),
        record_id="pre-v6",
        created_at="2026-07-28T00:00:00Z",
        source_hashes={key: "a" * 64 for key in V6_SOURCE_KEYS},
        prior_trial_count=7,
    )

    assert event["prior_trial_count"] == 7
    assert event["effective_n_trials"] == 8
    assert event["validation_values_opened"] is False


@pytest.mark.parametrize(
    "source_hashes",
    [
        {key: "a" * 64 for key in V7_SOURCE_KEYS[1:]},
        {
            **{key: "a" * 64 for key in V7_SOURCE_KEYS},
            "src/reliability/fake.py": "b" * 64,
        },
        {
            **{
                key: "a" * 64
                for key in V7_SOURCE_KEYS
                if key != V7_SOURCE_KEYS[0]
            },
            "src/reliability/renamed_adjusted_prices.py": "a" * 64,
        },
    ],
    ids=("missing", "extra", "renamed"),
)
def test_v7_preregistration_requires_the_exact_frozen_source_key_set(
    source_hashes,
):
    with pytest.raises(ValueError, match="exact v7 source key set"):
        build_preregistered_event(
            _v7_protocol(),
            record_id="pre-v7",
            created_at="2026-07-29T00:00:00Z",
            source_hashes=source_hashes,
            prior_trial_count=6,
        )


def test_v7_preregistered_event_keeps_trial_accounting_value_blind():
    event = build_preregistered_event(
        _v7_protocol(),
        record_id="pre-v7",
        created_at="2026-07-29T00:00:00Z",
        source_hashes={key: "a" * 64 for key in V7_SOURCE_KEYS},
        prior_trial_count=6,
    )

    assert event["prior_trial_count"] == 6
    assert event["effective_n_trials"] == 7
    assert event["validation_values_opened"] is False


def test_v7_preregistered_event_includes_exact_canonical_supersession():
    event = build_preregistered_event(
        _v7_protocol(),
        record_id="pre-v7",
        created_at="2026-07-29T00:00:00Z",
        source_hashes={key: "a" * 64 for key in V7_SOURCE_KEYS},
        prior_trial_count=6,
    )

    assert event["supersedes"] == {
        "experiment_id": "nse-halal-residual-momentum-v6",
        "preregistration_sha256": (
            "21efd568affe40c7139d38bd5a4fc258de1146df817acadaefa1042cb3d5c6b8"
        ),
        "reason": (
            "v6 source seal predates canonical review authority and activation "
            "binding hardening; v7 seals the corrected fail-closed boundary"
        ),
    }


@pytest.mark.parametrize("prior_trial_count", [-1, 0, 5, 6.0, True])
def test_preregistered_event_requires_at_least_six_prior_trials(prior_trial_count):
    with pytest.raises(ValueError, match="prior_trial_count"):
        build_preregistered_event(
            _protocol(),
            record_id="pre-001",
            created_at="2026-07-13T00:00:00Z",
            source_hashes={"src/reliability/residual_momentum.py": "a" * 64},
            prior_trial_count=prior_trial_count,
        )


@pytest.mark.parametrize("n_trials_floor", [-100, -1, 0, 6])
def test_preregistered_event_rejects_trial_floor_below_seven(n_trials_floor):
    protocol = _protocol()
    protocol["statistical_policy"]["n_trials_floor"] = n_trials_floor
    with pytest.raises(ValueError, match="n_trials_floor"):
        build_preregistered_event(
            protocol,
            record_id="pre-001",
            created_at="2026-07-13T00:00:00Z",
            source_hashes={"src/reliability/residual_momentum.py": "a" * 64},
            prior_trial_count=6,
        )


def test_preregistered_event_is_json_normalized_and_detached_from_inputs():
    protocol = _protocol()
    protocol["parameters"]["score_lags"] = (252, 21)
    source_hashes = {"src/reliability/residual_momentum.py": "a" * 64}
    event = build_preregistered_event(
        protocol,
        record_id="pre-001",
        created_at="2026-07-13T00:00:00Z",
        source_hashes=source_hashes,
        prior_trial_count=8,
    )

    protocol["parameters"]["momentum_long"] = 1
    source_hashes["src/reliability/residual_momentum.py"] = "b" * 64

    assert event["protocol"]["parameters"]["momentum_long"] == 252
    assert event["protocol"]["parameters"]["score_lags"] == [252, 21]
    assert event["source_hashes"]["src/reliability/residual_momentum.py"] == "a" * 64
    assert event["prior_trial_count"] == 8
    assert event["effective_n_trials"] == 9


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        (("periods", "warmup", 0), "2013-12-01", "2013-12-02"),
        (("periods", "scored", 1), "2019-12-31", "2019-12-30"),
        (("universe",), "NIFTY 500", "NIFTY 200"),
        (("benchmark",), "NIFTY 50 TRI GROSS", "NIFTY 500 TRI"),
        (("parameters", "score_lags"), None, [252, 21]),
        (("parameters", "schedule"), None, "monthly"),
        (("parameters", "position_cap"), None, 0.10),
        (("parameters", "round_trip_cost_bps"), None, 30),
        (("parameters", "stop_atr_multiple"), None, 2.0),
        (("statistical_policy", "min_observations"), 504, 505),
        (("parameters", "regime_threshold"), None, 0.0),
        (("statistical_policy", "n_trials_floor"), 7, 8),
    ],
)
def test_every_material_protocol_field_changes_hash(path, before, after):
    protocol = _protocol()
    changed = deepcopy(protocol)

    target = changed
    for key in path[:-1]:
        target = target[key]
    key = path[-1]
    if before is None:
        assert key not in target
    else:
        assert target[key] == before
    target[key] = after

    assert sha256_json(protocol) != sha256_json(changed)
