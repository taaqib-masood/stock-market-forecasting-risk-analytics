"""Retain and normalize the official NIFTY 50 total-return index response."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests


NIFTY_TRI_URL = "https://www.niftyindices.com/BackPage/getTotalReturnIndexString"
_INDEX_NAME = "NIFTY 50"
_MAX_WINDOW_DAYS = 365
_ROW_FIELDS = {"Date", "TotalReturnsIndex", "Index Name", "RequestNumber", "NTR_Value"}
_REQUIRED_ROW_FIELDS = {"Date", "Index Name", "TotalReturnsIndex"}
_DATE_RE = re.compile(
    r"(?:0[1-9]|[12][0-9]|3[01]) (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) [0-9]{4}\Z"
)
_NUMBER_RE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_GROUPED_NUMBER_RE = re.compile(
    r"(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]+)?\Z"
)
_CANONICAL_FIELDS = {
    "content_type", "kind", "normalized_rows", "normalized_sha256", "raw_bytes",
    "raw_response_path", "raw_sha256", "request", "response", "retrieved_at",
    "status_code", "url", "window",
}
_MERGED_FIELDS = {
    "components",
    "index_name",
    "kind",
    "normalized_rows",
    "normalized_sha256",
    "schema_version",
    "window",
}
_COMPONENT_FIELDS = {
    "artifact_sha256",
    "normalized_sha256",
    "path",
    "raw_response_path",
    "raw_sha256",
    "retrieved_at",
    "window",
}


class NiftyTriError(RuntimeError):
    """Raised when the retained TRI source cannot be trusted."""


@dataclass(frozen=True)
class TriWindow:
    start: date
    end: date

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or not isinstance(self.end, date):
            raise TypeError("TRI window bounds must be dates")
        if self.end < self.start:
            raise ValueError("TRI window end must be on or after start")
        if (self.end - self.start).days > _MAX_WINDOW_DAYS:
            raise ValueError("TRI windows may span at most one year")


def build_tri_windows(start: date, end: date) -> list[TriWindow]:
    if end < start:
        raise ValueError("TRI end date must be on or after start date")
    windows = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=_MAX_WINDOW_DAYS), end)
        windows.append(TriWindow(current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def normalize_tri_rows(payload: object) -> list[dict[str, Any]]:
    rows = _unwrap_payload(payload)
    if not rows:
        raise NiftyTriError("TRI response contains no rows")

    normalized = []
    seen_dates: set[str] = set()
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise NiftyTriError(f"TRI row {position} is not an object")
        if set(row) - _ROW_FIELDS or not _REQUIRED_ROW_FIELDS <= set(row):
            raise NiftyTriError(f"TRI row {position} has schema drift")

        if _identity(row["Index Name"]) != _identity(_INDEX_NAME):
            raise NiftyTriError(f"TRI row {position} has mismatched index identity")
        if "RequestNumber" in row and (
            not isinstance(row["RequestNumber"], str)
            or not row["RequestNumber"].strip()
        ):
            raise NiftyTriError(f"TRI row {position} has an invalid request number")
        try:
            if not isinstance(row["Date"], str) or not _DATE_RE.fullmatch(row["Date"]):
                raise ValueError("noncanonical date")
            session_date = datetime.strptime(row["Date"], "%d %b %Y").date().isoformat()
        except (AttributeError, TypeError, ValueError) as exc:
            raise NiftyTriError(f"TRI row {position} has an invalid date") from exc
        if session_date in seen_dates:
            raise NiftyTriError(f"TRI response contains duplicate date {session_date}")
        seen_dates.add(session_date)

        try:
            value = _strict_positive_finite_float(row["TotalReturnsIndex"])
            if "NTR_Value" in row:
                _strict_positive_finite_float(row["NTR_Value"])
        except (TypeError, ValueError) as exc:
            raise NiftyTriError(f"TRI row {position} has an invalid TRI value") from exc
        normalized.append({"session_date": session_date, "tri": value})

    normalized.sort(key=lambda row: row["session_date"])
    return normalized


def validate_tri_session_coverage(
    rows: list[dict[str, Any]], required_sessions: Iterable[date | str]
) -> None:
    """Require every calendar session in ``required_sessions`` to be present."""
    observed = set()
    for row in rows:
        session_date = _validated_normalized_row(row)["session_date"]
        if session_date in observed:
            raise NiftyTriError(f"duplicate normalized session: {session_date}")
        observed.add(session_date)
    required = {_required_session_date(session) for session in required_sessions}
    missing = sorted(required - observed)
    if missing:
        raise NiftyTriError("missing required sessions: " + ", ".join(missing))


def merge_tri_windows(windows: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for window_number, rows in enumerate(windows):
        seen_in_window: set[str] = set()
        for row in rows:
            canonical_row = _validated_normalized_row(row)
            session_date = canonical_row["session_date"]
            if session_date in seen_in_window:
                raise NiftyTriError(
                    f"window {window_number} contains duplicate date {session_date}"
                )
            seen_in_window.add(session_date)
            previous = merged.get(session_date)
            if previous is not None:
                if previous["tri"] != canonical_row["tri"]:
                    raise NiftyTriError(f"changed TRI overlap at {session_date}")
                continue
            merged[session_date] = canonical_row
    return [merged[key] for key in sorted(merged)]


class NiftyTriAcquirer:
    def __init__(
        self,
        root: str | Path,
        *,
        client=None,
        retries: int = 3,
        timeout: tuple[float, float] = (10.0, 60.0),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be at least 1")
        self.root = Path(root)
        self.catalogue = self.root / "source-catalogue.jsonl"
        self.client = client or self._session()
        self.retries = retries
        self.timeout = timeout
        self.sleep = sleep

    @staticmethod
    def _session() -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        })
        return session

    def acquire(self, window: TriWindow) -> dict[str, Any]:
        path = self._path(window)
        raw_path = self._raw_path(window)
        if path.exists():
            artifact = self._load_cache(path, window)
            result = {**artifact, "status": "cached", "path": path, "raw_path": raw_path}
            self._catalogue(result)
            return result

        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        raw_part = raw_path.with_name(raw_path.name + ".part")
        request = _request_body(window)
        last_error: Exception | None = None
        try:
            for attempt in range(1, self.retries + 1):
                raw_replaced = False
                canonical_replaced = False
                retained = False
                try:
                    response = self.client.post(
                        NIFTY_TRI_URL,
                        json=request,
                        headers={"Content-Type": "application/json; charset=utf-8"},
                        timeout=self.timeout,
                    )
                    payload, raw_response, status_code, content_type = self._response_payload(response)
                    normalized = normalize_tri_rows(payload)
                    _validate_window_rows(normalized, window)
                    artifact = self._artifact(
                        window, request, payload, normalized, raw_path=raw_path,
                        raw_response=raw_response, status_code=status_code,
                        content_type=content_type,
                    )
                    encoded = _file_bytes(artifact)
                    _write_part(raw_part, raw_response)
                    with part.open("xb") as handle:
                        handle.write(encoded)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(raw_part, raw_path)
                    raw_replaced = True
                    _fsync_directory(raw_path.parent)
                    os.replace(part, path)
                    canonical_replaced = True
                    _fsync_directory(path.parent)
                    retained = True
                    result = {**artifact, "status": "downloaded", "path": path, "raw_path": raw_path}
                    try:
                        self._catalogue(result)
                    except Exception as exc:
                        raise NiftyTriError("TRI retained but catalogue append failed") from exc
                    return result
                except Exception as exc:
                    if retained:
                        raise
                    last_error = exc
                    part.unlink(missing_ok=True)
                    raw_part.unlink(missing_ok=True)
                    if canonical_replaced:
                        path.unlink(missing_ok=True)
                    if raw_replaced:
                        raw_path.unlink(missing_ok=True)
                    if attempt < self.retries:
                        self.sleep(min(2 ** (attempt - 1), 8))
            self._catalogue_failure(window, request, last_error)
            raise NiftyTriError(f"failed to acquire {NIFTY_TRI_URL}: {last_error}") from last_error
        finally:
            part.unlink(missing_ok=True)
            raw_part.unlink(missing_ok=True)

    @staticmethod
    def _response_payload(response) -> tuple[object, bytes, int, str]:
        status_code = response.status_code
        content_type = _content_type(response)
        _validate_response_metadata(status_code, content_type)
        raw_response = getattr(response, "content", None)
        if not isinstance(raw_response, (bytes, bytearray)):
            raise NiftyTriError("TRI response does not expose raw body bytes")
        raw_response = bytes(raw_response)
        payload = _parse_raw_response(raw_response)
        return payload, raw_response, status_code, content_type

    def _load_cache(self, path: Path, window: TriWindow) -> dict[str, Any]:
        try:
            encoded = path.read_bytes()
            artifact = json.loads(encoded)
        except (OSError, ValueError) as exc:
            raise NiftyTriError(f"invalid TRI cache: {path}") from exc
        if not isinstance(artifact, dict) or set(artifact) != _CANONICAL_FIELDS:
            raise NiftyTriError(f"TRI cache schema is invalid: {path}")
        if encoded != _file_bytes(artifact):
            raise NiftyTriError(f"TRI cache is not canonical: {path}")
        try:
            raw_path = self._raw_path(window)
            if artifact["raw_response_path"] != str(raw_path):
                raise NiftyTriError("TRI cache raw response path does not match its window")
            raw_response = raw_path.read_bytes()
            if artifact["raw_bytes"] != len(raw_response):
                raise NiftyTriError("TRI cache raw response size does not match")
            if artifact["raw_sha256"] != hashlib.sha256(raw_response).hexdigest():
                raise NiftyTriError("TRI cache raw response hash does not match")
            _validate_response_metadata(artifact["status_code"], artifact["content_type"])
            if artifact["request"] != _request_body(window):
                raise NiftyTriError("TRI cache request does not match its window")
            raw_payload = _parse_raw_response(raw_response)
            if _canonical_json_bytes(raw_payload) != _canonical_json_bytes(artifact["response"]):
                raise NiftyTriError("TRI raw response envelope mismatch")
            normalized = normalize_tri_rows(raw_payload)
            _validate_window_rows(normalized, window)
            expected = self._artifact(
                window, artifact["request"], raw_payload,
                normalized, raw_path=raw_path, raw_response=raw_response,
                status_code=artifact["status_code"], content_type=artifact["content_type"],
                retrieved_at=artifact["retrieved_at"],
            )
        except OSError as exc:
            raise NiftyTriError(f"TRI cache integrity check failed: {path}") from exc
        except NiftyTriError as exc:
            raise NiftyTriError(
                f"TRI cache integrity check failed: {path}: {exc}"
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise NiftyTriError(f"TRI cache integrity check failed: {path}") from exc
        if artifact != expected:
            raise NiftyTriError(f"TRI cache integrity check failed: {path}")
        return artifact

    def merged_path(self, start: date, end: date) -> Path:
        build_tri_windows(start, end)
        return self.root / "retained" / "nifty_tri" / (
            f"nifty-50-tri-merged-{start:%Y%m%d}-{end:%Y%m%d}.json"
        )

    def merge_retained(self, start: date, end: date) -> Path:
        """Retain one canonical benchmark manifest over every requested window."""
        windows = build_tri_windows(start, end)
        artifacts = []
        components = []
        for window in windows:
            path = self._path(window)
            artifact = self._load_cache(path, window)
            if not self._catalogued_window(artifact, path):
                raise NiftyTriError(
                    f"TRI component catalogue evidence is missing: {path}"
                )
            artifacts.append(artifact["normalized_rows"])
            components.append({
                "artifact_sha256": _file_sha256(path),
                "normalized_sha256": artifact["normalized_sha256"],
                "path": str(path.resolve()),
                "raw_response_path": str(
                    Path(artifact["raw_response_path"]).resolve()
                ),
                "raw_sha256": artifact["raw_sha256"],
                "retrieved_at": artifact["retrieved_at"],
                "window": artifact["window"],
            })

        normalized = merge_tri_windows(artifacts)
        payload = {
            "components": components,
            "index_name": _INDEX_NAME,
            "kind": "nifty_50_tri_merged",
            "normalized_rows": normalized,
            "normalized_sha256": _sha256_json(normalized),
            "schema_version": 1,
            "window": {
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        }
        encoded = _canonical_json_bytes(payload)
        path = self.merged_path(start, end)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != encoded:
                raise NiftyTriError(
                    f"immutable merged TRI manifest differs: {path}"
                )
        else:
            part = path.with_name(path.name + ".part")
            try:
                _write_part(part, encoded)
                os.replace(part, path)
                _fsync_directory(path.parent)
            finally:
                part.unlink(missing_ok=True)
        self._catalogue_merged(path, payload)
        return path

    def load_merged(
        self,
        path: str | Path,
        *,
        start: date,
        end: date,
    ) -> dict[str, Any]:
        """Verify a merged manifest and every retained component byte."""
        path = Path(path)
        expected_path = self.merged_path(start, end)
        if path.resolve() != expected_path.resolve():
            raise NiftyTriError("merged TRI manifest path is not canonical")
        try:
            encoded = path.read_bytes()
            payload = json.loads(encoded)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise NiftyTriError("invalid merged TRI manifest") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != _MERGED_FIELDS
            or encoded != _canonical_json_bytes(payload)
            or payload.get("schema_version") != 1
            or payload.get("kind") != "nifty_50_tri_merged"
            or payload.get("index_name") != _INDEX_NAME
            or payload.get("window") != {
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        ):
            raise NiftyTriError("merged TRI manifest schema is invalid")

        components = payload.get("components")
        windows = build_tri_windows(start, end)
        if not isinstance(components, list) or len(components) != len(windows):
            raise NiftyTriError("merged TRI component set is incomplete")
        component_rows = []
        for component, window in zip(components, windows):
            if not isinstance(component, dict) or set(component) != _COMPONENT_FIELDS:
                raise NiftyTriError("merged TRI component schema is invalid")
            component_path = self._path(window)
            if (
                component.get("window") != {
                    "start": window.start.isoformat(),
                    "end": window.end.isoformat(),
                }
                or component.get("path") != str(component_path.resolve())
            ):
                raise NiftyTriError("merged TRI component window is invalid")
            try:
                artifact = self._load_cache(component_path, window)
            except NiftyTriError as exc:
                raise NiftyTriError(
                    f"merged TRI component verification failed: {component_path}"
                ) from exc
            expected_component = {
                "artifact_sha256": _file_sha256(component_path),
                "normalized_sha256": artifact["normalized_sha256"],
                "path": str(component_path.resolve()),
                "raw_response_path": str(
                    Path(artifact["raw_response_path"]).resolve()
                ),
                "raw_sha256": artifact["raw_sha256"],
                "retrieved_at": artifact["retrieved_at"],
                "window": artifact["window"],
            }
            if component != expected_component or not self._catalogued_window(
                artifact, component_path
            ):
                raise NiftyTriError(
                    f"merged TRI component provenance differs: {component_path}"
                )
            component_rows.append(artifact["normalized_rows"])

        normalized = merge_tri_windows(component_rows)
        if (
            payload.get("normalized_rows") != normalized
            or payload.get("normalized_sha256") != _sha256_json(normalized)
        ):
            raise NiftyTriError("merged TRI provenance is invalid")
        if not self._catalogued_merged(path, payload):
            raise NiftyTriError(
                "merged TRI catalogue evidence is missing"
            )
        return payload

    def _path(self, window: TriWindow) -> Path:
        return self.root / "nifty_tri" / f"{window.start:%Y}" / f"{window.start:%m}" / (
            f"nifty-50-tri-{window.start:%Y%m%d}-{window.end:%Y%m%d}.json"
        )

    def _raw_path(self, window: TriWindow) -> Path:
        return self._path(window).with_suffix(".raw")

    @staticmethod
    def _artifact(
        window: TriWindow,
        request: dict[str, str],
        response: object,
        normalized: list[dict[str, Any]],
        *,
        raw_path: Path,
        raw_response: bytes,
        status_code: int,
        content_type: str,
        retrieved_at: str | None = None,
    ) -> dict[str, Any]:
        if retrieved_at is None:
            retrieved_at = _utc_now()
        return {
            "content_type": content_type,
            "kind": "nifty_50_tri",
            "normalized_rows": normalized,
            "normalized_sha256": _sha256_json(normalized),
            "raw_bytes": len(raw_response),
            "raw_response_path": str(raw_path),
            "raw_sha256": hashlib.sha256(raw_response).hexdigest(),
            "request": request,
            "response": response,
            "retrieved_at": retrieved_at,
            "status_code": status_code,
            "url": NIFTY_TRI_URL,
            "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        }

    def _catalogue(self, result: dict[str, Any]) -> None:
        self._append({
            "recorded_at": _utc_now(),
            "available_at": result["retrieved_at"],
            "status": result["status"],
            "kind": result["kind"],
            "window": result["window"],
            "url": result["url"],
            "request": result["request"],
            "path": str(result["path"]),
            "raw_sha256": result["raw_sha256"],
            "normalized_sha256": result["normalized_sha256"],
            "raw_bytes": result["raw_bytes"],
            "raw_response_path": str(result["raw_path"]),
            "status_code": result["status_code"],
            "content_type": result["content_type"],
        })

    def _catalogue_merged(
        self,
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        available_at = max(
            component["retrieved_at"]
            for component in payload["components"]
        )
        record = {
            "available_at": available_at,
            "component_sha256s": [
                component["artifact_sha256"]
                for component in payload["components"]
            ],
            "coverage": {
                "end": payload["window"]["end"],
                "expected_sessions": len(payload["normalized_rows"]),
                "observed_sessions": len(payload["normalized_rows"]),
                "start": payload["window"]["start"],
            },
            "domain": "tri",
            "kind": payload["kind"],
            "path": str(path.resolve()),
            "recorded_at": _utc_now(),
            "sha256": _file_sha256(path),
            "source_id": "NIFTY INDICES",
            "status": "retained",
            "window": payload["window"],
        }
        if not self._catalogued_merged(path, payload):
            self._append(record)

    def _catalogue_records(self) -> list[dict[str, Any]]:
        try:
            return [
                json.loads(line)
                for line in self.catalogue.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line
            ]
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise NiftyTriError("TRI acquisition catalogue is invalid") from exc

    def _catalogued_window(
        self,
        artifact: dict[str, Any],
        path: Path,
    ) -> bool:
        expected = {
            "available_at": artifact["retrieved_at"],
            "content_type": artifact["content_type"],
            "kind": artifact["kind"],
            "normalized_sha256": artifact["normalized_sha256"],
            "path": str(path),
            "raw_bytes": artifact["raw_bytes"],
            "raw_response_path": artifact["raw_response_path"],
            "raw_sha256": artifact["raw_sha256"],
            "request": artifact["request"],
            "status_code": artifact["status_code"],
            "url": artifact["url"],
            "window": artifact["window"],
        }
        return any(
            isinstance(record, dict)
            and record.get("status") in {"downloaded", "cached"}
            and all(record.get(key) == value for key, value in expected.items())
            for record in self._catalogue_records()
        )

    def _catalogued_merged(
        self,
        path: Path,
        payload: dict[str, Any],
    ) -> bool:
        expected = {
            "component_sha256s": [
                component["artifact_sha256"]
                for component in payload["components"]
            ],
            "coverage": {
                "end": payload["window"]["end"],
                "expected_sessions": len(payload["normalized_rows"]),
                "observed_sessions": len(payload["normalized_rows"]),
                "start": payload["window"]["start"],
            },
            "domain": "tri",
            "kind": payload["kind"],
            "path": str(path.resolve()),
            "sha256": _file_sha256(path),
            "source_id": "NIFTY INDICES",
            "status": "retained",
            "window": payload["window"],
        }
        return any(
            isinstance(record, dict)
            and all(record.get(key) == value for key, value in expected.items())
            for record in self._catalogue_records()
        )

    def _catalogue_failure(
        self, window: TriWindow, request: dict[str, str], error: Exception | None
    ) -> None:
        self._append({
            "recorded_at": _utc_now(),
            "status": "failed",
            "kind": "nifty_50_tri",
            "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
            "url": NIFTY_TRI_URL,
            "request": request,
            "error": str(error),
        })

    def _append(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.catalogue.open("ab") as handle:
            handle.write(_canonical_json_bytes(record))
            handle.flush()
            os.fsync(handle.fileno())


def _request_body(window: TriWindow) -> dict[str, str]:
    start = _provider_date(window.start)
    end = _provider_date(window.end)
    return {
        "cinfo": (
            "{'name':'NIFTY 50','startDate':'" + start + "','endDate':'" + end
            + "','indexName':'NIFTY 50'}"
        )
    }


def _provider_date(value: date) -> str:
    return value.strftime("%d-%b-%Y")


def _identity(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.casefold()


def _strict_positive_finite_float(value: object) -> float:
    if not isinstance(value, str):
        raise ValueError("numeric value must be a string")
    if not (_NUMBER_RE.fullmatch(value) or _GROUPED_NUMBER_RE.fullmatch(value)):
        raise ValueError("numeric value has invalid grouping")
    result = float(value.replace(",", ""))
    if not math.isfinite(result) or result <= 0:
        raise ValueError("TRI must be positive and finite")
    return result


def _validated_normalized_row(row: object) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != {"session_date", "tri"}:
        raise NiftyTriError("normalized TRI row schema is invalid")
    try:
        parsed = date.fromisoformat(row["session_date"])
        if parsed.isoformat() != row["session_date"]:
            raise ValueError("noncanonical date")
        value = _strict_positive_finite_float(str(row["tri"]))
    except (TypeError, ValueError) as exc:
        raise NiftyTriError("normalized TRI row is invalid") from exc
    return {"session_date": row["session_date"], "tri": value}


def _unwrap_payload(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict) or set(payload) != {"d"}:
        raise NiftyTriError("TRI response has an unrecognized envelope")
    wrapped = payload["d"]
    if isinstance(wrapped, str):
        try:
            wrapped = json.loads(wrapped)
        except (TypeError, ValueError) as exc:
            raise NiftyTriError("TRI response has an invalid d envelope") from exc
    if not isinstance(wrapped, list):
        raise NiftyTriError("TRI response has an invalid d envelope")
    return wrapped


def _required_session_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise NiftyTriError(f"invalid required session: {value}") from exc
        if parsed.isoformat() != value:
            raise NiftyTriError(f"invalid required session: {value}")
        return value
    raise NiftyTriError("required sessions must be dates or ISO dates")


def _validate_window_rows(rows: list[dict[str, Any]], window: TriWindow) -> None:
    outside = [
        row["session_date"] for row in rows
        if not window.start.isoformat() <= row["session_date"] <= window.end.isoformat()
    ]
    if outside:
        raise NiftyTriError(
            "TRI rows outside requested window: " + ", ".join(sorted(outside))
        )


def _content_type(response) -> str:
    headers = getattr(response, "headers", {})
    for key, value in headers.items():
        if key.lower() == "content-type":
            return str(value)
    return ""


def _parse_raw_response(raw_response: bytes) -> object:
    if raw_response.lstrip().lower().startswith((b"<html", b"<!doctype")):
        raise NiftyTriError("received HTML instead of TRI JSON")
    try:
        return json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise NiftyTriError("TRI response is not valid JSON") from exc


def _validate_response_metadata(status_code: object, content_type: object) -> None:
    if not isinstance(status_code, int) or not 200 <= status_code < 300:
        raise NiftyTriError(f"TRI API HTTP {status_code}")
    if not isinstance(content_type, str):
        raise NiftyTriError("TRI response has an invalid content type")
    lowered = content_type.lower()
    if "json" not in lowered and not lowered.startswith("text/html"):
        raise NiftyTriError("TRI response has an invalid content type")


def _write_part(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
    except (TypeError, ValueError) as exc:
        raise NiftyTriError("TRI payload is not canonical JSON") from exc
    return (encoded + "\n").encode("utf-8")


def _file_bytes(value: object) -> bytes:
    encoded = json.dumps(
        value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True
    )
    return (encoded + "\n").encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
