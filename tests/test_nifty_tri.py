import hashlib
import json
from datetime import date

import pytest
import requests

from src.reliability.nifty_tri import (
    NIFTY_TRI_URL,
    NiftyTriAcquirer,
    NiftyTriError,
    TriWindow,
    _file_bytes,
    _request_body,
    build_tri_windows,
    merge_tri_windows,
    normalize_tri_rows,
    validate_tri_session_coverage,
)
from src.reliability.preregistration import canonical_json_bytes


class FakeResponse:
    def __init__(
        self, payload, status_code=200, content_type="application/json", text=None, raw_body=None
    ):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        if raw_body is None:
            raw_body = (text if text is not None else json.dumps(payload)).encode()
        self.content = raw_body
        self.text = text if text is not None else raw_body.decode()

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _payload(*rows):
    return list(rows)


def _official_row(day, value, index="Nifty 50"):
    return {
        "RequestNumber": "TRI-test",
        "Index Name": index,
        "Date": day,
        "TotalReturnsIndex": value,
        "NTR_Value": "99.00",
    }


def _minimal_row(day="01 Jan 2024", value="100"):
    return {
        "Date": day,
        "Index Name": "Nifty 50",
        "TotalReturnsIndex": value,
    }


def _artifact_payload(result):
    return {
        key: value for key, value in result.items()
        if key not in {"status", "path", "raw_path"}
    }


def _write_canonical_artifact(result):
    result["path"].write_text(json.dumps(
        _artifact_payload(result), indent=2, sort_keys=True
    ) + "\n")


def _retain_window(acquirer, window, *, value):
    day = window.start
    raw_payload = [_minimal_row(day.strftime("%d %b %Y"), str(value))]
    raw_response = canonical_json_bytes(raw_payload)
    normalized = [{"session_date": day.isoformat(), "tri": float(value)}]
    path = acquirer._path(window)
    raw_path = acquirer._raw_path(window)
    artifact = acquirer._artifact(
        window,
        _request_body(window),
        raw_payload,
        normalized,
        raw_path=raw_path,
        raw_response=raw_response,
        status_code=200,
        content_type="application/json",
        retrieved_at="2026-07-24T00:00:00Z",
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw_response)
    path.write_bytes(_file_bytes(artifact))
    acquirer._catalogue({
        **artifact,
        "status": "downloaded",
        "path": path,
        "raw_path": raw_path,
    })
    return path


def test_normalizer_accepts_minimal_required_row_without_optional_extras():
    assert normalize_tri_rows([_minimal_row()]) == [
        {"session_date": "2024-01-01", "tri": 100.0},
    ]


def test_normalizer_validates_optional_official_extras_when_present():
    assert normalize_tri_rows([_official_row("01 Jan 2024", "100")]) == [
        {"session_date": "2024-01-01", "tri": 100.0},
    ]
    with pytest.raises(NiftyTriError, match="request number"):
        normalize_tri_rows([{**_minimal_row(), "RequestNumber": 123}])
    with pytest.raises(NiftyTriError, match="request number"):
        normalize_tri_rows([{**_minimal_row(), "RequestNumber": " "}])
    with pytest.raises(NiftyTriError, match="TRI"):
        normalize_tri_rows([{**_minimal_row(), "NTR_Value": "1,2,3"}])


def test_normalizer_accepts_official_fields_and_sorts_dates():
    payload = [
        _official_row("02 Jan 2019", "10,100.50"),
        _official_row("01 Jan 2019", "10000"),
    ]

    assert normalize_tri_rows(payload) == [
        {"session_date": "2019-01-01", "tri": 10000.0},
        {"session_date": "2019-01-02", "tri": 10100.5},
    ]


def test_normalizer_rejects_schema_drift_and_mismatched_index_identity():
    with pytest.raises(NiftyTriError, match="schema"):
        normalize_tri_rows([{
            **_official_row("01 Jan 2024", "100"), "Unexpected": 1,
        }])

    with pytest.raises(NiftyTriError, match="schema"):
        normalize_tri_rows([{
            "Date": "01 Jan 2024", "TotalReturnsIndex": "100",
            "NTR_Value": "99.00", "RequestNumber": "TRI-test",
        }])

    with pytest.raises(NiftyTriError, match="index identity"):
        normalize_tri_rows([_official_row("01 Jan 2024", "100", index="NIFTY 500")])


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "1,2,3", "10,00", " 100", 100, None])
def test_normalizer_rejects_nonpositive_or_nonfinite_values(value):
    with pytest.raises(NiftyTriError, match="TRI"):
        normalize_tri_rows([{
            **_official_row("01 Jan 2024", value),
        }])


