import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
import requests

import src.reliability.corporate_action_candidate_evidence as candidate_evidence_module
from src.reliability.corporate_action_candidate_evidence import (
    CandidateEvidenceDurabilityError,
    CandidateEvidenceError,
    retain_candidate_attachments,
)
from src.reliability.preregistration import canonical_json_bytes


PDF_BYTES = b"%PDF-1.7\nproposal evidence\n%%EOF\n"
ALLOWED_HOST = "nsearchives.nseindia.com"
SOURCE_SHA256 = "1" * 64
REVIEW_ID = "2" * 64


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected network request")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        response.url = url
        return response


class StreamingRaw:
    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, chunk_size, decode_content=True):
        del chunk_size, decode_content
        yield from self._chunks

    def close(self):
        pass


class FailingStreamingRaw(StreamingRaw):
    def stream(self, chunk_size, decode_content=True):
        del chunk_size, decode_content
        yield PDF_BYTES[:8]
        raise requests.ConnectionError("stream interrupted")


def _response(
    body=PDF_BYTES,
    *,
    status=200,
    headers=None,
    chunks=None,
):
    response = requests.Response()
    response.status_code = status
    response.headers.update(
        headers
        if headers is not None
        else {
            "Content-Length": str(len(body)),
            "Content-Type": "application/pdf",
        }
    )
    if chunks is None:
        response._content = body
        response._content_consumed = True
    else:
        response._content = False
        response._content_consumed = False
        response.raw = StreamingRaw(chunks)
    return response


def _pdf_headers(byte_count):
    return {
        "Content-Length": str(byte_count),
        "Content-Type": "application/pdf",
    }


def _candidate(url, *, snapshot_sha256=SOURCE_SHA256, seq_id="123"):
    return {
        "seq_id": seq_id,
        "symbol": "ACME",
        "broadcast_at": "2024-01-09T10:00:00+05:30",
        "description": "Rights issue",
        "subject": "Rights entitlement",
        "attachment_text": "Offer document",
        "attachment_url": url,
        "snapshot_path": "data/announcements.json",
        "snapshot_sha256": snapshot_sha256,
        "snapshot_bytes": 100,
        "snapshot_available_at": "2024-01-09T05:00:00Z",
        "ambiguity_reason": "CANDIDATE_NOT_CANONICAL",
    }


def _index_row(*urls, review_id=REVIEW_ID):
    candidates = [_candidate(url, seq_id=str(index)) for index, url in enumerate(urls)]
    return {
        "schema_version": "corporate-action-evidence-index-v1",
        "proposal_only": True,
        "review_id": review_id,
        "queue_kind": "visibility",
        "review_identity": {
            "symbol": "ACME",
            "action_type": "RIGHTS",
            "ex_date": "2024-01-10",
            "purpose": "Rights 1:4",
            "reason": "unverified",
        },
        "action_source": {
            "path": "data/actions.csv",
            "sha256": "3" * 64,
            "bytes": 200,
            "available_at": "2024-01-10T00:00:00Z",
        },
        "announcement_candidates": candidates,
        "candidate_resolution": (
            "AMBIGUOUS_REVIEW_REQUIRED" if candidates else "NO_COMPATIBLE_CANDIDATE"
        ),
    }


def _record(manifest):
    assert manifest["schema_version"] == "corporate-action-candidate-evidence-v1"
    assert manifest["proposal_only"] is True
    assert len(manifest["records"]) == 1
    return manifest["records"][0]


def _manifest_path(output_dir, manifest):
    digest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    return output_dir / "manifests" / "sha256" / digest[:2] / f"{digest}.json"


def _assert_timestamp(value):
    assert value.endswith("Z")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    assert parsed.tzinfo is not None


def test_https_allowed_host_retains_content_addressed_pdf_and_canonical_manifest(
    tmp_path,
):
    url = f"https://{ALLOWED_HOST}/corporate/acme.pdf"
    session = FakeSession([_response()])

    manifest = retain_candidate_attachments(
        [_index_row(url)],
        output_dir=tmp_path,
        allowed_hosts={ALLOWED_HOST},
        session=session,
    )

    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    relative_path = f"evidence/sha256/{digest[:2]}/{digest}.pdf"
    record = _record(manifest)
    assert record == {
        "schema_version": "corporate-action-candidate-evidence-v1",
        "proposal_only": True,
        "review_id": REVIEW_ID,
        "candidate_url": url,
        "attachment_sha256": digest,
        "attachment_path": relative_path,
        "byte_count": len(PDF_BYTES),
        "attempted_at": record["attempted_at"],
        "retrieved_at": record["retrieved_at"],
        "source_snapshot_sha256": SOURCE_SHA256,
        "status": "RETAINED",
        "failure_code": None,
    }
    _assert_timestamp(record["attempted_at"])
    _assert_timestamp(record["retrieved_at"])
    assert record["attempted_at"] <= record["retrieved_at"]
    assert (tmp_path / relative_path).read_bytes() == PDF_BYTES
    manifest_path = _manifest_path(tmp_path, manifest)
    assert manifest_path.read_bytes() == canonical_json_bytes(manifest)
    assert not list(tmp_path.rglob("*.part"))
    assert session.calls == [
        (
            url,
            {
                "stream": True,
                "allow_redirects": False,
                "timeout": (5.0, 30.0),
            },
        )
    ]


