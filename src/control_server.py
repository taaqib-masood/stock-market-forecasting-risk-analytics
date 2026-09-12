"""
Control server — lets the dashboard run the paper-trading commands without a
terminal. A tiny stdlib HTTP server that the static dashboard calls via fetch().

Endpoints (all JSON):
    GET  /health          liveness
    GET  /portfolio       paper portfolio value + recent trades (read-only)
    GET  /positions       open positions only, marked to market (cockpit table)
    GET  /readiness       retained release decision and channel capabilities
    POST /telegram/webhook/register  register configured HTTPS consent webhook
    GET  /broker/profile  validate the current backend-only Kite session
    GET  /broker/login-url  return the safe Zerodha login URL
    POST /broker/session/exchange {request_token} exchange and validate a session
    GET  /broker/reconcile  reconcile current holdings and the daily order book
    GET  /broker/risk-preview?ticker=RELIANCE&shares=1&price=...&stop=...&target=...
                         read-only live-order risk and protection preflight
    GET  /broker/orders  read the current daily broker order book
    POST /broker/order-cancel {order_id}  cancel an open/pending regular order
    GET  /broker/gtt-status?gtt_id=...  read-only GTT reconciliation
    POST /broker/gtt-cancel {gtt_id}  cancel protection before a manual close
    POST /broker/gtt/protect {ticker,shares,price,stop,target,request_id}
                                  retry protection for an accepted unprotected BUY
    POST /broker/postback  signed Kite order-status callback
    GET  /config          active holding-period preset + the full preset list
    POST /scan            run the live scan + refresh the dashboard feed
    POST /daily-briefing  full daily briefing (scan -> paper buys -> notify)
    POST /auto-close      close positions at stop/target/max-hold
    POST /buy             {ticker,shares,price,stop,target} paper BUY or gated Reliance live BUY
    POST /close           {ticker,gtt_id} close a HELD position in full (only halal exit)
    POST /config          {preset} switch active holding-period preset

Cockpit note: /buy and /close are deliberately NOT exposed over the public
serverless dispatch (netlify/functions/dispatch.js) — discrete trade triggers run
local-mode only, behind the token.

The POST actions shell out to the SAME modules you'd run by hand
(`python -m src.<module>`), so "the dashboard runs the commands" literally means
that — no duplicated logic.

SECURITY — read this before exposing it:
  * Every authenticated request must carry the shared token in the
    `X-Control-Token` header. URL tokens are rejected so credentials do not leak
    through browser history, referrers, or proxy logs. If CONTROL_TOKEN is unset
    the server refuses to start.
  * The default bind host is 127.0.0.1 and the default CORS origin is the local
    cockpit. Hosted use must explicitly set CONTROL_BIND_HOST and
    CONTROL_ALLOW_ORIGIN and must use TLS.
  * It can place paper or explicitly gated Zerodha orders. Do not expose it to
    the public internet without TLS, a narrowly scoped origin, and the token.

Run:
    CONTROL_TOKEN=yoursecret python -m src.control_server          # port 8765
    CONTROL_TOKEN=yoursecret python -m src.control_server --port 9000
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPITAL = os.getenv("CONTROL_CAPITAL", "50000")
TOKEN = os.getenv("CONTROL_TOKEN", "")
# Restrict which origin may call us in a browser (the deployed dashboard URL).
# The safe default is local-only; hosted use must opt into its exact origin.
ALLOW_ORIGIN = os.getenv("CONTROL_ALLOW_ORIGIN", "http://localhost:8765")
BIND_HOST = os.getenv("CONTROL_BIND_HOST", "127.0.0.1")
TIMEOUT = int(os.getenv("CONTROL_TIMEOUT", "600"))
MAX_BODY_BYTES = int(os.getenv("CONTROL_MAX_BODY_BYTES", "65536"))

_CANCELLABLE_ORDER_STATUSES = {
    "OPEN", "OPEN PENDING", "TRIGGER PENDING", "MODIFY PENDING",
    "AMO REQ RECEIVED", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED",
    "MODIFY VALIDATION PENDING",
}


def _live_symbol() -> str:
    return os.environ.get("BORO_LIVE_SYMBOL", "RELIANCE").strip().upper() or "RELIANCE"


def _broker_session_fingerprint() -> str:
    # Keep the token backend-only, but fingerprint the same env-or-owner-only
    # file source used by ZerodhaBroker. Otherwise the browser login exchange
    # succeeds while readiness still reports the file-backed session as absent.
    try:
        from src.broker_gateway import configured_access_token
        token = configured_access_token()
    except (OSError, TypeError, ValueError):
        token = ""
    return hashlib.sha256(token.encode()).hexdigest() if token else ""


def _broker_session_database() -> str:
    return os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")


def _record_broker_session(*, valid: bool, profile: dict | None = None) -> None:
    fingerprint = _broker_session_fingerprint()
    if not fingerprint:
        return
    database = _broker_session_database()
    if database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS broker_session_checks (
                token_fingerprint TEXT PRIMARY KEY,
                checked_at TEXT NOT NULL,
                status TEXT NOT NULL,
                user_id TEXT
            )"""
        )
        connection.execute(
            """INSERT INTO broker_session_checks
               (token_fingerprint, checked_at, status, user_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(token_fingerprint) DO UPDATE SET
                 checked_at=excluded.checked_at,
                 status=excluded.status,
                 user_id=excluded.user_id""",
            (fingerprint, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "VALID" if valid else "INVALID", str((profile or {}).get("user_id", "")) or None),
        )
        connection.commit()
    finally:
        connection.close()


def _broker_session_status() -> dict[str, object]:
    fingerprint = _broker_session_fingerprint()
    max_age = int(os.environ.get("BORO_BROKER_SESSION_MAX_AGE_SECONDS", "3600"))
    if not fingerprint:
        return {"valid": False, "reason": "KITE_ACCESS_TOKEN_MISSING", "max_age_seconds": max_age}
    database = _broker_session_database()
    if database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT checked_at, status, user_id FROM broker_session_checks WHERE token_fingerprint = ?",
            (fingerprint,),
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    finally:
        connection.close()
    if row is None:
        return {"valid": False, "reason": "BROKER_SESSION_NOT_VALIDATED", "max_age_seconds": max_age}
    try:
        checked_at = datetime.fromisoformat(str(row["checked_at"]).replace("Z", "+00:00"))
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        age = max(0, int((datetime.now(timezone.utc) - checked_at.astimezone(timezone.utc)).total_seconds()))
    except (TypeError, ValueError):
        return {"valid": False, "reason": "BROKER_SESSION_TIMESTAMP_INVALID", "max_age_seconds": max_age}
    valid = row["status"] == "VALID" and age <= max_age
    return {
        "valid": valid,
        "status": row["status"],
        "checked_at": row["checked_at"],
        "age_seconds": age,
        "max_age_seconds": max_age,
        "user_id": row["user_id"],
        "reason": "verified" if valid else "BROKER_SESSION_VALIDATION_EXPIRED",
    }


def _live_risk_policy() -> dict[str, float]:
    """Return the same default 2% risk discipline used by signal sizing."""
    try:
        capital = float(os.environ.get("BORO_LIVE_CAPITAL", CAPITAL))
        max_risk_pct = float(os.environ.get("BORO_LIVE_MAX_RISK_PCT", "0.02"))
        max_notional_pct = float(os.environ.get("BORO_LIVE_MAX_NOTIONAL_PCT", "0.20"))
    except (TypeError, ValueError) as error:
        raise ValueError("live risk policy must contain numeric values") from error
    if capital <= 0 or not 0 < max_risk_pct <= 1 or not 0 < max_notional_pct <= 1:
        raise ValueError("live risk policy values are outside safe bounds")
    return {
        "capital": capital,
        "max_risk_pct": max_risk_pct,
        "max_notional_pct": max_notional_pct,
    }