@pytest.mark.parametrize("date_text", ["1 Jan 2024", "01 January 2024", "01 Jan 2024 "])
def test_normalizer_rejects_noncanonical_dates(date_text):
    with pytest.raises(NiftyTriError, match="date"):
        normalize_tri_rows([_official_row(date_text, "100")])


def test_normalizer_rejects_duplicate_dates():
    with pytest.raises(NiftyTriError, match="duplicate date"):
        normalize_tri_rows([
            _official_row("01 Jan 2024", "100"),
            _official_row("01 Jan 2024", "100"),
        ])


@pytest.mark.parametrize("payload", [
    {"d": "[{\"Date\": \"01 Jan 2024\"}]", "extra": 1},
    {"rows": [_official_row("01 Jan 2024", "100")]},
    {"d": {"Date": "01 Jan 2024"}},
    {"d": "{\"Date\": \"01 Jan 2024\"}"},
])
def test_normalizer_rejects_unrecognized_envelopes(payload):
    with pytest.raises(NiftyTriError, match="envelope"):
        normalize_tri_rows(payload)


@pytest.mark.parametrize("payload", [
    {"d": "[{\"Date\": \"01 Jan 2024\", \"Index Name\": \"Nifty 50\", "
            "\"TotalReturnsIndex\": \"100\", \"NTR_Value\": \"99.00\", "
            "\"RequestNumber\": \"TRI-test\"}]"},
    {"d": [_official_row("01 Jan 2024", "100")]},
])
def test_normalizer_accepts_official_aspnet_envelopes(payload):
    assert normalize_tri_rows(payload) == [
        {"session_date": "2024-01-01", "tri": 100.0},
    ]


def test_session_coverage_validator_is_deterministic_and_fail_closed():
    rows = normalize_tri_rows([
        _official_row("02 Jan 2024", "101"),
        _official_row("01 Jan 2024", "100"),
    ])
    validate_tri_session_coverage(rows, [date(2024, 1, 1), date(2024, 1, 2)])

    with pytest.raises(NiftyTriError, match="missing required sessions"):
        validate_tri_session_coverage(rows, [date(2024, 1, 1), date(2024, 1, 3)])


def test_tri_windows_are_inclusive_and_limited_to_one_year():
    windows = build_tri_windows(date(2024, 1, 1), date(2025, 6, 30))

    assert windows == [
        TriWindow(date(2024, 1, 1), date(2024, 12, 31)),
        TriWindow(date(2025, 1, 1), date(2025, 6, 30)),
    ]
    assert all((window.end - window.start).days <= 365 for window in windows)


def test_tri_window_rejects_invalid_or_overlong_ranges():
    with pytest.raises(ValueError, match="on or after"):
        TriWindow(date(2024, 1, 2), date(2024, 1, 1))
    with pytest.raises(ValueError, match="one year"):
        TriWindow(date(2024, 1, 1), date(2025, 1, 2))


def test_merge_accepts_equal_overlap_and_sorts_rows():
    assert merge_tri_windows([
        [{"session_date": "2024-01-02", "tri": 102.0}],
        [
            {"session_date": "2024-01-02", "tri": 102.0},
            {"session_date": "2024-01-03", "tri": 103.0},
        ],
    ]) == [
        {"session_date": "2024-01-02", "tri": 102.0},
        {"session_date": "2024-01-03", "tri": 103.0},
    ]


def test_merge_rejects_changed_overlap():
    with pytest.raises(NiftyTriError, match="overlap"):
        merge_tri_windows([
            [{"session_date": "2019-01-02", "tri": 101.0}],
            [{"session_date": "2019-01-02", "tri": 102.0}],
        ])


