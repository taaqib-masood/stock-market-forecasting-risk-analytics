"""
Cockpit guard tests — the halal + safety rules on the control_server trade
endpoints, exercised WITHOUT network or a live socket. We call the handler
helpers directly and monkeypatch paper_trader / the preset config path so nothing
touches yfinance or the real results/ state.
"""
import pytest
import hashlib
from io import BytesIO

from src import control_server as cs
from src import strategy_presets as sp


def test_broker_login_url_is_secret_free(monkeypatch):
    class FakeBroker:
        def login_url(self):
            return "https://kite.example/connect?api_key=public-key"

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)
    result = cs._broker_login_url()

    assert result == {
        "ok": True,
        "login_url": "https://kite.example/connect?api_key=public-key",
    }


def test_broker_session_exchange_persists_token_and_returns_only_profile_metadata(monkeypatch):
    stored = []

    class FakeBroker:
        def exchange_request_token(self, request_token):
            assert request_token == "short-lived-request-token"
            return {"access_token": "never-return-this", "user_id": "AB123"}

        def profile(self):
            return {"user_id": "AB123", "broker": "ZERODHA", "exchanges": ["NSE"]}

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)
    monkeypatch.setattr(cs, "_persist_broker_access_token", stored.append)
    monkeypatch.setattr(cs, "_record_broker_session", lambda **kwargs: None)

    result = cs._broker_session_exchange({"request_token": "short-lived-request-token"})

    assert result == {
        "ok": True,
        "user_id": "AB123",
        "broker": "ZERODHA",
        "exchanges": ["NSE"],
        "login_time": None,
    }
    assert stored == ["never-return-this"]
    assert "never-return-this" not in str(result)


def test_broker_session_exchange_rejects_missing_request_token():
    result = cs._broker_session_exchange({})

    assert result == {"ok": False, "error": "KITE_REQUEST_TOKEN_MISSING"}


# ── BUY guard: bad input must be rejected BEFORE any price fetch ─────────────────

@pytest.mark.parametrize("body,frag", [
    ({"ticker": "REL!", "shares": 5, "price": 100}, "alphanumeric"),
    ({"ticker": "RELIANCE", "shares": 0, "price": 100}, "shares must be > 0"),
    ({"ticker": "RELIANCE", "shares": -3, "price": 100}, "shares must be > 0"),
    ({"ticker": "RELIANCE", "shares": 5, "price": -1}, "price must be >= 0"),
    ({"ticker": "", "shares": 5, "price": 100}, "alphanumeric"),
])
def test_buy_rejects_bad_input(body, frag):
    r = cs._buy(body)
    assert r["ok"] is False
    assert frag in r["error"]


def test_buy_valid_input_reaches_trade_layer(monkeypatch):
    """Valid input should pass the guard and call paper_trader.buy (stubbed)."""
    captured = {}

    def fake_buy(ticker, shares, price):
        captured.update(ticker=ticker, shares=shares, price=price)
        return {"ok": True, "fill_price": price or 0, "cash_left": 1000}

    import src.paper_trader as pt
    monkeypatch.setattr(pt, "buy", fake_buy)
    r = cs._buy({"ticker": "reliance", "shares": 5, "price": 0})
    assert r["ok"] is True
    assert captured["ticker"] == "RELIANCE"   # upper-cased
    assert captured["shares"] == 5
    assert captured["price"] is None          # 0 → live fetch


