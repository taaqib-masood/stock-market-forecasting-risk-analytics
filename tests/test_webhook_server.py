from src import webhook_server


def test_tradingview_webhook_requires_secret(monkeypatch):
    handler = object.__new__(webhook_server.WebhookHandler)
    handler.headers = {}
    monkeypatch.setattr(webhook_server, "WEBHOOK_SECRET", "secret")

    assert handler._authorized() is False
    handler.headers = {"X-Webhook-Secret": "secret"}
    assert handler._authorized() is True


def test_legacy_alpaca_execution_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WEBHOOK_ENABLE_ALPACA", raising=False)
    monkeypatch.setenv("ALPACA_API_KEY", "key")

    result = webhook_server._execute_alpaca("RELIANCE", 1, 1)

    assert result == {"status": "skipped", "reason": "LEGACY_ALPACA_EXECUTION_DISABLED"}


def test_legacy_alpaca_live_endpoint_is_rejected(monkeypatch):
    monkeypatch.setenv("WEBHOOK_ENABLE_ALPACA", "I_UNDERSTAND_LEGACY_ALPACA_PAPER")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")

    result = webhook_server._execute_alpaca("RELIANCE", 1, 1)

    assert result == {"status": "skipped", "reason": "LEGACY_ALPACA_LIVE_ENDPOINT_DISABLED"}
