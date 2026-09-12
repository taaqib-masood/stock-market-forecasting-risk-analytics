"""Append-only registry for strategy trials and immutable evidence reports."""

from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from .preregistration import (
    V4_SOURCE_KEYS,
    V5_SOURCE_KEYS,
    V6_SOURCE_KEYS,
    V7_SOURCE_KEYS,
    V7_SUPERSESSION,
    canonical_json_bytes,
    sha256_json,
    validate_protocol,
)


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_UTC_Z_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z"
)
_LIFECYCLE_TYPES = {"PREREGISTERED", "EVALUATION_STARTED", "EVALUATED"}
_LEGACY_NSE_SWING_FAMILY = "nse-swing-2020-2024"
_CURRENT_NSE_SWING_FAMILY = "nse-halal-swing"


class ExperimentRegistryError(ValueError):
    """Raised when experiment evidence is invalid or attempts to mutate history."""


class _PreregistrationTransaction:
    def __init__(
        self,
        registry: "ExperimentRegistry",
        handle,
        rows: list[dict],
    ) -> None:
        self._registry = registry
        self._handle = handle
        self._rows = rows
        self._events = registry._events_from_rows(rows)

    def events(self, experiment_id: str) -> list[dict]:
        return [
            event
            for event in self._events
            if self._registry._experiment_id(event) == experiment_id
        ]

    def relevant_trial_count(self, family: str) -> int:
        experiment_families: dict[str, str] = {}
        consumed_attempts: set[str] = set()
        for event in self._events:
            experiment_id = self._registry._experiment_id(event)
            if event["record_type"] == "PREREGISTERED":
                experiment_families[experiment_id] = event["protocol"]["family"]
            elif event["record_type"] == "LEGACY_EVALUATED":
                experiment_families[experiment_id] = event["family"]
                consumed_attempts.add(experiment_id)
            elif event["record_type"] in {"EVALUATION_STARTED", "EVALUATED"}:
                consumed_attempts.add(experiment_id)
        return sum(
            self._registry._is_relevant_family(
                experiment_families.get(experiment_id),
                family,
            )
            for experiment_id in consumed_attempts
        )

    def read_artifact(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            encoded = path.read_bytes()
            value = json.loads(encoded)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExperimentRegistryError(
                "invalid preregistration artifact"
            ) from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) != encoded:
            raise ExperimentRegistryError(
                "preregistration artifact is not canonical"
            )
        return value

    def commit_preregistration(
        self,
        event: dict,
        artifact: Path,
        encoded: bytes,
    ) -> None:
        normalized = self._registry._normalize(event)
        if encoded != canonical_json_bytes(normalized):
            raise ExperimentRegistryError(
                "preregistration artifact bytes must be canonical"
            )

        existing_by_record_id = {
            row["record_id"]: row
            for row in self._events
            if row.get("record_id") is not None
        }
        prior = existing_by_record_id.get(normalized.get("record_id"))
        if prior is not None and prior != normalized:
            raise ExperimentRegistryError("record IDs are immutable")
        if prior is None:
            self._registry._events_from_rows([*self._rows, normalized])

        artifact_before = artifact.read_bytes() if artifact.exists() else None
        if artifact_before is not None and artifact_before != encoded:
            raise ExperimentRegistryError(
                "immutable preregistration artifact already exists"
            )

        self._handle.seek(0)
        registry_before = self._handle.read()
        artifact_changed = False
        try:
            if artifact_before is None:
                self._registry._write_artifact_atomic(artifact, encoded)
                artifact_changed = True
            if prior is None:
                self._registry._append_locked(self._handle, encoded)
                self._rows.append(normalized)
                self._events.append(normalized)
        except Exception as exc:
            self._registry._restore_locked(self._handle, registry_before)
            if artifact_changed:
                self._registry._restore_artifact(artifact, artifact_before)
            raise ExperimentRegistryError(
                "preregistration transaction failed and was rolled back"
            ) from exc


class ExperimentRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def register(self, record: dict) -> None:
        """Append a legacy completed-report record without changing its wire format."""
        normalized = self._validate_legacy(record)
        with self._locked_transaction():
            rows = self._raw_rows()
            existing = {
                row["experiment_id"]: row
                for row in rows
                if "record_type" not in row and row.get("experiment_id")
            }
            prior = existing.get(normalized["experiment_id"])
            if prior is not None:
                if prior != normalized:
                    raise ExperimentRegistryError(
                        "experiment records are immutable"
                    )
                return
            if any(
                self._experiment_id(row) == normalized["experiment_id"]
                for row in self._events_from_rows(rows)
            ):
                raise ExperimentRegistryError("experiment records are immutable")
            self._append_legacy(normalized)

    def append_event(self, event: dict) -> None:
        """Validate and durably append one immutable lifecycle event."""
        normalized = self._normalize(event)
        if normalized.get("record_type") not in _LIFECYCLE_TYPES:
            raise ExperimentRegistryError("unsupported lifecycle record_type")

        with self._locked_transaction():
            rows = self._raw_rows()
            history = self._events_from_rows(rows)
            existing = {
                row["record_id"]: row
                for row in history
                if row.get("record_id") is not None
            }
            prior = existing.get(normalized.get("record_id"))
            if prior is not None:
                if prior != normalized:
                    raise ExperimentRegistryError("record IDs are immutable")
                return

            self._events_from_rows([*rows, normalized])
            self._append(normalized)

    def events(self, experiment_id: str | None = None) -> list[dict]:
        """Return validated immutable events, optionally for one experiment."""
        events = self._events_from_rows(self._raw_rows())
        if experiment_id is None:
            return events
        return [
            event for event in events if self._experiment_id(event) == experiment_id
        ]

    def state(self, experiment_id: str) -> str | None:
        """Return the latest lifecycle state or final verdict for an experiment."""
        experiment_events = self.events(experiment_id)
        if not experiment_events:
            return None
        latest = experiment_events[-1]
        if latest["record_type"] in {"EVALUATED", "LEGACY_EVALUATED"}:
            return latest["verdict"]
        return latest["record_type"]

    def trial_count(self, family: str) -> int:
        """Preserve the legacy completed-report family counter."""
        return len(
            {
                row["experiment_id"]
                for row in self._raw_rows()
                if row.get("family") == family
            }
        )

    def relevant_trial_count(self, family: str) -> int:
        """Count completed and started attempts relevant to a preregistration family."""
        experiment_families: dict[str, str] = {}
        consumed_attempts: set[str] = set()
        for event in self.events():
            experiment_id = self._experiment_id(event)
            if event["record_type"] == "PREREGISTERED":
                experiment_families[experiment_id] = event["protocol"]["family"]
            elif event["record_type"] == "LEGACY_EVALUATED":
                experiment_families[experiment_id] = event["family"]
                consumed_attempts.add(experiment_id)
            elif event["record_type"] in {"EVALUATION_STARTED", "EVALUATED"}:
                consumed_attempts.add(experiment_id)

        return sum(
            self._is_relevant_family(experiment_families.get(experiment_id), family)
            for experiment_id in consumed_attempts
        )

    @contextmanager
    def _locked_transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "r+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield handle
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def preregistration_transaction(self):
        """Hold one registry lock through artifact and event commit."""
        with self._locked_transaction() as handle:
            yield _PreregistrationTransaction(
                self,
                handle,
                self._raw_rows(),
            )

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_artifact_atomic(self, path: Path, encoded: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".part")
        if temporary.exists():
            raise ExperimentRegistryError(
                f"incomplete temporary artifact exists: {temporary}"
            )
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._fsync_directory(path.parent)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise

    def _restore_artifact(
        self,
        path: Path,
        prior: bytes | None,
    ) -> None:
        temporary = path.with_name(path.name + ".part")
        if temporary.exists():
            temporary.unlink()
        if prior is None:
            if path.exists():
                path.unlink()
                self._fsync_directory(path.parent)
            return
        if path.exists():
            path.unlink()
        self._write_artifact_atomic(path, prior)

    @staticmethod
    def _append_locked(handle, encoded: bytes) -> None:
        handle.seek(0, os.SEEK_END)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())

    @staticmethod
    def _restore_locked(handle, prior: bytes) -> None:
        handle.seek(0)
        handle.write(prior)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())

    def _append(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _append_legacy(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _raw_rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ExperimentRegistryError(
                    f"invalid registry JSON at line {number}"
                ) from exc
            if not isinstance(row, dict):
                raise ExperimentRegistryError(
                    f"invalid registry record at line {number}"
                )
            rows.append(row)
        return rows

    def _events_from_rows(self, rows: list[dict]) -> list[dict]:
        events: list[dict] = []
        record_ids: set[str] = set()
        states: dict[str, dict[str, Any]] = {}
        last_timestamp: datetime | None = None

        for position, row in enumerate(rows, 1):
            if "record_type" not in row:
                event = {
                    **self._validate_legacy(row),
                    "record_type": "LEGACY_EVALUATED",
                }
                experiment_id = event["experiment_id"]
                if experiment_id in states:
                    raise ExperimentRegistryError("experiment records are immutable")
                states[experiment_id] = {"legacy": event}
                events.append(event)
                continue

            event = self._normalize(row)
            record_type = event.get("record_type")
            if record_type not in _LIFECYCLE_TYPES:
                raise ExperimentRegistryError(
                    f"unsupported lifecycle record_type at line {position}"
                )
            record_id = self._required_string(event, "record_id")
            if record_id in record_ids:
                raise ExperimentRegistryError("record IDs are immutable")
            record_ids.add(record_id)

            timestamp = self._timestamp(event)
            if last_timestamp is not None and timestamp < last_timestamp:
                raise ExperimentRegistryError("lifecycle timestamps must be monotonic")
            last_timestamp = timestamp

            experiment_id = self._validate_lifecycle_event(event, states)
            states.setdefault(experiment_id, {})[record_type] = event
            events.append(event)

        return events

    def _validate_lifecycle_event(
        self, event: dict, states: dict[str, dict[str, Any]]
    ) -> str:
        record_type = event["record_type"]
        if record_type == "PREREGISTERED":
            return self._validate_preregistered(event, states)
        if record_type == "EVALUATION_STARTED":
            return self._validate_started(event, states)
        return self._validate_evaluated(event, states)

    def _validate_preregistered(
        self, event: dict, states: dict[str, dict[str, Any]]
    ) -> str:
        required = {
            "record_id", "record_type", "created_at", "protocol", "protocol_sha256",
            "source_hashes", "prior_trial_count", "effective_n_trials",
            "validation_values_opened",
        }
        self._require_fields(event, required)
        try:
            validate_protocol(event["protocol"], now=event["created_at"])
        except (TypeError, ValueError) as exc:
            raise ExperimentRegistryError(f"invalid preregistration: {exc}") from exc
        self._require_hash(event, "protocol_sha256")
        if event["protocol_sha256"] != sha256_json(event["protocol"]):
            raise ExperimentRegistryError(
                "preregistration protocol hash does not match protocol"
            )
        if not isinstance(event["source_hashes"], dict) or not event["source_hashes"]:
            raise ExperimentRegistryError("preregistration source_hashes are required")
        for digest in event["source_hashes"].values():
            if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
                raise ExperimentRegistryError(
                    "preregistration source_hashes must be SHA-256"
                )
        if (
            event["protocol"]["experiment_id"]
            == "nse-halal-residual-momentum-v4"
            and set(event["source_hashes"]) != set(V4_SOURCE_KEYS)
        ):
            raise ExperimentRegistryError(
                "preregistration source_hashes must use the exact v4 source key set"
            )
        if (
            event["protocol"]["experiment_id"]
            == "nse-halal-residual-momentum-v5"
            and set(event["source_hashes"]) != set(V5_SOURCE_KEYS)
        ):
            raise ExperimentRegistryError(
                "preregistration source_hashes must use the exact v5 source key set"
            )
        if (
            event["protocol"]["experiment_id"]
            == "nse-halal-residual-momentum-v6"
            and set(event["source_hashes"]) != set(V6_SOURCE_KEYS)
        ):
            raise ExperimentRegistryError(
                "preregistration source_hashes must use the exact v6 source key set"
            )
        if (
            event["protocol"]["experiment_id"]
            == "nse-halal-residual-momentum-v7"
            and set(event["source_hashes"]) != set(V7_SOURCE_KEYS)
        ):
            raise ExperimentRegistryError(
                "preregistration source_hashes must use the exact v7 source key set"
            )
        if (
            event["protocol"]["experiment_id"]
            == "nse-halal-residual-momentum-v7"
            and event.get("supersedes") != dict(V7_SUPERSESSION)
        ):
            raise ExperimentRegistryError(
                "v7 supersession must use the exact canonical record"
            )
        prior_count = event["prior_trial_count"]
        trial_floor = event["protocol"]["statistical_policy"]["n_trials_floor"]
        expected_prior_count = self._relevant_trial_count_from_states(
            states, event["protocol"]["family"]
        )
        if (
            isinstance(prior_count, bool)
            or not isinstance(prior_count, int)
            or prior_count < 6
        ):
            raise ExperimentRegistryError("preregistration prior_trial_count is invalid")
        if prior_count != expected_prior_count:
            raise ExperimentRegistryError(
                "preregistration prior_trial_count must equal "
                f"{expected_prior_count}"
            )
        if event["effective_n_trials"] != max(
            expected_prior_count + 1, trial_floor
        ):
            raise ExperimentRegistryError(
                "preregistration effective_n_trials is invalid"
            )
        if event["validation_values_opened"] is not False:
            raise ExperimentRegistryError("preregistration must be value blind")

        experiment_id = event["protocol"]["experiment_id"]
        if experiment_id in states:
            raise ExperimentRegistryError(
                "one preregistration is allowed per experiment"
            )
        return experiment_id

    def _validate_started(self, event: dict, states: dict[str, dict[str, Any]]) -> str:
        required = {
            "record_id", "record_type", "experiment_id", "created_at",
            "preregistration_sha256",
            "dataset_manifest_sha256",
            "input_manifest_sha256",
            "effective_n_trials",
        }
        self._require_fields(event, required)
        experiment_id = self._required_string(event, "experiment_id")
        state = states.get(experiment_id)
        if state is None or "PREREGISTERED" not in state:
            raise ExperimentRegistryError(
                "EVALUATION_STARTED requires PREREGISTERED evidence"
            )
        if "EVALUATION_STARTED" in state or "EVALUATED" in state:
            raise ExperimentRegistryError("only one evaluation start is allowed")
        preregistered = state["PREREGISTERED"]
        self._validate_preregistration_reference(event, preregistered)
        if event["effective_n_trials"] != preregistered[
            "effective_n_trials"
        ]:
            raise ExperimentRegistryError(
                "evaluation start must bind preregistered effective_n_trials"
            )
        self._require_hash(event, "dataset_manifest_sha256")
        self._require_hash(event, "input_manifest_sha256")
        return experiment_id

    def _validate_evaluated(
        self, event: dict, states: dict[str, dict[str, Any]]
    ) -> str:
        required = {
            "record_id", "record_type", "experiment_id", "created_at",
            "preregistration_sha256",
            "dataset_manifest_sha256",
            "input_manifest_sha256",
            "report_sha256",
            "code_sha256",
            "environment_manifest_sha256",
            "metrics",
            "failed_gates", "verdict",
        }
        self._require_fields(event, required)
        experiment_id = self._required_string(event, "experiment_id")
        state = states.get(experiment_id)
        if state is None or "EVALUATION_STARTED" not in state:
            raise ExperimentRegistryError(
                "EVALUATED requires EVALUATION_STARTED evidence"
            )
        if "EVALUATED" in state:
            raise ExperimentRegistryError("only one evaluation is allowed")
        preregistered = state["PREREGISTERED"]
        started = state["EVALUATION_STARTED"]
        self._validate_preregistration_reference(event, preregistered)
        for field in (
            "dataset_manifest_sha256", "input_manifest_sha256", "report_sha256",
            "code_sha256", "environment_manifest_sha256",
        ):
            self._require_hash(event, field)
        for field in ("dataset_manifest_sha256", "input_manifest_sha256"):
            if event[field] != started[field]:
                raise ExperimentRegistryError(
                    "evaluation must use the exact started input set"
                )
        if event["verdict"] not in {"ACCEPTED", "REJECTED", "INVALID"}:
            raise ExperimentRegistryError("evaluation verdict is invalid")
        if not isinstance(event["metrics"], dict):
            raise ExperimentRegistryError("evaluation metrics must be a dictionary")
        if not isinstance(event["failed_gates"], list) or not all(
            isinstance(gate, str) for gate in event["failed_gates"]
        ):
            raise ExperimentRegistryError(
                "evaluation failed_gates must be a list of strings"
            )
        return experiment_id

    def _relevant_trial_count_from_states(
        self, states: dict[str, dict[str, Any]], family: str
    ) -> int:
        count = 0
        for state in states.values():
            legacy = state.get("legacy")
            if legacy is not None:
                if self._is_relevant_family(legacy["family"], family):
                    count += 1
                continue

            preregistered = state.get("PREREGISTERED")
            if (
                preregistered is not None
                and ("EVALUATION_STARTED" in state or "EVALUATED" in state)
                and self._is_relevant_family(
                    preregistered["protocol"]["family"], family
                )
            ):
                count += 1
        return count

    @staticmethod
    def _validate_preregistration_reference(event: dict, preregistered: dict) -> None:
        ExperimentRegistry._require_hash(event, "preregistration_sha256")
        if event["preregistration_sha256"] != sha256_json(preregistered):
            raise ExperimentRegistryError(
                "preregistration hash does not match registered evidence"
            )

    @staticmethod
    def _validate_legacy(record: dict) -> dict:
        if not isinstance(record, dict) or "record_type" in record:
            raise ExperimentRegistryError("legacy records cannot contain record_type")
        required = {
            "experiment_id", "family", "strategy_version", "protocol_version",
            "report_sha256", "verdict",
        }
        ExperimentRegistry._require_fields(record, required)
        ExperimentRegistry._required_string(record, "experiment_id")
        ExperimentRegistry._require_hash(record, "report_sha256")
        return ExperimentRegistry._normalize(record)

    @staticmethod
    def _require_fields(event: dict, required: set[str]) -> None:
        missing = sorted(required - set(event))
        if missing:
            raise ExperimentRegistryError(
                f"missing experiment fields: {', '.join(missing)}"
            )

    @staticmethod
    def _required_string(event: dict, field: str) -> str:
        value = event.get(field)
        if not isinstance(value, str) or not value:
            raise ExperimentRegistryError(f"{field} must be a non-empty string")
        return value

    @staticmethod
    def _require_hash(event: dict, field: str) -> None:
        value = event.get(field)
        if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
            raise ExperimentRegistryError(f"{field} must be a lowercase SHA-256 digest")

    @staticmethod
    def _normalize(value: object) -> dict:
        if not isinstance(value, dict):
            raise ExperimentRegistryError("registry record must be a dictionary")
        try:
            normalized = json.loads(canonical_json_bytes(value))
        except (TypeError, ValueError) as exc:
            raise ExperimentRegistryError(
                "registry record is not canonical JSON"
            ) from exc
        return normalized

    @staticmethod
    def _timestamp(event: dict) -> datetime:
        value = event.get("created_at")
        if not isinstance(value, str) or not _UTC_Z_PATTERN.fullmatch(value):
            raise ExperimentRegistryError("created_at must be a valid UTC Z timestamp")
        try:
            return datetime.fromisoformat(value[:-1] + "+00:00")
        except ValueError as exc:
            raise ExperimentRegistryError(
                "created_at must be a valid UTC Z timestamp"
            ) from exc

    @staticmethod
    def _experiment_id(event: dict) -> str:
        if event["record_type"] == "PREREGISTERED":
            return event["protocol"]["experiment_id"]
        return event["experiment_id"]

    @staticmethod
    def _is_relevant_family(event_family: str | None, requested_family: str) -> bool:
        return event_family == requested_family or (
            requested_family == _CURRENT_NSE_SWING_FAMILY
            and event_family == _LEGACY_NSE_SWING_FAMILY
        )