def test_live_buy_routes_to_broker_and_never_paper_trader(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setattr(cs, "_release_status", lambda: {
        "approved": False,
        "blockers": ["RELEASE_GATE_NOT_APPROVED"],
    })
    paper_called = []
    monkeypatch.setattr("src.paper_trader.buy", lambda *args: paper_called.append(args))

    result = cs._buy({"ticker": "RELIANCE", "shares": 1, "price": 2450})

    assert result["ok"] is False
    assert "RELEASE_GATE_NOT_APPROVED" in result["error"]
    assert paper_called == []


def test_release_status_reports_operational_kill_switch(monkeypatch):
    monkeypatch.setenv("BORO_OPERATIONAL_KILL_SWITCH", "yes")

    result = cs._release_status()

    assert result["approved"] is False
    assert result["operational_kill_switch"] is True
    assert "OPERATIONAL_KILL_SWITCH_ACTIVE" in result["blockers"]
    assert result["telegram_recommendations"] is False
    assert result["broker_orders"] is False


def test_release_status_separates_private_personal_trading_from_public_release(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setenv("BORO_PERSONAL_LIVE_TRADING_ACK", "I_UNDERSTAND_PERSONAL_LIVE_TRADING")
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_LIVE_CONFIRMATION", "I_UNDERSTAND_LIVE_ORDER")
    monkeypatch.setenv("KITE_API_KEY", "key")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "token")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "private-live.db"))
    monkeypatch.setattr(
        cs, "_broker_session_status", lambda: {"valid": True, "reason": "verified"}
    )

    result = cs._release_status()

    assert result["approved"] is False
    assert result["personal_live_trading_acknowledged"] is True
    assert result["broker_orders"] is True
    assert result["telegram_recommendations"] is False


def test_live_close_remains_available_when_entries_are_paused(tmp_path, monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "close.db"))
    monkeypatch.setattr(cs, "_release_status", lambda: {
        "approved": False, "broker_orders": False, "broker_exits": True,
        "blockers": ["OPERATIONAL_KILL_SWITCH_ACTIVE"],
    })

    class FakeBroker:
        def close_holding(self, ticker, *, gtt_id=None):
            return {"accepted": True, "order_id": "123", "gtt_id": gtt_id}

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: True)

    result = cs._close({"ticker": "RELIANCE", "gtt_id": "7", "request_id": "close-test-1"})

    assert result["ok"] is True
    assert result["order_id"] == "123"


def test_live_close_is_idempotent_across_browser_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "close.db"))
    monkeypatch.setattr(cs, "_release_status", lambda: {
        "approved": False, "broker_orders": False, "broker_exits": True,
        "blockers": ["OPERATIONAL_KILL_SWITCH_ACTIVE"],
    })
    calls = []

    class FakeBroker:
        def close_holding(self, ticker, *, gtt_id=None):
            calls.append((ticker, gtt_id))
            return {"accepted": True, "order_id": "456", "gtt_id": gtt_id}

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: True)
    body = {"ticker": "RELIANCE", "gtt_id": "8", "request_id": "close-retry-1"}

    first = cs._close(body)
    second = cs._close(body)

    assert first["ok"] is True
    assert second == first
    assert calls == [("RELIANCE", "8")]


def test_broker_reconcile_reports_scope_issues_and_audits_orders(monkeypatch):
    class FakeBroker:
        def holdings(self):
            return [{"tradingsymbol": "RELIANCE", "quantity": 3}]

        def orders(self):
            return [
                {"order_id": "1", "tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "CNC", "status": "COMPLETE"},
                {"order_id": "2", "tradingsymbol": "INFY", "exchange": "NSE", "product": "MIS", "status": "OPEN"},
            ]

    monkeypatch.setattr(cs, "_broker_readiness", lambda **_kwargs: (FakeBroker(), None))
    audited = []
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: audited.append(args) or True)

    result = cs._broker_reconcile()

    assert result["ok"] is True
    assert len(result["holdings"]) == 1
    assert result["orders_reconciled"] == 2
    assert result["scope_issues"] == [{
        "order_id": "2", "ticker": "INFY",
        "reasons": ["LIVE_SYMBOL_RESTRICTED:RELIANCE", "BROKER_ORDER_PRODUCT_OUT_OF_SCOPE"],
    }]
    assert len(audited) == 2


def test_telegram_audience_status_reports_outbox_health(tmp_path, monkeypatch):
    database = tmp_path / "telegram-status.db"
    monkeypatch.setenv("BORO_TELEGRAM_AUDIENCE_DB", str(database))
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(database))
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")

    result = cs._telegram_audience_status()

    assert result["active_recipients"] == 0
    assert result["delivery"]["total"] == 0
    assert result["delivery"]["dead_letter"] == 0
    assert result["delivery"]["unreconciled"] == 0


