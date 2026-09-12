"""Bounded, non-authoritative retention for candidate corporate-action PDFs."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

import requests

from src.reliability.preregistration import canonical_json_bytes


SCHEMA_VERSION = "corporate-action-candidate-evidence-v1"
INDEX_SCHEMA_VERSION = "corporate-action-evidence-index-v1"
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 30.0
STREAM_CHUNK_BYTES = 64 * 1024
_PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf"}

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_INDEX_ROW_FIELDS = {
    "schema_version",
    "proposal_only",
    "review_id",
    "queue_kind",
    "review_identity",
    "action_source",
    "announcement_candidates",
    "candidate_resolution",
}
_REVIEW_IDENTITY_FIELDS = {"symbol", "action_type", "ex_date", "purpose", "reason"}
_ACTION_SOURCE_FIELDS = {"path", "sha256", "bytes", "available_at"}
_CANDIDATE_FIELDS = {
    "seq_id",
    "symbol",
    "broadcast_at",
    "description",
    "subject",
    "attachment_text",
    "attachment_url",
    "snapshot_path",
    "snapshot_sha256",
    "snapshot_bytes",
    "snapshot_available_at",
    "ambiguity_reason",
}
_PROHIBITED_AUTHORITY_FIELDS = {
    "approval",
    "approved",
    "audit_authority",
    "canonical_decision",
    "decision",
    "reviewed_corporate_action_audit",
}


class CandidateEvidenceError(ValueError):
    """Candidate evidence cannot be retained without weakening an integrity boundary."""


class CandidateEvidenceDurabilityError(CandidateEvidenceError):
    """A destination changed, but parent-directory durability is uncertain."""


class _ExistingContentLimitError(CandidateEvidenceError):
    """An existing content-addressed object exceeded its verification bound."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _reject_authority(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise CandidateEvidenceError("proposal input keys must be strings")
            if key.lower() in _PROHIBITED_AUTHORITY_FIELDS:
                raise CandidateEvidenceError("proposal input cannot carry audit authority")
            _reject_authority(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_authority(nested)


def _exact_mapping(
    value: object,
    fields: set[str],
    *,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CandidateEvidenceError(f"proposal {label} schema is invalid")
    return value


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _validate_index_rows(index_rows: object) -> list[dict[str, object]]:
    if not isinstance(index_rows, list) or any(
        not isinstance(row, dict) for row in index_rows
    ):
        raise CandidateEvidenceError("proposal index rows must be a list of objects")

    seen_review_ids: set[str] = set()
    for row in index_rows:
        _reject_authority(row)
        _exact_mapping(row, _INDEX_ROW_FIELDS, label="index row")
        if row.get("schema_version") != INDEX_SCHEMA_VERSION:
            raise CandidateEvidenceError("proposal index schema version is invalid")
        if row.get("proposal_only") is not True:
            raise CandidateEvidenceError("proposal_only must be true")
        review_id = row.get("review_id")
        if not _valid_sha256(review_id) or review_id in seen_review_ids:
            raise CandidateEvidenceError("proposal review ID is invalid or duplicated")
        seen_review_ids.add(review_id)
        if row.get("queue_kind") not in {"visibility", "factor"}:
            raise CandidateEvidenceError("proposal queue kind is invalid")

        identity = _exact_mapping(
            row.get("review_identity"),
            _REVIEW_IDENTITY_FIELDS,
            label="review identity",
        )
        if any(not isinstance(identity[field], str) for field in identity):
            raise CandidateEvidenceError("proposal review identity is invalid")

        source = _exact_mapping(
            row.get("action_source"),
            _ACTION_SOURCE_FIELDS,
            label="action source",
        )
        if (
            not isinstance(source.get("path"), str)
            or not source["path"]
            or not _valid_sha256(source.get("sha256"))
            or type(source.get("bytes")) is not int
            or source["bytes"] < 0
            or not isinstance(source.get("available_at"), str)
            or not source["available_at"]
        ):
            raise CandidateEvidenceError("proposal action source is invalid")

        candidates = row.get("announcement_candidates")
        if not isinstance(candidates, list):
            raise CandidateEvidenceError("proposal announcement candidates are invalid")
        for value in candidates:
            candidate = _exact_mapping(
                value,
                _CANDIDATE_FIELDS,
                label="announcement candidate",
            )
            string_fields = _CANDIDATE_FIELDS - {"snapshot_bytes"}
            if (
                any(not isinstance(candidate.get(field), str) for field in string_fields)
                or not _valid_sha256(candidate.get("snapshot_sha256"))
                or type(candidate.get("snapshot_bytes")) is not int
                or candidate["snapshot_bytes"] < 0
                or candidate.get("ambiguity_reason") != "CANDIDATE_NOT_CANONICAL"
            ):
                raise CandidateEvidenceError("proposal announcement candidate is invalid")
        expected_resolution = (
            "AMBIGUOUS_REVIEW_REQUIRED"
            if candidates
            else "NO_COMPATIBLE_CANDIDATE"
        )
        if row.get("candidate_resolution") != expected_resolution:
            raise CandidateEvidenceError("proposal candidate resolution is invalid")
    return index_rows


def _validate_configuration(
    *,
    output_dir: str | Path,
    allowed_hosts: set[str],
    max_bytes: int,
) -> tuple[Path, frozenset[str]]:
    if isinstance(output_dir, bool) or not isinstance(output_dir, (str, Path)):
        raise CandidateEvidenceError("output directory is invalid")
    output = Path(output_dir)
    if not isinstance(allowed_hosts, set) or any(
        not isinstance(host, str)
        or not host
        or host != host.strip().lower()
        or "/" in host
        or ":" in host
        for host in allowed_hosts
    ):
        raise CandidateEvidenceError("allowed hosts must be normalized host names")
    if type(max_bytes) is not int or max_bytes <= 0:
        raise CandidateEvidenceError("maximum attachment bytes must be positive")
    return output, frozenset(allowed_hosts)


def _failure_record(
    *,
    review_id: str,
    candidate_url: str,
    snapshot_sha256: str,
    attempted_at: str | None,
    failure_code: str,
    attachment_sha256: str | None = None,
    attachment_path: str | None = None,
    byte_count: int | None = None,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_only": True,
        "review_id": review_id,
        "candidate_url": candidate_url,
        "attachment_sha256": attachment_sha256,
        "attachment_path": attachment_path,
        "byte_count": byte_count,
        "attempted_at": attempted_at,
        "retrieved_at": None,
        "source_snapshot_sha256": snapshot_sha256,
        "status": "FAILED",
        "failure_code": failure_code,
    }


def _success_record(
    *,
    review_id: str,
    candidate_url: str,
    snapshot_sha256: str,
    attempted_at: str,
    retrieved_at: str,
    attachment_sha256: str,
    attachment_path: str,
    byte_count: int,
    status: str,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_only": True,
        "review_id": review_id,
        "candidate_url": candidate_url,
        "attachment_sha256": attachment_sha256,
        "attachment_path": attachment_path,
        "byte_count": byte_count,
        "attempted_at": attempted_at,
        "retrieved_at": retrieved_at,
        "source_snapshot_sha256": snapshot_sha256,
        "status": status,
        "failure_code": None,
    }


def _validated_url(url: str, allowed_hosts: frozenset[str]) -> str | None:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "MALFORMED_URL"
    if parsed.scheme.lower() != "https":
        return "URL_NOT_HTTPS"
    if (
        not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in (None, 443)
    ):
        return "MALFORMED_URL"
    if hostname.lower() not in allowed_hosts:
        return "HOST_NOT_ALLOWED"
    return None


def _parse_content_length(value: object) -> int | None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[0-9]{1,20}", value, flags=re.ASCII) is None
    ):
        return None
    return int(value)


def _read_existing_content(path: Path, *, max_bytes: int) -> tuple[str, int] | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise CandidateEvidenceError("content-addressed destination is unsafe") from error
    digest = hashlib.sha256()
    byte_count = 0
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CandidateEvidenceError("content-addressed destination is not regular")
        while True:
            chunk = os.read(descriptor, STREAM_CHUNK_BYTES)
            if not chunk:
                break
            byte_count += len(chunk)
            if byte_count > max_bytes:
                raise _ExistingContentLimitError(
                    "existing content-addressed object exceeds the verification limit"
                )
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest(), byte_count


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _mkdirs_at(parent_descriptor: int, parts: tuple[str, ...]) -> None:
    current = os.dup(parent_descriptor)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            descriptor = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=current,
            )
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise CandidateEvidenceError("candidate output component is unsafe")
            os.close(current)
            current = descriptor
    finally:
        os.close(current)


