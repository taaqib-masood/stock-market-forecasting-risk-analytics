from datetime import datetime, timezone

from src.reliability.controls import ControlDecision
from src.reliability.ledger import SignalLedger
from src.reliability.outbox import DeliveryOutbox
from src.reliability.shadow import ShadowCoordinator
from src.reliability.store import ReliabilityStore


NOW = datetime(2024, 7, 1, 4, 0, tzinfo=timezone.utc)


def _coordinator(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    ledger = SignalLedger(store.connection)
    outbox = DeliveryOutbox(store.connection)
    return ShadowCoordinator(ledger, outbox), ledger, outbox


def _snapshot():
    return {
        "ticker": "RELIANCE",
        "decision_session": "2024-07-01",
        "strategy_version": "rule-v2.0.0",
        "data_manifest_hash": "a" * 64,
        "entry": 3000.0,
        "stop": 2940.0,
        "target": 3120.0,
        "rationale": {"regime": "BULL", "score": 71},
    }


def test_shadow_flow_persists_before_enqueue_and_suppresses_duplicate_run(tmp_path):
    coordinator, ledger, outbox = _coordinator(tmp_path)
    allowed = ControlDecision(allowed=True, hard_failures=())

    first = coordinator.record_signal(_snapshot(), "BUY RELIANCE", allowed, now=NOW)
    second = coordinator.record_signal(_snapshot(), "BUY RELIANCE", allowed, now=NOW)

    assert first["created"] is True
    assert second["created"] is False
    assert [event["event_type"] for event in ledger.events(first["signal_id"])] == [
        "SIGNAL_CREATED"
    ]
    assert outbox.metrics()["total"] == 1


def test_shadow_delivery_acknowledgement_is_appended_to_ledger(tmp_path):
    coordinator, ledger, _outbox = _coordinator(tmp_path)
    result = coordinator.record_signal(
        _snapshot(), "BUY RELIANCE", ControlDecision(True, ()), now=NOW
    )

    delivery = coordinator.deliver_due(lambda _text: {"message_id": "telegram-42"}, now=NOW)

    assert delivery["delivered"] == 1
    assert [event["event_type"] for event in ledger.events(result["signal_id"])] == [
        "SIGNAL_CREATED", "DELIVERY_ACKNOWLEDGED"
    ]


def test_failed_controls_are_ledgered_but_not_enqueued(tmp_path):
    coordinator, ledger, outbox = _coordinator(tmp_path)
    blocked = ControlDecision(False, ("HALAL_UNKNOWN", "STALE_DATA"))

    result = coordinator.record_signal(_snapshot(), "BUY RELIANCE", blocked, now=NOW)

    assert result["queued"] is False
    assert [event["event_type"] for event in ledger.events(result["signal_id"])] == [
        "SIGNAL_REJECTED"
    ]
    assert outbox.metrics()["total"] == 0


def test_snapshot_requires_strategy_and_data_versions(tmp_path):
    coordinator, _ledger, _outbox = _coordinator(tmp_path)
    snapshot = _snapshot()
    snapshot.pop("data_manifest_hash")

    try:
        coordinator.record_signal(snapshot, "BUY RELIANCE", ControlDecision(True, ()), now=NOW)
    except ValueError as exc:
        assert "data_manifest_hash" in str(exc)
    else:
        raise AssertionError("missing data version should block shadow recording")
