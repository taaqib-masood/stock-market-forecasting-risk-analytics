from datetime import datetime, timedelta, timezone

from src.reliability.outbox import DeliveryOutbox
from src.reliability.store import ReliabilityStore


NOW = datetime(2024, 7, 1, 4, 0, tzinfo=timezone.utc)


def test_enqueue_is_idempotent(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    outbox = DeliveryOutbox(store.connection)

    first = outbox.enqueue("daily:2024-07-01:RELIANCE", "sig-1", "BUY RELIANCE", now=NOW)
    second = outbox.enqueue("daily:2024-07-01:RELIANCE", "sig-1", "BUY RELIANCE", now=NOW)

    assert first["message_id"] == second["message_id"]
    assert first["created"] is True
    assert second["created"] is False
    assert outbox.metrics()["total"] == 1


def test_failed_delivery_retries_with_exponential_backoff(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    outbox = DeliveryOutbox(store.connection, max_attempts=3, base_delay_seconds=60)
    outbox.enqueue("key-1", "sig-1", "payload", now=NOW)
    calls = {"count": 0}

    def sender(_text):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary outage")
        return {"message_id": "telegram-42"}

    first = outbox.deliver_due(sender, now=NOW)
    assert first == {"delivered": 0, "failed": 1, "dead_letter": 0}
    assert outbox.claim_due(NOW + timedelta(seconds=59)) == []

    second = outbox.deliver_due(sender, now=NOW + timedelta(seconds=60))
    assert second == {"delivered": 1, "failed": 0, "dead_letter": 0}
    assert outbox.metrics()["delivered"] == 1


def test_exhausted_delivery_moves_to_dead_letter(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    outbox = DeliveryOutbox(store.connection, max_attempts=2, base_delay_seconds=10)
    outbox.enqueue("key-1", "sig-1", "payload", now=NOW)

    def sender(_text):
        raise RuntimeError("permanent outage")

    outbox.deliver_due(sender, now=NOW)
    result = outbox.deliver_due(sender, now=NOW + timedelta(seconds=10))

    assert result["dead_letter"] == 1
    assert outbox.metrics()["dead_letter"] == 1


def test_metrics_report_acknowledged_delivery_rate(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    outbox = DeliveryOutbox(store.connection, max_attempts=1)
    outbox.enqueue("ok", "sig-1", "one", now=NOW)
    outbox.enqueue("bad", "sig-2", "two", now=NOW)

    outbox.deliver_due(
        lambda text: {"message_id": "1"} if text == "one" else (_ for _ in ()).throw(RuntimeError("x")),
        now=NOW,
    )

    metrics = outbox.metrics()
    assert metrics["delivered"] == 1
    assert metrics["dead_letter"] == 1
    assert metrics["acknowledged_delivery_rate"] == 0.5


def test_post_delivery_reconciliation_failure_never_retries_provider(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.db")
    outbox = DeliveryOutbox(store.connection)
    outbox.enqueue("key-1", "sig-1", "payload", now=NOW)
    sends = {"count": 0}

    def sender(_text):
        sends["count"] += 1
        return {"message_id": "telegram-42"}

    def broken_reconciliation(_message, _ack):
        raise RuntimeError("ledger unavailable")

    result = outbox.deliver_due(sender, now=NOW, on_delivered=broken_reconciliation)
    outbox.deliver_due(sender, now=NOW + timedelta(hours=1))

    assert sends["count"] == 1
    assert result["unreconciled"] == 1
    assert outbox.metrics()["unreconciled"] == 1
