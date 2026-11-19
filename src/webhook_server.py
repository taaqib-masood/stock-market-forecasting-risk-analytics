"""
TradingView → Webhook → Signal Server
======================================

How it works:
  1. TradingView fires an alert (Pine Script or indicator-based).
  2. The alert sends a JSON POST to this server's /webhook endpoint.
  3. The server runs the signal through RiskManager, logs it, and optionally
     executes it via Alpaca paper/live trading API.

Setup:
  1. Run this server:       python -m src.webhook_server
  2. Expose it publicly:    ngrok http 8080   (or deploy to any VPS)
  3. Copy the public URL.
  4. In TradingView → Alert → Webhook URL → paste URL + "/webhook"
  5. Alert message format (paste into TradingView message box):
     {
       "ticker":    "{{ticker}}",
       "action":    "{{strategy.order.action}}",
       "price":     {{close}},
       "atr":       {{ta.atr(14)}},
       "vix":       15,
       "confidence": 0.70
     }
     action BUY/LONG buys; SELL/CLOSE/EXIT closes the held position; anything else is rejected.

Endpoints:
  POST /webhook     — receive TradingView alert, evaluate, optionally execute
  GET  /signals     — view last 50 received signals as JSON
  GET  /health      — liveness check
"""

import json
import hmac
import math
import os
import re
import threading
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.risk_manager import RiskManager

PORT = int(os.environ.get("WEBHOOK_PORT", 8080))
CAPITAL = float(os.environ.get("WEBHOOK_CAPITAL", 100_000))
BIND_HOST = os.environ.get("WEBHOOK_BIND_HOST", "127.0.0.1")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
ALPACA_DATA_URL = "https://data.alpaca.markets"
PRICE_TOLERANCE = 0.02  # alert price must be within 2% of the server-side quote
BUY_ACTIONS = {"BUY", "LONG"}
EXIT_ACTIONS = {"SELL", "CLOSE", "EXIT"}
TICKER_RE = re.compile(r"[A-Z][A-Z0-9.]{0,11}")

# In-memory log (last 100 signals)
_signal_log: deque = deque(maxlen=100)
_log_lock = threading.Lock()

rm = RiskManager(
    capital=CAPITAL,
    max_risk_pct=0.02,
    atr_multiplier=2.0,
    min_rr=2.0,
    max_position_pct=0.05,
    max_consecutive_losses=3,
)


def _alpaca_headers():
    """Return (base_url, headers, None), or (None, None, skip_result) when execution is disabled."""
    if os.environ.get("WEBHOOK_ENABLE_ALPACA", "").strip() != "I_UNDERSTAND_LEGACY_ALPACA_PAPER":
        return None, None, {"status": "skipped", "reason": "LEGACY_ALPACA_EXECUTION_DISABLED"}
    api_key    = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    base_url   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if "paper-api.alpaca.markets" not in base_url:
        return None, None, {"status": "skipped", "reason": "LEGACY_ALPACA_LIVE_ENDPOINT_DISABLED"}
    if not api_key:
        return None, None, {"status": "skipped", "reason": "ALPACA_API_KEY not set"}
    headers = {
        "APCA-API-KEY-ID":     api_key,
        "APCA-API-SECRET-KEY": secret_key,
        "Content-Type":        "application/json",
    }
    return base_url, headers, None


def _alpaca_call(method: str, url: str, headers: dict, payload: dict = None) -> dict:
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except (URLError, ValueError) as e:
        return {"status": "error", "reason": str(e)}


def _execute_alpaca(ticker: str, shares: int, alert_price: float):
    """
    Submit a BUY market order to Alpaca paper trading, size-checked against a
    server-side quote. Requires ALPACA_API_KEY, ALPACA_SECRET_KEY in environment.
    """
    base_url, headers, skipped = _alpaca_headers()
    if skipped:
        return skipped

    quote = _alpaca_call("GET", f"{ALPACA_DATA_URL}/v2/stocks/{ticker}/trades/latest?feed=iex", headers)
    market = (quote.get("trade") or {}).get("p")
    if isinstance(market, bool) or not isinstance(market, (int, float)) or not math.isfinite(market) or market <= 0:
        return {"status": "rejected", "reason": "market price unavailable"}
    if abs(alert_price - market) > PRICE_TOLERANCE * market:
        return {"status": "rejected", "reason": f"alert price {alert_price} deviates from market {market}"}
    if shares * market > rm.capital * rm.max_position_pct:
        return {"status": "rejected", "reason": "order notional exceeds max position size"}

    return _alpaca_call("POST", f"{base_url}/v2/orders", headers, {
        "symbol":        ticker,
        "qty":           str(shares),
        "side":          "buy",
        "type":          "market",
        "time_in_force": "day",
    })