def test_telegram_webhook_registration_returns_secret_free_provider_result(monkeypatch):
    monkeypatch.setattr(
        "src.telegram_provider.register_webhook",
        lambda: {"ok": True, "webhook_url": "https://example.test/telegram/webhook"},
    )

    result = cs._telegram_register_webhook()

    assert result == {"ok": True, "webhook_url": "https://example.test/telegram/webhook"}


def test_telegram_provider_health_is_secret_free_and_fail_closed(monkeypatch):
    monkeypatch.setattr(
        "src.telegram_provider.provider_status",
        lambda: {"ok": False, "blockers": ["TELEGRAM_WEBHOOK_NOT_REGISTERED"]},
    )

    result = cs._telegram_provider_health()

    assert result == {"ok": False, "blockers": ["TELEGRAM_WEBHOOK_NOT_REGISTERED"]}


def test_telegram_configuration_blockers_are_secret_free(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "configured-token")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_URL", raising=False)

    assert cs._telegram_configuration_blockers() == [
        "TELEGRAM_WEBHOOK_SECRET_MISSING",
        "TELEGRAM_WEBHOOK_URL_MISSING",
    ]


def test_telegram_outbox_retry_reuses_gated_worker(monkeypatch):
    report = {"ok": False, "blocked": True, "reason": "RELEASE_GATE_NOT_APPROVED"}
    monkeypatch.setattr(
        "scripts.deliver_telegram_outbox.deliver_outbox",
        lambda: report,
    )

    assert cs._telegram_retry_outbox() is report


def test_control_server_rejects_url_tokens(monkeypatch):
    handler = object.__new__(cs.Handler)
    handler.path = "/readiness?token=secret"
    handler.headers = {}
    monkeypatch.setattr(cs, "TOKEN", "secret")

    assert handler._authed() is False

    handler.headers = {"X-Control-Token": "secret"}
    assert handler._authed() is True


def test_control_server_rejects_oversized_json_body():
    handler = object.__new__(cs.Handler)
    handler.headers = {"Content-Length": str(cs.MAX_BODY_BYTES + 1)}
    handler.rfile = BytesIO(b"{}")

    assert handler._body() == {}


def test_broker_session_validation_is_bound_to_current_token(tmp_path, monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "session.db"))
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "access-one")
    monkeypatch.setenv("BORO_BROKER_SESSION_MAX_AGE_SECONDS", "3600")

    assert cs._broker_session_status()["valid"] is False
    cs._record_broker_session(valid=True, profile={"user_id": "AB123"})
    checked = cs._broker_session_status()
    assert checked["valid"] is True
    assert checked["user_id"] == "AB123"

    monkeypatch.setenv("KITE_ACCESS_TOKEN", "access-two")
    assert cs._broker_session_status()["valid"] is False


def test_broker_session_status_uses_owner_only_file_token(tmp_path, monkeypatch):
    database = tmp_path / "session-file.db"
    token_file = tmp_path / "kite-token"
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(database))
    monkeypatch.setenv("KITE_ACCESS_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("KITE_ACCESS_TOKEN", raising=False)

    from src.broker_gateway import persist_access_token
    persist_access_token("file-backed-access-token")

    assert cs._broker_session_status()["valid"] is False
    cs._record_broker_session(valid=True, profile={"user_id": "AB123"})
    checked = cs._broker_session_status()

    assert checked["valid"] is True
    assert checked["user_id"] == "AB123"
    assert "file-backed-access-token" not in str(checked)


def test_live_buy_is_restricted_to_configured_personal_symbol(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_LIVE_SYMBOL", "RELIANCE")
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True})

    result = cs._buy({
        "ticker": "INFY", "shares": 1, "price": 1500,
        "stop": 1450, "target": 1600,
    })

    assert result == {"ok": False, "error": "LIVE_SYMBOL_RESTRICTED:RELIANCE"}


def test_live_buy_enforces_two_percent_risk_limit_before_broker_call(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_LIVE_SYMBOL", "RELIANCE")
    monkeypatch.setenv("BORO_LIVE_CAPITAL", "50000")
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True})

    result = cs._buy({
        "ticker": "RELIANCE", "shares": 10, "price": 2450,
        "stop": 2200, "target": 2800,
    })

    assert result["ok"] is False
    assert result["error"] == "LIVE_RISK_LIMIT_EXCEEDED"
    assert result["risk_amount"] == 2500
    assert result["max_risk"] == 1000


