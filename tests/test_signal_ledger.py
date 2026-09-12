import json

import pytest

from src.reliability.ledger import SignalLedger
from src.reliability.store import ReliabilityStore


def _payload():
    return {
        "ticker": "RELIANCE",
        "strategy_version": "rule-v1.2.0",
        "data_manifest_hash": "a" * 64,
        "decision": "BUY",
        "rationale": {"regime": "BULL", "score": 71},
    }


def test_ledger_retains_versions_and_verifies_chain(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    ledger = SignalLedger(store.connection)

    ledger.append("SIGNAL_CREATED", "sig-001", _payload(), created_at="2024-07-01T04:00:00Z")
    ledger.append(
        "DELIVERY_ACKNOWLEDGED", "sig-001", {"provider_message_id": "42"},
        created_at="2024-07-01T04:00:02Z",
    )

    events = ledger.events("sig-001")
    assert events[0]["payload"]["strategy_version"] == "rule-v1.2.0"
    assert events[0]["payload"]["data_manifest_hash"] == "a" * 64
    assert ledger.verify_chain() == {"valid": True, "events": 2, "broken_at": None}


def test_payload_tampering_breaks_verification(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    ledger = SignalLedger(store.connection)
    ledger.append("SIGNAL_CREATED", "sig-001", _payload(), created_at="2024-07-01T04:00:00Z")

    with pytest.raises(Exception, match="append-only"):
        store.connection.execute(
            "UPDATE signal_events SET payload_json = ? WHERE signal_id = ?",
            (json.dumps({"decision": "SELL"}), "sig-001"),
        )

    assert ledger.verify_chain()["valid"] is True


def test_ledger_events_cannot_be_deleted(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    ledger = SignalLedger(store.connection)
    ledger.append("SIGNAL_CREATED", "sig-001", _payload(), created_at="2024-07-01T04:00:00Z")

    with pytest.raises(Exception, match="append-only"):
        store.connection.execute("DELETE FROM signal_events WHERE signal_id = 'sig-001'")


def test_same_signal_event_cannot_be_appended_twice(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    ledger = SignalLedger(store.connection)
    ledger.append("SIGNAL_CREATED", "sig-001", _payload(), created_at="2024-07-01T04:00:00Z")

    with pytest.raises(ValueError, match="already exists"):
        ledger.append("SIGNAL_CREATED", "sig-001", _payload(), created_at="2024-07-01T04:00:01Z")


def test_same_signal_accepts_distinct_lifecycle_events(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    ledger = SignalLedger(store.connection)

    ledger.append("SIGNAL_CREATED", "sig-001", _payload(), created_at="2024-07-01T04:00:00Z")
    ledger.append("SIGNAL_REJECTED", "sig-001", {"reason": "portfolio_limit"},
                  created_at="2024-07-01T04:00:01Z")

    assert [event["event_type"] for event in ledger.events("sig-001")] == [
        "SIGNAL_CREATED", "SIGNAL_REJECTED"
    ]