def _close_alpaca_position(ticker: str):
    """Close the held position (Alpaca sells only the held quantity, never opens a short)."""
    base_url, headers, skipped = _alpaca_headers()
    if skipped:
        return skipped
    return _alpaca_call("DELETE", f"{base_url}/v2/positions/{ticker}", headers)


def _parse_alert(body) -> dict:
    """Validate the alert body at the trust boundary; raises ValueError on bad input."""
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    ticker = str(body.get("ticker", "")).strip().upper()
    if not TICKER_RE.fullmatch(ticker):
        raise ValueError("invalid ticker")
    action = str(body.get("action", "")).strip().upper()
    if action not in BUY_ACTIONS | EXIT_ACTIONS:
        raise ValueError("action must be one of " + ", ".join(sorted(BUY_ACTIONS | EXIT_ACTIONS)))

    def num(key, default):
        value = body.get(key, default)
        if isinstance(value, bool):
            raise ValueError(f"{key} must be a number")
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if not math.isfinite(value):
            raise ValueError(f"{key} must be finite")
        return value

    price = num("price", 0)
    atr = num("atr", price * 0.02)  # default 2% ATR
    vix = num("vix", 15.0)
    confidence = num("confidence", 0.65)
    if action in BUY_ACTIONS:
        if price <= 0 or atr <= 0:
            raise ValueError("price and atr must be positive")
        if not 0 <= vix <= 100:
            raise ValueError("vix must be between 0 and 100")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
    return {"ticker": ticker, "action": action, "price": price, "atr": atr,
            "vix": vix, "confidence": confidence}


class WebhookHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # silence default access log

    def _send(self, status: int, body: dict):
        raw = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Webhook-Secret", "")
        return bool(WEBHOOK_SECRET) and hmac.compare_digest(supplied, WEBHOOK_SECRET)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "timestamp": datetime.utcnow().isoformat()})
        elif self.path == "/signals":
            if not self._authorized():
                self._send(401, {"error": "webhook secret required"})
                return
            with _log_lock:
                self._send(200, {"signals": list(_signal_log)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            self._send(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send(401, {"error": "webhook secret required"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})
            return

        try:
            alert = _parse_alert(body)
        except ValueError as e:
            self._send(400, {"error": str(e)})
            return
        ticker, action = alert["ticker"], alert["action"]
        price, vix, confidence = alert["price"], alert["vix"], alert["confidence"]

        if action in EXIT_ACTIONS:
            decision = {"approved": True, "shares": 0, "reason": "EXIT: close held position"}
            order_result = _close_alpaca_position(ticker)
        else:
            decision = rm.evaluate(
                entry_price=price,
                atr=alert["atr"],
                confidence=confidence,
                direction=1,  # halal: BUY-only, never short
                vix=vix,
            )
            order_result = {}
            if decision["approved"]:
                order_result = _execute_alpaca(ticker, decision["shares"], price)

        record = {
            "timestamp":  datetime.utcnow().isoformat(),
            "ticker":     ticker,
            "action":     action,
            "price":      price,
            "confidence": confidence,
            "vix":        vix,
            "decision":   decision,
            "order":      order_result,
        }

        with _log_lock:
            _signal_log.appendleft(record)

        status_code = 200 if decision["approved"] else 422
        print(f"[{record['timestamp']}] {ticker} {action} @ {price} → {decision['reason']}")
        self._send(status_code, record)


def run():
    server = HTTPServer((BIND_HOST, PORT), WebhookHandler)
    print(f"""
╔══════════════════════════════════════════════════════╗
║        TradingView Webhook Server — Ready            ║
╠══════════════════════════════════════════════════════╣
║  Listening on  : http://{BIND_HOST}:{PORT:<24}║
║  Health check  : GET  /health                        ║
║  Signal log    : GET  /signals                       ║
║  Webhook URL   : POST /webhook                       ║
╠══════════════════════════════════════════════════════╣
║  To expose publicly:                                 ║
║    ngrok http {PORT}   →  copy HTTPS URL              ║
║  Paste in TradingView: Alerts → Webhook URL          ║
╚══════════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    run()
