"""Canonical, validated records for sealed strategy preregistration."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from types import MappingProxyType
from typing import Any


_REQUIRED_PROTOCOL_KEYS = {
    "experiment_id",
    "family",
    "strategy_version",
    "protocol_version",
    "periods",
    "universe",
    "benchmark",
    "parameters",
    "statistical_policy",
}

_FROZEN_IDENTITIES = {
    "nse-halal-residual-momentum-v1": {
        "experiment_id": "nse-halal-residual-momentum-v1",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v1",
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
    },
    "nse-halal-residual-momentum-v2": {
        "experiment_id": "nse-halal-residual-momentum-v2",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v2",
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
    },
    "nse-halal-residual-momentum-v3": {
        "experiment_id": "nse-halal-residual-momentum-v3",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v3",
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
    },
    "nse-halal-residual-momentum-v4": {
        "experiment_id": "nse-halal-residual-momentum-v4",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v4",
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
    },
    "nse-halal-residual-momentum-v5": {
        "experiment_id": "nse-halal-residual-momentum-v5",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v5",
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
    },
    "nse-halal-residual-momentum-v6": {
        "experiment_id": "nse-halal-residual-momentum-v6",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v6",
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
    },
    "nse-halal-residual-momentum-v7": {
        "experiment_id": "nse-halal-residual-momentum-v7",
        "family": "nse-halal-swing",
        "strategy_version": "residual-momentum-v1",
        "protocol_version": "pit-nifty500-next-open-v7",
        "universe": "NIFTY 500",
        "benchmark": "NIFTY 50 TRI GROSS",
    },
}

_FROZEN_V3_PROTOCOL = {
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

V4_SOURCE_KEYS = (
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
)

V5_SOURCE_KEYS = (
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
)

V6_SOURCE_KEYS = V5_SOURCE_KEYS
V7_SOURCE_KEYS = V6_SOURCE_KEYS

V7_SUPERSESSION = MappingProxyType({
    "experiment_id": "nse-halal-residual-momentum-v6",
    "preregistration_sha256": (
        "21efd568affe40c7139d38bd5a4fc258de1146df817acadaefa1042cb3d5c6b8"
    ),
    "reason": (
        "v6 source seal predates canonical review authority and activation "
        "binding hardening; v7 seals the corrected fail-closed boundary"
    ),
})

_FROZEN_V4_PROTOCOL = {
    **_FROZEN_V3_PROTOCOL,
    "experiment_id": "nse-halal-residual-momentum-v4",
    "protocol_version": "pit-nifty500-next-open-v4",
}

_FROZEN_V5_PROTOCOL = {
    **_FROZEN_V4_PROTOCOL,
    "experiment_id": "nse-halal-residual-momentum-v5",
    "protocol_version": "pit-nifty500-next-open-v5",
}

_FROZEN_V6_PROTOCOL = {
    **_FROZEN_V5_PROTOCOL,
    "experiment_id": "nse-halal-residual-momentum-v6",
    "protocol_version": "pit-nifty500-next-open-v6",
}

_FROZEN_V7_PROTOCOL = {
    **_FROZEN_V6_PROTOCOL,
    "experiment_id": "nse-halal-residual-momentum-v7",
    "protocol_version": "pit-nifty500-next-open-v7",
}

_FROZEN_PERIODS = {
    "warmup": ["2013-12-01", "2014-12-31"],
    "scored": ["2015-01-01", "2019-12-31"],
    "burned": [["2020-01-01", "2024-06-30"]],
}

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_UTC_Z_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)
_LOWERCASE_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _validate_mapping_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical JSON mapping keys must be strings")
            _validate_mapping_keys(nested_value)
    elif isinstance(value, (list, tuple)):
        for nested_value in value:
            _validate_mapping_keys(nested_value)


def canonical_json_bytes(value: object) -> bytes:
    """Serialize a JSON value deterministically as UTF-8 with a final newline."""
    _validate_mapping_keys(value)
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (encoded + "\n").encode("utf-8")


def sha256_json(value: object) -> str:
    """Return the lowercase SHA-256 digest of canonical JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _parse_utc_z_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not _UTC_Z_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be a valid UTC Z timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid UTC Z timestamp") from exc


def _parse_period(value: object, *, field: str) -> tuple[date, date]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{field} must be an inclusive [start, end] period")

    parsed = []
    for item in value:
        if not isinstance(item, str) or not _DATE_PATTERN.fullmatch(item):
            raise ValueError(f"{field} must contain YYYY-MM-DD dates")
        try:
            parsed.append(date.fromisoformat(item))
        except ValueError as exc:
            raise ValueError(f"{field} must contain valid dates") from exc

    start, end = parsed
    if start > end:
        raise ValueError(f"{field} start must be on or before its inclusive end")
    return start, end


