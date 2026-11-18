from src import web_dashboard


def test_legacy_dashboard_trade_api_requires_header_token(monkeypatch):
    handler = object.__new__(web_dashboard.Handler)
    handler.headers = {}
    monkeypatch.setattr(web_dashboard, "TRADE_TOKEN", "local-secret")

    assert handler._trade_authed() is False
    handler.headers = {"X-Web-Trade-Token": "local-secret"}
    assert handler._trade_authed() is True


def test_legacy_dashboard_trade_api_is_disabled_without_token(monkeypatch):
    handler = object.__new__(web_dashboard.Handler)
    handler.headers = {"X-Web-Trade-Token": "anything"}
    monkeypatch.setattr(web_dashboard, "TRADE_TOKEN", "")

    assert handler._trade_authed() is False


def _handler(headers, port=5000):
    handler = object.__new__(web_dashboard.Handler)
    handler.headers = headers
    handler.server = type("S", (), {"server_address": ("127.0.0.1", port)})()
    return handler


def test_dashboard_rejects_rebound_host():
    assert _handler({"Host": "127.0.0.1:5000"})._host_allowed() is True
    assert _handler({"Host": "localhost:5000"})._host_allowed() is True
    assert _handler({"Host": "evil.example:5000"})._host_allowed() is False
    assert _handler({"Host": "localhost:6000"})._host_allowed() is False
    assert _handler({})._host_allowed() is False


def test_dashboard_post_requires_local_origin():
    ok = {"Host": "127.0.0.1:5000"}
    assert _handler(ok)._host_allowed(check_origin=True) is True
    assert _handler({**ok, "Origin": "http://127.0.0.1:5000"})._host_allowed(check_origin=True) is True
    assert _handler({**ok, "Origin": "http://evil.example:5000"})._host_allowed(check_origin=True) is False
    assert _handler({**ok, "Origin": "null"})._host_allowed(check_origin=True) is False


def test_dashboard_extra_allowed_hosts(monkeypatch):
    monkeypatch.setattr(web_dashboard, "ALLOWED_HOSTS", ["box.lan"])
    assert _handler({"Host": "box.lan:5000"})._host_allowed() is True