def test_successful_raw_stream_is_retained_without_reopening_response_body(tmp_path):
    url = f"https://{ALLOWED_HOST}/corporate/streamed.pdf"
    chunks = [PDF_BYTES[:7], PDF_BYTES[7:19], PDF_BYTES[19:]]
    session = FakeSession(
        [_response(headers=_pdf_headers(len(PDF_BYTES)), chunks=chunks)]
    )

    record = _record(
        retain_candidate_attachments(
            [_index_row(url)],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "RETAINED"
    assert (tmp_path / record["attachment_path"]).read_bytes() == PDF_BYTES
    assert not list(tmp_path.rglob("*.part"))


def test_retrieved_at_is_verified_retention_completion_time(tmp_path, monkeypatch):
    timestamps = iter(["2026-08-01T10:00:00.000000Z", "2026-08-01T10:00:01.000000Z"])
    monkeypatch.setattr(candidate_evidence_module, "_utc_now", lambda: next(timestamps))

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/timed.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=FakeSession([_response()]),
        )
    )

    assert record["attempted_at"] == "2026-08-01T10:00:00.000000Z"
    assert record["retrieved_at"] == "2026-08-01T10:00:01.000000Z"
    assert (tmp_path / record["attachment_path"]).exists()


def test_request_timeout_is_explicit_and_leaves_no_retrieval_timestamp(tmp_path):
    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/timeout.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=FakeSession([requests.Timeout("read timed out")]),
        )
    )

    assert record["failure_code"] == "REQUEST_FAILED"
    _assert_timestamp(record["attempted_at"])
    assert record["retrieved_at"] is None
    assert not list(tmp_path.rglob("*.part"))


def test_midstream_request_error_is_explicit_and_cleans_part(tmp_path):
    response = _response(headers=_pdf_headers(len(PDF_BYTES)), chunks=[])
    response.raw = FailingStreamingRaw([])

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/interrupted.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=FakeSession([response]),
        )
    )

    assert record["failure_code"] == "STREAM_FAILED"
    _assert_timestamp(record["attempted_at"])
    assert record["retrieved_at"] is None
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.pdf"))