def test_merged_retained_manifest_binds_every_catalogued_window(tmp_path):
    start = date(2024, 1, 1)
    end = date(2025, 1, 2)
    windows = build_tri_windows(start, end)
    acquirer = NiftyTriAcquirer(tmp_path, client=FakeClient([]), retries=1)
    component_paths = [
        _retain_window(acquirer, window, value=100 + position)
        for position, window in enumerate(windows)
    ]

    merged_path = acquirer.merge_retained(start, end)
    merged = acquirer.load_merged(merged_path, start=start, end=end)

    assert merged_path == acquirer.merged_path(start, end)
    assert (tmp_path / "retained") in merged_path.parents
    assert merged_path.read_bytes() == canonical_json_bytes(
        json.loads(merged_path.read_text())
    )
    assert merged["window"] == {
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    assert [item["path"] for item in merged["components"]] == [
        str(path.resolve()) for path in component_paths
    ]
    assert [row["session_date"] for row in merged["normalized_rows"]] == [
        window.start.isoformat() for window in windows
    ]
    catalogue = [
        json.loads(line)
        for line in acquirer.catalogue.read_text().splitlines()
    ]
    assert catalogue[-1]["domain"] == "tri"
    assert catalogue[-1]["path"] == str(merged_path.resolve())
    assert catalogue[-1]["sha256"] == hashlib.sha256(
        merged_path.read_bytes()
    ).hexdigest()


def test_merged_manifest_rejects_component_mutation(tmp_path):
    start = end = date(2024, 1, 1)
    acquirer = NiftyTriAcquirer(tmp_path, client=FakeClient([]), retries=1)
    component = _retain_window(
        acquirer, TriWindow(start, end), value=100
    )
    merged_path = acquirer.merge_retained(start, end)
    component.write_bytes(component.read_bytes() + b" ")

    with pytest.raises(NiftyTriError, match="component"):
        acquirer.load_merged(merged_path, start=start, end=end)


def test_acquirer_posts_exact_body_and_retains_hash_bound_envelope(tmp_path):
    response_payload = _payload(
        _official_row("02 Jan 2024", "10,100.50"),
        _official_row("01 Jan 2024", "10000"),
    )
    raw_body = b' [ {"official": "bytes", "Date": "02 Jan 2024"} ] '
    client = FakeClient([FakeResponse(
        response_payload, content_type="text/html", raw_body=(
            json.dumps(response_payload, separators=(",", ":")).encode()
        ),
    )])
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 2))

    result = NiftyTriAcquirer(tmp_path, client=client, retries=1).acquire(window)

    expected_body = {
        "cinfo": "{'name':'NIFTY 50','startDate':'01-Jan-2024',"
        "'endDate':'02-Jan-2024','indexName':'NIFTY 50'}"
    }
    assert client.calls == [(
        NIFTY_TRI_URL,
        {
            "json": expected_body,
            "headers": {"Content-Type": "application/json; charset=utf-8"},
            "timeout": (10.0, 60.0),
        },
    )]
    assert result["status"] == "downloaded"
    assert result["url"] == NIFTY_TRI_URL
    assert result["request"] == expected_body
    assert result["response"] == response_payload
    assert result["status_code"] == 200
    assert result["content_type"] == "text/html"
    assert result["normalized_rows"] == [
        {"session_date": "2024-01-01", "tri": 10000.0},
        {"session_date": "2024-01-02", "tri": 10100.5},
    ]
    assert result["retrieved_at"].endswith("Z")
    assert result["raw_sha256"] == hashlib.sha256(result["raw_path"].read_bytes()).hexdigest()
    assert result["raw_path"].read_bytes() == json.dumps(
        response_payload, separators=(",", ":")
    ).encode()
    assert len(result["normalized_sha256"]) == 64
    assert result["path"].read_bytes() == (
        json.dumps(_artifact_payload(result), indent=2, sort_keys=True) + "\n"
    ).encode()

    catalogue = [json.loads(line) for line in (tmp_path / "source-catalogue.jsonl").read_text().splitlines()]
    assert catalogue[-1]["status"] == "downloaded"
    assert catalogue[-1]["available_at"] == result["retrieved_at"]
    assert catalogue[-1]["raw_sha256"] == result["raw_sha256"]
    assert catalogue[-1]["normalized_sha256"] == result["normalized_sha256"]