def _validate_live_risk(shares: int, price: float, stop_price: float) -> dict[str, float] | None:
    try:
        policy = _live_risk_policy()
    except ValueError as error:
        return {"error": str(error)}
    risk_amount = (price - stop_price) * shares
    notional = price * shares
    max_risk = policy["capital"] * policy["max_risk_pct"]
    max_notional = policy["capital"] * policy["max_notional_pct"]
    if risk_amount > max_risk:
        return {"error": "LIVE_RISK_LIMIT_EXCEEDED", "risk_amount": risk_amount,
                "max_risk": max_risk}
    if notional > max_notional:
        return {"error": "LIVE_NOTIONAL_LIMIT_EXCEEDED", "notional": notional,
                "max_notional": max_notional}
    return None


def _broker_risk_preview(params: dict[str, list[str]] | dict[str, str]) -> dict:
    """Return a secret-free, read-only preflight for a Reliance live BUY."""
    def value(name: str) -> str:
        raw = params.get(name, "")
        return str(raw[0] if isinstance(raw, list) else raw).strip()

    ticker = value("ticker").upper()
    if ticker != _live_symbol():
        return {"ok": False, "error": f"LIVE_SYMBOL_RESTRICTED:{_live_symbol()}"}
    try:
        shares = int(value("shares"))
        price = float(value("price"))
        stop = float(value("stop"))
        target = float(value("target"))
        policy = _live_risk_policy()
    except (TypeError, ValueError):
        return {"ok": False, "error": "shares, price, stop, and target must be numeric"}
    if shares <= 0 or price <= 0 or stop <= 0 or target <= 0:
        return {"ok": False, "error": "shares and all live BUY prices must be positive"}
    if not stop < price < target:
        return {"ok": False, "error": "LIVE_GTT_REQUIRES_STOP_BELOW_PRICE_BELOW_TARGET"}
    risk_amount = (price - stop) * shares
    notional = price * shares
    max_risk = policy["capital"] * policy["max_risk_pct"]
    max_notional = policy["capital"] * policy["max_notional_pct"]
    risk_error = _validate_live_risk(shares, price, stop)
    try:
        from src.broker_gateway import build_protection_gtt_payload
        build_protection_gtt_payload(
            ticker=ticker, shares=shares, last_price=price,
            stop_price=stop, target_price=target,
        )
        protection_valid = True
    except Exception:  # noqa: BLE001
        protection_valid = False
    return {
        "ok": risk_error is None and protection_valid,
        "ticker": ticker,
        "shares": shares,
        "price": price,
        "stop": stop,
        "target": target,
        "risk_amount": risk_amount,
        "max_risk": max_risk,
        "notional": notional,
        "max_notional": max_notional,
        "risk_pct": policy["max_risk_pct"],
        "notional_pct": policy["max_notional_pct"],
        "protection_valid": protection_valid,
        "error": risk_error.get("error") if risk_error else None,
    }


def _live_buy_request_hash(body: dict) -> tuple[str, str] | tuple[None, str]:
    request_id = str(body.get("request_id", "")).strip()
    if not request_id or len(request_id) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", request_id):
        return None, "LIVE_REQUEST_ID_REQUIRED"
    request_payload = json.dumps({
        "ticker": str(body.get("ticker", "")).strip().upper(),
        "shares": int(body.get("shares", 0)),
        "price": float(body.get("price", 0) or 0),
        "stop": float(body.get("stop", 0) or 0),
        "target": float(body.get("target", 0) or 0),
    }, sort_keys=True, separators=(",", ":"))
    return request_id, hashlib.sha256(request_payload.encode()).hexdigest()