def test_http_url_is_recorded_as_failure_without_network_or_attachment(tmp_path):
    url = f"http://{ALLOWED_HOST}/corporate/acme.pdf"
    session = FakeSession([])

    record = _record(
        retain_candidate_attachments(
            [_index_row(url)],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "URL_NOT_HTTPS"
    assert record["attachment_sha256"] is None
    assert record["attachment_path"] is None
    assert record["byte_count"] is None
    assert record["attempted_at"] is None
    assert record["retrieved_at"] is None
    assert session.calls == []
    assert not list((tmp_path / "evidence").rglob("*.pdf"))


def test_unapproved_host_is_recorded_as_failure_without_network(tmp_path):
    url = "https://example.com/acme.pdf"
    session = FakeSession([])

    record = _record(
        retain_candidate_attachments(
            [_index_row(url)],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["failure_code"] == "HOST_NOT_ALLOWED"
    assert record["attempted_at"] is None
    assert record["retrieved_at"] is None
    assert session.calls == []


def test_redirect_to_unapproved_host_is_not_followed_and_is_recorded(tmp_path):
    url = f"https://{ALLOWED_HOST}/corporate/acme.pdf"
    response = _response(
        body=b"",
        status=302,
        headers={
            "Content-Length": "0",
            "Content-Type": "application/pdf",
            "Location": "https://example.com/acme.pdf",
        },
    )
    session = FakeSession([response])

    record = _record(
        retain_candidate_attachments(
            [_index_row(url)],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "REDIRECT_REJECTED"
    _assert_timestamp(record["attempted_at"])
    assert record["retrieved_at"] is None
    assert len(session.calls) == 1
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("content_length", [None, "", "unknown", "-1", "1.5"])
def test_missing_or_invalid_content_length_is_recorded(
    tmp_path,
    content_length,
):
    headers = {} if content_length is None else {"Content-Length": content_length}
    session = FakeSession([_response(headers=headers)])

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "INVALID_CONTENT_LENGTH"
    assert not list(tmp_path.rglob("*.pdf"))


def test_pathologically_large_numeric_content_length_is_invalid(tmp_path):
    session = FakeSession([_response(headers={"Content-Length": "9" * 5_000})])

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["failure_code"] == "INVALID_CONTENT_LENGTH"


def test_streamed_byte_count_must_equal_declared_content_length(tmp_path):
    session = FakeSession(
        [
            _response(
                headers=_pdf_headers(len(PDF_BYTES) + 1),
                chunks=[PDF_BYTES],
            )
        ]
    )

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["failure_code"] == "CONTENT_LENGTH_MISMATCH"
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.pdf"))


def test_declared_content_length_above_limit_is_rejected_before_streaming(tmp_path):
    session = FakeSession(
        [_response(headers={"Content-Length": "25000001"}, chunks=[PDF_BYTES])]
    )

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["failure_code"] == "CONTENT_LENGTH_EXCEEDS_LIMIT"
    assert not list(tmp_path.rglob("*.part"))


def test_streamed_size_above_default_25_mb_is_recorded_and_part_removed(tmp_path):
    chunk = b"x" * 65_536
    chunks = [b"%PDF-"] + [chunk] * 382
    session = FakeSession(
        [_response(headers=_pdf_headers(25_000_000), chunks=chunks)]
    )

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["failure_code"] == "STREAM_EXCEEDS_LIMIT"
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.pdf"))


@pytest.mark.parametrize(
    "content_type",
    ["application/pdf", "application/pdf; charset=binary", "application/x-pdf"],
)
def test_sane_pdf_content_types_are_accepted(tmp_path, content_type):
    session = FakeSession(
        [
            _response(
                headers={
                    "Content-Length": str(len(PDF_BYTES)),
                    "Content-Type": content_type,
                }
            )
        ]
    )

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "RETAINED"


@pytest.mark.parametrize("content_type", [None, "text/html", "application/octet-stream"])
def test_missing_or_non_pdf_content_type_is_an_explicit_failure(
    tmp_path,
    content_type,
):
    headers = {"Content-Length": str(len(PDF_BYTES))}
    if content_type is not None:
        headers["Content-Type"] = content_type
    session = FakeSession([_response(headers=headers)])

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "INVALID_CONTENT_TYPE"
    assert record["retrieved_at"] is None
    assert not list(tmp_path.rglob("*.pdf"))


def test_gzip_content_encoding_is_rejected_without_retaining_a_file(tmp_path):
    session = FakeSession(
        [
            _response(
                headers={
                    "Content-Length": str(len(PDF_BYTES)),
                    "Content-Type": "application/pdf",
                    "Content-Encoding": "gzip",
                }
            )
        ]
    )

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/encoded.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "CONTENT_ENCODING_REJECTED"
    assert record["attachment_path"] is None
    assert not list(tmp_path.rglob("*.pdf"))


@pytest.mark.parametrize(
    ("response", "failure_code"),
    [
        (_response(body=b"<html>not a pdf</html>"), "INVALID_PDF_MAGIC"),
        (_response(status=500), "HTTP_STATUS_REJECTED"),
    ],
)
def test_html_or_error_response_masquerading_as_pdf_is_recorded(
    tmp_path,
    response,
    failure_code,
):
    session = FakeSession([response])

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["failure_code"] == failure_code
    assert record["attachment_path"] is None
    assert not list(tmp_path.rglob("*.pdf"))


def test_duplicate_content_under_two_urls_reuses_one_content_address(tmp_path):
    first_url = f"https://{ALLOWED_HOST}/first.pdf"
    second_url = f"https://{ALLOWED_HOST}/second.pdf"
    session = FakeSession([_response(), _response()])

    manifest = retain_candidate_attachments(
        [_index_row(first_url, second_url)],
        output_dir=tmp_path,
        allowed_hosts={ALLOWED_HOST},
        session=session,
    )

    assert [record["status"] for record in manifest["records"]] == [
        "RETAINED",
        "REUSED",
    ]
    assert (
        manifest["records"][0]["attachment_path"]
        == manifest["records"][1]["attachment_path"]
    )
    assert len(list(tmp_path.rglob("*.pdf"))) == 1


def test_existing_matching_content_is_reused(tmp_path):
    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    target = tmp_path / "evidence" / "sha256" / digest[:2] / f"{digest}.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(PDF_BYTES)
    session = FakeSession([_response()])

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "REUSED"
    assert target.read_bytes() == PDF_BYTES
    assert not list(tmp_path.rglob("*.part"))


def test_existing_conflicting_content_fails_without_replacement(tmp_path):
    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    target = tmp_path / "evidence" / "sha256" / digest[:2] / f"{digest}.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"conflicting bytes")
    session = FakeSession([_response()])

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "CONTENT_ADDRESS_CONFLICT"
    assert record["attachment_sha256"] == digest
    assert target.read_bytes() == b"conflicting bytes"
    assert not list(tmp_path.rglob("*.part"))


def test_target_created_at_publication_is_never_overwritten(tmp_path, monkeypatch):
    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    target = tmp_path / "evidence" / "sha256" / digest[:2] / f"{digest}.pdf"
    conflicting = b"published by racing writer"
    real_link = candidate_evidence_module.os.link
    real_replace = candidate_evidence_module.os.replace

    def racing_link(source, destination):
        if Path(destination) == target:
            target.write_bytes(conflicting)
        return real_link(source, destination)

    def racing_replace(source, destination):
        if Path(destination) == target:
            target.write_bytes(conflicting)
        return real_replace(source, destination)

    monkeypatch.setattr(candidate_evidence_module.os, "link", racing_link)
    monkeypatch.setattr(candidate_evidence_module.os, "replace", racing_replace)

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/race.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=FakeSession([_response()]),
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "CONTENT_ADDRESS_CONFLICT"
    assert target.read_bytes() == conflicting
    assert not list(tmp_path.rglob("*.part"))


def test_existing_content_verification_is_bounded_by_max_bytes(tmp_path):
    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    target = tmp_path / "evidence" / "sha256" / digest[:2] / f"{digest}.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x" * (len(PDF_BYTES) + 1))

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/bounded-existing.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=FakeSession([_response()]),
            max_bytes=len(PDF_BYTES),
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "EXISTING_CONTENT_EXCEEDS_LIMIT"
    assert target.read_bytes() == b"x" * (len(PDF_BYTES) + 1)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(proposal_only=False),
        lambda row: row.update(canonical_decision="APPROVED"),
        lambda row: row["announcement_candidates"][0].update(
            audit_authority="verified"
        ),
    ],
)
def test_authoritative_or_nonproposal_input_is_rejected_before_side_effects(
    tmp_path,
    mutation,
):
    row = _index_row(f"https://{ALLOWED_HOST}/acme.pdf")
    mutation(row)
    session = FakeSession([])

    with pytest.raises(CandidateEvidenceError, match="proposal|authority|schema"):
        retain_candidate_attachments(
            [row],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=session,
        )

    assert session.calls == []
    assert list(tmp_path.iterdir()) == []


def test_rerun_retains_immutable_manifest_history(
    tmp_path,
    monkeypatch,
):
    timestamps = iter(
        [
            "2026-08-01T10:00:00.000000Z",
            "2026-08-01T10:00:01.000000Z",
            "2026-08-01T11:00:00.000000Z",
            "2026-08-01T11:00:01.000000Z",
        ]
    )
    monkeypatch.setattr(candidate_evidence_module, "_utc_now", lambda: next(timestamps))
    row = _index_row(f"https://{ALLOWED_HOST}/history.pdf")

    first = retain_candidate_attachments(
        [row],
        output_dir=tmp_path,
        allowed_hosts={ALLOWED_HOST},
        session=FakeSession([_response()]),
    )
    first_path = _manifest_path(tmp_path, first)
    first_bytes = first_path.read_bytes()
    second = retain_candidate_attachments(
        [row],
        output_dir=tmp_path,
        allowed_hosts={ALLOWED_HOST},
        session=FakeSession([_response()]),
    )
    second_path = _manifest_path(tmp_path, second)

    assert first_path != second_path
    assert first_path.read_bytes() == first_bytes == canonical_json_bytes(first)
    assert second_path.read_bytes() == canonical_json_bytes(second)
    assert len(list((tmp_path / "manifests").rglob("*.json"))) == 2
    assert [first["records"][0]["status"], second["records"][0]["status"]] == [
        "RETAINED",
        "REUSED",
    ]


def test_identical_verified_rerun_reuses_reproducible_manifest(tmp_path, monkeypatch):
    digest = hashlib.sha256(PDF_BYTES).hexdigest()
    target = tmp_path / "evidence" / "sha256" / digest[:2] / f"{digest}.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(PDF_BYTES)
    timestamps = iter(
        [
            "2026-08-01T10:00:00.000000Z",
            "2026-08-01T10:00:01.000000Z",
            "2026-08-01T10:00:00.000000Z",
            "2026-08-01T10:00:01.000000Z",
        ]
    )
    monkeypatch.setattr(candidate_evidence_module, "_utc_now", lambda: next(timestamps))
    row = _index_row(f"https://{ALLOWED_HOST}/reproducible.pdf")

    first = retain_candidate_attachments(
        [row],
        output_dir=tmp_path,
        allowed_hosts={ALLOWED_HOST},
        session=FakeSession([_response()]),
    )
    second = retain_candidate_attachments(
        [row],
        output_dir=tmp_path,
        allowed_hosts={ALLOWED_HOST},
        session=FakeSession([_response()]),
    )

    assert first == second
    assert _manifest_path(tmp_path, first) == _manifest_path(tmp_path, second)
    assert len(list((tmp_path / "manifests").rglob("*.json"))) == 1


def test_conflicting_immutable_manifest_is_never_overwritten(tmp_path):
    manifest = {
        "schema_version": "corporate-action-candidate-evidence-v1",
        "proposal_only": True,
        "records": [],
    }
    manifest_path = _manifest_path(tmp_path, manifest)
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(b"conflicting manifest bytes\n")

    with pytest.raises(CandidateEvidenceError, match="manifest.*conflict"):
        retain_candidate_attachments(
            [],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=FakeSession([]),
        )

    assert manifest_path.read_bytes() == b"conflicting manifest bytes\n"
    assert not list(tmp_path.rglob("*.part"))


def test_attachment_parent_fsync_failure_is_an_explicit_durability_failure(
    tmp_path,
    monkeypatch,
):
    real_fsync_parent = candidate_evidence_module._fsync_parent

    def fail_attachment_parent(path):
        if Path(path).suffix == ".pdf":
            raise OSError("attachment parent fsync failed")
        return real_fsync_parent(path)

    monkeypatch.setattr(
        candidate_evidence_module,
        "_fsync_parent",
        fail_attachment_parent,
    )

    record = _record(
        retain_candidate_attachments(
            [_index_row(f"https://{ALLOWED_HOST}/acme.pdf")],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=FakeSession([_response()]),
        )
    )

    assert record["status"] == "FAILED"
    assert record["failure_code"] == "ATTACHMENT_DURABILITY_UNCERTAIN"
    assert record["retrieved_at"] is None
    assert record["attachment_path"] is not None
    assert (tmp_path / record["attachment_path"]).read_bytes() == PDF_BYTES
    assert not list(tmp_path.rglob("*.part"))


def test_manifest_parent_fsync_failure_reports_published_destination(
    tmp_path,
    monkeypatch,
):
    real_fsync_parent = candidate_evidence_module._fsync_parent

    def fail_manifest_parent(path):
        if Path(path).suffix == ".json":
            raise OSError("manifest parent fsync failed")
        return real_fsync_parent(path)

    monkeypatch.setattr(candidate_evidence_module, "_fsync_parent", fail_manifest_parent)

    with pytest.raises(
        CandidateEvidenceDurabilityError,
        match="manifest.*published.*durability.*uncertain",
    ):
        retain_candidate_attachments(
            [],
            output_dir=tmp_path,
            allowed_hosts={ALLOWED_HOST},
            session=FakeSession([]),
        )

    manifest_paths = list((tmp_path / "manifests").rglob("*.json"))
    assert len(manifest_paths) == 1
    manifest_path = manifest_paths[0]
    assert json.loads(manifest_path.read_text()) == {
        "schema_version": "corporate-action-candidate-evidence-v1",
        "proposal_only": True,
        "records": [],
    }
    assert not list(tmp_path.rglob("*.part"))


def test_manifest_contains_one_explicit_record_for_each_candidate_and_no_authority(
    tmp_path,
):
    valid_url = f"https://{ALLOWED_HOST}/valid.pdf"
    invalid_url = "http://example.com/invalid.pdf"
    manifest = retain_candidate_attachments(
        [_index_row(valid_url, invalid_url)],
        output_dir=tmp_path,
        allowed_hosts={ALLOWED_HOST},
        session=FakeSession([_response()]),
    )

    assert len(manifest["records"]) == 2
    assert [record["candidate_url"] for record in manifest["records"]] == [
        valid_url,
        invalid_url,
    ]
    encoded = json.dumps(manifest).lower()
    assert "canonical_decision" not in encoded
    assert "audit_authority" not in encoded
    assert '"decision"' not in encoded
