import json

import pytest

from src import notify
from src.reliability.outbox import DeliveryOutbox
from src.reliability.store import ReliabilityStore
from src.reliability.telegram_audience import TelegramAudience
from src.notify import DeliveryError
from datetime import datetime, timezone


def test_direct_trade_card_delivery_is_blocked_without_release_approval(monkeypatch):
    sent = []
    monkeypatch.delenv("BORO_RELIABILITY_MODE", raising=False)
    monkeypatch.setattr(notify, "_send", lambda text: sent.append(text) or True)

    result = notify.send_trade_cards([{
        "ticker": "TCS",
        "signal": "BUY",
        "score": 80,
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "rr": 2.0,
        "shares": 1,
        "invest": 100.0,
        "risk_rs": 5.0,
        "reward_rs": 10.0,
        "rsi": 55,
        "vol_surge": 1.2,
        "ret_5d": 2.0,
    }])

    assert result is False
    assert sent == []


def test_recommendation_delivery_is_blocked_by_operational_kill_switch(monkeypatch):
    monkeypatch.setenv("BORO_OPERATIONAL_KILL_SWITCH", "true")
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")

    assert notify._recommendation_delivery_approved() is False


def test_legacy_trade_card_helper_cannot_bypass_consent_registry(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setattr(notify, "_send", lambda text: sent.append(text) or True)

    result = notify.send_trade_cards([], "09 Aug", signal_id="signal-1")

    assert result is False
    assert sent == []


def test_legacy_direct_send_shim_never_calls_telegram(monkeypatch):
    monkeypatch.setattr(notify, "send_raw", lambda *args, **kwargs: pytest.fail("direct send bypassed outbox"))

    assert notify._send("operator message") is False


def test_transport_rejects_implicit_default_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")

    with pytest.raises(DeliveryError, match="consent-bound path"):
        notify.send_raw("operator message")


def test_generic_audience_message_uses_consent_bound_outbox(tmp_path, monkeypatch):
    database = tmp_path / "generic-message.db"
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience = TelegramAudience(database)
    audience.subscribe("12345", "terms-v1", now=now)
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(database))
    monkeypatch.setenv("BORO_TELEGRAM_AUDIENCE_DB", str(database))
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setattr(notify, "send_raw", lambda *args, **kwargs: {"message_id": "telegram-1"})

    result = notify.queue_audience_message(
        "System notice", "notice-1", now=now, database=str(database)
    )

    assert result["queued"] == 1
    assert result["delivery"]["delivered"] == 1


def test_recommendation_queue_requires_approval_and_has_recipient_idempotency(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.db")
    audience = TelegramAudience(store.connection)
    outbox = DeliveryOutbox(store.connection)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience.subscribe("12345", "terms-v1", now=now)
    audience.subscribe("-99", "terms-v1", now=now)
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)

    first = notify.queue_recommendation_for_audience(
        "BUY TCS", "signal-1", audience, outbox, now=now
    )
    second = notify.queue_recommendation_for_audience(
        "BUY TCS", "signal-1", audience, outbox, now=now
    )

    assert first["queued"] == 2
    payload = store.connection.execute(
        "SELECT payload FROM delivery_outbox ORDER BY message_id LIMIT 1"
    ).fetchone()[0]
    assert json.loads(payload)["consent_version"] == "terms-v1"
    assert second["created"] == 0
    assert outbox.metrics()["total"] == 2


def test_recommendation_queue_blocks_without_release_approval(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.db")
    audience = TelegramAudience(store.connection)
    outbox = DeliveryOutbox(store.connection)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience.subscribe("12345", "terms-v1", now=now)
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: False)

    result = notify.queue_recommendation_for_audience(
        "BUY TCS", "signal-1", audience, outbox, now=now
    )

    assert result["queued"] == 0
    assert result["blockers"] == ["RELEASE_GATE_NOT_APPROVED"]
    assert outbox.metrics()["total"] == 0


def test_recommendation_queue_blocks_before_enqueue_without_bot_token(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.db")
    audience = TelegramAudience(store.connection)
    outbox = DeliveryOutbox(store.connection)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience.subscribe("12345", "terms-v1", now=now)
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)

    result = notify.queue_recommendation_for_audience(
        "BUY TCS", "signal-1", audience, outbox, now=now
    )

    assert result["blockers"] == ["TELEGRAM_CREDENTIALS_MISSING"]
    assert outbox.metrics()["total"] == 0


