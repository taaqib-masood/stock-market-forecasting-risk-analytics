"""Retain point-in-time snapshots from NSE corporate filing APIs."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import requests


NSE_ROOT = "https://www.nseindia.com"


class ApiSnapshotError(RuntimeError):
    """Raised when an NSE API response cannot be retained safely."""


@dataclass(frozen=True)
class ApiRequest:
    kind: str
    snapshot_date: date
    endpoint: str
    params: dict[str, str]
    filename: str
    bootstrap_url: str


@dataclass(frozen=True)
class ApiSnapshotResult:
    status: str
    request: ApiRequest
    path: Path
    sha256: str
    byte_count: int
    available_at: str


def corporate_actions_request(start: date, end: date) -> ApiRequest:
    if end < start or (end - start).days > 30:
        raise ValueError("corporate action requests must span at most 31 days")
    return ApiRequest(
        kind="corporate_actions",
        snapshot_date=end,
        endpoint=f"{NSE_ROOT}/api/corporates-corporateActions",
        params={"index": "equities", "from_date": start.strftime("%d-%m-%Y"),
                "to_date": end.strftime("%d-%m-%Y")},
        filename=f"corporate-actions-{start:%Y%m%d}-{end:%Y%m%d}.json",
        bootstrap_url=f"{NSE_ROOT}/companies-listing/corporate-filings-actions",
    )


def corporate_announcements_request(start: date, end: date) -> ApiRequest:
    if end < start or (end - start).days > 30:
        raise ValueError("corporate announcement requests must span at most 31 days")
    return ApiRequest(
        kind="corporate_announcements",
        snapshot_date=end,
        endpoint=f"{NSE_ROOT}/api/corporate-announcements",
        params={"index": "equities", "from_date": start.strftime("%d-%m-%Y"),
                "to_date": end.strftime("%d-%m-%Y")},
        filename=f"corporate-announcements-{start:%Y%m%d}-{end:%Y%m%d}.json",
        bootstrap_url=f"{NSE_ROOT}/companies-listing/corporate-filings-announcements",
    )


def financial_results_request(snapshot_date: date, period: str = "Quarterly") -> ApiRequest:
    allowed = {"Quarterly", "Annual", "Half-Yearly", "Others"}
    if period not in allowed:
        raise ValueError(f"unsupported financial result period: {period}")
    slug = period.lower().replace("-", "_")
    return ApiRequest(
        kind="financial_results",
        snapshot_date=snapshot_date,
        endpoint=f"{NSE_ROOT}/api/corporates-financial-results",
        params={"index": "equities", "period": period},
        filename=f"financial-results-{slug}-{snapshot_date:%Y%m%d}.json",
        bootstrap_url=f"{NSE_ROOT}/companies-listing/corporate-filings-financial-results",
    )


def financial_results_range_request(
    start: date, end: date, period: str = "Quarterly"
) -> ApiRequest:
    if end < start or (end - start).days > 30:
        raise ValueError("financial result requests must span at most 31 days")
    request = financial_results_request(end, period)
    slug = period.lower().replace("-", "_")
    return ApiRequest(
        kind=request.kind,
        snapshot_date=end,
        endpoint=request.endpoint,
        params={**request.params, "from_date": start.strftime("%d-%m-%Y"),
                "to_date": end.strftime("%d-%m-%Y")},
        filename=f"financial-results-{slug}-{start:%Y%m%d}-{end:%Y%m%d}.json",
        bootstrap_url=request.bootstrap_url,
    )


def annual_reports_request(symbol: str, snapshot_date: date) -> ApiRequest:
    normalized = symbol.strip().upper()
    if not normalized or not normalized.replace("-", "").isalnum():
        raise ValueError("invalid NSE symbol")
    return ApiRequest(
        kind="annual_reports",
        snapshot_date=snapshot_date,
        endpoint=f"{NSE_ROOT}/api/annual-reports",
        params={"index": "equities", "symbol": normalized},
        filename=f"annual-reports-{normalized}-{snapshot_date:%Y%m%d}.json",
        bootstrap_url=(f"{NSE_ROOT}/companies-listing/corporate-filings-annual-reports"
                       f"?symbol={normalized}&tabIndex=equity"),
    )


class ApiSnapshotAcquirer:
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
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })
        return session

    def acquire(self, request: ApiRequest) -> ApiSnapshotResult:
        directory = self.root / request.kind / f"{request.snapshot_date:%Y}" / f"{request.snapshot_date:%m}"
        path = directory / request.filename
        if path.exists():
            payload = self._load_retained(path)
            encoded = self._encode(payload)
            if path.read_bytes() != encoded:
                raise ApiSnapshotError(f"retained snapshot is not canonical: {path}")
            result = self._result("cached", request, path, encoded, _utc_now())
            self._catalogue_result(result)
            return result

        directory.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        last_error: Exception | None = None
        try:
            for attempt in range(1, self.retries + 1):
                try:
                    bootstrap = self.client.get(request.bootstrap_url, timeout=self.timeout)
                    if bootstrap.status_code >= 400:
                        raise ApiSnapshotError(f"bootstrap HTTP {bootstrap.status_code}")
                    response = self.client.get(
                        request.endpoint, params=request.params, timeout=self.timeout,
                        headers={"Referer": request.bootstrap_url},
                    )
                    payload = self._response_payload(response)
                    encoded = self._encode(payload)
                    with part.open("xb") as handle:
                        handle.write(encoded)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(part, path)
                    available_at = _utc_now()
                    result = self._result("downloaded", request, path, encoded, available_at)
                    self._catalogue_result(result)
                    return result
                except Exception as exc:
                    last_error = exc
                    part.unlink(missing_ok=True)
                    if attempt < self.retries:
                        self.sleep(min(2 ** (attempt - 1), 8))
            self._catalogue_failure(request, last_error)
            raise ApiSnapshotError(f"failed to acquire {request.endpoint}: {last_error}") from last_error
        finally:
            part.unlink(missing_ok=True)

    @staticmethod
    def _response_payload(response) -> list[dict[str, Any]] | dict[str, Any]:
        content_type = response.headers.get("content-type", "").lower()
        if response.status_code >= 400:
            raise ApiSnapshotError(f"API HTTP {response.status_code}")
        if "html" in content_type or response.text.lstrip().lower().startswith(("<html", "<!doctype")):
            raise ApiSnapshotError("received HTML instead of API JSON")
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise ApiSnapshotError("API response is not valid JSON") from exc
        if not isinstance(payload, (list, dict)):
            raise ApiSnapshotError("API response must be a JSON object or array")
        if isinstance(payload, dict) and set(payload) <= {"message", "error"}:
            raise ApiSnapshotError("API returned an error object")
        if isinstance(payload, list) and any(not isinstance(row, dict) for row in payload):
            raise ApiSnapshotError("API array must contain objects")
        return payload

    @staticmethod
    def _load_retained(path: Path) -> list[dict[str, Any]] | dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ApiSnapshotError(f"invalid retained snapshot: {path}") from exc
        if not isinstance(payload, (list, dict)):
            raise ApiSnapshotError(f"invalid retained snapshot schema: {path}")
        return payload

    @staticmethod
    def _encode(payload: object) -> bytes:
        return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")

    @staticmethod
    def _result(
        status: str, request: ApiRequest, path: Path, encoded: bytes, available_at: str
    ) -> ApiSnapshotResult:
        return ApiSnapshotResult(
            status, request, path, hashlib.sha256(encoded).hexdigest(), len(encoded), available_at
        )

    def _catalogue_result(self, result: ApiSnapshotResult) -> None:
        self._append({
            "recorded_at": _utc_now(), "available_at": result.available_at,
            "status": result.status, "kind": result.request.kind,
            "snapshot_date": result.request.snapshot_date.isoformat(),
            "url": result.request.endpoint, "params": result.request.params,
            "path": str(result.path), "sha256": result.sha256, "bytes": result.byte_count,
        })

    def _catalogue_failure(self, request: ApiRequest, error: Exception | None) -> None:
        self._append({
            "recorded_at": _utc_now(), "status": "failed", "kind": request.kind,
            "snapshot_date": request.snapshot_date.isoformat(), "url": request.endpoint,
            "params": request.params, "error": str(error),
        })

    @staticmethod
    def _request_identity(record: Mapping[str, Any]) -> tuple[object, ...]:
        return (
            record.get("kind"),
            record.get("snapshot_date"),
            record.get("url"),
            json.dumps(record.get("params"), sort_keys=True, separators=(",", ":")),
        )

    @classmethod
    def _snapshot_identity(cls, record: Mapping[str, Any]) -> tuple[object, ...]:
        return (
            *cls._request_identity(record),
            record.get("path"),
            record.get("sha256"),
            record.get("bytes"),
        )

    def _has_catalogued_snapshot(self, record: dict[str, Any]) -> bool:
        if not self.catalogue.exists():
            return False
        try:
            lines = self.catalogue.read_text(encoding="utf-8").splitlines()
            duplicate = False
            request_identity = self._request_identity(record)
            snapshot_identity = self._snapshot_identity(record)
            for line in lines:
                previous = json.loads(line)
                if not isinstance(previous, dict):
                    raise ValueError("catalogue record is not an object")
                if (
                    previous.get("status") in {"downloaded", "cached"}
                    and self._request_identity(previous) == request_identity
                ):
                    if self._snapshot_identity(previous) != snapshot_identity:
                        raise ApiSnapshotError(
                            "conflicting retained snapshots for the same request"
                        )
                    duplicate = True
            return duplicate
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ApiSnapshotError("source catalogue is malformed") from error

    def _append(self, record: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if (
            record.get("status") in {"downloaded", "cached"}
            and self._has_catalogued_snapshot(record)
        ):
            return
        with self.catalogue.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