def test_live_buy_enforces_notional_limit(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_LIVE_SYMBOL", "RELIANCE")
    monkeypatch.setenv("BORO_LIVE_CAPITAL", "50000")
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True})

    result = cs._buy({
        "ticker": "RELIANCE", "shares": 5, "price": 2450,
        "stop": 2440, "target": 2600,
    })

    assert result["ok"] is False
    assert result["error"] == "LIVE_NOTIONAL_LIMIT_EXCEEDED"
    assert result["notional"] == 12250
    assert result["max_notional"] == 10000


def test_broker_risk_preview_is_read_only_and_reports_limits(monkeypatch):
    monkeypatch.setenv("BORO_LIVE_CAPITAL", "50000")
    result = cs._broker_risk_preview({
        "ticker": ["RELIANCE"], "shares": ["1"], "price": ["2450"],
        "stop": ["2380"], "target": ["2600"],
    })

    assert result["ok"] is True
    assert result["risk_amount"] == 70.0
    assert result["max_risk"] == 1000.0
    assert result["notional"] == 2450.0
    assert result["max_notional"] == 10000.0
    assert result["protection_valid"] is True


def test_broker_risk_preview_rejects_unscoped_symbol(monkeypatch):
    result = cs._broker_risk_preview({
        "ticker": ["INFY"], "shares": ["1"], "price": ["1800"],
        "stop": ["1750"], "target": ["1900"],
    })

    assert result == {"ok": False, "error": "LIVE_SYMBOL_RESTRICTED:RELIANCE"}


def test_approved_live_buy_requires_and_creates_protection_gtt(monkeypatch, tmp_path):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "reliability.db"))
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True})
    recorded = []
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: recorded.append(args) or True)

    class FakeBroker:
        def place_cnc_order(self, *args, **kwargs):
            return {"accepted": True, "order_id": "order-1", "status": "PLACED"}

        def place_protection_gtt(self, *args, **kwargs):
            return {"protection_created": True, "gtt_id": "777"}

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)
    result = cs._buy({
        "ticker": "RELIANCE", "shares": 2, "price": 2450,
        "stop": 2380, "target": 2600, "request_id": "test-buy-1",
    })

    assert result["ok"] is True
    assert result["gtt_id"] == "777"
    assert recorded and recorded[0][0] == "BROKER_ORDER_ACCEPTED"


def test_live_buy_request_is_idempotent_on_retry(monkeypatch, tmp_path):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "reliability.db"))
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True})
    calls = []

    class FakeBroker:
        def place_cnc_order(self, *args, **kwargs):
            calls.append("entry")
            return {"accepted": True, "order_id": "order-idempotent", "status": "PLACED"}

        def place_protection_gtt(self, *args, **kwargs):
            calls.append("gtt")
            return {"protection_created": True, "gtt_id": "778"}

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: True)
    body = {
        "ticker": "RELIANCE", "shares": 2, "price": 2450,
        "stop": 2380, "target": 2600, "request_id": "retry-1",
    }

    first = cs._buy(body)
    second = cs._buy(body)

    assert first["ok"] is True
    assert second == first
    assert calls == ["entry", "gtt"]


