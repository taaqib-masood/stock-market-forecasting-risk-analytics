from scripts import readiness_check


def test_preflight_requires_both_channels_by_default(monkeypatch, capsys):
    monkeypatch.setattr(readiness_check, "_release_status", lambda: {
        "mode": "research", "execution_mode": "paper", "live_symbol": "RELIANCE",
        "telegram_recommendations": False, "broker_orders": False,
        "telegram_reason": "requires approval", "broker_reason": "paper mode",
        "blockers": ["RELEASE_GATE_NOT_APPROVED"],
    })

    assert readiness_check.main(["--json"]) == 1
    report = capsys.readouterr().out
    assert '"missing_channels": ["broker", "telegram"]' in report


def test_preflight_can_require_only_telegram(monkeypatch, capsys):
    monkeypatch.setattr(readiness_check, "_release_status", lambda: {
        "mode": "private", "execution_mode": "paper", "live_symbol": "RELIANCE",
        "telegram_recommendations": True, "broker_orders": False, "blockers": [],
        "telegram_reason": "enabled", "broker_reason": "paper mode",
    })

    assert readiness_check.main(["--require", "telegram"]) == 0
    assert "READY" in capsys.readouterr().out
