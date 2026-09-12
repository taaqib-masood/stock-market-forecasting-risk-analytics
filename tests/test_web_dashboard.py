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
