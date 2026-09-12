"""Explicit, fail-closed Zerodha order gateway.

This module never treats an accepted order ID as a fill. Live placement requires
either an approved release decision or the explicit private owner acknowledgement,
explicit live execution mode, a deliberate confirmation value, and both Kite
credentials.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class BrokerOrderError(RuntimeError):
    """A broker order was refused or could not be reconciled."""


def _access_token_file() -> Path:
    return Path(os.environ.get("KITE_ACCESS_TOKEN_FILE", "results/kite_access_token"))


def configured_access_token() -> str:
    """Read the backend-only access token, preferring the process environment."""
    token = os.environ.get("KITE_ACCESS_TOKEN", "").strip()
    if token:
        return token
    path = _access_token_file()
    try:
        if path.is_symlink():
            return ""
        mode = path.stat().st_mode
        if mode & 0o077:
            return ""
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def persist_access_token(token: str) -> None:
    """Atomically persist a short-lived token with owner-only permissions."""
    value = str(token).strip()
    if not value or len(value) > 512 or any(ch.isspace() for ch in value):
        raise BrokerOrderError("KITE_ACCESS_TOKEN_INVALID")
    path = _access_token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise BrokerOrderError("KITE_ACCESS_TOKEN_FILE_SYMLINK")
    fd, temporary = tempfile.mkstemp(prefix=".kite-token-", dir=str(path.parent), text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise BrokerOrderError("KITE_ACCESS_TOKEN_PERSIST_FAILED") from error


def _live_symbol() -> str:
    return os.environ.get("BORO_LIVE_SYMBOL", "RELIANCE").strip().upper() or "RELIANCE"


def _assert_live_symbol(ticker: str) -> str:
    """Keep direct gateway callers inside the personal live-trading scope."""
    symbol = str(ticker).strip().upper()
    if symbol != _live_symbol():
        raise BrokerOrderError(f"LIVE_SYMBOL_RESTRICTED:{_live_symbol()}")
    return symbol


def verify_order_postback(payload: dict[str, object], *, api_secret: str | None = None) -> bool:
    """Verify Kite's signed order-status callback without trusting its body."""
    secret = api_secret or os.environ.get("KITE_API_SECRET", "")
    order_id = str(payload.get("order_id", ""))
    timestamp = str(payload.get("order_timestamp", ""))
    checksum = str(payload.get("checksum", ""))
    if not secret or not order_id or not timestamp or not checksum:
        return False
    expected = hashlib.sha256(
        f"{order_id}{timestamp}{secret}".encode("utf-8")
    ).hexdigest()
    return hmac.compare_digest(expected, checksum)


def build_cnc_order_payload(
    *, ticker: str, shares: int, side: str, price: float | None = None
) -> dict[str, str]:
    symbol = str(ticker).strip().upper()
    transaction = str(side).strip().upper()
    if not symbol.isalnum():
        raise BrokerOrderError("invalid NSE tradingsymbol")
    if transaction not in {"BUY", "SELL"}:
        raise BrokerOrderError("transaction_type must be BUY or SELL")
    if type(shares) is not int or shares <= 0:
        raise BrokerOrderError("quantity must be a positive integer")
    if price is not None and price <= 0:
        raise BrokerOrderError("limit price must be positive")
    order = {
        "tradingsymbol": symbol,
        "exchange": "NSE",
        "transaction_type": transaction,
        "order_type": "LIMIT" if price is not None else "MARKET",
        "quantity": str(shares),
        "product": "CNC",
        "validity": "DAY",
    }
    if price is not None:
        order["price"] = str(price)
    return order


