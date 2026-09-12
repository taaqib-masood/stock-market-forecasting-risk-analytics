from src import auto_close


def test_auto_close_fails_closed_in_live_mode(monkeypatch):
    monkeypatch.setenv("BORO_EXECUTION_MODE", "live")
    monkeypatch.setattr(auto_close, "_load", lambda: (_ for _ in ()).throw(AssertionError("paper state read")))

    assert auto_close.check_and_close() == []
