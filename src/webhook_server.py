"""
TradingView → Webhook → Signal Server
======================================

How it works:
  1. TradingView fires an alert (Pine Script or indicator-based).
  2. The alert sends a JSON POST to this server's /webhook endpoint.
  3. The server runs the signal through RiskManager, logs it, and optionally
     executes it via Alpaca paper/live trading API.

Setup:
  1. Set a shared secret:   export WEBHOOK_SECRET=<long random passphrase>
  2. Run this server:       python -m src.webhook_server
  3. Expose it publicly:    ngrok http 8080   (or deploy to any VPS)
  4. Copy the public URL.
  5. In TradingView → Alert → Webhook URL → paste URL + "/webhook"
  6. Alert message format (paste into TradingView message box — the "secret"
     field is required; TradingView can't set headers, so the secret travels
     in the body, or use "/webhook?secret=..." as the URL instead):
     {
       "secret":    "<same WEBHOOK_SECRET>",
       "ticker":    "{{ticker}}",
       "action":    "{{strategy.order.action}}",
       "price":     {{close}},
       "atr":       {{ta.atr(14)}},
       "vix":       15,
       "confidence": 0.70
     }

SECURITY:
  - Every request must authenticate with WEBHOOK_SECRET via the
    X-Webhook-Secret header, a ?secret= query param, or a "secret" body field.
    The server refuses to start when WEBHOOK_SECRET is unset.
  - Binds to 127.0.0.1 by default (tunnels like ngrok still work).
    Set WEBHOOK_HOST=0.0.0.0 only if you expose the port directly.
  - Tickers must match ^[A-Za-z0-9.-]{1,15}$; WEBHOOK_ALLOWED_TICKERS
    (comma list) optionally restricts to a fixed allowlist.

Endpoints:
  POST /webhook     — receive TradingView alert, evaluate, optionally execute
  GET  /signals     — view last 100 received signals as JSON (auth required)
  GET  /health      — liveness check
"""

import hmac
import json
import os
import re
import sys
import threading
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from src.risk_manager import RiskManager

PORT = int(os.environ.get("WEBHOOK_PORT", 8080))
HOST = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
CAPITAL = float(os.environ.get("WEBHOOK_CAPITAL", 100_000))
SECRET = os.environ.get("WEBHOOK_SECRET", "")
MAX_BODY = 8192
TICKER_RE = re.compile(r"^[A-Za-z0-9.\-]{1,15}$")
ALLOWED_TICKERS = {
    t.strip().upper()
    for t in os.environ.get("WEBHOOK_ALLOWED_TICKERS", "").split(",")
    if t.strip()
}

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


def _execute_alpaca(ticker: str, shares: int, direction: int):
    """
    Submit a market order to Alpaca (paper or live).
    Requires ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL in environment.
    """
    api_key    = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    base_url   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not api_key:
        return {"status": "skipped", "reason": "ALPACA_API_KEY not set"}

    from urllib.request import urlopen, Request
    from urllib.error import URLError

    side = "buy" if direction == 1 else "sell"
    payload = json.dumps({
        "symbol":        ticker,
        "qty":           str(shares),
        "side":          side,
        "type":          "market",
        "time_in_force": "day",
    }).encode()

    req = Request(
        f"{base_url}/v2/orders",
        data=payload,
        headers={
            "APCA-API-KEY-ID":     api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type":        "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except URLError as e:
        return {"status": "error", "reason": str(e)}


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

    def _authed(self, body: dict | None = None) -> bool:
        supplied = (
            self.headers.get("X-Webhook-Secret")
            or parse_qs(urlparse(self.path).query).get("secret", [""])[0]
            or str((body or {}).get("secret", ""))
        )
        return bool(SECRET) and hmac.compare_digest(supplied, SECRET)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"status": "ok", "timestamp": datetime.utcnow().isoformat()})
        elif path == "/signals":
            if not self._authed():
                self._send(401, {"error": "missing/invalid secret"})
                return
            with _log_lock:
                self._send(200, {"signals": list(_signal_log)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/webhook":
            self._send(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY:
            self._send(413, {"error": "body too large"})
            return
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})
            return
        if not isinstance(body, dict):
            self._send(400, {"error": "JSON body must be an object"})
            return

        if not self._authed(body):
            self._send(401, {"error": "missing/invalid secret"})
            return

        ticker = str(body.get("ticker", "")).upper()
        if not TICKER_RE.match(ticker) or (ALLOWED_TICKERS and ticker not in ALLOWED_TICKERS):
            self._send(400, {"error": "ticker not allowed"})
            return

        action     = str(body.get("action", "")).upper()   # "BUY" | "SELL"
        price      = float(body.get("price", 0))
        atr        = float(body.get("atr", price * 0.02))  # default 2% ATR
        vix        = float(body.get("vix", 15.0))
        confidence = float(body.get("confidence", 0.65))
        direction  = 1 if action in ("BUY", "LONG") else -1

        decision = rm.evaluate(
            entry_price=price,
            atr=atr,
            confidence=confidence,
            direction=direction,
            vix=vix,
        )

        order_result = {}
        if decision["approved"]:
            order_result = _execute_alpaca(ticker, decision["shares"], direction)

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
    if not SECRET:
        sys.exit("WEBHOOK_SECRET is not set — refusing to start an unauthenticated "
                 "order-placing server. Run: WEBHOOK_SECRET=yoursecret python -m src.webhook_server")
    server = HTTPServer((HOST, PORT), WebhookHandler)
    print(f"""
╔══════════════════════════════════════════════════════╗
║        TradingView Webhook Server — Ready            ║
╠══════════════════════════════════════════════════════╣
║  Listening on  : http://{HOST}:{PORT:<24}║
║  Health check  : GET  /health                        ║
║  Signal log    : GET  /signals  (secret required)    ║
║  Webhook URL   : POST /webhook  (secret required)    ║
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
