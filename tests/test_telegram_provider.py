import json

from src import telegram_provider


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_provider_status_verifies_token_and_webhook_without_exposing_secret(monkeypatch):
    expected = "https://example.test/telegram/webhook"
    monkeypatch.setenv("TELEGRAM_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", expected)

    def fake_urlopen(request, timeout):
        assert timeout == 10
        if request.full_url.endswith("/getMe"):
            return _Response({"ok": True, "result": {"username": "boro_bot"}})
        return _Response({"ok": True, "result": {
            "url": expected, "pending_update_count": 2,
        }})

    monkeypatch.setattr(telegram_provider, "urlopen", fake_urlopen)

    result = telegram_provider.provider_status()

    assert result["ok"] is True
    assert result["token_valid"] is True
    assert result["bot_username"] == "boro_bot"
    assert result["webhook"]["matches"] is True
    assert result["webhook"]["pending_update_count"] == 2
    assert "secret-token" not in json.dumps(result)
    assert "webhook-secret" not in json.dumps(result)


def test_provider_status_flags_webhook_mismatch(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "secret-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.test/telegram/webhook")
    monkeypatch.setattr(
        telegram_provider,
        "urlopen",
        lambda request, timeout: _Response(
            {"ok": True, "result": {"username": "boro_bot"}}
            if request.full_url.endswith("/getMe")
            else {"ok": True, "result": {"url": "https://other.test/telegram/webhook"}},
        ),
    )

    result = telegram_provider.provider_status()

    assert result["ok"] is False
    assert "TELEGRAM_WEBHOOK_URL_MISMATCH" in result["blockers"]


def test_provider_status_fails_without_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_URL", raising=False)

    result = telegram_provider.provider_status()

    assert result["ok"] is False
    assert result["blockers"] == ["TELEGRAM_TOKEN_MISSING"]


def test_register_webhook_posts_secret_bound_https_configuration(monkeypatch):
    expected = "https://example.test/telegram/webhook"
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "a-secret-that-is-long-enough")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", expected)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode()
        return _Response({"ok": True, "result": True})

    monkeypatch.setattr(telegram_provider, "urlopen", fake_urlopen)
    result = telegram_provider.register_webhook()

    assert result == {"ok": True, "webhook_url": expected}
    assert captured["url"] == "https://api.telegram.org/botbot-token/setWebhook"
    assert "secret_token=a-secret-that-is-long-enough" in captured["body"]
    assert "allowed_updates=%5B%22message%22%5D" in captured["body"]
    assert "bot-token" not in str(result)


def test_register_webhook_rejects_non_https_url(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "a-secret-that-is-long-enough")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "http://example.test/telegram/webhook")

    result = telegram_provider.register_webhook()

    assert result == {"ok": False, "blockers": ["TELEGRAM_WEBHOOK_URL_INVALID"]}


def test_register_webhook_rejects_invalid_secret_contract(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "invalid secret with spaces")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.test/telegram/webhook")

    result = telegram_provider.register_webhook()

    assert result == {"ok": False, "blockers": ["TELEGRAM_WEBHOOK_SECRET_INVALID"]}


def test_register_webhook_rejects_secret_over_provider_limit(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "a" * 257)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_URL", "https://example.test/telegram/webhook")

    result = telegram_provider.register_webhook()

    assert result == {"ok": False, "blockers": ["TELEGRAM_WEBHOOK_SECRET_INVALID"]}