def test_auto_close_is_paper_only_in_live_mode(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setattr(cs, "_run_module", lambda *args: pytest.fail("paper auto-close invoked"))

    status, result = cs._auto_close_action()

    assert status == 409
    assert result["error"] == "LIVE_AUTO_CLOSE_DISABLED"


def test_live_positions_use_broker_holdings_not_paper_state(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")

    class FakeBroker:
        def holdings(self):
            return [{
                "tradingsymbol": "RELIANCE", "quantity": 2,
                "average_price": 2400, "last_price": 2450, "pnl": 100,
            }]

    monkeypatch.setattr(cs, "_broker_readiness", lambda **_kwargs: (FakeBroker(), None))
    monkeypatch.setattr("src.paper_trader.portfolio_value", lambda *_: pytest.fail("paper state used"))

    result = cs._positions()

    assert result["ok"] is True
    assert result["live"] is True
    assert result["positions"]["RELIANCE"]["shares"] == 2
    assert result["positions"]["RELIANCE"]["unrealised"] == 100


def test_broker_order_cancel_is_audited(monkeypatch):
    captured = []

    class FakeBroker:
        def order_status(self, order_id):
            return {"status": "OPEN", "raw": {
                "order_id": order_id, "tradingsymbol": "RELIANCE",
                "exchange": "NSE", "product": "CNC", "status": "OPEN",
            }}

        def cancel_order(self, order_id):
            return {"order_id": order_id, "cancel_requested": True, "status": "CANCEL_PENDING"}

    monkeypatch.setattr(cs, "_broker_readiness", lambda **_kwargs: (FakeBroker(), None))
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: captured.append(args) or True)

    result = cs._broker_order_cancel("order-1")

    assert result["ok"] is True
    assert result["cancel_requested"] is True
    assert captured[0][0] == "BROKER_ORDER_CANCEL_REQUESTED"


def test_broker_order_cancel_rejects_other_symbol_before_cancel(monkeypatch):
    cancelled = []

    class FakeBroker:
        def order_status(self, _order_id):
            return {"status": "OPEN", "raw": {
                "tradingsymbol": "INFY", "exchange": "NSE", "product": "CNC",
            }}

        def cancel_order(self, _order_id):
            cancelled.append(True)
            return {"order_id": "123", "cancel_requested": True}

    monkeypatch.setattr(cs, "_broker_readiness", lambda **_kwargs: (FakeBroker(), None))

    result = cs._broker_order_cancel("123")

    assert result == {"ok": False, "error": "LIVE_SYMBOL_RESTRICTED:RELIANCE"}
    assert cancelled == []


def test_broker_order_cancel_rejects_completed_order_before_cancel(monkeypatch):
    cancelled = []

    class FakeBroker:
        def order_status(self, _order_id):
            return {"status": "COMPLETE", "raw": {
                "tradingsymbol": "RELIANCE", "exchange": "NSE", "product": "CNC",
            }}

        def cancel_order(self, _order_id):
            cancelled.append(True)
            return {"order_id": "123", "cancel_requested": True}

    monkeypatch.setattr(cs, "_broker_readiness", lambda **_kwargs: (FakeBroker(), None))

    result = cs._broker_order_cancel("123")

    assert result == {"ok": False, "error": "ORDER_NOT_CANCELLABLE:COMPLETE"}
    assert cancelled == []


def test_broker_gtt_cancel_rejects_other_symbol_before_cancel(monkeypatch):
    cancelled = []

    class FakeBroker:
        def gtt_status(self, _trigger_id):
            return {"status": "active", "raw": {
                "condition": {"tradingsymbol": "INFY"},
            }}

        def cancel_gtt(self, _trigger_id):
            cancelled.append(True)
            return {"gtt_id": "7", "cancelled": True}

    monkeypatch.setattr(cs, "_broker_readiness", lambda **_kwargs: (FakeBroker(), None))

    result = cs._broker_gtt_cancel("7")

    assert result == {"ok": False, "error": "LIVE_SYMBOL_RESTRICTED:RELIANCE"}
    assert cancelled == []


def test_broker_gtt_cancel_is_audited(monkeypatch):
    captured = []

    class FakeBroker:
        def gtt_status(self, _trigger_id):
            return {"status": "active", "raw": {
                "condition": {"tradingsymbol": "RELIANCE"},
            }}

        def cancel_gtt(self, trigger_id):
            return {"gtt_id": trigger_id, "cancelled": True}

    monkeypatch.setattr(cs, "_broker_readiness", lambda **_kwargs: (FakeBroker(), None))
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: captured.append(args) or True)

    result = cs._broker_gtt_cancel("7")

    assert result["ok"] is True
    assert result["audit_recorded"] is True
    assert captured[0][0] == "BROKER_GTT_CANCEL_REQUESTED"
    assert captured[0][1]["order_id"] == "gtt:7"