def _periods_overlap(left: tuple[date, date], right: tuple[date, date]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def validate_protocol(protocol: dict, *, now: str) -> None:
    """Validate the frozen residual-momentum protocol without opening data."""
    if not isinstance(protocol, dict):
        raise ValueError("protocol must be a dictionary")

    missing = sorted(_REQUIRED_PROTOCOL_KEYS - protocol.keys())
    if missing:
        raise ValueError(f"protocol missing required key: {missing[0]}")

    identities = _FROZEN_IDENTITIES.get(protocol.get("experiment_id"))
    if identities is None:
        raise ValueError(
            "protocol experiment_id must equal a frozen experiment version"
        )
    for field, expected in identities.items():
        if protocol[field] != expected:
            raise ValueError(f"protocol {field} must equal {expected!r}")

    frozen_protocols = {
        "nse-halal-residual-momentum-v3": _FROZEN_V3_PROTOCOL,
        "nse-halal-residual-momentum-v4": _FROZEN_V4_PROTOCOL,
        "nse-halal-residual-momentum-v5": _FROZEN_V5_PROTOCOL,
        "nse-halal-residual-momentum-v6": _FROZEN_V6_PROTOCOL,
        "nse-halal-residual-momentum-v7": _FROZEN_V7_PROTOCOL,
    }
    frozen_protocol = frozen_protocols.get(protocol["experiment_id"])
    if frozen_protocol is not None and canonical_json_bytes(protocol) != canonical_json_bytes(
        frozen_protocol
    ):
        raise ValueError("protocol must equal the frozen experiment semantics")

    if not isinstance(protocol["parameters"], dict):
        raise ValueError("protocol parameters must be a dictionary")
    if (
        protocol["experiment_id"] == "nse-halal-residual-momentum-v2"
        and protocol["parameters"].get("halal_max_age_days") != 365
    ):
        raise ValueError(
            "protocol halal_max_age_days must equal 365 for v2"
        )
    if not isinstance(protocol["statistical_policy"], dict):
        raise ValueError("protocol statistical_policy must be a dictionary")
    trial_floor = protocol["statistical_policy"].get("n_trials_floor")
    if (
        isinstance(trial_floor, bool)
        or not isinstance(trial_floor, int)
        or trial_floor < 7
    ):
        raise ValueError(
            "protocol statistical_policy n_trials_floor must be an integer "
            "greater than or equal to 7"
        )

    preregistered_at = _parse_utc_z_timestamp(now, field="now")
    periods = protocol["periods"]
    if not isinstance(periods, dict):
        raise ValueError("protocol periods must be a dictionary")
    for field in ("warmup", "scored", "burned"):
        if field not in periods:
            raise ValueError(f"protocol periods missing required key: {field}")

    warmup = _parse_period(periods["warmup"], field="warmup")
    scored = _parse_period(periods["scored"], field="scored")
    if warmup[1] >= scored[0]:
        raise ValueError("warmup period must end before the scored period starts")

    burned_values = periods["burned"]
    if not isinstance(burned_values, list) or not burned_values:
        raise ValueError("burned must contain at least one period")

    burned_periods = [
        _parse_period(value, field=f"burned[{index}]")
        for index, value in enumerate(burned_values)
    ]
    for burned in burned_periods:
        if _periods_overlap(warmup, burned) or _periods_overlap(scored, burned):
            raise ValueError("warmup and scored periods must not overlap a burned period")

    for index, burned in enumerate(burned_periods):
        for other in burned_periods[index + 1 :]:
            if _periods_overlap(burned, other):
                raise ValueError("burned periods must not overlap each other")

    if scored[1] >= preregistered_at.date():
        raise ValueError("scored period must end before preregistration time")

    for field, expected in _FROZEN_PERIODS.items():
        if periods[field] != expected:
            raise ValueError(f"protocol {field} period must equal {expected!r}")

    canonical_json_bytes(protocol)


def _json_normalized(value: Any) -> Any:
    return json.loads(canonical_json_bytes(value))


def build_preregistered_event(
    protocol: dict,
    *,
    record_id: str,
    created_at: str,
    source_hashes: dict[str, str],
    prior_trial_count: int,
) -> dict:
    """Build a detached, hash-bound PREREGISTERED event."""
    validate_protocol(protocol, now=created_at)

    if not isinstance(record_id, str) or not record_id:
        raise ValueError("record_id must be a non-empty string")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError("source_hashes must be a non-empty dictionary")
    if any(
        not isinstance(path, str)
        or not path
        or not isinstance(digest, str)
        or not _LOWERCASE_SHA256_PATTERN.fullmatch(digest)
        for path, digest in source_hashes.items()
    ):
        raise ValueError("source_hashes values must be lowercase SHA-256 digests")
    if (
        protocol["experiment_id"] == "nse-halal-residual-momentum-v4"
        and set(source_hashes) != set(V4_SOURCE_KEYS)
    ):
        raise ValueError("source_hashes must use the exact v4 source key set")
    if (
        protocol["experiment_id"] == "nse-halal-residual-momentum-v5"
        and set(source_hashes) != set(V5_SOURCE_KEYS)
    ):
        raise ValueError("source_hashes must use the exact v5 source key set")
    if (
        protocol["experiment_id"] == "nse-halal-residual-momentum-v6"
        and set(source_hashes) != set(V6_SOURCE_KEYS)
    ):
        raise ValueError("source_hashes must use the exact v6 source key set")
    if (
        protocol["experiment_id"] == "nse-halal-residual-momentum-v7"
        and set(source_hashes) != set(V7_SOURCE_KEYS)
    ):
        raise ValueError("source_hashes must use the exact v7 source key set")
    if (
        isinstance(prior_trial_count, bool)
        or not isinstance(prior_trial_count, int)
        or prior_trial_count < 6
    ):
        raise ValueError("prior_trial_count must be an integer greater than or equal to 6")

    trial_floor = protocol["statistical_policy"]["n_trials_floor"]

    event = {
        "record_id": record_id,
        "record_type": "PREREGISTERED",
        "created_at": created_at,
        "protocol": protocol,
        "protocol_sha256": sha256_json(protocol),
        "source_hashes": source_hashes,
        "prior_trial_count": prior_trial_count,
        "effective_n_trials": max(prior_trial_count + 1, trial_floor),
        "validation_values_opened": False,
    }
    if protocol["experiment_id"] == "nse-halal-residual-momentum-v7":
        event["supersedes"] = dict(V7_SUPERSESSION)
    return _json_normalized(event)
