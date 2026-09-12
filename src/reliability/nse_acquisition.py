"""Integrity-checked acquisition of raw NSE report archives."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

import requests


ARCHIVE_ROOT = "https://archives.nseindia.com"
CURRENT_ARCHIVE_ROOT = "https://nsearchives.nseindia.com"


class AcquisitionError(RuntimeError):
    """Raised when a source cannot be acquired without compromising integrity."""


@dataclass(frozen=True)
class DownloadSpec:
    kind: str
    session_date: date
    url: str
    filename: str
    archive_type: str


@dataclass(frozen=True)
class AcquisitionResult:
    status: str
    spec: DownloadSpec
    archive_path: Path | None
    extracted_paths: tuple[Path, ...]
    sha256: str | None
    byte_count: int


def legacy_bhavcopy_spec(day: date) -> DownloadSpec:
    month = day.strftime("%b").upper()
    filename = f"cm{day:%d}{month}{day:%Y}bhav.csv.zip"
    url = f"{ARCHIVE_ROOT}/content/historical/EQUITIES/{day:%Y}/{month}/{filename}"
    return DownloadSpec("bhavcopy", day, url, filename, "zip")


def udiff_bhavcopy_spec(
    day: date,
    template: str = CURRENT_ARCHIVE_ROOT + "/content/cm/{filename}",
) -> DownloadSpec:
    filename = f"BhavCopy_NSE_CM_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"
    return DownloadSpec("bhavcopy", day, template.format(date=day, filename=filename), filename, "zip")


def security_master_spec(
    day: date,
    template: str = CURRENT_ARCHIVE_ROOT + "/content/cm/{filename}",
) -> DownloadSpec:
    filename = f"NSE_CM_security_{day:%d%m%Y}.csv.gz"
    return DownloadSpec("security_master", day, template.format(date=day, filename=filename), filename, "gzip")


def existing_weekdays(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("end date must be on or after start date")
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def plan_weekdays(start: date, end: date, holidays: Iterable[date] = ()) -> list[date]:
    excluded = set(holidays)
    return [day for day in existing_weekdays(start, end) if day not in excluded]


class ArchiveDownloader:
    def __init__(
        self,
        root: str | Path,
        *,
        client=None,
        retries: int = 3,
        timeout: tuple[float, float] = (10.0, 60.0),
        max_bytes: int = 100 * 1024 * 1024,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be at least 1")
        self.root = Path(root)
        self.catalogue = self.root / "source-catalogue.jsonl"
        self.client = client or self._nse_session()
        self.retries = retries
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.sleep = sleep

    @staticmethod
    def _nse_session() -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/all-reports",
        })
        return session

    def acquire(self, spec: DownloadSpec) -> AcquisitionResult:
        directory = self.root / spec.kind / f"{spec.session_date:%Y}" / f"{spec.session_date:%m}"
        archive_path = directory / spec.filename
        if archive_path.exists():
            self._validate_archive(archive_path, spec.archive_type)
            extracted = self._extract(archive_path, spec.archive_type)
            digest, size = _digest(archive_path)
            result = AcquisitionResult("cached", spec, archive_path, extracted, digest, size)
            self._catalogue(result)
            return result

        directory.mkdir(parents=True, exist_ok=True)
        part = archive_path.with_name(archive_path.name + ".part")
        last_error: Exception | None = None
        try:
            for attempt in range(1, self.retries + 1):
                try:
                    response = self.client.get(spec.url, stream=True, timeout=self.timeout)
                    if response.status_code in (404, 410):
                        result = AcquisitionResult("missing_report", spec, None, (), None, 0)
                        self._catalogue(result)
                        return result
                    if response.status_code >= 400:
                        raise AcquisitionError(f"HTTP {response.status_code} for {spec.url}")
                    self._write_response(response, part)
                    self._validate_response(response, part)
                    self._validate_archive(part, spec.archive_type)
                    os.replace(part, archive_path)
                    extracted = self._extract(archive_path, spec.archive_type)
                    digest, size = _digest(archive_path)
                    result = AcquisitionResult("downloaded", spec, archive_path, extracted, digest, size)
                    self._catalogue(result)
                    return result
                except Exception as exc:
                    last_error = exc
                    part.unlink(missing_ok=True)
                    if attempt < self.retries:
                        self.sleep(min(2 ** (attempt - 1), 8))
            self._catalogue_failure(spec, last_error)
            raise AcquisitionError(f"failed to acquire {spec.url}: {last_error}") from last_error
        finally:
            part.unlink(missing_ok=True)

    def acquire_range(
        self,
        specs: Iterable[DownloadSpec],
        *,
        delay_seconds: float = 1.0,
    ) -> list[AcquisitionResult]:
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        results = []
        for index, spec in enumerate(specs):
            if index:
                self.sleep(delay_seconds)
            results.append(self.acquire(spec))
        return results

    def _write_response(self, response, destination: Path) -> None:
        size = 0
        with destination.open("xb") as handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > self.max_bytes:
                    raise AcquisitionError(f"download exceeds {self.max_bytes} bytes")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if size == 0:
            raise AcquisitionError("empty response")

    @staticmethod
    def _validate_response(response, path: Path) -> None:
        content_type = response.headers.get("content-type", "").lower()
        prefix = path.read_bytes()[:64].lstrip().lower()
        if "text/html" in content_type or prefix.startswith((b"<html", b"<!doctype")):
            raise AcquisitionError("received HTML instead of an NSE archive")
        if "json" in content_type or prefix.startswith((b"{", b"[")):
            raise AcquisitionError("received JSON instead of an NSE archive")

    @staticmethod
    def _validate_archive(path: Path, archive_type: str) -> None:
        try:
            if archive_type == "zip":
                with zipfile.ZipFile(path) as archive:
                    if not archive.namelist() or archive.testzip() is not None:
                        raise AcquisitionError("invalid ZIP archive")
            elif archive_type == "gzip":
                with gzip.open(path, "rb") as archive:
                    if not archive.read(1):
                        raise AcquisitionError("empty GZIP archive")
            else:
                raise AcquisitionError(f"unsupported archive type: {archive_type}")
        except (OSError, EOFError, zipfile.BadZipFile) as exc:
            raise AcquisitionError(f"invalid {archive_type.upper()} archive") from exc

    def _extract(self, archive_path: Path, archive_type: str) -> tuple[Path, ...]:
        if archive_type == "gzip":
            targets = [(archive_path.with_suffix(""), gzip.open(archive_path, "rb").read())]
        else:
            with zipfile.ZipFile(archive_path) as archive:
                targets = []
                target_names = set()
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    member_path = PurePosixPath(member.filename)
                    parts = member_path.parts
                    safe_nested = len(parts) == 2 and parts[0] == parts[1]
                    if (member_path.is_absolute() or ".." in parts
                            or (len(parts) > 1 and not safe_nested)):
                        raise AcquisitionError("archive contains nested or unsafe paths")
                    target_name = member_path.name
                    if target_name in target_names:
                        raise AcquisitionError("archive contains ambiguous output filenames")
                    target_names.add(target_name)
                    targets.append((archive_path.parent / target_name, archive.read(member)))
        outputs = []
        for target, content in targets:
            if target.exists():
                if target.read_bytes() != content:
                    raise AcquisitionError(f"refusing to overwrite changed extracted file: {target}")
            else:
                part = target.with_name(target.name + ".part")
                part.write_bytes(content)
                os.replace(part, target)
            outputs.append(target)
        return tuple(outputs)

    def _catalogue(self, result: AcquisitionResult) -> None:
        record = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "status": result.status,
            "kind": result.spec.kind,
            "session_date": result.spec.session_date.isoformat(),
            "url": result.spec.url,
            "archive_path": str(result.archive_path) if result.archive_path else None,
            "extracted_paths": [str(path) for path in result.extracted_paths],
            "sha256": result.sha256,
            "bytes": result.byte_count,
        }
        self._append_record(record)

    def _catalogue_failure(self, spec: DownloadSpec, error: Exception | None) -> None:
        self._append_record({
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "kind": spec.kind,
            "session_date": spec.session_date.isoformat(),
            "url": spec.url,
            "error": str(error),
        })

    def _append_record(self, record: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.catalogue.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