def _claim_live_buy_request(body: dict) -> dict | None:
    """Claim a live BUY once; a retry returns the original result or stays blocked."""
    request_id, request_hash = _live_buy_request_hash(body)
    if request_id is None:
        return {"ok": False, "error": request_hash}
    database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    path = Path(database)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS live_buy_requests (
                request_id TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = connection.execute(
            "SELECT request_hash, status, result_json FROM live_buy_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is not None:
            if row[0] != request_hash:
                return {"ok": False, "error": "LIVE_REQUEST_ID_REUSED"}
            if row[2]:
                return json.loads(row[2])
            return {"ok": False, "error": "LIVE_ORDER_REQUEST_IN_PROGRESS", "request_id": request_id}
        connection.execute(
            "INSERT INTO live_buy_requests VALUES (?, ?, 'PENDING', NULL, ?, ?)",
            (request_id, request_hash, now, now),
        )
        connection.commit()
        return None
    finally:
        connection.close()


def _finish_live_buy_request(request_id: str, result: dict) -> None:
    database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    connection = sqlite3.connect(str(database))
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            "UPDATE live_buy_requests SET status = ?, result_json = ?, updated_at = ? WHERE request_id = ?",
            ("COMPLETED" if result.get("ok") else "REJECTED",
             json.dumps(result, sort_keys=True), now, request_id),
        )
        connection.commit()
    finally:
        connection.close()


def _live_protection_request_hash(body: dict) -> tuple[str, str] | tuple[None, str]:
    request_id = str(body.get("request_id", "")).strip()
    if not request_id or len(request_id) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", request_id):
        return None, "LIVE_PROTECTION_REQUEST_ID_REQUIRED"
    try:
        request_payload = json.dumps({
            "ticker": str(body.get("ticker", "")).strip().upper(),
            "shares": int(body.get("shares", 0)),
            "price": float(body.get("price", 0) or 0),
            "stop": float(body.get("stop", 0) or 0),
            "target": float(body.get("target", 0) or 0),
            "order_id": str(body.get("order_id", "")).strip(),
        }, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None, "LIVE_PROTECTION_INPUT_INVALID"
    return request_id, hashlib.sha256(request_payload.encode()).hexdigest()


def _claim_live_protection_request(body: dict) -> dict | None:
    """Claim a protection retry so a browser retry cannot create two GTTs."""
    request_id, request_hash = _live_protection_request_hash(body)
    if request_id is None:
        return {"ok": False, "error": request_hash}
    database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    path = Path(database)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS live_gtt_protection_requests (
                request_id TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = connection.execute(
            "SELECT request_hash, result_json FROM live_gtt_protection_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is not None:
            if row[0] != request_hash:
                return {"ok": False, "error": "LIVE_PROTECTION_REQUEST_ID_REUSED"}
            if row[1]:
                return json.loads(row[1])
            return {"ok": False, "error": "LIVE_PROTECTION_REQUEST_IN_PROGRESS", "request_id": request_id}
        connection.execute(
            "INSERT INTO live_gtt_protection_requests VALUES (?, ?, 'PENDING', NULL, ?, ?)",
            (request_id, request_hash, now, now),
        )
        connection.commit()
        return None
    finally:
        connection.close()


def _finish_live_protection_request(request_id: str, result: dict) -> None:
    database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    connection = sqlite3.connect(str(database))
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            """UPDATE live_gtt_protection_requests
               SET status = ?, result_json = ?, updated_at = ?
               WHERE request_id = ?""",
            ("COMPLETED" if result.get("ok") else "REJECTED",
             json.dumps(result, sort_keys=True), now, request_id),
        )
        connection.commit()
    finally:
        connection.close()


def _live_close_request_hash(body: dict) -> tuple[str, str] | tuple[None, str]:
    request_id = str(body.get("request_id", "")).strip()
    if not request_id or len(request_id) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", request_id):
        return None, "LIVE_CLOSE_REQUEST_ID_REQUIRED"
    request_payload = json.dumps({
        "ticker": str(body.get("ticker", "")).strip().upper(),
        "gtt_id": str(body.get("gtt_id", "")).strip(),
    }, sort_keys=True, separators=(",", ":"))
    return request_id, hashlib.sha256(request_payload.encode()).hexdigest()


def _claim_live_close_request(body: dict) -> dict | None:
    """Claim a live CLOSE once so browser retries cannot submit duplicate sells."""
    request_id, request_hash = _live_close_request_hash(body)
    if request_id is None:
        return {"ok": False, "error": request_hash}
    database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    path = Path(database)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS live_close_requests (
                request_id TEXT PRIMARY KEY,
                request_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = connection.execute(
            "SELECT request_hash, status, result_json FROM live_close_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if row is not None:
            if row[0] != request_hash:
                return {"ok": False, "error": "LIVE_CLOSE_REQUEST_ID_REUSED"}
            if row[2]:
                return json.loads(row[2])
            return {"ok": False, "error": "LIVE_CLOSE_REQUEST_IN_PROGRESS", "request_id": request_id}
        connection.execute(
            "INSERT INTO live_close_requests VALUES (?, ?, 'PENDING', NULL, ?, ?)",
            (request_id, request_hash, now, now),
        )
        connection.commit()
        return None
    finally:
        connection.close()


def _finish_live_close_request(request_id: str, result: dict) -> None:
    database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    connection = sqlite3.connect(str(database))
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            "UPDATE live_close_requests SET status = ?, result_json = ?, updated_at = ? WHERE request_id = ?",
            ("COMPLETED" if result.get("ok") else "REJECTED",
             json.dumps(result, sort_keys=True), now, request_id),
        )
        connection.commit()
    finally:
        connection.close()


def _run_module(module: str, *args: str) -> dict:
    """Run `python -m src.<module> <args>` from the repo root; capture output."""
    cmd = [sys.executable, "-m", f"src.{module}", *args]
    try:
        p = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                           text=True, timeout=TIMEOUT)
        out = (p.stdout or "")[-4000:]
        err = (p.stderr or "")[-1000:]
        return {"ok": p.returncode == 0, "returncode": p.returncode,
                "stdout": out, "stderr": err, "cmd": " ".join(cmd[2:])}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {TIMEOUT}s", "cmd": " ".join(cmd[2:])}


def _portfolio() -> dict:
    try:
        from src import paper_trader as pt
        state = pt._load()
        pv = pt.portfolio_value(state)
        stats = pt.trade_stats(state) if hasattr(pt, "trade_stats") else {}
        return {"ok": True, **pv, "stats": stats, "trades": state.get("trades", [])[-10:]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _positions() -> dict:
    """Open positions only, marked to market — for the cockpit's positions table."""
    try:
        if os.environ.get("BORO_EXECUTION_MODE", "paper").lower() == "live":
            broker, error = _broker_readiness(read_only=True)
            if error:
                return error
            holdings = broker.holdings()
            positions = {}
            total_value = 0.0
            for holding in holdings:
                ticker = str(holding.get("tradingsymbol", "")).strip().upper()
                quantity = int(holding.get("quantity", 0) or 0)
                if not ticker or quantity <= 0:
                    continue
                average_price = float(holding.get("average_price", 0) or 0)
                current_price = float(holding.get("last_price", 0) or 0)
                unrealised = float(holding.get("pnl", 0) or 0)
                market_value = current_price * quantity
                total_value += market_value
                positions[ticker] = {
                    "shares": quantity,
                    "avg_entry": average_price,
                    "current_price": current_price,
                    "unrealised": unrealised,
                    "unrealised_pct": round(
                        unrealised / (average_price * quantity) * 100, 2
                    ) if average_price > 0 else 0.0,
                    "market_value": market_value,
                }
            return {"ok": True, "live": True, "cash": None,
                    "total_val": round(total_value, 2), "positions": positions}
        from src import paper_trader as pt
        pv = pt.portfolio_value(pt._load())
        return {"ok": True, "live": False, "cash": pv["cash"], "total_val": pv["total_val"],
                "positions": pv["marked"]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _telegram_audience_status() -> dict:
    try:
        from src.reliability.telegram_audience import TelegramAudience
        from src.reliability.outbox import DeliveryOutbox
        from src.reliability.store import ReliabilityStore
        from src.telegram_provider import webhook_secret_is_valid
        database = os.environ.get(
            "BORO_TELEGRAM_AUDIENCE_DB",
            os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db"),
        )
        outbox_database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
        terms_version = os.environ.get("BORO_TELEGRAM_TERMS_VERSION", "terms-v1")
        with TelegramAudience(database) as audience:
            all_active = audience.active_subscribers()
            active = audience.active_subscribers(terms_version)
        with ReliabilityStore(outbox_database) as store:
            delivery = DeliveryOutbox(store.connection).metrics()
        consent_versions = {}
        for record in active:
            version = record["consent_version"]
            consent_versions[version] = consent_versions.get(version, 0) + 1
        return {
            "configured": bool(os.environ.get("TELEGRAM_TOKEN")),
            "webhook_secret_configured": webhook_secret_is_valid(
                os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
            ),
            "terms_version": os.environ.get("BORO_TELEGRAM_TERMS_VERSION", "terms-v1"),
            "active_recipients": len(active),
            "stale_consent_recipients": len(all_active) - len(active),
            "active_consent_versions": consent_versions,
            "delivery": delivery,
        }
    except (OSError, TypeError, ValueError):
        return {
            "configured": False,
            "webhook_secret_configured": False,
            "terms_version": os.environ.get("BORO_TELEGRAM_TERMS_VERSION", "terms-v1"),
            "active_recipients": 0,
            "active_consent_versions": {},
            "delivery": {"error": "TELEGRAM_OUTBOX_UNAVAILABLE"},
            "error": "TELEGRAM_AUDIENCE_UNAVAILABLE",
        }


def _telegram_register_webhook() -> dict:
    """Register only the configured HTTPS consent webhook; never send a signal."""
    try:
        from src.telegram_provider import register_webhook
        return register_webhook()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "blockers": ["TELEGRAM_WEBHOOK_REGISTRATION_UNAVAILABLE"],
            "error_type": type(exc).__name__,
        }


def _telegram_provider_health() -> dict[str, object]:
    """Return secret-free provider verification for readiness decisions."""
    try:
        from src.telegram_provider import provider_status
        result = provider_status()
        return result if isinstance(result, dict) else {
            "ok": False, "blockers": ["TELEGRAM_PROVIDER_STATUS_INVALID"]
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "blockers": ["TELEGRAM_PROVIDER_STATUS_UNAVAILABLE"],
            "error_type": type(exc).__name__,
        }


def _telegram_configuration_blockers() -> list[str]:
    """Return local Telegram setup blockers without contacting the provider."""
    from src.telegram_provider import _valid_webhook_url, webhook_secret_is_valid

    blockers = []
    if not os.environ.get("TELEGRAM_TOKEN", "").strip():
        blockers.append("TELEGRAM_TOKEN_MISSING")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not secret:
        blockers.append("TELEGRAM_WEBHOOK_SECRET_MISSING")
    elif not webhook_secret_is_valid(secret):
        blockers.append("TELEGRAM_WEBHOOK_SECRET_INVALID")
    url = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()
    if not url:
        blockers.append("TELEGRAM_WEBHOOK_URL_MISSING")
    elif not _valid_webhook_url(url):
        blockers.append("TELEGRAM_WEBHOOK_URL_INVALID")
    return blockers


def _telegram_retry_outbox() -> dict:
    """Run one authenticated, gated retry pass for due Telegram messages."""
    try:
        from scripts.deliver_telegram_outbox import deliver_outbox
        return deliver_outbox()
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        return {
            "ok": False,
            "blocked": False,
            "reason": "TELEGRAM_OUTBOX_RETRY_UNAVAILABLE",
            "error_type": type(exc).__name__,
        }


def _telegram_webhook(body: dict, supplied_secret: str) -> tuple[int, dict]:
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if not expected or not hmac.compare_digest(supplied_secret, expected):
        return 401, {"ok": False, "error": "invalid webhook secret"}
    try:
        from src.reliability.telegram_audience import TelegramAudience
        from src.telegram_webhook import handle_update
        database = os.environ.get(
            "BORO_TELEGRAM_AUDIENCE_DB",
            os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db"),
        )
        with TelegramAudience(database) as audience:
            update_id = body.get("update_id")
            if update_id is not None and not audience.claim_update(
                update_id, now=datetime.now(timezone.utc)
            ):
                return 200, {"ok": True, "duplicate": True, "update_id": int(update_id)}
            result = handle_update(
                body,
                audience,
                consent_version=os.environ.get("BORO_TELEGRAM_TERMS_VERSION", "terms-v1"),
                now=datetime.now(timezone.utc),
            )
        reply_sent = False
        if result.get("reply") and result.get("chat_id") and os.environ.get("TELEGRAM_TOKEN"):
            try:
                from src.notify import send_raw
                send_raw(result["reply"], chat_id=result["chat_id"])
                reply_sent = True
            except Exception:  # noqa: BLE001
                # A reply failure must not make Telegram retry the consent update.
                reply_sent = False
        return 200, {"ok": True, **result, "reply_sent": reply_sent}
    except (TypeError, ValueError, OSError) as error:
        return 400, {"ok": False, "error": str(error)}


def _broker_postback(body: dict) -> tuple[int, dict]:
    try:
        from src.broker_gateway import verify_order_postback
        if not verify_order_postback(body):
            return 401, {"ok": False, "error": "invalid broker postback checksum"}
        order_id = str(body.get("order_id", "")).strip()
        status = str(body.get("status", "UNKNOWN")).strip().upper()
        if not order_id:
            return 400, {"ok": False, "error": "order_id is required"}
        recorded = _record_broker_event(
            "BROKER_ORDER_STATUS_" + status,
            {"order_id": order_id, "status": status},
            {"postback": True, "order_timestamp": body.get("order_timestamp"),
             "filled_quantity": body.get("filled_quantity"),
             "average_price": body.get("average_price")},
        )
        return 200, {"ok": True, "order_id": order_id, "status": status,
                     "audit_recorded": recorded}
    except (TypeError, ValueError, OSError) as error:
        return 400, {"ok": False, "error": str(error)}


def _release_status() -> dict:
    """Expose the same release decision used by recommendation delivery."""
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
        decision = evaluate_release(
            evidence, policy,
            corporate_action_audit=load_release_corporate_action_audit(),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        decision = {"approved": False, "blockers": ["RELEASE_EVIDENCE_INVALID"], "error": str(error)}
    release_approved = decision.get("approved") is True
    from src.reliability.controls import operational_kill_switch_active
    kill_switch_active = operational_kill_switch_active()
    if kill_switch_active:
        decision = {
            **decision,
            "approved": False,
            "blockers": list(dict.fromkeys([
                *decision.get("blockers", []), "OPERATIONAL_KILL_SWITCH_ACTIVE",
            ])),
        }
    mode = os.environ.get("BORO_RELIABILITY_MODE", "research").lower()
    live_symbol = _live_symbol()
    try:
        risk_policy = _live_risk_policy()
    except ValueError as error:
        risk_policy = {"error": str(error)}
    try:
        broker_session = _broker_session_status()
    except (OSError, sqlite3.Error, TypeError, ValueError) as error:
        broker_session = {"valid": False, "reason": "BROKER_SESSION_STATUS_UNAVAILABLE", "error": str(error)}
    approved = release_approved
    personal_live_acknowledged = (
        mode == "private"
        and os.environ.get("BORO_PERSONAL_LIVE_TRADING_ACK")
        == "I_UNDERSTAND_PERSONAL_LIVE_TRADING"
    )
    live_execution_ready = (
        (approved or personal_live_acknowledged)
        and mode in {"private", "public"}
        and os.environ.get("BORO_EXECUTION_MODE", "paper").lower() == "live"
        and os.environ.get("BORO_LIVE_CONFIRMATION") == "I_UNDERSTAND_LIVE_ORDER"
        and bool(os.environ.get("KITE_API_KEY"))
        and bool(_broker_session_fingerprint())
        and broker_session.get("valid") is True
    )
    live_ready = live_execution_ready and not kill_switch_active
    live_exits = live_execution_ready
    broker_credentials_configured = bool(
        os.environ.get("KITE_API_KEY") and _broker_session_fingerprint()
    )
    audience = _telegram_audience_status()
    delivery = audience.get("delivery", {})
    delivery_healthy = (
        isinstance(delivery, dict)
        and "error" not in delivery
        and int(delivery.get("dead_letter", 0)) == 0
        and int(delivery.get("unreconciled", 0)) == 0
    )
    provider = {"ok": False, "blockers": ["TELEGRAM_PROVIDER_CHECK_SKIPPED"]}
    provider_check_required = (
        approved
        and mode in {"private", "public"}
        and audience.get("configured") is True
        and audience.get("webhook_secret_configured") is True
        and int(audience.get("active_recipients", 0)) > 0
    )
    if provider_check_required:
        provider = _telegram_provider_health()
    provider_healthy = provider.get("ok") is True
    telegram_configuration_blockers = _telegram_configuration_blockers()
    telegram_ready = (
        approved
        and mode in {"private", "public"}
        and audience.get("configured") is True
        and audience.get("webhook_secret_configured") is True
        and int(audience.get("active_recipients", 0)) > 0
        and delivery_healthy
        and provider_healthy
    )
    return {
        **decision,
        "mode": mode,
        "execution_mode": os.environ.get("BORO_EXECUTION_MODE", "paper").lower(),
        "live_symbol": live_symbol,
        "operational_kill_switch": kill_switch_active,
        "personal_live_trading_acknowledged": personal_live_acknowledged,
        "live_risk_policy": risk_policy,
        "telegram_recommendations": telegram_ready,
        "telegram_reason": (
            "enabled"
            if telegram_ready
            else "blocked by operational kill switch"
            if kill_switch_active
            else "blocked by Telegram delivery health"
            if not delivery_healthy
            else "blocked by Telegram provider/webhook verification"
            if not provider_healthy and provider_check_required
            else "Telegram setup incomplete: " + ", ".join(telegram_configuration_blockers)
            if telegram_configuration_blockers
            else "requires approved release, bot credentials, webhook secret, and active consent"
        ),
        "telegram_configuration_blockers": telegram_configuration_blockers,
        "telegram_audience": audience,
        "telegram_provider": provider,
        "broker_orders": live_ready,
        "broker_exits": live_exits,
        "broker_session": broker_session,
        "broker_reason": (
            "enabled"
            if live_ready
            else "blocked by operational kill switch"
            if kill_switch_active
            and live_exits
            else "requires a recent successful /broker/profile validation"
            if broker_credentials_configured and broker_session.get("valid") is not True
            else "requires private owner acknowledgement or approved release, live confirmation, and Kite credential validation"
        ),
        "broker_exit_reason": (
            "enabled"
            if live_exits
            else "disabled until release approval, live confirmation, and Kite credential validation"
        ),
        "broker_credentials_configured": broker_credentials_configured,
        "broker_provider": "zerodha",
    }


def _broker_readiness(*, read_only: bool = False) -> tuple[dict | None, dict | None]:
    release = _release_status()
    if not read_only and not release.get("approved") and not release.get("broker_exits"):
        return None, {"ok": False, "error": "RELEASE_GATE_NOT_APPROVED",
                      "blockers": release.get("blockers", [])}
    try:
        from src.broker_gateway import ZerodhaBroker
        return ZerodhaBroker(), None
    except Exception as error:  # noqa: BLE001
        return None, {"ok": False, "error": str(error)}


def _record_broker_event(event_type: str, order: dict, payload: dict | None = None) -> bool:
    """Append broker lifecycle evidence to the same tamper-evident chain as signals."""
    order_id = str(order.get("order_id", "")).strip()
    if not order_id:
        return False
    from src.reliability.ledger import SignalLedger
    from src.reliability.store import ReliabilityStore
    database = os.environ.get("BORO_RELIABILITY_DB", "results/reliability.db")
    signal_id = "broker:" + order_id
    with ReliabilityStore(database) as store:
        ledger = SignalLedger(store.connection)
        if any(event["event_type"] == event_type for event in ledger.events(signal_id)):
            return True
        ledger.append(
            event_type,
            signal_id,
            {**order, **(payload or {})},
            created_at=datetime.now(timezone.utc),
        )
    return True


def _broker_holdings() -> dict:
    broker, error = _broker_readiness(read_only=True)
    if error:
        return error
    try:
        return {"ok": True, "holdings": broker.holdings()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_profile() -> dict:
    try:
        from src.broker_gateway import ZerodhaBroker
        profile = ZerodhaBroker().profile()
        _record_broker_session(valid=True, profile=profile)
        # Do not return email or other personal profile fields to the dashboard.
        return {"ok": True, "user_id": profile.get("user_id"),
                "broker": profile.get("broker"), "exchanges": profile.get("exchanges"),
                "login_time": profile.get("login_time")}
    except Exception as exc:  # noqa: BLE001
        try:
            _record_broker_session(valid=False)
        except (OSError, sqlite3.Error):
            pass
        return {"ok": False, "error": str(exc)}


def _persist_broker_access_token(token: str) -> None:
    from src.broker_gateway import persist_access_token
    persist_access_token(token)


def _broker_login_url() -> dict:
    try:
        from src.broker_gateway import ZerodhaBroker
        return {"ok": True, "login_url": ZerodhaBroker().login_url()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_session_exchange(body: dict) -> dict:
    request_token = str(body.get("request_token", "")).strip()
    if not request_token:
        return {"ok": False, "error": "KITE_REQUEST_TOKEN_MISSING"}
    if len(request_token) > 256 or any(char.isspace() for char in request_token):
        return {"ok": False, "error": "KITE_REQUEST_TOKEN_INVALID"}
    if os.environ.get("KITE_ACCESS_TOKEN", "").strip():
        return {"ok": False, "error": "KITE_ACCESS_TOKEN_ALREADY_CONFIGURED"}
    try:
        from src.broker_gateway import ZerodhaBroker
        exchanged = ZerodhaBroker().exchange_request_token(request_token)
        access_token = str(exchanged.get("access_token", "")).strip()
        if not access_token:
            return {"ok": False, "error": "KITE_ACCESS_TOKEN_MISSING"}
        _persist_broker_access_token(access_token)
        profile = ZerodhaBroker().profile()
        _record_broker_session(valid=True, profile=profile)
        return {
            "ok": True,
            "user_id": profile.get("user_id"),
            "broker": profile.get("broker"),
            "exchanges": profile.get("exchanges"),
            "login_time": profile.get("login_time"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_order_status(order_id: str) -> dict:
    if not str(order_id).strip():
        return {"ok": False, "error": "order_id is required"}
    broker, error = _broker_readiness(read_only=True)
    if error:
        return error
    try:
        status = broker.order_status(order_id)
        return {"ok": True, **status,
                "audit_recorded": _record_broker_event(
                    "BROKER_ORDER_STATUS_" + str(status.get("status", "UNKNOWN")).upper(),
                    status,
                )}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_orders() -> dict:
    broker, error = _broker_readiness(read_only=True)
    if error:
        return error
    try:
        return {"ok": True, "orders": broker.orders()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_reconcile() -> dict:
    """Reconcile broker holdings/orders and flag anything outside live scope."""
    broker, error = _broker_readiness(read_only=True)
    if error:
        return error
    try:
        holdings = broker.holdings()
        orders = broker.orders()
        scope_issues = []
        reconciled = 0
        for order in orders:
            if not isinstance(order, dict):
                continue
            order_id = str(order.get("order_id", "")).strip()
            ticker = str(order.get("tradingsymbol", "")).strip().upper()
            exchange = str(order.get("exchange", "")).strip().upper()
            product = str(order.get("product", "")).strip().upper()
            reasons = []
            if ticker != _live_symbol():
                reasons.append(f"LIVE_SYMBOL_RESTRICTED:{_live_symbol()}")
            if exchange != "NSE":
                reasons.append("BROKER_ORDER_EXCHANGE_OUT_OF_SCOPE")
            if product != "CNC":
                reasons.append("BROKER_ORDER_PRODUCT_OUT_OF_SCOPE")
            if reasons:
                scope_issues.append({
                    "order_id": order_id,
                    "ticker": ticker,
                    "reasons": reasons,
                })
            if order_id:
                reconciled += int(_record_broker_event(
                    "BROKER_ORDER_RECONCILED",
                    {"order_id": order_id, "status": order.get("status", "UNKNOWN")},
                    {"ticker": ticker, "exchange": exchange, "product": product},
                ))
        return {
            "ok": True,
            "live_symbol": _live_symbol(),
            "holdings": holdings,
            "orders": orders,
            "scope_issues": scope_issues,
            "orders_reconciled": reconciled,
            "reconciled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_order_cancel(order_id: str) -> dict:
    if not str(order_id).strip():
        return {"ok": False, "error": "order_id is required"}
    broker, error = _broker_readiness()
    if error:
        return error
    try:
        status = broker.order_status(order_id)
        raw = status.get("raw") if isinstance(status, dict) else None
        if not isinstance(raw, dict):
            return {"ok": False, "error": "BROKER_ORDER_SCOPE_UNVERIFIED"}
        if str(raw.get("tradingsymbol", "")).strip().upper() != _live_symbol():
            return {"ok": False, "error": f"LIVE_SYMBOL_RESTRICTED:{_live_symbol()}"}
        if str(raw.get("exchange", "")).strip().upper() != "NSE" or str(raw.get("product", "")).strip().upper() != "CNC":
            return {"ok": False, "error": "BROKER_ORDER_SCOPE_RESTRICTED"}
        current_status = str(status.get("status", raw.get("status", ""))).strip().upper()
        if current_status not in _CANCELLABLE_ORDER_STATUSES:
            return {"ok": False, "error": f"ORDER_NOT_CANCELLABLE:{current_status or 'UNKNOWN'}"}
        result = broker.cancel_order(order_id)
        return {"ok": True, **result,
                "audit_recorded": _record_broker_event(
                    "BROKER_ORDER_CANCEL_REQUESTED", result,
                    {"pre_cancel_status": current_status, "ticker": _live_symbol()},
                )}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_gtt_status(trigger_id: str) -> dict:
    if not str(trigger_id).strip():
        return {"ok": False, "error": "gtt_id is required"}
    broker, error = _broker_readiness(read_only=True)
    if error:
        return error
    try:
        status = broker.gtt_status(trigger_id)
        return {"ok": True, **status}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_gtt_cancel(trigger_id: str) -> dict:
    if not str(trigger_id).strip():
        return {"ok": False, "error": "gtt_id is required"}
    broker, error = _broker_readiness()
    if error:
        return error
    try:
        status = broker.gtt_status(trigger_id)
        raw = status.get("raw") if isinstance(status, dict) else None
        condition = raw.get("condition") if isinstance(raw, dict) else None
        if not isinstance(condition, dict):
            return {"ok": False, "error": "BROKER_GTT_SCOPE_UNVERIFIED"}
        if str(condition.get("tradingsymbol", "")).strip().upper() != _live_symbol():
            return {"ok": False, "error": f"LIVE_SYMBOL_RESTRICTED:{_live_symbol()}"}
        if str(status.get("status", "")).strip().lower() != "active":
            return {"ok": False, "error": "GTT_NOT_ACTIVE"}
        result = broker.cancel_gtt(trigger_id)
        audit_recorded = _record_broker_event(
            "BROKER_GTT_CANCEL_REQUESTED",
            {"order_id": f"gtt:{str(trigger_id).strip()}", "gtt_id": str(trigger_id).strip()},
            {"ticker": _live_symbol(), "pre_cancel_status": "ACTIVE"},
        )
        return {"ok": True, **result, "audit_recorded": audit_recorded}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _broker_gtt_protect(body: dict) -> dict:
    """Create one idempotent two-leg GTT for an accepted unprotected BUY."""
    ticker = str(body.get("ticker", "")).strip().upper()
    if ticker != _live_symbol():
        return {"ok": False, "error": f"LIVE_SYMBOL_RESTRICTED:{_live_symbol()}"}
    try:
        shares = int(body.get("shares", 0))
        price = float(body.get("price", 0) or 0)
        stop = float(body.get("stop", 0) or 0)
        target = float(body.get("target", 0) or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "shares and protection prices must be numeric"}
    if shares <= 0 or price <= 0 or stop <= 0 or target <= 0:
        return {"ok": False, "error": "protection requires positive shares, price, stop, and target"}
    release = _release_status()
    if not release.get("broker_orders", release.get("approved") is True):
        return {"ok": False, "error": "; ".join(
            release.get("blockers", ["RELEASE_GATE_NOT_APPROVED"])
        )}
    request_claim = _claim_live_protection_request(body)
    if request_claim:
        return request_claim
    request_id = str(body.get("request_id", "")).strip()
    try:
        from src.broker_gateway import (
            BrokerOrderError, ZerodhaBroker, build_protection_gtt_payload,
        )
        risk_error = _validate_live_risk(shares, price, stop)
        if risk_error:
            result = {"ok": False, **risk_error, "request_id": request_id}
            _finish_live_protection_request(request_id, result)
            return result
        build_protection_gtt_payload(
            ticker=ticker, shares=shares, last_price=price,
            stop_price=stop, target_price=target,
        )
        protection = ZerodhaBroker().place_protection_gtt(
            ticker, shares, last_price=price,
            stop_price=stop, target_price=target,
        )
        order_id = str(body.get("order_id", "")).strip()
        result = {
            "ok": True,
            **protection,
            "request_id": request_id,
            "audit_recorded": _record_broker_event(
                "BROKER_GTT_PROTECTION_CREATED",
                {"order_id": f"gtt:{protection['gtt_id']}", "gtt_id": protection["gtt_id"]},
                {"ticker": ticker, "order_id": order_id, "shares": shares,
                 "stop_price": stop, "target_price": target},
            ),
        }
        _finish_live_protection_request(request_id, result)
        return result
    except BrokerOrderError as error:
        result = {"ok": False, "error": str(error), "request_id": request_id}
        _finish_live_protection_request(request_id, result)
        return result
    except (TypeError, ValueError, OSError) as error:
        result = {"ok": False, "error": str(error), "request_id": request_id}
        _finish_live_protection_request(request_id, result)
        return result


def _buy(body: dict) -> dict:
    """Paper BUY. Halal: buying is the only entry. Validates input then reuses
    `paper_trader.buy` — the exact function the `--buy` CLI runs (one source of
    truth, no duplicated trade logic)."""
    ticker = str(body.get("ticker", "")).strip().upper()
    if not ticker.isalnum():
        return {"ok": False, "error": "ticker must be an alphanumeric NSE symbol"}
    try:
        shares = int(body.get("shares", 0))
        price = float(body.get("price", 0) or 0)
        stop_price = float(body.get("stop", 0) or 0)
        target_price = float(body.get("target", 0) or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "shares must be an integer, prices must be numeric"}
    if shares <= 0:
        return {"ok": False, "error": "shares must be > 0"}
    if price < 0:
        return {"ok": False, "error": "price must be >= 0 (use 0 to fetch live)"}
    if os.environ.get("BORO_EXECUTION_MODE", "paper").lower() == "live":
        live_symbol = os.environ.get("BORO_LIVE_SYMBOL", "RELIANCE").strip().upper() or "RELIANCE"
        if ticker != live_symbol:
            return {"ok": False, "error": f"LIVE_SYMBOL_RESTRICTED:{live_symbol}"}
        release = _release_status()
        if not release.get("broker_orders", release.get("approved") is True):
            return {"ok": False, "error": "; ".join(release.get("blockers", ["RELEASE_GATE_NOT_APPROVED"]))}
        try:
            from src.broker_gateway import (
                BrokerOrderError, ZerodhaBroker, build_protection_gtt_payload,
            )
            if price <= 0 or stop_price <= 0 or target_price <= 0:
                return {"ok": False, "error": "live BUY requires price, stop, and target"}
            risk_error = _validate_live_risk(shares, price, stop_price)
            if risk_error:
                return {"ok": False, **risk_error}
            try:
                build_protection_gtt_payload(
                    ticker=ticker, shares=shares, last_price=price,
                    stop_price=stop_price, target_price=target_price,
                )
            except BrokerOrderError as error:
                return {"ok": False, "error": str(error)}
            request_id = str(body.get("request_id", "")).strip()
            request_claim = _claim_live_buy_request(body)
            if request_claim:
                return request_claim
            broker = ZerodhaBroker()
            order = broker.place_cnc_order(
                ticker, shares, "BUY", price=price or None, stop_price=stop_price
            )
            try:
                protection = broker.place_protection_gtt(
                    ticker, shares, last_price=price,
                    stop_price=stop_price, target_price=target_price,
                )
                order.update(protection)
            except BrokerOrderError as error:
                # The entry may already be accepted; expose the unprotected state.
                _record_broker_event(
                    "BROKER_ORDER_ACCEPTED", order,
                    {"ticker": ticker, "side": "BUY", "requested_shares": shares,
                     "stop_price": stop_price, "target_price": target_price,
                     "protection_created": False, "protection_error": str(error)},
                )
                result = {"ok": False, **order, "protection_created": False,
                          "protection_error": str(error),
                          "error": "ENTRY_ACCEPTED_PROTECTION_FAILED",
                          "request_id": request_id}
                _finish_live_buy_request(request_id, result)
                return result
            result = {"ok": True, **order,
                      "request_id": request_id,
                      "audit_recorded": _record_broker_event(
                        "BROKER_ORDER_ACCEPTED", order,
                        {"ticker": ticker, "side": "BUY", "requested_shares": shares,
                         "stop_price": stop_price, "target_price": target_price},
                      )}
            _finish_live_buy_request(request_id, result)
            return result
        except BrokerOrderError as error:
            result = {"ok": False, "error": str(error)}
            if "request_id" in locals() and request_id:
                _finish_live_buy_request(request_id, result)
            return result
    from src import paper_trader as pt
    return pt.buy(ticker, shares, price if price > 0 else None)


def _close(body: dict) -> dict:
    """Close a HELD position in full at the live price — the only halal exit.
    Refuses to sell anything not held (that would be initiating a short)."""
    ticker = str(body.get("ticker", "")).strip().upper()
    if os.environ.get("BORO_EXECUTION_MODE", "paper").lower() == "live":
        live_symbol = os.environ.get("BORO_LIVE_SYMBOL", "RELIANCE").strip().upper() or "RELIANCE"
        if ticker != live_symbol:
            return {"ok": False, "error": f"LIVE_SYMBOL_RESTRICTED:{live_symbol}"}
        release = _release_status()
        if not release.get("broker_exits", release.get("approved") is True):
            return {"ok": False, "error": "; ".join(
                release.get("blockers", ["RELEASE_GATE_NOT_APPROVED"])
            )}
        try:
            from src.broker_gateway import BrokerOrderError, ZerodhaBroker
            gtt_id = str(body.get("gtt_id", "")).strip()
            if not gtt_id:
                return {"ok": False, "error": "LIVE_CLOSE_REQUIRES_GTT_ID"}
            request_id = str(body.get("request_id", "")).strip()
            request_claim = _claim_live_close_request(body)
            if request_claim:
                return request_claim
            broker = ZerodhaBroker()
            order = broker.close_holding(ticker, gtt_id=gtt_id)
            result = {"ok": True, **order,
                      "request_id": request_id,
                      "audit_recorded": _record_broker_event(
                          "BROKER_ORDER_ACCEPTED", order,
                          {"ticker": ticker, "side": "SELL"},
                      )}
            _finish_live_close_request(request_id, result)
            return result
        except BrokerOrderError as error:
            result = {"ok": False, "error": str(error)}
            if "request_id" in locals() and request_id:
                _finish_live_close_request(request_id, result)
            return result
    from src import paper_trader as pt
    state = pt._load()
    if ticker not in state.get("positions", {}):
        return {"ok": False,
                "error": f"no open position in {ticker} — refusing to sell (no shorting)"}
    return pt.sell(ticker)  # shares=None → all; price=None → live


def _auto_close_action() -> tuple[int, dict]:
    """Run paper auto-close only; live positions use broker-side protection."""
    if os.environ.get("BORO_EXECUTION_MODE", "paper").lower() == "live":
        return 409, {
            "ok": False,
            "error": "LIVE_AUTO_CLOSE_DISABLED",
            "reason": "live positions are protected by broker GTTs and must be reconciled through the broker cockpit",
        }
    return 200, _run_module("auto_close")


def _config_get() -> dict:
    from src import strategy_presets as sp
    return {"ok": True, "active": sp.active(), "presets": sp.list_presets()}


def _config_set(body: dict) -> dict:
    from src import strategy_presets as sp
    try:
        sp.set_active(str(body.get("preset", "")).strip())
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "active": sp.active(), "presets": sp.list_presets()}


# ── Command center — whitelisted "run a command without a terminal" ──────────────
# Every command maps to a FIXED argv builder (no arbitrary execution). Args are
# validated; the only interpolated value is a strict ticker. `cloud` names the
# GitHub-Actions job the dashboard can dispatch instead when in cloud mode.

_TICKER_RE = re.compile(r"^[A-Za-z0-9.&-]{1,15}$")


def _arg_ticker(args: dict) -> str:
    t = str(args.get("ticker", "")).strip().upper()
    if not _TICKER_RE.match(t):
        raise ValueError("ticker must be 1-15 chars: letters, digits, . & -")
    return t


def _arg_years(args: dict) -> int:
    try:
        y = int(args.get("years", 5))
    except (TypeError, ValueError):
        raise ValueError("years must be an integer")
    if not 1 <= y <= 10:
        raise ValueError("years must be between 1 and 10")
    return y


# id -> (group, label, [arg names], cloud_job|None, danger, build(args)->python argv)
_COMMANDS = {
    # Daily ops
    "daily_briefing": ("Daily", "Morning scan + Telegram", [], "nightly-scan", False,
                       lambda a: ["-m", "src.daily_briefing", "--capital", CAPITAL]),
    "auto_close":     ("Daily", "Close stop / target / max-hold", [], "auto-close", False,
                       lambda a: ["-m", "src.auto_close"]),
    # Paper trading
    "paper_view":  ("Paper", "View portfolio", [], None, False,
                    lambda a: ["-m", "src.paper_trader"]),
    "paper_scan":  ("Paper", "Scan + auto-place top signals", [], "nightly-scan", False,
                    lambda a: ["-m", "src.paper_trader", "--scan"]),
    "paper_reset": ("Paper", "Reset to ₹50,000 (wipes trades)", [], None, True,
                    lambda a: ["-c", "from src.paper_trader import _save,_fresh; "
                               "_save(_fresh()); print('Portfolio reset to 50000')"]),
    # Halal / Zakat / Drawdown
    "halal_screen":  ("Halal", "Screen a stock (live fundamentals)", ["ticker"], None, False,
                      lambda a: ["-c", "from src.halal_screen import screen_ticker; import json; "
                                 f"print(json.dumps(screen_ticker('{_arg_ticker(a)}'), indent=2))"]),
    "halal_lookup":  ("Halal", "Halal card (citation + as-of)", ["ticker"], None, False,
                      lambda a: ["-c", "from src.halal_lookup import lookup, format_card; "
                                 f"print(format_card(lookup('{_arg_ticker(a)}')))"]),
    "halal_history": ("Halal", "Point-in-time halal history", ["ticker"], None, False,
                      lambda a: ["-c", "from src.halal_history import tier_timeline, format_timeline; "
                                 f"print(format_timeline(tier_timeline('{_arg_ticker(a)}')))"]),
    "tier_monitor":  ("Halal", "Tier-change alerts vs snapshot", [], "quarterly-rescreen", False,
                      lambda a: ["-m", "src.tier_monitor"]),
    "zakat":         ("Halal", "Zakat + purification (paper holdings)", [], None, False,
                      lambda a: ["-c", "from src.paper_trader import _load; "
                                 "from src.zakat import portfolio_zakat_report; import json; "
                                 "s=_load(); h=[{'ticker':k,'qty':v['shares'],'price':v['avg_entry'],"
                                 "'cost_basis':v['avg_entry']} for k,v in s['positions'].items()]; "
                                 "print(json.dumps(portfolio_zakat_report(h), indent=2))"]),
    "drawdown_guard":("Halal", "Drawdown-guard de-risk card", [], None, False,
                      lambda a: ["-m", "src.drawdown_guard", "--capital", CAPITAL]),
    # Train / backtest / validate
    "backtest":      ("Models", "Train + backtest a ticker", ["ticker", "years"], "weekly-backtest", False,
                      lambda a: ["-m", "src.pipeline", "--ticker", _arg_ticker(a),
                                 "--years", str(_arg_years(a))]),
    "walkforward":   ("Models", "Walk-forward validation gate", ["ticker", "years"], None, False,
                      lambda a: ["-m", "src.walk_forward", "--ticker", _arg_ticker(a),
                                 "--years", str(_arg_years(a)), "--splits", "4"]),
    "walkforward_portfolio": ("Models", "Walk-forward — full universe", [], None, False,
                      lambda a: ["-m", "src.walk_forward", "--portfolio", "--years", "3"]),
    "compare_models": ("Models", "Compare runs (win_rate top 10)", [], None, False,
                       lambda a: ["-m", "scripts.compare_models", "--metric", "win_rate", "--top", "10"]),
    # Signals / drift / data
    "drift":  ("Signals", "Drift check", ["ticker"], None, False,
               lambda a: ["-m", "src.drift_detector", "--ticker", _arg_ticker(a)]),
    "news":   ("Signals", "News sentiment", ["ticker"], None, False,
               lambda a: ["-c", "from src.news_sentiment import get_news_sentiment; import json; "
                          f"t='{_arg_ticker(a)}'; print(json.dumps(get_news_sentiment(t, t), indent=2))"]),
    "macro":  ("Signals", "Macro indicators", [], None, False,
               lambda a: ["-c", "from src.macro_indicators import get_macro_indicators; import json; "
                          "print(json.dumps(get_macro_indicators(), indent=2))"]),
    # Ops
    "export_dashboard": ("Ops", "Refresh dashboard feed", [], None, False,
                         lambda a: ["-m", "scripts.export_dashboard", "--capital", CAPITAL]),
    "tests": ("Ops", "Run test suite", [], None, False,
              lambda a: ["-m", "pytest", "tests/", "-q"]),
}

# Commands that change paper/dashboard state → refresh the feed after running.
_REFRESH_AFTER = {"daily_briefing", "auto_close", "paper_scan", "paper_reset"}


def _run_argv(py_args: list) -> dict:
    """Run `python <py_args...>` from repo root; capture output (whitelisted only)."""
    cmd = [sys.executable, *py_args]
    try:
        p = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                           text=True, timeout=TIMEOUT)
        return {"ok": p.returncode == 0, "returncode": p.returncode,
                "stdout": (p.stdout or "")[-8000:], "stderr": (p.stderr or "")[-1500:],
                "cmd": " ".join(str(x) for x in py_args[:4])}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {TIMEOUT}s"}


def _commands_catalog() -> dict:
    return {"ok": True, "capital": CAPITAL, "commands": [
        {"id": cid, "group": g, "label": lbl, "args": argn, "cloud": cloud, "danger": dng}
        for cid, (g, lbl, argn, cloud, dng, _b) in _COMMANDS.items()
    ]}


def _run_command(body: dict) -> dict:
    cid = str(body.get("id", ""))
    spec = _COMMANDS.get(cid)
    if not spec:
        return {"ok": False, "error": f"unknown command {cid!r}"}
    _g, _lbl, _argn, _cloud, _dng, build = spec
    try:
        argv = build(body.get("args") or {})
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    r = _run_argv(argv)
    if cid in _REFRESH_AFTER:
        _run_argv(["-m", "scripts.export_dashboard", "--capital", CAPITAL])
    return r


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter logs
        pass

    # ── helpers ──
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "X-Control-Token, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, status: int, body: dict):
        payload = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _authed(self) -> bool:
        # Never accept the token in a URL: URLs leak through browser history,
        # referrers, proxy logs, and screenshots.
        supplied = self.headers.get("X-Control-Token", "")
        return bool(TOKEN) and supplied == TOKEN

    def _path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n < 0 or n > MAX_BODY_BYTES:
                return {}
            raw = self.rfile.read(n) if n else b""
            return json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def _refresh_feed(self):
        """Regenerate dashboard_data.js after a state change (best-effort)."""
        _run_module("export_dashboard", "--capital", CAPITAL)

    # ── verbs ──
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self._path()
        if path == "/health":
            return self._json(200, {"ok": True, "service": "control_server"})
        if not self._authed():
            return self._json(401, {"ok": False, "error": "missing/invalid token"})
        if path == "/portfolio":
            return self._json(200, _portfolio())
        if path == "/positions":
            return self._json(200, _positions())
        if path == "/readiness":
            return self._json(200, _release_status())
        if path == "/telegram/audience":
            return self._json(200, {"ok": True, **_telegram_audience_status()})
        if path == "/telegram/provider":
            try:
                from src.telegram_provider import provider_status
                return self._json(200, provider_status())
            except (OSError, TypeError, ValueError):
                return self._json(200, {"ok": False, "blockers": ["TELEGRAM_PROVIDER_STATUS_UNAVAILABLE"]})
        if path == "/broker/holdings":
            return self._json(200, _broker_holdings())
        if path == "/broker/profile":
            return self._json(200, _broker_profile())
        if path == "/broker/login-url":
            return self._json(200, _broker_login_url())
        if path == "/broker/reconcile":
            return self._json(200, _broker_reconcile())
        if path == "/broker/risk-preview":
            return self._json(200, _broker_risk_preview(parse_qs(urlparse(self.path).query)))
        if path == "/broker/order-status":
            order_id = parse_qs(urlparse(self.path).query).get("order_id", [""])[0]
            return self._json(200, _broker_order_status(order_id))
        if path == "/broker/orders":
            return self._json(200, _broker_orders())
        if path == "/broker/gtt-status":
            trigger_id = parse_qs(urlparse(self.path).query).get("gtt_id", [""])[0]
            return self._json(200, _broker_gtt_status(trigger_id))
        if path == "/config":
            return self._json(200, _config_get())
        if path == "/commands":
            return self._json(200, _commands_catalog())
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self._path()
        if path == "/telegram/webhook":
            status, result = _telegram_webhook(
                self._body(), self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            )
            return self._json(status, result)
        if path == "/broker/postback":
            status, result = _broker_postback(self._body())
            return self._json(status, result)
        if not self._authed():
            return self._json(401, {"ok": False, "error": "missing/invalid token"})
        if path == "/telegram/webhook/register":
            r = _telegram_register_webhook()
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/telegram/outbox/retry":
            r = _telegram_retry_outbox()
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/scan":
            r = _run_module("daily_briefing", "--capital", CAPITAL) if os.getenv("CONTROL_SCAN_FULL") \
                else _run_module("scanner")
            _run_module("export_dashboard", "--capital", CAPITAL)  # refresh the feed
            return self._json(200 if r.get("ok") else 500, r)
        if path == "/daily-briefing":
            r = _run_module("daily_briefing", "--capital", CAPITAL)
            _run_module("export_dashboard", "--capital", CAPITAL)
            return self._json(200 if r.get("ok") else 500, r)
        if path == "/auto-close":
            status, r = _auto_close_action()
            if status != 200:
                return self._json(status, r)
            _run_module("export_dashboard", "--capital", CAPITAL)
            return self._json(status if r.get("ok") else 500, r)
        # ── Cockpit: discrete, guarded actions (BUY-only; local-mode only) ──
        if path == "/buy":
            r = _buy(self._body())
            if r.get("ok"):
                self._refresh_feed()
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/close":
            r = _close(self._body())
            if r.get("ok"):
                self._refresh_feed()
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/broker/gtt-cancel":
            r = _broker_gtt_cancel(str(self._body().get("gtt_id", "")))
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/broker/gtt/protect":
            r = _broker_gtt_protect(self._body())
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/broker/order-cancel":
            r = _broker_order_cancel(str(self._body().get("order_id", "")))
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/broker/session/exchange":
            r = _broker_session_exchange(self._body())
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/config":
            r = _config_set(self._body())
            return self._json(200 if r.get("ok") else 400, r)
        if path == "/command":
            r = _run_command(self._body())
            return self._json(200 if r.get("ok") else 400, r)
        self._json(404, {"ok": False, "error": "not found"})


def run(port: int = 8765):
    if not TOKEN:
        sys.exit("CONTROL_TOKEN is not set — refusing to start an unauthenticated "
                 "trade-trigger server. Run: CONTROL_TOKEN=yoursecret python -m src.control_server")
    server = HTTPServer((BIND_HOST, port), Handler)
    print(f"control_server on http://{BIND_HOST}:{port}  (token required; origin={ALLOW_ORIGIN})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    run(ap.parse_args().port)


if __name__ == "__main__":
    main()
