from scripts import zerodha_session


def test_cli_exchange_persists_token_without_printing_secret(monkeypatch, capsys):
    saved = []

    class FakeBroker:
        def exchange_request_token(self, request_token):
            assert request_token == "request-token"
            return {
                "access_token": "sensitive-token",
                "user_id": "AB123",
                "login_time": "2026-08-09 09:00:00",
                "exchanges": ["NSE"],
            }

    monkeypatch.setattr(zerodha_session, "ZerodhaBroker", FakeBroker)
    monkeypatch.setattr(zerodha_session, "persist_access_token", saved.append)
    monkeypatch.setattr(zerodha_session, "_access_token_file", lambda: "/tmp/kite-token")
    monkeypatch.setattr("sys.argv", ["zerodha_session.py", "exchange", "request-token"])

    assert zerodha_session.main() == 0
    output = capsys.readouterr().out
    assert saved == ["sensitive-token"]
    assert "sensitive-token" not in output
    assert "AB123" in output