def test_broker_gtt_protection_retry_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "protection.db"))
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True, "broker_orders": True})
    calls = []

    class FakeBroker:
        def place_protection_gtt(self, ticker, shares, *, last_price, stop_price, target_price):
            calls.append((ticker, shares, last_price, stop_price, target_price))
            return {"protection_created": True, "gtt_id": "777", "gtt_type": "two-leg"}

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: True)
    body = {
        "ticker": "RELIANCE", "shares": 2, "price": 2450,
        "stop": 2380, "target": 2600, "order_id": "123", "request_id": "protect-1",
    }

    first = cs._broker_gtt_protect(body)
    second = cs._broker_gtt_protect(body)

    assert first["ok"] is True
    assert second == first
    assert calls == [("RELIANCE", 2, 2450.0, 2380.0, 2600.0)]


def test_broker_gtt_protection_retry_requires_request_id(monkeypatch):
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True, "broker_orders": True})

    result = cs._broker_gtt_protect({
        "ticker": "RELIANCE", "shares": 1,
        "price": 2450, "stop": 2380, "target": 2600,
    })

    assert result == {"ok": False, "error": "LIVE_PROTECTION_REQUEST_ID_REQUIRED"}


def test_broker_order_book_uses_broker(monkeypatch):
    class FakeBroker:
        def orders(self):
            return [{"order_id": "123456", "status": "COMPLETE"}]

    monkeypatch.setattr(cs, "_broker_readiness", lambda **_kwargs: (FakeBroker(), None))

    assert cs._broker_orders() == {
        "ok": True,
        "orders": [{"order_id": "123456", "status": "COMPLETE"}],
    }


def test_read_only_broker_observation_survives_release_entry_gate(monkeypatch):
    monkeypatch.setattr(cs, "_release_status", lambda: {
        "approved": False,
        "broker_exits": False,
        "blockers": ["RELEASE_GATE_NOT_APPROVED"],
    })

    class FakeBroker:
        pass

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)

    live_broker, live_error = cs._broker_readiness()
    observed_broker, observed_error = cs._broker_readiness(read_only=True)

    assert live_broker is None
    assert live_error["error"] == "RELEASE_GATE_NOT_APPROVED"
    assert isinstance(observed_broker, FakeBroker)
    assert observed_error is None


# ── CLOSE guard: refuse to sell what isn't held (no shorting) ────────────────────

def test_close_rejects_unheld_ticker(monkeypatch):
    import src.paper_trader as pt
    monkeypatch.setattr(pt, "_load", lambda: {"positions": {}})
    r = cs._close({"ticker": "RELIANCE"})
    assert r["ok"] is False
    assert "no open position" in r["error"]


def test_close_held_ticker_calls_sell(monkeypatch):
    import src.paper_trader as pt
    monkeypatch.setattr(pt, "_load", lambda: {"positions": {"RELIANCE": {"shares": 5}}})
    monkeypatch.setattr(pt, "sell", lambda t: {"ok": True, "ticker": t, "pnl": 50, "pnl_pct": 1.0})
    r = cs._close({"ticker": "reliance"})
    assert r["ok"] is True
    assert r["ticker"] == "RELIANCE"


def test_live_close_never_routes_to_paper_position_store_when_gate_is_blocked(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setattr(cs, "_release_status", lambda: {
        "approved": False,
        "blockers": ["RELEASE_GATE_NOT_APPROVED"],
    })
    monkeypatch.setattr("src.paper_trader._load", lambda: {"positions": {
        "RELIANCE": {"shares": 2},
    }})
    paper_called = []
    monkeypatch.setattr("src.paper_trader.sell", lambda *args: paper_called.append(args))

    result = cs._close({"ticker": "RELIANCE"})

    assert result["ok"] is False
    assert "RELEASE_GATE_NOT_APPROVED" in result["error"]
    assert paper_called == []


def test_live_close_requires_gtt_id_before_submitting_sell(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True})
    result = cs._close({"ticker": "RELIANCE"})

    assert result == {"ok": False, "error": "LIVE_CLOSE_REQUIRES_GTT_ID"}


