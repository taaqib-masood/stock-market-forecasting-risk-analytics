from datetime import datetime, timezone

from scripts import deliver_telegram_outbox as worker
from src.reliability.outbox import DeliveryOutbox
from src.reliability.store import ReliabilityStore


def test_worker_does_not_touch_queue_when_release_is_blocked(tmp_path, monkeypatch):
    database = tmp_path / "blocked.db"
    monkeypatch.delenv("BORO_OPERATIONAL_KILL_SWITCH", raising=False)
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "research")

    report = worker.deliver_outbox(database=str(database))

    assert report["ok"] is False
    assert report["blocked"] is True
    with ReliabilityStore(database) as store:
        outbox = DeliveryOutbox(store.connection)
        assert outbox.metrics()["total"] == 0


def test_worker_delivers_due_messages_and_reports_health(tmp_path, monkeypatch):
    database = tmp_path / "delivery.db"
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret-value")
    monkeypatch.setattr(worker, "operational_kill_switch_active", lambda: False)
    monkeypatch.setattr(worker, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setattr(
        worker,
        "send_outbox_payload",
        lambda payload: {"message_id": "telegram-1"},
    )
    point = datetime(2026, 8, 9, tzinfo=timezone.utc)
    with ReliabilityStore(database) as store:
        outbox = DeliveryOutbox(store.connection)
        outbox.enqueue("signal:chat", "signal", "{}", now=point)

    report = worker.deliver_outbox(database=str(database), now=point)

    assert report["ok"] is True
    assert report["delivered"] == 1
    assert report["failed"] == 0
    assert report["health"]["delivered"] == 1


def test_worker_rejects_unsafe_batch_limit(tmp_path):
    try:
        worker.deliver_outbox(database=str(tmp_path / "invalid.db"), limit=1001)
    except ValueError as error:
        assert "between 1 and 1000" in str(error)
    else:
        raise AssertionError("unsafe batch limit was accepted")
