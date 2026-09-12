from datetime import datetime, timezone

from src.reliability.store import ReliabilityStore


AS_OF = datetime(2024, 6, 30, 23, 59, tzinfo=timezone.utc)


def test_future_membership_and_classification_are_invisible(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    manifest = store.register_manifest(
        "nse-security-file", b"frozen-source", available_at="2024-07-01T08:00:00Z"
    )
    store.put_membership(
        "RELIANCE", valid_from="2024-01-01", available_at="2024-07-01T08:00:00Z",
        manifest_hash=manifest,
    )
    store.put_halal_classification(
        "RELIANCE", effective_from="2024-01-01", available_at="2024-07-01T08:00:00Z",
        tier="GREEN", tradeable=True, ruleset_version="aaoifi-v1", manifest_hash=manifest,
    )

    assert store.eligible_universe(AS_OF) == []
    assert store.halal_as_of("RELIANCE", AS_OF)["tradeable"] is False


def test_unknown_halal_status_fails_closed(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")

    result = store.halal_as_of("MISSING", AS_OF)

    assert result == {
        "symbol": "MISSING",
        "tier": "UNKNOWN",
        "tradeable": False,
        "reason": "no point-in-time halal classification",
    }


def test_duplicate_imports_are_idempotent(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    manifest = store.register_manifest(
        "nse-bhavcopy", b"same-bytes", available_at="2024-06-30T18:00:00Z"
    )

    for _ in range(2):
        store.put_bar(
            "INFY", session_date="2024-06-28", open_=1500, high=1520, low=1490,
            close=1510, volume=1_000_000, available_at="2024-06-28T18:00:00Z",
            manifest_hash=manifest,
        )

    count = store.connection.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
    assert count == 1


def test_manifest_uses_sha256_and_retains_metadata(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")

    digest = store.register_manifest(
        "nse-corporate-actions", b"payload", available_at="2024-06-30T18:00:00Z",
        metadata={"url": "https://www.nseindia.com/all-reports"},
    )
    row = store.manifest(digest)

    assert len(digest) == 64
    assert row["source"] == "nse-corporate-actions"
    assert row["metadata"]["url"].startswith("https://www.nseindia.com")


def test_stale_halal_status_fails_closed(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    manifest = store.register_manifest(
        "fundamentals", b"q1", available_at="2024-01-15T00:00:00Z"
    )
    store.put_halal_classification(
        "TCS", effective_from="2024-01-01", available_at="2024-01-15T00:00:00Z",
        tier="GREEN", tradeable=True, ruleset_version="aaoifi-v1", manifest_hash=manifest,
    )

    result = store.halal_as_of("TCS", AS_OF, max_age_days=90)

    assert result["tradeable"] is False
    assert result["reason"] == "halal classification is stale"


def test_latest_membership_correction_closes_previously_open_interval(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    first = store.register_manifest("security-file", b"first", "2024-01-02T00:00:00Z")
    correction = store.register_manifest("security-file", b"correction", "2024-07-02T00:00:00Z")
    store.put_membership("DELISTED", "2024-01-01", "2024-01-02T00:00:00Z", first)
    store.put_membership(
        "DELISTED", "2024-01-01", "2024-07-02T00:00:00Z", correction,
        valid_to="2024-06-30",
    )

    assert store.eligible_universe("2024-07-01T00:00:00Z") == ["DELISTED"]
    assert store.eligible_universe("2024-07-03T00:00:00Z") == []


def test_business_classification_is_point_in_time_and_future_safe(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    manifest = store.register_manifest("business-review", b"v1", "2024-07-01T08:00:00Z")
    store.put_business_classification(
        "IBULHSGFIN",
        business_type="CONVENTIONAL_NBFC",
        effective_from="2024-01-01",
        available_at="2024-07-01T08:00:00Z",
        methodology_version="business-v1",
        manifest_hash=manifest,
        reason="housing finance lender",
    )

    assert store.business_as_of("IBULHSGFIN", AS_OF)["business_type"] == "UNKNOWN"
    result = store.business_as_of("IBULHSGFIN", "2024-07-02T00:00:00Z")
    assert result["business_type"] == "CONVENTIONAL_NBFC"
    assert result["methodology_version"] == "business-v1"


def test_missing_business_classification_fails_closed(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")

    assert store.business_as_of("MISSING", AS_OF) == {
        "symbol": "MISSING",
        "business_type": "UNKNOWN",
        "reason": "no point-in-time business classification",
    }


def test_tradable_universe_comes_from_that_sessions_retained_bars(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    manifest = store.register_manifest("bhavcopy", b"day", "2020-03-20T18:00:00Z")
    store.put_bar("OLDCO", "2020-03-20", 10, 11, 9, 10.5, 1000,
                  "2020-03-20T18:00:00Z", manifest)
    store.put_bar("STILLCO", "2020-03-20", 20, 21, 19, 20.5, 2000,
                  "2020-03-20T18:00:00Z", manifest)
    later = store.register_manifest("bhavcopy", b"later", "2024-07-05T18:00:00Z")
    store.put_bar("STILLCO", "2024-07-05", 30, 31, 29, 30.5, 3000,
                  "2024-07-05T18:00:00Z", later)

    assert store.tradable_universe("2020-03-20", "2020-03-20T23:59:59Z") == [
        "OLDCO", "STILLCO"
    ]
    assert store.tradable_universe("2024-07-05", "2024-07-05T23:59:59Z") == ["STILLCO"]


def test_bulk_bar_insert_is_idempotent(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    manifest = store.register_manifest("bhavcopy", b"bulk", "2020-01-02T18:00:00Z")
    rows = [{"symbol": "TCS", "session_date": "2020-01-02", "open": 1,
             "high": 2, "low": 0.5, "close": 1.5, "volume": 100,
             "available_at": "2020-01-02T18:00:00Z"}]

    store.put_bars(rows, manifest)
    store.put_bars(rows, manifest)

    assert store.connection.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 1
