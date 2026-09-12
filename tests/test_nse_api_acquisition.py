import hashlib
import json
from datetime import date

import pytest

from src.reliability.nse_api_acquisition import (
    ApiSnapshotAcquirer,
    ApiSnapshotError,
    annual_reports_request,
    corporate_announcements_request,
    corporate_actions_request,
    financial_results_range_request,
    financial_results_request,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, content_type="application/json", text=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.text = text if text is not None else (
            "invalid" if isinstance(payload, Exception) else json.dumps(payload)
        )

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_official_api_requests_use_bounded_dates_and_period():
    actions = corporate_actions_request(date(2024, 7, 1), date(2024, 7, 31))
    assert actions.endpoint.endswith("/api/corporates-corporateActions")
    assert actions.params == {
        "index": "equities", "from_date": "01-07-2024", "to_date": "31-07-2024"
    }

    announcements = corporate_announcements_request(date(2024, 7, 1), date(2024, 7, 31))
    assert announcements.endpoint.endswith("/api/corporate-announcements")
    assert announcements.params == {
        "index": "equities", "from_date": "01-07-2024", "to_date": "31-07-2024"
    }
    assert announcements.kind == "corporate_announcements"

    results = financial_results_request(date(2024, 7, 31), period="Quarterly")
    assert results.endpoint.endswith("/api/corporates-financial-results")
    assert results.params == {"index": "equities", "period": "Quarterly"}
    assert results.snapshot_date == date(2024, 7, 31)

    historical = financial_results_range_request(
        date(2024, 6, 1), date(2024, 6, 30), period="Quarterly"
    )
    assert historical.params["from_date"] == "01-06-2024"
    assert historical.params["to_date"] == "30-06-2024"
    assert historical.filename.endswith("20240601-20240630.json")

    annual = annual_reports_request("TCS", date(2024, 7, 5))
    assert annual.endpoint.endswith("/api/annual-reports")
    assert annual.params == {"index": "equities", "symbol": "TCS"}
    assert annual.filename == "annual-reports-TCS-20240705.json"


def test_api_snapshot_bootstraps_cookies_retains_canonical_json_and_catalogues(tmp_path):
    payload = [{"symbol": "TCS", "subject": "Dividend", "exDate": "10-Jul-2024"}]
    client = FakeClient([FakeResponse({}, content_type="text/html"), FakeResponse(payload)])
    acquirer = ApiSnapshotAcquirer(tmp_path, client=client, retries=1)

    result = acquirer.acquire(corporate_actions_request(date(2024, 7, 1), date(2024, 7, 31)))

    expected = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    assert result.status == "downloaded"
    assert result.path.read_bytes() == expected
    assert result.sha256 == hashlib.sha256(expected).hexdigest()
    assert client.calls[0][0].endswith("/companies-listing/corporate-filings-actions")
    assert client.calls[1][1]["params"]["from_date"] == "01-07-2024"
    catalogue = [json.loads(row) for row in (tmp_path / "source-catalogue.jsonl").read_text().splitlines()]
    assert catalogue[-1]["status"] == "downloaded"
    assert catalogue[-1]["available_at"].endswith("Z")


def test_api_snapshot_is_immutable_and_reuses_matching_file(tmp_path):
    payload = [{"symbol": "TCS"}]
    client = FakeClient([FakeResponse({}, content_type="text/html"), FakeResponse(payload)])
    acquirer = ApiSnapshotAcquirer(tmp_path, client=client, retries=1)
    request = financial_results_request(date(2024, 7, 31))

    first = acquirer.acquire(request)
    second = acquirer.acquire(request)

    assert first.status == "downloaded"
    assert second.status == "cached"
    assert len(client.calls) == 2
    records = [
        json.loads(row)
        for row in (tmp_path / "source-catalogue.jsonl").read_text().splitlines()
    ]
    assert len(records) == 1


def test_api_snapshot_rejects_conflicting_catalogued_identity(tmp_path):
    payload = [{"symbol": "TCS"}]
    client = FakeClient([FakeResponse({}, content_type="text/html"), FakeResponse(payload)])
    acquirer = ApiSnapshotAcquirer(tmp_path, client=client, retries=1)
    request = financial_results_request(date(2024, 7, 31))
    acquirer.acquire(request)

    catalogue_path = tmp_path / "source-catalogue.jsonl"
    record = json.loads(catalogue_path.read_text().splitlines()[0])
    record["sha256"] = "0" * 64
    catalogue_path.write_text(json.dumps(record) + "\n")

    with pytest.raises(ApiSnapshotError, match="conflicting retained snapshots"):
        acquirer.acquire(request)


def test_api_snapshot_rejects_malformed_catalogue_after_duplicate(tmp_path):
    payload = [{"symbol": "TCS"}]
    client = FakeClient([FakeResponse({}, content_type="text/html"), FakeResponse(payload)])
    acquirer = ApiSnapshotAcquirer(tmp_path, client=client, retries=1)
    request = financial_results_request(date(2024, 7, 31))
    acquirer.acquire(request)

    catalogue_path = tmp_path / "source-catalogue.jsonl"
    catalogue_path.write_text(
        catalogue_path.read_text() + "not-json\n",
        encoding="utf-8",
    )

    with pytest.raises(ApiSnapshotError, match="source catalogue is malformed"):
        acquirer.acquire(request)


@pytest.mark.parametrize("response", [
    FakeResponse(text="<html>blocked</html>", content_type="text/html"),
    FakeResponse({"message": "rate limited"}, status_code=429),
    FakeResponse(ValueError("bad json")),
    FakeResponse("not a collection"),
])
def test_api_snapshot_rejects_block_pages_errors_and_wrong_schema(tmp_path, response):
    client = FakeClient([FakeResponse({}, content_type="text/html"), response])
    acquirer = ApiSnapshotAcquirer(tmp_path, client=client, retries=1)

    with pytest.raises(ApiSnapshotError):
        acquirer.acquire(corporate_actions_request(date(2024, 7, 1), date(2024, 7, 31)))

    assert not list(tmp_path.rglob("*.json"))
    records = [json.loads(row) for row in (tmp_path / "source-catalogue.jsonl").read_text().splitlines()]
    assert records[-1]["status"] == "failed"


def test_api_range_over_31_days_is_rejected():
    with pytest.raises(ValueError, match="31 days"):
        corporate_actions_request(date(2024, 1, 1), date(2024, 2, 1))
