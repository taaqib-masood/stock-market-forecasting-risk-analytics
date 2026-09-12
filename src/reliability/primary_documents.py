"""Immutable acquisition of allowlisted primary-source filing documents."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests


class PrimaryDocumentError(RuntimeError):
    """Raised when a primary filing document is untrusted or invalid."""


@dataclass(frozen=True)
class PrimaryDocumentResult:
    status: str
    url: str
    path: Path
    sha256: str
    byte_count: int
    available_at: str


class PrimaryDocumentAcquirer:
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
        self.client = client or requests.Session()
        if hasattr(self.client, "headers"):
            self.client.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/pdf,*/*"})
        self.retries = retries
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.sleep = sleep

    def acquire(self, url: str) -> PrimaryDocumentResult:
        filename = _trusted_filename(url)
        path = self.root / "primary_documents" / "bse" / filename
        if path.exists():
            content = path.read_bytes()
            _validate_pdf(content)
            result = self._result("cached", url, path, content)
            self._catalogue(result)
            return result
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        last_error = None
        try:
            for attempt in range(1, self.retries + 1):
                try:
                    response = self.client.get(url, timeout=self.timeout)
                    if response.status_code >= 400:
                        raise PrimaryDocumentError(f"HTTP {response.status_code} for {url}")
                    content = response.content
                    if len(content) > self.max_bytes:
                        raise PrimaryDocumentError(f"document exceeds {self.max_bytes} bytes")
                    if "html" in response.headers.get("content-type", "").lower():
                        raise PrimaryDocumentError("received HTML instead of a filing document")
                    _validate_pdf(content)
                    with part.open("xb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(part, path)
                    result = self._result("downloaded", url, path, content)
                    self._catalogue(result)
                    return result
                except Exception as exc:
                    last_error = exc
                    part.unlink(missing_ok=True)
                    if attempt < self.retries:
                        self.sleep(min(2 ** (attempt - 1), 8))
            self._append({"recorded_at": _utc_now(), "status": "failed",
                          "kind": "primary_document", "url": url, "error": str(last_error)})
            raise PrimaryDocumentError(f"failed to acquire {url}: {last_error}") from last_error
        finally:
            part.unlink(missing_ok=True)

    @staticmethod
    def _result(status: str, url: str, path: Path, content: bytes) -> PrimaryDocumentResult:
        return PrimaryDocumentResult(status, url, path, hashlib.sha256(content).hexdigest(),
                                     len(content), _utc_now())

    def _catalogue(self, result: PrimaryDocumentResult) -> None:
        self._append({"recorded_at": _utc_now(), "available_at": result.available_at,
                      "status": result.status, "kind": "primary_document", "url": result.url,
                      "path": str(result.path), "sha256": result.sha256, "bytes": result.byte_count})

    def _append(self, record: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.catalogue.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _trusted_filename(url: str) -> str:
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    allowed = parsed.scheme == "https" and parsed.hostname == "www.bseindia.com" and (
        parsed.path.startswith("/xml-data/corpfiling/AttachHis/")
        or parsed.path.startswith("/xml-data/corpfiling/AttachLive/")
    )
    if not allowed or not filename.lower().endswith(".pdf"):
        raise PrimaryDocumentError("document URL is outside the BSE filing allowlist")
    return filename


def _validate_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
        raise PrimaryDocumentError("invalid PDF document")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