def _safe_unlink_at(parent_descriptor: int, relative_path: str) -> None:
    try:
        os.unlink(relative_path, dir_fd=parent_descriptor)
    except OSError:
        pass


def _fsync_at(parent_descriptor: int, relative_path: str) -> None:
    descriptor = os.open(
        relative_path,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=parent_descriptor,
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stage_path(
    output_dir: Path,
    *,
    review_id: str,
    candidate_url: str,
    snapshot_sha256: str,
) -> Path:
    identity = canonical_json_bytes(
        {
            "candidate_url": candidate_url,
            "review_id": review_id,
            "source_snapshot_sha256": snapshot_sha256,
        }
    )
    name = hashlib.sha256(identity).hexdigest()
    return output_dir / "evidence" / ".parts" / f"{name}.part"


def _existing_attachment_record(
    *,
    target: Path,
    relative_path: Path,
    expected_sha256: str,
    expected_bytes: int,
    max_bytes: int,
    review_id: str,
    candidate_url: str,
    snapshot_sha256: str,
    attempted_at: str,
) -> dict[str, object] | None:
    try:
        existing = _read_existing_content(target, max_bytes=max_bytes)
    except _ExistingContentLimitError:
        return _failure_record(
            review_id=review_id,
            candidate_url=candidate_url,
            snapshot_sha256=snapshot_sha256,
            attempted_at=attempted_at,
            failure_code="EXISTING_CONTENT_EXCEEDS_LIMIT",
            attachment_sha256=expected_sha256,
            attachment_path=relative_path.as_posix(),
            byte_count=expected_bytes,
        )
    except CandidateEvidenceError:
        return _failure_record(
            review_id=review_id,
            candidate_url=candidate_url,
            snapshot_sha256=snapshot_sha256,
            attempted_at=attempted_at,
            failure_code="CONTENT_ADDRESS_CONFLICT",
            attachment_sha256=expected_sha256,
            attachment_path=relative_path.as_posix(),
            byte_count=expected_bytes,
        )
    if existing is None:
        return None
    if existing != (expected_sha256, expected_bytes):
        return _failure_record(
            review_id=review_id,
            candidate_url=candidate_url,
            snapshot_sha256=snapshot_sha256,
            attempted_at=attempted_at,
            failure_code="CONTENT_ADDRESS_CONFLICT",
            attachment_sha256=expected_sha256,
            attachment_path=relative_path.as_posix(),
            byte_count=expected_bytes,
        )
    return _success_record(
        review_id=review_id,
        candidate_url=candidate_url,
        snapshot_sha256=snapshot_sha256,
        attempted_at=attempted_at,
        retrieved_at=_utc_now(),
        attachment_sha256=expected_sha256,
        attachment_path=relative_path.as_posix(),
        byte_count=expected_bytes,
        status="REUSED",
    )


def _retain_one(
    *,
    review_id: str,
    candidate: Mapping[str, object],
    output_dir: Path,
    allowed_hosts: frozenset[str],
    session: requests.Session,
    max_bytes: int,
    root_descriptor: int | None = None,
) -> dict[str, object]:
    candidate_url = str(candidate["attachment_url"])
    snapshot_sha256 = str(candidate["snapshot_sha256"])
    url_failure = _validated_url(candidate_url, allowed_hosts)
    if url_failure is not None:
        return _failure_record(
            review_id=review_id,
            candidate_url=candidate_url,
            snapshot_sha256=snapshot_sha256,
            attempted_at=None,
            failure_code=url_failure,
        )

    attempted_at = _utc_now()
    try:
        response = session.get(
            candidate_url,
            stream=True,
            allow_redirects=False,
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )
    except requests.RequestException:
        return _failure_record(
            review_id=review_id,
            candidate_url=candidate_url,
            snapshot_sha256=snapshot_sha256,
            attempted_at=attempted_at,
            failure_code="REQUEST_FAILED",
        )

    try:
        if 300 <= response.status_code < 400:
            failure_code = "REDIRECT_REJECTED"
        elif response.status_code != 200:
            failure_code = "HTTP_STATUS_REJECTED"
        else:
            failure_code = None
        if failure_code is not None:
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code=failure_code,
            )

        declared_bytes = _parse_content_length(response.headers.get("Content-Length"))
        if declared_bytes is None:
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="INVALID_CONTENT_LENGTH",
            )
        if declared_bytes > max_bytes:
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="CONTENT_LENGTH_EXCEEDS_LIMIT",
            )
        content_type = response.headers.get("Content-Type")
        media_type = (
            content_type.split(";", 1)[0].strip().lower()
            if isinstance(content_type, str)
            else ""
        )
        if media_type not in _PDF_CONTENT_TYPES:
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="INVALID_CONTENT_TYPE",
            )
        content_encoding = response.headers.get("Content-Encoding", "identity").lower()
        if content_encoding not in {"", "identity"}:
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="CONTENT_ENCODING_REJECTED",
            )

        part = _stage_path(
            output_dir,
            review_id=review_id,
            candidate_url=candidate_url,
            snapshot_sha256=snapshot_sha256,
        )
        if root_descriptor is None:
            part.parent.mkdir(parents=True, exist_ok=True)
        else:
            _mkdirs_at(root_descriptor, ("evidence", "evidence", ".parts"))
        digest = hashlib.sha256()
        byte_count = 0
        prefix = bytearray()
        try:
            if root_descriptor is None:
                handle = part.open("xb")
            else:
                handle = os.fdopen(
                    os.open(
                        Path("evidence", "evidence", ".parts", part.name).as_posix(),
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                        dir_fd=root_descriptor,
                    ),
                    "wb",
                    buffering=0,
                )
        except (FileExistsError, OSError):
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="TEMPORARY_FILE_CONFLICT",
            )

        stream_failure = None
        try:
            with handle:
                for chunk in response.iter_content(chunk_size=STREAM_CHUNK_BYTES):
                    if not chunk:
                        continue
                    if not isinstance(chunk, bytes):
                        raise OSError("response yielded non-bytes content")
                    byte_count += len(chunk)
                    if byte_count > max_bytes:
                        stream_failure = "STREAM_EXCEEDS_LIMIT"
                        break
                    if len(prefix) < 5:
                        prefix.extend(chunk[: 5 - len(prefix)])
                    digest.update(chunk)
                    handle.write(chunk)
                if stream_failure is None:
                    handle.flush()
                    os.fsync(handle.fileno())
        except (OSError, requests.RequestException):
            if root_descriptor is None:
                _safe_unlink(part)
            else:
                _safe_unlink_at(root_descriptor, Path("evidence", "evidence", ".parts", part.name).as_posix())
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="STREAM_FAILED",
            )
        if stream_failure is not None:
            if root_descriptor is None:
                _safe_unlink(part)
            else:
                _safe_unlink_at(root_descriptor, Path("evidence", "evidence", ".parts", part.name).as_posix())
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code=stream_failure,
            )

        if byte_count != declared_bytes:
            if root_descriptor is None:
                _safe_unlink(part)
            else:
                _safe_unlink_at(root_descriptor, Path("evidence", "evidence", ".parts", part.name).as_posix())
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="CONTENT_LENGTH_MISMATCH",
            )
        if bytes(prefix) != b"%PDF-":
            if root_descriptor is None:
                _safe_unlink(part)
            else:
                _safe_unlink_at(root_descriptor, Path("evidence", "evidence", ".parts", part.name).as_posix())
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="INVALID_PDF_MAGIC",
            )

        attachment_sha256 = digest.hexdigest()
        relative_path = Path(
            "evidence", "sha256", attachment_sha256[:2], f"{attachment_sha256}.pdf"
        )
        target = output_dir / relative_path
        if root_descriptor is None:
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            _mkdirs_at(root_descriptor, ("evidence", "evidence", "sha256", attachment_sha256[:2]))
        existing_record = _existing_attachment_record(
            target=target,
            relative_path=relative_path,
            expected_sha256=attachment_sha256,
            expected_bytes=byte_count,
            max_bytes=max_bytes,
            review_id=review_id,
            candidate_url=candidate_url,
            snapshot_sha256=snapshot_sha256,
            attempted_at=attempted_at,
        )
        if existing_record is not None:
            if root_descriptor is None:
                _safe_unlink(part)
            else:
                _safe_unlink_at(root_descriptor, Path("evidence", "evidence", ".parts", part.name).as_posix())
            return existing_record

        try:
            if root_descriptor is None:
                os.link(part, target)
            else:
                os.link(
                    Path("evidence", "evidence", ".parts", part.name).as_posix(),
                    Path("evidence", "evidence", "sha256", attachment_sha256[:2], target.name).as_posix(),
                    src_dir_fd=root_descriptor,
                    dst_dir_fd=root_descriptor,
                )
        except FileExistsError:
            if root_descriptor is None:
                _safe_unlink(part)
            else:
                _safe_unlink_at(root_descriptor, Path("evidence", "evidence", ".parts", part.name).as_posix())
            raced_record = _existing_attachment_record(
                target=target,
                relative_path=relative_path,
                expected_sha256=attachment_sha256,
                expected_bytes=byte_count,
                max_bytes=max_bytes,
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
            )
            if raced_record is not None:
                return raced_record
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="ATTACHMENT_PUBLICATION_FAILED",
                attachment_sha256=attachment_sha256,
                attachment_path=relative_path.as_posix(),
                byte_count=byte_count,
            )
        except OSError:
            if root_descriptor is None:
                _safe_unlink(part)
            else:
                _safe_unlink_at(root_descriptor, Path("evidence", "evidence", ".parts", part.name).as_posix())
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="ATTACHMENT_PUBLICATION_FAILED",
                attachment_sha256=attachment_sha256,
                attachment_path=relative_path.as_posix(),
                byte_count=byte_count,
            )
        if root_descriptor is None:
            _safe_unlink(part)
        else:
            _safe_unlink_at(root_descriptor, Path("evidence", "evidence", ".parts", part.name).as_posix())
        try:
            if root_descriptor is None:
                _fsync_parent(target)
            else:
                _fsync_at(
                    root_descriptor,
                    Path("evidence", "evidence", "sha256", attachment_sha256[:2]).as_posix(),
                )
        except OSError:
            return _failure_record(
                review_id=review_id,
                candidate_url=candidate_url,
                snapshot_sha256=snapshot_sha256,
                attempted_at=attempted_at,
                failure_code="ATTACHMENT_DURABILITY_UNCERTAIN",
                attachment_sha256=attachment_sha256,
                attachment_path=relative_path.as_posix(),
                byte_count=byte_count,
            )
        return _success_record(
            review_id=review_id,
            candidate_url=candidate_url,
            snapshot_sha256=snapshot_sha256,
            attempted_at=attempted_at,
            retrieved_at=_utc_now(),
            attachment_sha256=attachment_sha256,
            attachment_path=relative_path.as_posix(),
            byte_count=byte_count,
            status="RETAINED",
        )
    finally:
        response.close()