def test_recommendation_queue_blocks_without_webhook_secret(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.db")
    audience = TelegramAudience(store.connection)
    outbox = DeliveryOutbox(store.connection)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience.subscribe("12345", "terms-v1", now=now)
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)

    result = notify.queue_recommendation_for_audience(
        "BUY TCS", "signal-1", audience, outbox, now=now
    )

    assert result["blockers"] == ["TELEGRAM_WEBHOOK_SECRET_MISSING"]
    assert outbox.metrics()["total"] == 0


def test_recommendation_queue_blocks_invalid_webhook_secret(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "notify-invalid-secret.db")
    audience = TelegramAudience(store.connection)
    outbox = DeliveryOutbox(store.connection)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience.subscribe("12345", "terms-v1", now=now)
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "invalid secret")

    result = notify.queue_recommendation_for_audience(
        "BUY TCS", "signal-invalid-secret", audience, outbox, now=now
    )

    assert result["blockers"] == ["TELEGRAM_WEBHOOK_SECRET_INVALID"]
    assert outbox.metrics()["total"] == 0


def test_recommendation_queue_blocks_when_outbox_has_dead_letter(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.db")
    audience = TelegramAudience(store.connection)
    outbox = DeliveryOutbox(store.connection, max_attempts=2)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience.subscribe("12345", "terms-v1", now=now)
    outbox.enqueue("failed-message", "old-signal", "old payload", now=now)
    outbox.mark_failed(1, "provider unavailable", now=now)
    outbox.mark_failed(1, "provider unavailable", now=now)
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")

    result = notify.queue_recommendation_for_audience(
        "BUY TCS", "signal-1", audience, outbox, now=now
    )

    assert result["blockers"] == ["TELEGRAM_DELIVERY_HEALTH"]


def test_recommendation_queue_requires_current_consent_version(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "delivery.db")
    audience = TelegramAudience(store.connection)
    outbox = DeliveryOutbox(store.connection)
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience.subscribe("12345", "terms-v1", now=now)
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("BORO_TELEGRAM_TERMS_VERSION", "terms-v2")

    result = notify.queue_recommendation_for_audience(
        "BUY TCS", "signal-1", audience, outbox, now=now
    )

    assert result["blockers"] == ["TELEGRAM_CONSENT_VERSION_OUTDATED"]
    assert outbox.metrics()["total"] == 0


def test_outbox_delivery_rechecks_current_consent_before_network(tmp_path, monkeypatch):
    database = tmp_path / "delivery.db"
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience = TelegramAudience(database)
    audience.subscribe("12345", "terms-v1", now=now)
    monkeypatch.setenv("BORO_TELEGRAM_AUDIENCE_DB", str(database))
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setattr(notify, "send_raw", lambda *args, **kwargs: {"message_id": "1"})
    payload = json.dumps({"chat_id": "12345", "text": "BUY TCS",
                          "consent_version": "terms-v1", "consented_at": now.isoformat()})

    audience.revoke("12345", now=now)
    with pytest.raises(DeliveryError, match="consent is no longer active"):
        notify.send_outbox_payload(payload)


def test_outbox_delivery_rejects_stale_consent_version(tmp_path, monkeypatch):
    database = tmp_path / "delivery.db"
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    audience = TelegramAudience(database)
    audience.subscribe("12345", "terms-v1", now=now)
    monkeypatch.setenv("BORO_TELEGRAM_AUDIENCE_DB", str(database))
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("BORO_TELEGRAM_TERMS_VERSION", "terms-v2")
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    payload = json.dumps({"chat_id": "12345", "text": "BUY TCS",
                          "consent_version": "terms-v1", "consented_at": now.isoformat()})

    with pytest.raises(DeliveryError, match="consent version is no longer current"):
        notify.send_outbox_payload(payload)
def test_shadow_acknowledgement_is_deterministic_and_network_free():
    first = notify.acknowledge_shadow_payload("shadow message")
    second = notify.acknowledge_shadow_payload("shadow message")

    assert first == second
    assert first.provider == "shadow"
    assert first.message_id.startswith("shadow:")
