import json
import hashlib

import pytest

from src.broker_gateway import (
    BrokerOrderError,
    ZerodhaBroker,
    build_cnc_order_payload,
    build_protection_gtt_payload,
    configured_access_token,
    persist_access_token,
    verify_order_postback,
)


def test_build_cnc_limit_order_payload_is_explicit():
    assert build_cnc_order_payload(
        ticker="reliance", shares=3, side="BUY", price=2450.5
    ) == {
        "tradingsymbol": "RELIANCE",
        "exchange": "NSE",
        "transaction_type": "BUY",
        "order_type": "LIMIT",
        "quantity": "3",
        "product": "CNC",
        "validity": "DAY",
        "price": "2450.5",
    }


def test_access_token_file_is_owner_only_and_never_required_in_frontend(tmp_path, monkeypatch):
    token_file = tmp_path / "kite-token"
    monkeypatch.setenv("KITE_ACCESS_TOKEN_FILE", str(token_file))

    persist_access_token("short-lived-token")

    assert configured_access_token() == "short-lived-token"
    assert token_file.stat().st_mode & 0o777 == 0o600


def test_live_order_is_blocked_before_network_when_release_is_not_approved(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "token")
    monkeypatch.setattr(
        "src.broker_gateway._release_approved",
        lambda: False,
    )
    network_called = []
    monkeypatch.setattr(
        "src.broker_gateway.urlopen",
        lambda *args, **kwargs: network_called.append(True),
    )

    with pytest.raises(BrokerOrderError, match="RELEASE_GATE_NOT_APPROVED"):
        ZerodhaBroker().place_cnc_order("RELIANCE", 1, "BUY", price=2450.0)
    assert network_called == []