def test_live_close_passes_gtt_id_to_broker_before_sell(tmp_path, monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "close.db"))
    monkeypatch.setattr(cs, "_release_status", lambda: {"approved": True})
    captured = {}

    class FakeBroker:
        def close_holding(self, ticker, *, gtt_id):
            captured.update(ticker=ticker, gtt_id=gtt_id)
            return {"accepted": True, "order_id": "sell-1", "status": "PLACED"}

    monkeypatch.setattr("src.broker_gateway.ZerodhaBroker", FakeBroker)
    monkeypatch.setattr(cs, "_record_broker_event", lambda *args: True)

    result = cs._close({"ticker": "RELIANCE", "gtt_id": "777", "request_id": "close-gtt-1"})

    assert result["ok"] is True
    assert captured == {"ticker": "RELIANCE", "gtt_id": "777"}


def test_broker_order_event_is_recorded_in_signal_hash_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "reliability.db"))
    order = {"order_id": "abc-123", "status": "PLACED", "accepted": True}

    assert cs._record_broker_event(
        "BROKER_ORDER_ACCEPTED", order, {"ticker": "RELIANCE", "side": "BUY"}
    ) is True
    # Reconciliation is idempotent for the same lifecycle event.
    assert cs._record_broker_event(
        "BROKER_ORDER_ACCEPTED", order, {"ticker": "RELIANCE", "side": "BUY"}
    ) is True

    from src.reliability.ledger import SignalLedger
    from src.reliability.store import ReliabilityStore
    with ReliabilityStore(tmp_path / "reliability.db") as store:
        ledger = SignalLedger(store.connection)
        events = ledger.events("broker:abc-123")
        assert len(events) == 1
        assert events[0]["event_type"] == "BROKER_ORDER_ACCEPTED"
        assert ledger.verify_chain()["valid"] is True


def test_signed_broker_postback_records_status_and_rejects_forgery(tmp_path, monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "reliability.db"))
    monkeypatch.setenv("KITE_API_SECRET", "secret")
    body = {
        "order_id": "order-1",
        "order_timestamp": "2026-08-09 09:15:00",
        "status": "COMPLETE",
        "filled_quantity": 2,
        "average_price": 2450.0,
    }
    body["checksum"] = hashlib.sha256(
        b"order-12026-08-09 09:15:00secret"
    ).hexdigest()

    status, result = cs._broker_postback(body)
    assert status == 200
    assert result["audit_recorded"] is True

    body["order_id"] = "forged"
    status, result = cs._broker_postback(body)
    assert status == 401
    assert result["ok"] is False


# ── Preset config ───────────────────────────────────────────────────────────────

def test_config_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "CONFIG_FILE", tmp_path / "cockpit_config.json")
    # default active is the baseline
    assert sp.active() == sp.DEFAULT
    r = cs._config_set({"preset": "intra_week"})
    assert r["ok"] is True and r["active"] == "intra_week"
    assert sp.active() == "intra_week"
    bad = cs._config_set({"preset": "nope"})
    assert bad["ok"] is False and "unknown preset" in bad["error"]


def test_rm_kwargs_only_risk_keys():
    rk = sp.rm_kwargs("intra_month")
    assert set(rk) == {"atr_multiplier", "min_rr"}   # nothing RiskManager can't take
    assert isinstance(sp.max_hold_days("intra_month"), int)


def test_validation_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "CONFIG_FILE", tmp_path / "cockpit_config.json")
    assert sp.is_validated("swing") is True          # blessed baseline
    assert sp.is_validated("intra_week") is False     # must earn it via walk_forward


def test_release_status_reports_live_channels_blocked(monkeypatch):
    monkeypatch.delenv("BORO_RELIABILITY_MODE", raising=False)
    monkeypatch.delenv("BORO_LIVE_SYMBOL", raising=False)

    result = cs._release_status()

    assert result["approved"] is False
    assert result["telegram_recommendations"] is False
    assert result["broker_orders"] is False
    assert result["live_symbol"] == "RELIANCE"
    assert "CORPORATE_ACTION_REVIEW_MISSING" in result["blockers"]
