"""Immutable NSE XBRL acquisition and conservative halal screening facts."""

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
from xml.etree import ElementTree

import requests


ALLOWED_HOST = "nsearchives.nseindia.com"
ALLOWED_PREFIX = "/corporate/xbrl/"


class XbrlError(RuntimeError):
    """Raised when an XBRL document is unavailable, untrusted, or invalid."""


@dataclass(frozen=True)
class XbrlResult:
    status: str
    url: str
    path: Path
    sha256: str
    byte_count: int
    available_at: str


class XbrlAcquirer:
    def __init__(
        self,
        root: str | Path,
        *,
        client=None,
        retries: int = 3,
        timeout: tuple[float, float] = (10.0, 60.0),
        max_bytes: int = 20 * 1024 * 1024,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if retries < 1:
            raise ValueError("retries must be at least 1")
        self.root = Path(root)
        self.catalogue = self.root / "source-catalogue.jsonl"
        self.client = client or requests.Session()
        if hasattr(self.client, "headers"):
            self.client.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/xml,text/xml,*/*"})
        self.retries = retries
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.sleep = sleep

    def acquire(self, url: str) -> XbrlResult:
        filename = _trusted_filename(url)
        path = self.root / "xbrl" / filename
        if path.exists():
            content = path.read_bytes()
            _validate_xml(content)
            result = self._result("cached", url, path, content, _utc_now())
            self._catalogue(result)
            return result

        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + ".part")
        last_error: Exception | None = None
        try:
            for attempt in range(1, self.retries + 1):
                try:
                    response = self.client.get(url, timeout=self.timeout)
                    if response.status_code >= 400:
                        raise XbrlError(f"HTTP {response.status_code} for {url}")
                    content = response.content
                    if len(content) > self.max_bytes:
                        raise XbrlError(f"XBRL exceeds {self.max_bytes} bytes")
                    content_type = response.headers.get("content-type", "").lower()
                    if "html" in content_type or content.lstrip().lower().startswith(b"<html"):
                        raise XbrlError("received HTML instead of XBRL")
                    _validate_xml(content)
                    with part.open("xb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(part, path)
                    result = self._result("downloaded", url, path, content, _utc_now())
                    self._catalogue(result)
                    return result
                except Exception as exc:
                    last_error = exc
                    part.unlink(missing_ok=True)
                    if attempt < self.retries:
                        self.sleep(min(2 ** (attempt - 1), 8))
            self._append({"recorded_at": _utc_now(), "status": "failed", "kind": "xbrl",
                          "url": url, "error": str(last_error)})
            raise XbrlError(f"failed to acquire {url}: {last_error}") from last_error
        finally:
            part.unlink(missing_ok=True)

    @staticmethod
    def _result(status: str, url: str, path: Path, content: bytes, available_at: str) -> XbrlResult:
        return XbrlResult(status, url, path, hashlib.sha256(content).hexdigest(), len(content), available_at)

    def _catalogue(self, result: XbrlResult) -> None:
        self._append({"recorded_at": _utc_now(), "available_at": result.available_at,
                      "status": result.status, "kind": "xbrl", "url": result.url,
                      "path": str(result.path), "sha256": result.sha256, "bytes": result.byte_count})

    def _append(self, record: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.catalogue.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def parse_halal_financial_facts(
    path: str | Path, *, symbol: str, period_end: str, available_at: str
) -> dict:
    content = Path(path).read_bytes()
    root = _validate_xml(content)
    contexts = []
    for context in root.iter():
        if _local(context.tag) != "context":
            continue
        dates = {_local(child.tag): (child.text or "").strip() for child in context.iter()}
        if dates.get("endDate") == period_end or dates.get("instant") == period_end:
            context_id = context.attrib.get("id")
            if context_id:
                dimensional = any(
                    _local(child.tag) in {"segment", "scenario", "explicitMember", "typedMember"}
                    for child in context.iter()
                )
                contexts.append((context_id, dates, dimensional))

    plain = [item for item in contexts if not item[2]] or contexts
    instant_contexts = {item[0] for item in plain if item[1].get("instant") == period_end}
    durations = [item for item in plain if item[1].get("endDate") == period_end
                 and item[1].get("startDate")]
    earliest_start = min((item[1]["startDate"] for item in durations), default=None)
    flow_contexts = {item[0] for item in durations if item[1]["startDate"] == earliest_start}
    all_matching = {item[0] for item in plain}
    balance_contexts = instant_contexts or flow_contexts or all_matching
    flow_contexts = flow_contexts or all_matching

    balance_facts: dict[str, list[float]] = {}
    flow_facts: dict[str, list[float]] = {}
    for element in root.iter():
        value = _number(element.text)
        if value is None:
            continue
        context_ref = element.attrib.get("contextRef")
        name = _local(element.tag)
        if context_ref in balance_contexts:
            balance_facts.setdefault(name, []).append(value)
        if context_ref in flow_contexts:
            flow_facts.setdefault(name, []).append(value)

    assets = _fact(balance_facts, "Assets", "TotalAssets")
    total_debt = _fact(balance_facts, "TotalDebt", "Borrowings")
    if total_debt is None:
        debt_parts = [_fact(balance_facts, "BorrowingsCurrent"),
                      _fact(balance_facts, "BorrowingsNoncurrent")]
        present = [value for value in debt_parts if value is not None]
        total_debt = sum(present) if present else None
    revenue = _fact(flow_facts, "RevenueFromOperations", "Revenue")
    interest = _fact(flow_facts, "InterestIncome", "FinanceIncome")
    candidate_names = (
        "AdjustmentsForInterestIncome",
        "InterestReceivedClassifiedAsInvestingActivities",
        "InterestReceivedClassifiedAsOperatingActivities",
        "InterestEarned",
    )
    interest_candidates = {
        name: flow_facts[name] for name in candidate_names if flow_facts.get(name)
    }
    return {
        "symbol": symbol.upper(), "period_end": period_end, "effective_from": available_at[:10],
        "available_at": available_at,
        "debt_to_assets": total_debt / assets if total_debt is not None and assets not in (None, 0) else None,
        "interest_income_ratio": abs(interest) / revenue
        if interest is not None and revenue not in (None, 0) else None,
        "payload": {"total_debt": total_debt, "total_assets": assets,
                    "interest_income": interest, "total_revenue": revenue,
                    "interest_income_candidates": interest_candidates,
                    "source_file": Path(path).name},
    }


def _trusted_filename(url: str) -> str:
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST or not parsed.path.startswith(ALLOWED_PREFIX):
        raise XbrlError("XBRL URL is outside the NSE archive allowlist")
    if not filename.lower().endswith(".xml") or filename in ("-", ".xml"):
        raise XbrlError("XBRL URL has an invalid filename")
    return filename


def _validate_xml(content: bytes):
    if not content or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise XbrlError("empty or unsafe XML document")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise XbrlError("invalid XML document") from exc
    if _local(root.tag).lower() != "xbrl":
        raise XbrlError("XML root is not an XBRL instance")
    return root


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(",", "")
    if not text or text in ("-", "NA", "N/A"):
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _fact(facts: dict[str, list[float]], *names: str) -> float | None:
    for name in names:
        values = facts.get(name)
        if values:
            return values[0]
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
