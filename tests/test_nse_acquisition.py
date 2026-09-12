import gzip
import hashlib
import io
import json
import zipfile
from datetime import date

import pytest

from src.reliability.nse_acquisition import (
    AcquisitionError,
    ArchiveDownloader,
    DownloadSpec,
    existing_weekdays,
    legacy_bhavcopy_spec,
    plan_weekdays,
    security_master_spec,
    udiff_bhavcopy_spec,
)


class FakeResponse:
    def __init__(self, body, status_code=200, content_type="application/octet-stream"):
        self.content = body
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def iter_content(self, chunk_size=64 * 1024):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _zip(name="report.csv", body=b"SYMBOL,CLOSE\nTCS,100\n"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, body)
    return buffer.getvalue()


def test_versioned_source_specs_use_official_naming_patterns():
    old = legacy_bhavcopy_spec(date(2024, 6, 28))
    assert old.url.endswith("/EQUITIES/2024/JUN/cm28JUN2024bhav.csv.zip")
    assert old.archive_type == "zip"

    current = udiff_bhavcopy_spec(date(2024, 7, 8))
    assert current.filename == "BhavCopy_NSE_CM_0_0_0_20240708_F_0000.csv.zip"
    assert current.url.startswith("https://nsearchives.nseindia.com/")

    security = security_master_spec(date(2024, 7, 8))
    assert security.filename == "NSE_CM_security_08072024.csv.gz"
    assert security.url.startswith("https://nsearchives.nseindia.com/")


def test_downloader_atomically_retains_archive_extracts_and_catalogues(tmp_path):
    payload = _zip()
    spec = DownloadSpec("bhavcopy", date(2024, 6, 28), "https://example.test/a.zip", "a.zip", "zip")
    downloader = ArchiveDownloader(tmp_path, client=FakeClient([FakeResponse(payload)]), retries=1)

    result = downloader.acquire(spec)

    assert result.status == "downloaded"
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.archive_path.read_bytes() == payload
    assert result.extracted_paths[0].read_text() == "SYMBOL,CLOSE\nTCS,100\n"
    rows = [json.loads(line) for line in (tmp_path / "source-catalogue.jsonl").read_text().splitlines()]
    assert rows[-1]["sha256"] == result.sha256
    assert not list(tmp_path.rglob("*.part"))


def test_downloader_reuses_identical_archive_without_network(tmp_path):
    payload = gzip.compress(b"SYMBOL,SERIES\nTCS,EQ\n")
    spec = DownloadSpec("security", date(2024, 7, 8), "https://example.test/a.gz", "a.csv.gz", "gzip")
    client = FakeClient([FakeResponse(payload)])
    downloader = ArchiveDownloader(tmp_path, client=client, retries=1)
    first = downloader.acquire(spec)
    second = downloader.acquire(spec)

    assert first.status == "downloaded"
    assert second.status == "cached"
    assert client.calls == 1
    assert second.extracted_paths[0].read_bytes().startswith(b"SYMBOL")


@pytest.mark.parametrize("response", [
    FakeResponse(b"<html>Access denied</html>", content_type="text/html"),
    FakeResponse(b'{"error":"blocked"}', content_type="application/json"),
    FakeResponse(b"not a zip"),
])
def test_downloader_rejects_error_pages_and_invalid_archives(tmp_path, response):
    spec = DownloadSpec("bhavcopy", date(2024, 7, 8), "https://example.test/a.zip", "a.zip", "zip")
    downloader = ArchiveDownloader(tmp_path, client=FakeClient([response]), retries=1)

    with pytest.raises(AcquisitionError):
        downloader.acquire(spec)

    assert not list(tmp_path.rglob("*.zip"))


def test_retryable_transport_failure_is_not_recorded_as_missing_report(tmp_path):
    spec = DownloadSpec("bhavcopy", date(2024, 7, 8), "https://example.test/a.zip", "a.zip", "zip")
    client = FakeClient([OSError("timeout"), FakeResponse(_zip())])
    result = ArchiveDownloader(tmp_path, client=client, retries=2, sleep=lambda _: None).acquire(spec)

    assert result.status == "downloaded"
    assert client.calls == 2


def test_weekday_planner_excludes_weekends_but_only_explicit_holidays():
    planned = plan_weekdays(date(2024, 7, 5), date(2024, 7, 9), holidays={date(2024, 7, 8)})
    assert planned == [date(2024, 7, 5), date(2024, 7, 9)]
    assert existing_weekdays(date(2024, 7, 6), date(2024, 7, 7)) == []


def test_downloader_safely_flattens_nse_same_name_nested_member(tmp_path):
    payload = _zip("report.csv/report.csv")
    spec = DownloadSpec("bhavcopy", date(2020, 7, 13), "https://example.test/a.zip",
                        "a.zip", "zip")

    result = ArchiveDownloader(
        tmp_path, client=FakeClient([FakeResponse(payload)]), retries=1
    ).acquire(spec)

    assert result.extracted_paths[0].name == "report.csv"
    assert result.extracted_paths[0].parent == result.archive_path.parent


@pytest.mark.parametrize("member", ["../report.csv", "/tmp/report.csv"])
def test_downloader_rejects_zip_path_traversal(tmp_path, member):
    spec = DownloadSpec("bhavcopy", date(2020, 7, 13), "https://example.test/a.zip",
                        "a.zip", "zip")

    with pytest.raises(AcquisitionError, match="unsafe"):
        ArchiveDownloader(
            tmp_path, client=FakeClient([FakeResponse(_zip(member))]), retries=1
        ).acquire(spec)
