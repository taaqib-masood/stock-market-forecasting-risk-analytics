from datetime import datetime, timezone

from src import control_server
from src.reliability.telegram_audience import TelegramAudience
from src.telegram_webhook import handle_update


NOW = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)


def _update(text, chat_id=12345):
    return {"update_id": 1, "message": {
        "chat": {"id": chat_id}, "text": text,
    }}


def test_start_requires_exact_current_consent_version(tmp_path):
    with TelegramAudience(tmp_path / "audience.db") as audience:
        result = handle_update(_update("/start old-terms"), audience,
                               consent_version="terms-v1", now=NOW)
        assert result["action"] == "CONSENT_REQUIRED"
        assert audience.active_chat_ids() == []


def test_start_subscribes_telegram_supplied_chat_and_stop_revokes(tmp_path):
    with TelegramAudience(tmp_path / "audience.db") as audience:
        subscribed = handle_update(_update("/start terms-v1"), audience,
                                   consent_version="terms-v1", now=NOW)
        assert subscribed["action"] == "SUBSCRIBED"
        assert audience.active_chat_ids() == ["12345"]

        revoked = handle_update(_update("/stop"), audience,
                                consent_version="terms-v1", now=NOW)
        assert revoked["action"] == "REVOKED"
        assert audience.active_chat_ids() == []


def test_help_command_explains_consent_controls_without_subscribing(tmp_path):
    with TelegramAudience(tmp_path / "audience.db") as audience:
        result = handle_update(_update("/help"), audience,
                               consent_version="terms-v1", now=NOW)

        assert result["action"] == "HELP"
        assert "/start terms-v1" in result["reply"]
        assert "/stop" in result["reply"]
        assert audience.active_chat_ids() == []


def test_status_command_reports_only_callers_own_consent_state(tmp_path):
    with TelegramAudience(tmp_path / "audience.db") as audience:
        inactive = handle_update(_update("/status"), audience,
                                 consent_version="terms-v1", now=NOW)
        assert inactive["action"] == "STATUS"
        assert inactive["subscription_status"] == "NOT_SUBSCRIBED"

        audience.subscribe("12345", "terms-v1", now=NOW)
        active = handle_update(_update("/status"), audience,
                               consent_version="terms-v1", now=NOW)
        assert active["subscription_status"] == "ACTIVE"
        assert "12345" not in active["reply"]


def test_group_chat_ids_and_bot_suffix_are_supported(tmp_path):
    with TelegramAudience(tmp_path / "audience.db") as audience:
        result = handle_update(_update("/start@boro_bot terms-v1", chat_id=-10099),
                               audience, consent_version="terms-v1", now=NOW)
        assert result["action"] == "SUBSCRIBED"
        assert audience.active_chat_ids() == ["-10099"]


def test_control_webhook_requires_secret_and_enrolls_without_control_token(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("BORO_TELEGRAM_AUDIENCE_DB", str(tmp_path / "audience.db"))
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)

    status, rejected = control_server._telegram_webhook(
        _update("/start terms-v1"), "wrong-secret"
    )
    assert status == 401
    assert rejected["ok"] is False

    status, accepted = control_server._telegram_webhook(
        _update("/start terms-v1"), "webhook-secret"
    )
    assert status == 200
    assert accepted["action"] == "SUBSCRIBED"
    assert accepted["reply_sent"] is False


def test_control_webhook_sends_non_recommendation_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("BORO_TELEGRAM_AUDIENCE_DB", str(tmp_path / "audience.db"))
    sent = []
    monkeypatch.setattr(
        "src.notify.send_raw",
        lambda text, *, chat_id=None: sent.append((text, chat_id)) or {"message_id": "1"},
    )

    status, result = control_server._telegram_webhook(
        _update("/start terms-v1"), "webhook-secret"
    )
    assert status == 200
    assert result["reply_sent"] is True
    assert sent and sent[0][1] == "12345"


def test_control_webhook_deduplicates_provider_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("BORO_TELEGRAM_AUDIENCE_DB", str(tmp_path / "audience.db"))
    sent = []
    monkeypatch.setattr(
        "src.notify.send_raw",
        lambda text, *, chat_id=None: sent.append((text, chat_id)) or {"message_id": "1"},
    )

    update = _update("/start terms-v1")
    assert control_server._telegram_webhook(update, "webhook-secret")[1]["reply_sent"] is True
    status, result = control_server._telegram_webhook(update, "webhook-secret")

    assert status == 200
    assert result["duplicate"] is True
    assert len(sent) == 1