def build_protection_gtt_payload(
    *, ticker: str, shares: int, last_price: float,
    stop_price: float, target_price: float,
) -> dict[str, str]:
    symbol = str(ticker).strip().upper()
    if not symbol.isalnum():
        raise BrokerOrderError("invalid NSE tradingsymbol")
    if type(shares) is not int or shares <= 0:
        raise BrokerOrderError("quantity must be a positive integer")
    prices = (last_price, stop_price, target_price)
    if any(price <= 0 for price in prices):
        raise BrokerOrderError("GTT prices must be positive")
    if not stop_price < last_price < target_price:
        raise BrokerOrderError("GTT requires stop < last price < target")
    condition = {
        "exchange": "NSE",
        "tradingsymbol": symbol,
        "trigger_values": [stop_price, target_price],
        "last_price": last_price,
    }
    orders = [
        {
            "exchange": "NSE", "tradingsymbol": symbol,
            "transaction_type": "SELL", "quantity": shares,
            "order_type": "LIMIT", "product": "CNC", "price": stop_price,
        },
        {
            "exchange": "NSE", "tradingsymbol": symbol,
            "transaction_type": "SELL", "quantity": shares,
            "order_type": "LIMIT", "product": "CNC", "price": target_price,
        },
    ]
    return {
        "type": "two-leg",
        "condition": json.dumps(condition, separators=(",", ":")),
        "orders": json.dumps(orders, separators=(",", ":")),
    }


def _release_approved() -> bool:
    if os.environ.get("BORO_RELIABILITY_MODE", "research").lower() not in {"private", "public"}:
        return False
    try:
        from src.reliability.governance import (
            evaluate_release, load_policy, load_release_corporate_action_audit,
        )

        evidence = json.loads(Path(os.environ.get(
            "BORO_RELEASE_EVIDENCE", "data/reliability/current-release-evidence.json"
        )).read_text(encoding="utf-8"))
        policy = load_policy(Path(os.environ.get(
            "BORO_RELEASE_POLICY", "config/reliability-policy.json"
        )))
        return evaluate_release(
            evidence, policy,
            corporate_action_audit=load_release_corporate_action_audit(),
        ).get("approved") is True
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def _personal_live_trading_acknowledged() -> bool:
    """Allow only an explicit, owner-scoped private live-trading opt-in.

    This is intentionally separate from public recommendation release approval:
    an owner may operate their own Reliance account without representing the
    system as an approved public signal service.
    """
    if os.environ.get("BORO_RELIABILITY_MODE", "research").lower() != "private":
        return False
    if os.environ.get("BORO_PERSONAL_LIVE_TRADING_ACK", "") != (
        "I_UNDERSTAND_PERSONAL_LIVE_TRADING"
    ):
        return False
    return True


