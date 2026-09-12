from datetime import datetime, timezone

import pytest

from src.reliability.telegram_audience import TelegramAudience, TelegramAudienceError


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def test_subscribe_requires_explicit_terms_and_is_idempotent(tmp_path):
    audience = TelegramAudience(tmp_path / "audience.db")
    with pytest.raises(TelegramAudienceError, match="consent version"):
        audience.subscribe("12345", "", now=NOW)

    first = audience.subscribe("12345", "terms-v1", now=NOW)
    second = audience.subscribe("12345", "terms-v1", now=NOW)

    assert first["created"] is True
    assert second["created"] is False
    assert audience.active_chat_ids() == ["12345"]


def test_revoked_subscriber_is_excluded_from_future_broadcasts(tmp_path):
    audience = TelegramAudience(tmp_path / "audience.db")
    audience.subscribe("12345", "terms-v1", now=NOW)
    audience.subscribe("-99", "terms-v1", now=NOW)
    audience.revoke("12345", now=NOW)

    assert audience.active_chat_ids() == ["-99"]


def test_chat_id_and_idempotency_key_are_stable(tmp_path):
    audience = TelegramAudience(tmp_path / "audience.db")
    with pytest.raises(TelegramAudienceError, match="chat ID"):
        audience.subscribe("not-a-chat", "terms-v1", now=NOW)

    key = audience.idempotency_key("signal-7", "12345")
    assert key == audience.idempotency_key("signal-7", "12345")
    assert key.startswith("telegram:signal-7:")


def test_telegram_update_claim_is_idempotent(tmp_path):
    audience = TelegramAudience(tmp_path / "audience.db")

    assert audience.claim_update(42, now=NOW) is True
    assert audience.claim_update(42, now=NOW) is False

    with pytest.raises(TelegramAudienceError, match="integer"):
        audience.claim_update("not-an-id", now=NOW)