def test_acquirer_retains_aspnet_wrapper_and_exact_raw_body(tmp_path):
    rows = _payload(_official_row("01 Jan 2024", "100"))
    wrapper = {"d": json.dumps(rows, separators=(",", ":"))}
    raw_body = json.dumps(wrapper, separators=(",", ":")).encode()
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))

    result = NiftyTriAcquirer(
        tmp_path,
        client=FakeClient([FakeResponse(
            wrapper, content_type="text/html; charset=utf-8", raw_body=raw_body
        )]),
        retries=1,
    ).acquire(window)

    assert result["response"] == wrapper
    assert result["raw_path"].read_bytes() == raw_body
    assert result["raw_sha256"] == hashlib.sha256(raw_body).hexdigest()


def test_acquirer_parses_exact_content_bytes_not_divergent_json_view(tmp_path):
    raw_payload = [_minimal_row(value="100")]
    divergent_json_view = [_minimal_row(value="999")]
    raw_body = json.dumps(raw_payload, separators=(",", ":")).encode()
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))

    result = NiftyTriAcquirer(
        tmp_path,
        client=FakeClient([FakeResponse(
            divergent_json_view, raw_body=raw_body
        )]),
        retries=1,
    ).acquire(window)

    assert result["response"] == raw_payload
    assert result["normalized_rows"] == [{"session_date": "2024-01-01", "tri": 100.0}]


def test_cache_rejects_raw_envelope_mismatch_even_when_sidecar_hash_is_updated(tmp_path):
    payload = _minimal_row()
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))
    result = NiftyTriAcquirer(
        tmp_path, client=FakeClient([FakeResponse([payload])]), retries=1
    ).acquire(window)

    mismatched_raw = json.dumps([_minimal_row(value="101")], separators=(",", ":")).encode()
    result["raw_path"].write_bytes(mismatched_raw)
    result["raw_bytes"] = len(mismatched_raw)
    result["raw_sha256"] = hashlib.sha256(mismatched_raw).hexdigest()
    _write_canonical_artifact(result)

    with pytest.raises(NiftyTriError, match="envelope"):
        NiftyTriAcquirer(tmp_path, client=FakeClient([]), retries=1).acquire(window)


def test_cache_missing_raw_sidecar_raises_nifty_tri_error(tmp_path):
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))
    result = NiftyTriAcquirer(
        tmp_path, client=FakeClient([FakeResponse([_minimal_row()])]), retries=1
    ).acquire(window)
    result["raw_path"].unlink()

    with pytest.raises(NiftyTriError, match="cache"):
        NiftyTriAcquirer(tmp_path, client=FakeClient([]), retries=1).acquire(window)


def test_acquirer_rejects_rows_outside_requested_window(tmp_path):
    payload = _payload(_official_row("03 Jan 2024", "100"))
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 2))

    with pytest.raises(NiftyTriError, match="outside requested window"):
        NiftyTriAcquirer(tmp_path, client=FakeClient([FakeResponse(payload)]), retries=1).acquire(window)


def test_acquirer_reuses_canonical_cache_without_network(tmp_path):
    payload = _payload(_official_row("01 Jan 2024", "100"))
    client = FakeClient([FakeResponse(payload)])
    acquirer = NiftyTriAcquirer(tmp_path, client=client, retries=1)
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))

    first = acquirer.acquire(window)
    second = acquirer.acquire(window)

    assert first["status"] == "downloaded"
    assert second["status"] == "cached"
    assert second["retrieved_at"] == first["retrieved_at"]
    assert len(client.calls) == 1
    assert len((tmp_path / "source-catalogue.jsonl").read_text().splitlines()) == 2


def test_acquirer_rejects_noncanonical_or_tampered_cache(tmp_path):
    payload = _payload(_official_row("01 Jan 2024", "100"))
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))
    acquirer = NiftyTriAcquirer(tmp_path, client=FakeClient([FakeResponse(payload)]), retries=1)
    first = acquirer.acquire(window)

    first["normalized_rows"][0]["tri"] = 101.0
    retained = {
        key: value for key, value in first.items()
        if key not in {"status", "path", "raw_path"}
    }
    first["path"].write_text(json.dumps(retained, indent=2, sort_keys=True) + "\n")
    with pytest.raises(NiftyTriError, match="cache"):
        NiftyTriAcquirer(tmp_path, client=FakeClient([]), retries=1).acquire(window)


