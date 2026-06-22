"""
Control server — lets the dashboard run the paper-trading commands without a
terminal. A tiny stdlib HTTP server that the static dashboard calls via fetch().

Endpoints (all JSON):
    GET  /health          liveness
    GET  /portfolio       paper portfolio value + recent trades (read-only)
    POST /scan            run the live scan + refresh the dashboard feed
    POST /daily-briefing  full daily briefing (scan -> paper buys -> notify)
    POST /auto-close      close positions at stop/target

The POST actions shell out to the SAME modules you'd run by hand
(`python -m src.<module>`), so "the dashboard runs the commands" literally means
that — no duplicated logic.

SECURITY — read this before exposing it:
  * Every request must carry the shared token, in header `X-Control-Token` or
    `?token=...`, matching env CONTROL_TOKEN. If CONTROL_TOKEN is unset the
    server refuses to start (no accidental open trade-trigger endpoint).
  * It can place (paper, or live if Alpaca keys are set) trades. Do NOT expose it
    to the public internet without TLS + the token. For personal use, run it on
    localhost (or your LAN) only.

Run:
    CONTROL_TOKEN=yoursecret python -m src.control_server          # port 8765
    CONTROL_TOKEN=yoursecret python -m src.control_server --port 9000
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPITAL = os.getenv("CONTROL_CAPITAL", "50000")
TOKEN = os.getenv("CONTROL_TOKEN", "")
# Restrict which origin may call us in a browser (the deployed dashboard URL).
# "*" is convenient for local dev; set CONTROL_ALLOW_ORIGIN in production.
ALLOW_ORIGIN = os.getenv("CONTROL_ALLOW_ORIGIN", "*")
TIMEOUT = int(os.getenv("CONTROL_TIMEOUT", "600"))


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
        q = parse_qs(urlparse(self.path).query)
        supplied = self.headers.get("X-Control-Token") or (q.get("token", [""])[0])
        return bool(TOKEN) and supplied == TOKEN

    def _path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

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
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self._path()
        if not self._authed():
            return self._json(401, {"ok": False, "error": "missing/invalid token"})
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
            r = _run_module("auto_close")
            _run_module("export_dashboard", "--capital", CAPITAL)
            return self._json(200 if r.get("ok") else 500, r)
        self._json(404, {"ok": False, "error": "not found"})


def run(port: int = 8765):
    if not TOKEN:
        sys.exit("CONTROL_TOKEN is not set — refusing to start an unauthenticated "
                 "trade-trigger server. Run: CONTROL_TOKEN=yoursecret python -m src.control_server")
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"control_server on http://localhost:{port}  (token required; origin={ALLOW_ORIGIN})")
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