class ZerodhaBroker:
    """Small form-encoded Kite Connect client with no implicit live mode."""

    def __init__(self, *, base_url: str | None = None):
        self.api_key = os.environ.get("KITE_API_KEY", "")
        self.access_token = configured_access_token()
        self.base_url = (base_url or os.environ.get(
            "KITE_API_BASE_URL", "https://api.kite.trade"
        )).rstrip("/")

    def login_url(self) -> str:
        if not self.api_key:
            raise BrokerOrderError("KITE_API_KEY_MISSING")
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={self.api_key}"

    def exchange_request_token(
        self, request_token: str, *, api_secret: str | None = None
    ) -> dict[str, object]:
        """Exchange a short-lived login token without exposing the API secret."""
        token = str(request_token).strip()
        secret = api_secret or os.environ.get("KITE_API_SECRET", "")
        if not self.api_key or not secret:
            raise BrokerOrderError("KITE_API_KEY_OR_SECRET_MISSING")
        if not token:
            raise BrokerOrderError("KITE_REQUEST_TOKEN_MISSING")
        checksum = hashlib.sha256(
            f"{self.api_key}{token}{secret}".encode("utf-8")
        ).hexdigest()
        request = Request(
            f"{self.base_url}/session/token",
            data=urlencode({
                "api_key": self.api_key,
                "request_token": token,
                "checksum": checksum,
            }).encode(),
            method="POST",
        )
        request.add_header("X-Kite-Version", "3")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise BrokerOrderError(f"KITE_SESSION_EXCHANGE_FAILED: {error}") from error
        if result.get("status") != "success":
            raise BrokerOrderError(
                f"KITE_SESSION_REJECTED: {result.get('message', 'unknown error')}"
            )
        data = result.get("data")
        if not isinstance(data, dict) or not data.get("access_token"):
            raise BrokerOrderError("KITE_ACCESS_TOKEN_MISSING")
        return data

    def profile(self) -> dict[str, object]:
        self._authorize_credentials()
        result = self._request("GET", "/user/profile")
        data = result.get("data")
        if not isinstance(data, dict):
            raise BrokerOrderError("KITE_PROFILE_INVALID")
        return data

    def _authorize_credentials(self) -> None:
        if not self.api_key or not self.access_token:
            raise BrokerOrderError("KITE_CREDENTIALS_MISSING")

    def _authorize_live(self) -> None:
        if not (_release_approved() or _personal_live_trading_acknowledged()):
            raise BrokerOrderError("RELEASE_GATE_NOT_APPROVED")
        if os.environ.get("BORO_EXECUTION_MODE", "paper").lower() != "live":
            raise BrokerOrderError("LIVE_EXECUTION_DISABLED")
        if os.environ.get("BORO_LIVE_CONFIRMATION") != "I_UNDERSTAND_LIVE_ORDER":
            raise BrokerOrderError("LIVE_CONFIRMATION_REQUIRED")
        self._authorize_credentials()
        try:
            from src.control_server import _broker_session_status
            session = _broker_session_status()
        except (ImportError, OSError, ValueError, TypeError):
            raise BrokerOrderError("BROKER_SESSION_STATUS_UNAVAILABLE")
        if session.get("valid") is not True:
            raise BrokerOrderError(str(session.get("reason", "BROKER_SESSION_NOT_VALIDATED")))

    def _authorize_observation(self) -> None:
        """Authorize read-only broker observation without opening execution."""
        self._authorize_credentials()
        try:
            from src.control_server import _broker_session_status
            session = _broker_session_status()
        except (ImportError, OSError, ValueError, TypeError):
            raise BrokerOrderError("BROKER_SESSION_STATUS_UNAVAILABLE")
        if session.get("valid") is not True:
            raise BrokerOrderError(str(session.get("reason", "BROKER_SESSION_NOT_VALIDATED")))

    def _request(self, method: str, path: str, payload: dict[str, str] | None = None) -> dict:
        body = urlencode(payload or {}).encode() if payload is not None else None
        request = Request(f"{self.base_url}{path}", data=body, method=method)
        request.add_header("X-Kite-Version", "3")
        request.add_header("Authorization", f"token {self.api_key}:{self.access_token}")
        if body is not None:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise BrokerOrderError(f"KITE_REQUEST_FAILED: {error}") from error
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as error:
            raise BrokerOrderError("KITE_RESPONSE_INVALID") from error
        if result.get("status") != "success":
            raise BrokerOrderError(f"KITE_ORDER_REJECTED: {result.get('message', 'unknown error')}")
        return result

    def place_cnc_order(
        self, ticker: str, shares: int, side: str, *, price: float | None = None,
        stop_price: float | None = None,
    ) -> dict[str, object]:
        self._authorize_live()
        symbol = _assert_live_symbol(ticker)
        transaction = str(side).strip().upper()
        from src.reliability.controls import operational_kill_switch_active
        if operational_kill_switch_active() and transaction != "SELL":
            raise BrokerOrderError("OPERATIONAL_KILL_SWITCH_ACTIVE")
        if transaction == "BUY":
            if price is None or price <= 0:
                raise BrokerOrderError("LIVE_BUY_LIMIT_PRICE_REQUIRED")
            if stop_price is None or stop_price <= 0 or not stop_price < price:
                raise BrokerOrderError("LIVE_BUY_STOP_PRICE_REQUIRED")
            try:
                capital = float(os.environ.get("BORO_LIVE_CAPITAL", "50000"))
                max_risk_pct = float(os.environ.get("BORO_LIVE_MAX_RISK_PCT", "0.02"))
                max_notional_pct = float(os.environ.get("BORO_LIVE_MAX_NOTIONAL_PCT", "0.20"))
            except (TypeError, ValueError) as error:
                raise BrokerOrderError("live risk policy must contain numeric values") from error
            risk_amount = (price - stop_price) * shares
            notional = price * shares
            if risk_amount > capital * max_risk_pct:
                raise BrokerOrderError("LIVE_RISK_LIMIT_EXCEEDED")
            if notional > capital * max_notional_pct:
                raise BrokerOrderError("LIVE_NOTIONAL_LIMIT_EXCEEDED")
        payload = build_cnc_order_payload(
            ticker=symbol, shares=shares, side=transaction, price=price
        )
        result = self._request("POST", "/orders/regular", payload)
        order_id = result.get("data", {}).get("order_id")
        if not order_id:
            raise BrokerOrderError("KITE_ORDER_ID_MISSING")
        return {
            "accepted": True,
            "execution_confirmed": False,
            "status": "PLACED",
            "order_id": str(order_id),
            "payload": payload,
        }

    def place_protection_gtt(
        self, ticker: str, shares: int, *, last_price: float,
        stop_price: float, target_price: float,
    ) -> dict[str, object]:
        self._authorize_live()
        symbol = _assert_live_symbol(ticker)
        payload = build_protection_gtt_payload(
            ticker=symbol, shares=shares, last_price=last_price,
            stop_price=stop_price, target_price=target_price,
        )
        result = self._request("POST", "/gtt/triggers", payload)
        trigger_id = result.get("data", {}).get("trigger_id")
        if trigger_id is None:
            raise BrokerOrderError("KITE_GTT_TRIGGER_ID_MISSING")
        return {
            "protection_created": True,
            "gtt_id": str(trigger_id),
            "gtt_type": "two-leg",
            "gtt_payload": payload,
        }

    def order_status(self, order_id: str) -> dict[str, object]:
        self._authorize_observation()
        value = str(order_id).strip()
        if not value.isdigit() or int(value) <= 0:
            raise BrokerOrderError("order_id must be a positive integer")
        result = self._request("GET", f"/orders/{value}")
        history = result.get("data")
        if not isinstance(history, list) or not history:
            raise BrokerOrderError("KITE_ORDER_HISTORY_MISSING")
        latest = history[-1]
        return {
            "order_id": value,
            "status": latest.get("status"),
            "execution_confirmed": latest.get("status") == "COMPLETE",
            "raw": latest,
        }

    def orders(self) -> list[dict[str, object]]:
        """Retrieve the broker's current daily order book."""
        self._authorize_observation()
        result = self._request("GET", "/orders")
        data = result.get("data")
        if not isinstance(data, list):
            raise BrokerOrderError("KITE_ORDERS_RESPONSE_INVALID")
        return [row for row in data if isinstance(row, dict)]

    def cancel_order(self, order_id: str) -> dict[str, object]:
        """Request cancellation of an open or pending regular CNC order."""
        self._authorize_live()
        value = str(order_id).strip()
        if not value.isdigit() or int(value) <= 0:
            raise BrokerOrderError("order_id must be a positive integer")
        result = self._request("DELETE", f"/orders/regular/{value}")
        data = result.get("data")
        if not isinstance(data, dict) or str(data.get("order_id", "")) != value:
            raise BrokerOrderError("KITE_ORDER_CANCEL_RESPONSE_INVALID")
        return {"order_id": value, "cancel_requested": True, "status": "CANCEL_PENDING"}

    def gtt_status(self, trigger_id: str) -> dict[str, object]:
        self._authorize_observation()
        value = str(trigger_id).strip()
        if not value.isdigit() or int(value) <= 0:
            raise BrokerOrderError("gtt_id must be a positive integer")
        result = self._request("GET", f"/gtt/triggers/{value}")
        trigger = result.get("data")
        if not isinstance(trigger, dict):
            raise BrokerOrderError("KITE_GTT_RESPONSE_INVALID")
        return {
            "gtt_id": value,
            "status": trigger.get("status"),
            "raw": trigger,
        }

    def _cancel_gtt_request(self, value: str) -> dict[str, object]:
        """Issue the already-validated broker DELETE for a GTT."""
        value = str(value).strip()
        result = self._request("DELETE", f"/gtt/triggers/{value}")
        data = result.get("data")
        if not isinstance(data, dict) or not data.get("trigger_id"):
            raise BrokerOrderError("KITE_GTT_DELETE_RESPONSE_INVALID")
        return {"gtt_id": value, "cancelled": True, "status": "DELETED"}

    def cancel_gtt(self, trigger_id: str) -> dict[str, object]:
        """Delete only an active GTT protecting the configured live symbol."""
        self._authorize_live()
        value = str(trigger_id).strip()
        if not value.isdigit() or int(value) <= 0:
            raise BrokerOrderError("gtt_id must be a positive integer")
        protection = self.gtt_status(value)
        raw = protection.get("raw") or {}
        condition = raw.get("condition") if isinstance(raw, dict) else None
        protected_symbol = str(condition.get("tradingsymbol", "")).upper() if isinstance(condition, dict) else ""
        live_symbol = os.environ.get("BORO_LIVE_SYMBOL", "RELIANCE").strip().upper() or "RELIANCE"
        if protected_symbol != live_symbol:
            raise BrokerOrderError("LIVE_GTT_SYMBOL_MISMATCH")
        if str(protection.get("status", "")).lower() != "active":
            raise BrokerOrderError("LIVE_GTT_NOT_ACTIVE")
        return self._cancel_gtt_request(value)

    def holdings(self) -> list[dict[str, object]]:
        self._authorize_observation()
        result = self._request("GET", "/portfolio/holdings")
        holdings = result.get("data")
        if not isinstance(holdings, list):
            raise BrokerOrderError("KITE_HOLDINGS_INVALID")
        return holdings

    def close_holding(self, ticker: str, *, gtt_id: str | None = None) -> dict[str, object]:
        """Cancel protection only after confirming a sellable holding exists."""
        self._authorize_live()
        symbol = _assert_live_symbol(ticker)
        holding = next((row for row in self.holdings()
                        if row.get("exchange") == "NSE"
                        and str(row.get("tradingsymbol", "")).upper() == symbol), None)
        if holding is None:
            raise BrokerOrderError("LIVE_HOLDING_NOT_FOUND")
        quantity = int(holding.get("quantity", 0)) - int(holding.get("used_quantity", 0))
        if quantity <= 0:
            raise BrokerOrderError("LIVE_HOLDING_HAS_NO_SELLABLE_QUANTITY")
        cancelled = None
        if gtt_id:
            protection = self.gtt_status(gtt_id)
            raw = protection.get("raw") or {}
            condition = raw.get("condition") if isinstance(raw, dict) else None
            protected_symbol = str(condition.get("tradingsymbol", "")).upper() if isinstance(condition, dict) else ""
            if protected_symbol != symbol:
                raise BrokerOrderError("LIVE_GTT_SYMBOL_MISMATCH")
            if str(protection.get("status", "")).lower() != "active":
                raise BrokerOrderError("LIVE_GTT_NOT_ACTIVE")
            cancelled = self._cancel_gtt_request(str(gtt_id).strip())
        try:
            order = self.place_cnc_order(symbol, quantity, "SELL")
        except BrokerOrderError as error:
            if cancelled:
                raise BrokerOrderError(
                    f"GTT_CANCELLED_SELL_FAILED: {error}"
                ) from error
            raise
        if cancelled:
            order["gtt_cancelled"] = cancelled
        return order