def _write_manifest(
    manifest: dict[str, object],
    output_dir: Path,
    *,
    root_descriptor: int | None = None,
) -> Path:
    output_bytes = canonical_json_bytes(manifest)
    digest = hashlib.sha256(output_bytes).hexdigest()
    destination = (
        output_dir
        / "manifests"
        / "sha256"
        / digest[:2]
        / f"{digest}.json"
    )
    if root_descriptor is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        _mkdirs_at(root_descriptor, ("evidence", "manifests", "sha256", digest[:2]))
    part = destination.with_name(destination.name + ".part")
    try:
        if root_descriptor is None:
            handle = part.open("xb")
        else:
            handle = os.fdopen(
                os.open(
                    Path("evidence", "manifests", "sha256", digest[:2], part.name).as_posix(),
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=root_descriptor,
                ),
                "wb",
                buffering=0,
            )
    except (FileExistsError, OSError) as error:
        raise CandidateEvidenceError(
            "candidate manifest temporary-file conflict"
        ) from error
    try:
        with handle:
            handle.write(output_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if root_descriptor is None:
            os.link(part, destination)
        else:
            os.link(
                Path("evidence", "manifests", "sha256", digest[:2], part.name).as_posix(),
                Path("evidence", "manifests", "sha256", digest[:2], destination.name).as_posix(),
                src_dir_fd=root_descriptor,
                dst_dir_fd=root_descriptor,
            )
    except FileExistsError:
        if root_descriptor is None:
            _safe_unlink(part)
        else:
            _safe_unlink_at(root_descriptor, Path("evidence", "manifests", "sha256", digest[:2], part.name).as_posix())
        try:
            existing = _read_existing_content(
                destination,
                max_bytes=len(output_bytes),
            )
        except CandidateEvidenceError as error:
            raise CandidateEvidenceError(
                "candidate manifest content-address conflict"
            ) from error
        if existing != (digest, len(output_bytes)):
            raise CandidateEvidenceError(
                "candidate manifest content-address conflict"
            )
        return destination
    except OSError as error:
        if root_descriptor is None:
            _safe_unlink(part)
        else:
            _safe_unlink_at(root_descriptor, Path("evidence", "manifests", "sha256", digest[:2], part.name).as_posix())
        raise CandidateEvidenceError(
            "candidate manifest publication failed"
        ) from error

    if root_descriptor is None:
        _safe_unlink(part)
    else:
        _safe_unlink_at(root_descriptor, Path("evidence", "manifests", "sha256", digest[:2], part.name).as_posix())
    try:
        if root_descriptor is None:
            _fsync_parent(destination)
        else:
            _fsync_at(
                root_descriptor,
                Path("evidence", "manifests", "sha256", digest[:2]).as_posix(),
            )
    except OSError as error:
        raise CandidateEvidenceDurabilityError(
            "candidate manifest published but parent durability is uncertain"
        ) from error
    return destination


def retain_candidate_attachments(
    index_rows: list[dict[str, object]],
    *,
    output_dir: str | Path,
    allowed_hosts: set[str],
    session: requests.Session,
    max_bytes: int = 25_000_000,
    root_descriptor: int | None = None,
) -> dict[str, object]:
    """Retain candidate PDFs without creating review or audit authority."""

    validated = _validate_index_rows(index_rows)
    output, normalized_hosts = _validate_configuration(
        output_dir=output_dir,
        allowed_hosts=allowed_hosts,
        max_bytes=max_bytes,
    )
    records: list[dict[str, object]] = []
    for row in validated:
        review_id = str(row["review_id"])
        for candidate in row["announcement_candidates"]:
            records.append(
                _retain_one(
                    review_id=review_id,
                    candidate=candidate,
                    output_dir=output,
                    allowed_hosts=normalized_hosts,
                    session=session,
                    max_bytes=max_bytes,
                    root_descriptor=root_descriptor,
                )
            )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "proposal_only": True,
        "records": records,
    }
    _write_manifest(manifest, output, root_descriptor=root_descriptor)
    return manifest
