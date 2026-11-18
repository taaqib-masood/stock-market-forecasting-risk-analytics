"""One slow or idle client must not freeze the control or webhook servers."""
import socket
import threading
import urllib.request

import pytest

from src import control_server as cs
from src import webhook_server as ws


def _start(monkeypatch, module, run):
    """Run module.run() on an ephemeral loopback port and return the server."""
    ready = threading.Event()
    holder = {}

    class LoopbackServer(module.ThreadingHTTPServer):
        def __init__(self, _addr, handler):
            super().__init__(("127.0.0.1", 0), handler)
            holder["server"] = self
            ready.set()

    monkeypatch.setattr(module, "ThreadingHTTPServer", LoopbackServer)
    threading.Thread(target=run, daemon=True).start()
    assert ready.wait(5)
    return holder["server"]


@pytest.mark.parametrize("module, run, handler", [
    (cs, lambda: cs.run(0), cs.Handler),
    (ws, ws.run, ws.WebhookHandler),
])
def test_idle_connection_does_not_block_health(monkeypatch, module, run, handler):
    monkeypatch.setattr(cs, "TOKEN", "secret")
    assert 0 < handler.timeout <= 15
    server = _start(monkeypatch, module, run)
    port = server.server_address[1]
    try:
        with socket.create_connection(("127.0.0.1", port)):  # idle, sends nothing
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
                assert r.status == 200
    finally:
        server.shutdown()
        server.server_close()


class _NoRead:
    def read(self, *_):
        raise AssertionError("body must not be read")


@pytest.mark.parametrize("length", [None, "", "abc", "-1", "0", str(ws.MAX_BODY_BYTES + 1)])
def test_webhook_rejects_bad_content_length_before_reading(monkeypatch, length):
    monkeypatch.setattr(ws, "WEBHOOK_SECRET", "secret")
    handler = object.__new__(ws.WebhookHandler)
    handler.path = "/webhook"
    handler.headers = {"X-Webhook-Secret": "secret"}
    if length is not None:
        handler.headers["Content-Length"] = length
    handler.rfile = _NoRead()
    sent = []
    handler._send = lambda status, body: sent.append(status)

    handler.do_POST()

    assert sent == [400]


def test_control_body_is_read_once_and_cached():
    from io import BytesIO
    handler = object.__new__(cs.Handler)
    handler.headers = {"Content-Length": "9"}
    handler.rfile = BytesIO(b'{"a": 1}\n')

    assert handler._body() == {"a": 1}
    assert handler._body() == {"a": 1}
