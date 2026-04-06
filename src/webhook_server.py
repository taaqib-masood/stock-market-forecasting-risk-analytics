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

Endpoints:
  POST /webhook     — receive TradingView alert, evaluate, optionally execute
  GET  /signals     — view last 50 received signals as JSON
  GET  /health      — liveness check
"""

import json
import os
import threading
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.risk_manager import RiskManager

PORT = int(os.environ.get("WEBHOOK_PORT", 8080))
CAPITAL = float(os.environ.get("WEBHOOK_CAPITAL", 100_000))

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

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok", "timestamp": datetime.utcnow().isoformat()})
        elif self.path == "/signals":
            with _log_lock:
                self._send(200, {"signals": list(_signal_log)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            self._send(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})
            return

        ticker     = body.get("ticker", "UNKNOWN")
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
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"""
╔══════════════════════════════════════════════════════╗
║        TradingView Webhook Server — Ready            ║
╠══════════════════════════════════════════════════════╣
║  Listening on  : http://0.0.0.0:{PORT:<24}║
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
