import json
from datetime import datetime, timezone

from src.reliability.importers import import_bhavcopy_history, import_bundle
from src.reliability.store import ReliabilityStore


def _bundle():
    return {
        "source": "nse-normalized-test",
        "available_at": "2024-07-01T18:00:00Z",
        "memberships": [
            {"symbol": "RELIANCE", "valid_from": "2024-01-01"},
            {"symbol": "DELISTED", "valid_from": "2020-01-01", "valid_to": "2023-01-01"},
        ],
        "bars": [
            {"symbol": "RELIANCE", "session_date": "2024-06-28", "open": 3000,
             "high": 3030, "low": 2980, "close": 3020, "volume": 1000000},
        ],
        "corporate_actions": [
            {"symbol": "RELIANCE", "action_type": "DIVIDEND", "ex_date": "2024-06-20",
             "payload": {"amount": 10}},
        ],
        "business_classifications": [
            {"symbol": "RELIANCE", "business_type": "NON_FINANCIAL",
             "effective_from": "2024-01-01", "methodology_version": "business-v1",
             "reason": "primary activity is energy and materials"},
        ],
        "fundamentals": [
            {"symbol": "RELIANCE", "period_end": "2024-03-31", "debt_to_assets": 0.20,
             "interest_income_ratio": 0.02, "effective_from": "2024-07-01"},
            {"symbol": "UNKNOWN", "period_end": "2024-03-31", "debt_to_assets": None,
             "interest_income_ratio": None, "effective_from": "2024-07-01"},
        ],
    }


def test_bundle_imports_every_point_in_time_record_type(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(_bundle()))
    store = ReliabilityStore(tmp_path / "reliability.db")

    result = import_bundle(store, path, ruleset_version="aaoifi-v1")

    assert result["counts"] == {
        "memberships": 2, "bars": 1, "corporate_actions": 1,
        "business_classifications": 1, "fundamentals": 2, "halal_classifications": 2,
    }
    assert len(result["manifest_hash"]) == 64


def test_imported_records_are_visible_only_after_bundle_availability(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(_bundle()))
    store = ReliabilityStore(tmp_path / "reliability.db")
    import_bundle(store, path)

    before = datetime(2024, 7, 1, 17, 59, tzinfo=timezone.utc)
    after = datetime(2024, 7, 1, 18, 1, tzinfo=timezone.utc)

    assert store.eligible_universe(before) == []
    assert store.eligible_universe(after) == ["RELIANCE"]
    assert store.halal_as_of("RELIANCE", before)["tradeable"] is False
    assert store.halal_as_of("RELIANCE", after)["tier"] == "GREEN"


def test_missing_fundamentals_create_fail_closed_unknown_classification(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(_bundle()))
    store = ReliabilityStore(tmp_path / "reliability.db")
    import_bundle(store, path)

    result = store.halal_as_of("UNKNOWN", "2024-07-02T00:00:00Z")

    assert result["tier"] == "UNKNOWN"
    assert result["tradeable"] is False


def test_reimporting_same_bundle_is_idempotent(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(_bundle()))
    store = ReliabilityStore(tmp_path / "reliability.db")

    import_bundle(store, path)
    import_bundle(store, path)

    assert store.connection.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 1
    assert store.connection.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0] == 2


def test_complete_ratios_without_business_type_remain_unknown(tmp_path):
    bundle = _bundle()
    bundle["business_classifications"] = []
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle))
    store = ReliabilityStore(tmp_path / "reliability.db")

    import_bundle(store, path)
    result = store.halal_as_of("RELIANCE", "2024-07-02T00:00:00Z")

    assert result["tier"] == "UNKNOWN"
    assert result["tradeable"] is False
    assert "business classification" in result["reason"]


def test_conventional_nbfc_is_excluded_before_ratio_screen(tmp_path):
    bundle = _bundle()
    bundle["business_classifications"][0]["business_type"] = "CONVENTIONAL_NBFC"
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle))
    store = ReliabilityStore(tmp_path / "reliability.db")

    import_bundle(store, path)
    result = store.halal_as_of("RELIANCE", "2024-07-02T00:00:00Z")

    assert result["tier"] == "RED"
    assert result["tradeable"] is False
    assert "riba-based primary business" in result["reason"]


def test_historical_bhavcopy_import_uses_session_availability_and_is_idempotent(tmp_path):
    path = tmp_path / "cm02JAN2020bhav.csv"
    path.write_text(
        "SYMBOL,SERIES,TIMESTAMP,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY\n"
        "OLDCO,EQ,02-JAN-2020,10,11,9,10.5,1000\n"
    )
    store = ReliabilityStore(tmp_path / "history.db")

    first = import_bhavcopy_history(store, [path])
    second = import_bhavcopy_history(store, [path])

    assert first == {"files": 1, "bars": 1, "first_session": "2020-01-02",
                     "last_session": "2020-01-02"}
    assert second == first
    assert store.tradable_universe("2020-01-02", "2020-01-02T17:59:59Z") == []
    assert store.tradable_universe("2020-01-02", "2020-01-02T18:00:00Z") == ["OLDCO"]