def test_release_approval_evaluation_remains_reachable(monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setattr(
        "src.reliability.governance.evaluate_release",
        lambda *args, **kwargs: {"approved": True},
    )
    monkeypatch.setattr(
        "src.reliability.governance.load_policy", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(
        "src.reliability.governance.load_release_corporate_action_audit",
        lambda: None,
    )
    monkeypatch.setenv("BORO_RELEASE_EVIDENCE", "__missing_release_evidence__")

    # The file loader is patched at the module boundary so this verifies the
    # governance call path rather than requiring real release artifacts.
    monkeypatch.setattr(
        "src.broker_gateway.json.loads", lambda raw: {"approved": True}
    )
    monkeypatch.setattr(
        "src.broker_gateway.Path.read_text", lambda *args, **kwargs: "{}"
    )

    from src.broker_gateway import _release_approved
    assert _release_approved() is True


def test_private_owner_ack_allows_reliance_live_order_without_public_release(monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setenv("BORO_PERSONAL_LIVE_TRADING_ACK", "I_UNDERSTAND_PERSONAL_LIVE_TRADING")
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_LIVE_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDER")
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "token")
    monkeypatch.setattr("src.broker_gateway._release_approved", lambda: False)
    monkeypatch.setattr(
        "src.control_server._broker_session_status",
        lambda: {"valid": True, "reason": "verified"},
    )
    broker = ZerodhaBroker()
    monkeypatch.setattr(
        broker, "_request",
        lambda method, path, payload: {"status": "success", "data": {"order_id": "personal-1"}},
    )

    result = broker.place_cnc_order(
        "RELIANCE", 1, "BUY", price=2450.0, stop_price=2400.0
    )

    assert result["accepted"] is True
    assert result["order_id"] == "personal-1"


def test_live_order_requires_explicit_execution_mode(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "token")
    monkeypatch.setattr("src.broker_gateway._release_approved", lambda: True)
    monkeypatch.delenv("BORO_EXECUTION_MODE", raising=False)

    with pytest.raises(BrokerOrderError, match="LIVE_EXECUTION_DISABLED"):
        ZerodhaBroker().place_cnc_order("RELIANCE", 1, "BUY", price=2450.0)


def test_live_order_is_blocked_by_operational_kill_switch(monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_LIVE_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDER")
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "token")
    monkeypatch.setenv("BORO_OPERATIONAL_KILL_SWITCH", "1")
    monkeypatch.setattr("src.broker_gateway._release_approved", lambda: True)
    monkeypatch.setattr(
        "src.control_server._broker_session_status",
        lambda: {"valid": True, "reason": "verified"},
    )

    with pytest.raises(BrokerOrderError, match="OPERATIONAL_KILL_SWITCH_ACTIVE"):
        ZerodhaBroker().place_cnc_order("RELIANCE", 1, "BUY", price=2450.0)


def test_live_order_requires_recent_profile_validation(monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_LIVE_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDER")
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "token")
    monkeypatch.setattr("src.broker_gateway._release_approved", lambda: True)
    monkeypatch.setattr(
        "src.control_server._broker_session_status",
        lambda: {"valid": False, "reason": "BROKER_SESSION_NOT_VALIDATED"},
    )

    with pytest.raises(BrokerOrderError, match="BROKER_SESSION_NOT_VALIDATED"):
        ZerodhaBroker().place_cnc_order("RELIANCE", 1, "BUY", price=2450.0)


def test_direct_gateway_order_is_restricted_to_personal_live_symbol(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_live", lambda: None)
    monkeypatch.setattr(broker, "_request", lambda *args: pytest.fail("network should not run"))

    with pytest.raises(BrokerOrderError, match="LIVE_SYMBOL_RESTRICTED:RELIANCE"):
        broker.place_cnc_order("INFY", 1, "BUY", price=1800.0)


def test_direct_gateway_protection_is_restricted_to_personal_live_symbol(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_live", lambda: None)
    monkeypatch.setattr(broker, "_request", lambda *args: pytest.fail("network should not run"))

    with pytest.raises(BrokerOrderError, match="LIVE_SYMBOL_RESTRICTED:RELIANCE"):
        broker.place_protection_gtt(
            "INFY", 1, last_price=1800.0, stop_price=1750.0, target_price=1900.0
        )


def test_direct_gateway_buy_requires_stop_and_shared_risk_limits(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_live", lambda: None)
    monkeypatch.setattr(broker, "_request", lambda *args: pytest.fail("network should not run"))

    with pytest.raises(BrokerOrderError, match="LIVE_BUY_STOP_PRICE_REQUIRED"):
        broker.place_cnc_order("RELIANCE", 1, "BUY", price=2450.0)
    with pytest.raises(BrokerOrderError, match="LIVE_RISK_LIMIT_EXCEEDED"):
        broker.place_cnc_order("RELIANCE", 1, "BUY", price=2450.0, stop_price=1000.0)


def test_kill_switch_allows_risk_reducing_sell_after_session_validation(monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_LIVE_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDER")
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "token")
    monkeypatch.setenv("BORO_OPERATIONAL_KILL_SWITCH", "true")
    monkeypatch.setattr("src.broker_gateway._release_approved", lambda: True)
    monkeypatch.setattr(
        "src.control_server._broker_session_status",
        lambda: {"valid": True, "reason": "verified"},
    )
    broker = ZerodhaBroker()
    monkeypatch.setattr(
        broker, "_request",
        lambda method, path, payload: {"status": "success", "data": {"order_id": "123"}},
    )

    result = broker.place_cnc_order("RELIANCE", 1, "SELL", price=2450.0)

    assert result["accepted"] is True
    assert result["order_id"] == "123"


def test_two_leg_gtt_payload_is_long_only_stop_target_oco():
    payload = build_protection_gtt_payload(
        ticker="reliance", shares=3, last_price=2450.0,
        stop_price=2380.0, target_price=2600.0,
    )
    assert payload["type"] == "two-leg"
    condition = json.loads(payload["condition"])
    orders = json.loads(payload["orders"])
    assert condition["trigger_values"] == [2380.0, 2600.0]
    assert [order["transaction_type"] for order in orders] == ["SELL", "SELL"]
    assert all(order["product"] == "CNC" for order in orders)


@pytest.mark.parametrize("stop,last,target", [(2500, 2450, 2600), (2300, 2450, 2400)])
def test_two_leg_gtt_rejects_invalid_long_price_order(stop, last, target):
    with pytest.raises(BrokerOrderError, match="stop < last price < target"):
        build_protection_gtt_payload(
            ticker="RELIANCE", shares=1, last_price=last,
            stop_price=stop, target_price=target,
        )


def test_place_protection_gtt_returns_trigger_id_without_real_network(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_live", lambda: None)
    calls = []
    monkeypatch.setattr(
        broker, "_request",
        lambda method, path, payload: calls.append((method, path, payload))
        or {"status": "success", "data": {"trigger_id": 777}},
    )

    result = broker.place_protection_gtt(
        "RELIANCE", 2, last_price=2450, stop_price=2380, target_price=2600
    )

    assert result["gtt_id"] == "777"
    assert calls[0][0:2] == ("POST", "/gtt/triggers")


def test_gtt_status_uses_trigger_endpoint(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_observation", lambda: None)
    monkeypatch.setattr(
        broker, "_request",
        lambda method, path: {"status": "success", "data": {"status": "active"}},
    )

    assert broker.gtt_status("777") == {
        "gtt_id": "777", "status": "active", "raw": {"status": "active"},
    }


def test_cancel_gtt_deletes_trigger_and_returns_deleted_state(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_live", lambda: None)
    monkeypatch.setattr(broker, "_authorize_observation", lambda: None)
    calls = []

    def fake_request(method, path):
        calls.append((method, path))
        if method == "GET":
            return {"status": "success", "data": {
                "status": "active",
                "condition": {"tradingsymbol": "RELIANCE"},
            }}
        return {"status": "success", "data": {"trigger_id": 777}}

    monkeypatch.setattr(
        broker, "_request", fake_request,
    )

    assert broker.cancel_gtt("777") == {
        "gtt_id": "777", "cancelled": True, "status": "DELETED",
    }
    assert calls == [
        ("GET", "/gtt/triggers/777"),
        ("DELETE", "/gtt/triggers/777"),
    ]


@pytest.mark.parametrize(
    "trigger,expected",
    [
        ({"status": "active", "condition": {"tradingsymbol": "INFY"}}, "LIVE_GTT_SYMBOL_MISMATCH"),
        ({"status": "triggered", "condition": {"tradingsymbol": "RELIANCE"}}, "LIVE_GTT_NOT_ACTIVE"),
    ],
)
def test_cancel_gtt_rejects_unscoped_or_inactive_trigger(monkeypatch, trigger, expected):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_live", lambda: None)
    monkeypatch.setattr(broker, "_authorize_observation", lambda: None)
    calls = []
    monkeypatch.setattr(
        broker, "_request",
        lambda method, path: calls.append((method, path))
        or {"status": "success", "data": trigger if method == "GET" else {"trigger_id": 777}},
    )

    with pytest.raises(BrokerOrderError, match=expected):
        broker.cancel_gtt("777")
    assert calls == [("GET", "/gtt/triggers/777")]


def test_cancel_order_uses_regular_order_endpoint(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_live", lambda: None)
    calls = []
    monkeypatch.setattr(
        broker, "_request",
        lambda method, path: calls.append((method, path))
        or {"status": "success", "data": {"order_id": "123456"}},
    )

    assert broker.cancel_order("123456") == {
        "order_id": "123456", "cancel_requested": True, "status": "CANCEL_PENDING",
    }
    assert calls == [("DELETE", "/orders/regular/123456")]


def test_order_status_rejects_non_numeric_identifier_before_request(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_observation", lambda: None)
    monkeypatch.setattr(broker, "_request", lambda *args: pytest.fail("request should not run"))

    with pytest.raises(BrokerOrderError, match="positive integer"):
        broker.order_status("order/../other")


def test_orders_reads_daily_order_book(monkeypatch):
    broker = ZerodhaBroker()
    calls = []
    monkeypatch.setattr(broker, "_authorize_observation", lambda: None)
    monkeypatch.setattr(
        broker, "_request", lambda method, path: calls.append((method, path)) or {
            "data": [{"order_id": "123456", "status": "OPEN"}, "ignored"]
        },
    )

    assert broker.orders() == [{"order_id": "123456", "status": "OPEN"}]
    assert calls == [("GET", "/orders")]


def test_read_only_order_book_requires_session_but_not_release_mode(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "api-key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "research")
    monkeypatch.setattr(
        "src.control_server._broker_session_status",
        lambda: {"valid": True, "reason": "verified"},
    )
    broker = ZerodhaBroker()
    monkeypatch.setattr(
        broker,
        "_request",
        lambda method, path: {"status": "success", "data": [{"order_id": "7"}]},
    )

    assert broker.orders() == [{"order_id": "7"}]


def test_close_holding_validates_gtt_symbol_before_cancellation(monkeypatch):
    broker = ZerodhaBroker()
    monkeypatch.setattr(broker, "_authorize_live", lambda: None)
    monkeypatch.setattr(broker, "holdings", lambda: [{
        "exchange": "NSE", "tradingsymbol": "RELIANCE",
        "quantity": 2, "used_quantity": 0,
    }])
    monkeypatch.setattr(broker, "gtt_status", lambda _gtt: {
        "status": "active", "raw": {"condition": {"tradingsymbol": "INFY"}}
    })
    cancelled = []
    monkeypatch.setattr(broker, "cancel_gtt", lambda _gtt: cancelled.append(True))

    with pytest.raises(BrokerOrderError, match="GTT_SYMBOL_MISMATCH"):
        broker.close_holding("RELIANCE", gtt_id="777")
    assert cancelled == []


def test_session_exchange_posts_checksum_without_authorization_header(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "api-key")
    broker = ZerodhaBroker(base_url="https://kite.test")
    captured = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self):
            return json.dumps({"status": "success", "data": {
                "access_token": "access-1", "user_id": "AB123",
                "login_time": "2026-08-09 08:00:00", "exchanges": ["NSE"],
            }}).encode()

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("src.broker_gateway.urlopen", fake_urlopen)
    result = broker.exchange_request_token("request-1", api_secret="secret")

    assert result["access_token"] == "access-1"
    body = captured["request"].data.decode()
    assert "checksum=" + hashlib.sha256(b"api-keyrequest-1secret").hexdigest() in body
    assert captured["request"].get_header("Authorization") is None


def test_profile_can_validate_token_without_live_execution_mode(monkeypatch):
    monkeypatch.setenv("KITE_API_KEY", "api-key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "access-token")
    broker = ZerodhaBroker()
    monkeypatch.setattr(
        broker, "_request",
        lambda method, path: {"status": "success", "data": {
            "user_id": "AB123", "broker": "ZERODHA", "exchanges": ["NSE"],
        }},
    )
    assert broker.profile()["user_id"] == "AB123"


def test_order_postback_checksum_is_verified():
    payload = {
        "order_id": "order-1",
        "order_timestamp": "2026-08-09 09:15:00",
        "checksum": hashlib.sha256(
            b"order-12026-08-09 09:15:00secret"
        ).hexdigest(),
    }
    assert verify_order_postback(payload, api_secret="secret") is True
    payload["status"] = "COMPLETE"
    payload["order_id"] = "forged"
    assert verify_order_postback(payload, api_secret="secret") is False