@pytest.mark.parametrize("response", [
    FakeResponse(_payload(_official_row("01 Jan 2024", "100")), content_type="text/plain"),
    FakeResponse(_payload(_official_row("01 Jan 2024", "100")), status_code=503),
    FakeResponse(None, content_type="application/json", text="<html>blocked</html>"),
])
def test_acquirer_rejects_invalid_content_and_leaves_no_partial_cache(tmp_path, response):
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))
    with pytest.raises(NiftyTriError):
        NiftyTriAcquirer(tmp_path, client=FakeClient([response]), retries=1).acquire(window)

    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("*.part"))
    records = [json.loads(line) for line in (tmp_path / "source-catalogue.jsonl").read_text().splitlines()]
    assert records[-1]["status"] == "failed"


def test_acquirer_rejects_provider_schema_errors_without_network(tmp_path):
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))
    client = FakeClient([FakeResponse([_official_row("01 Jan 2024", "0")])])

    with pytest.raises(NiftyTriError, match="TRI"):
        NiftyTriAcquirer(tmp_path, client=client, retries=1).acquire(window)

    assert len(client.calls) == 1


def test_acquirer_retries_transport_failure_with_backoff_then_succeeds(tmp_path):
    payload = _payload(_official_row("01 Jan 2024", "100"))
    client = FakeClient([OSError("timeout"), FakeResponse(payload)])
    sleeps = []
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))

    result = NiftyTriAcquirer(
        tmp_path, client=client, retries=2, sleep=sleeps.append
    ).acquire(window)

    assert result["status"] == "downloaded"
    assert len(client.calls) == 2
    assert sleeps == [1]


def test_acquirer_has_explicit_unexpected_network_guard(monkeypatch, tmp_path):
    def unexpected_network(*args, **kwargs):
        raise AssertionError("unexpected network")

    monkeypatch.setattr(requests.Session, "post", unexpected_network)
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))

    with pytest.raises(NiftyTriError, match="unexpected network"):
        NiftyTriAcquirer(tmp_path, retries=1).acquire(window)


def test_acquirer_cleans_partial_files_when_atomic_replace_fails(monkeypatch, tmp_path):
    payload = _payload(_official_row("01 Jan 2024", "100"))
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr("src.reliability.nifty_tri.os.replace", fail_replace)
    with pytest.raises(NiftyTriError, match="replace failed"):
        NiftyTriAcquirer(
            tmp_path, client=FakeClient([FakeResponse(payload)]), retries=1
        ).acquire(window)

    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("*.raw"))
    assert not list(tmp_path.rglob("*.part"))
    assert json.loads((tmp_path / "source-catalogue.jsonl").read_text().splitlines()[-1])["status"] == "failed"


def test_acquirer_preserves_retention_when_catalogue_append_fails(tmp_path):
    payload = _payload(_official_row("01 Jan 2024", "100"))
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))
    acquirer = NiftyTriAcquirer(
        tmp_path, client=FakeClient([FakeResponse(payload)]), retries=1
    )
    acquirer._append = lambda record: (_ for _ in ()).throw(OSError("catalogue failed"))

    with pytest.raises(NiftyTriError, match="catalogue"):
        acquirer.acquire(window)

    assert list(tmp_path.rglob("*.json"))
    assert list(tmp_path.rglob("*.raw"))


def test_acquirer_fsyncs_containing_directory_after_each_rename(monkeypatch, tmp_path):
    payload = _payload(_official_row("01 Jan 2024", "100"))
    window = TriWindow(date(2024, 1, 1), date(2024, 1, 1))
    directories = []
    monkeypatch.setattr(
        "src.reliability.nifty_tri._fsync_directory",
        lambda directory: directories.append(directory),
    )

    result = NiftyTriAcquirer(
        tmp_path, client=FakeClient([FakeResponse(payload)]), retries=1
    ).acquire(window)

    assert directories == [result["path"].parent, result["path"].parent]
