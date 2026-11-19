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


import io
import json

import pytest


def _post(monkeypatch, body, quote_price=200.0):
    monkeypatch.setattr(webhook_server, "WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("WEBHOOK_ENABLE_ALPACA", "I_UNDERSTAND_LEGACY_ALPACA_PAPER")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
    calls = []

    def fake_call(method, url, headers, payload=None):
        calls.append((method, url, payload))
        if "trades/latest" in url:
            return {"trade": {"p": quote_price}}
        return {"status": "accepted"}

    monkeypatch.setattr(webhook_server, "_alpaca_call", fake_call)
    raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
    handler = object.__new__(webhook_server.WebhookHandler)
    handler.path = "/webhook"
    handler.headers = {"X-Webhook-Secret": "secret", "Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    sent = {}
    handler._send = lambda status, payload: sent.update(status=status, body=payload)
    handler.do_POST()
    return sent, calls


def _orders(calls):
    return [c for c in calls if c[1].endswith("/v2/orders")]


@pytest.mark.parametrize("action", ["", "SHORT", "hold"])
def test_unknown_action_is_rejected_without_orders(monkeypatch, action):
    sent, calls = _post(monkeypatch, {"ticker": "AAPL", "action": action, "price": 200, "atr": 4})
    assert sent["status"] == 400
    assert calls == []


@pytest.mark.parametrize("action", ["sell", "CLOSE", "exit"])
def test_exit_actions_close_held_position_and_never_sell_order(monkeypatch, action):
    sent, calls = _post(monkeypatch, {"ticker": "AAPL", "action": action, "price": 200, "atr": 4})
    assert sent["status"] == 200
    assert _orders(calls) == []
    assert calls == [("DELETE", "https://paper-api.alpaca.markets/v2/positions/AAPL", None)]


def test_buy_places_buy_order_within_position_cap(monkeypatch):
    sent, calls = _post(monkeypatch, {"ticker": "AAPL", "action": "BUY", "price": 200, "atr": 4, "confidence": 1})
    assert sent["status"] == 200
    (order,) = _orders(calls)
    payload = order[2]
    assert payload["side"] == "buy"
    assert int(payload["qty"]) * 200 <= webhook_server.rm.capital * webhook_server.rm.max_position_pct


def test_tiny_price_and_atr_do_not_bypass_position_cap(monkeypatch):
    sent, calls = _post(monkeypatch, {"ticker": "AAPL", "action": "BUY", "price": 1, "atr": 0.25, "confidence": 1})
    assert sent["body"]["decision"]["approved"] is True
    assert _orders(calls) == []
    assert sent["body"]["order"]["status"] == "rejected"


def test_hard_notional_cap_rejects_oversized_order(monkeypatch):
    monkeypatch.setattr(webhook_server, "_alpaca_call", lambda *a, **k: {"trade": {"p": 200.0}})
    monkeypatch.setenv("WEBHOOK_ENABLE_ALPACA", "I_UNDERSTAND_LEGACY_ALPACA_PAPER")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
    result = webhook_server._execute_alpaca("AAPL", 1_000, 200.0)
    assert result == {"status": "rejected", "reason": "order notional exceeds max position size"}


@pytest.mark.parametrize("raw", [
    b'{"ticker": "AAPL", "action": "BUY", "price": 200, "atr": 4, "vix": NaN}',
    b'{"ticker": "AAPL", "action": "BUY", "price": Infinity, "atr": 4}',
    b'{"ticker": "AAPL", "action": "BUY", "price": -1, "atr": 4}',
    b'{"ticker": "AAPL", "action": "BUY", "price": 200, "atr": 0}',
    b'{"ticker": "AAPL", "action": "BUY", "price": "abc", "atr": 4}',
    b'{"ticker": "../account", "action": "BUY", "price": 200, "atr": 4}',
    b'["not", "an", "object"]',
])
def test_invalid_alert_fields_return_400(monkeypatch, raw):
    sent, calls = _post(monkeypatch, raw)
    assert sent["status"] == 400
    assert calls == []
