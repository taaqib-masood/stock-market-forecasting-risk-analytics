from datetime import datetime, timezone

from src import daily_briefing
from src import notify
from src.reliability import activation
from src.reliability.store import ReliabilityStore
from src.reliability.telegram_audience import TelegramAudience


NOW = datetime(2024, 7, 2, 4, 0, tzinfo=timezone.utc)


def test_telegram_briefing_does_not_leak_operator_portfolio_metrics():
    message = daily_briefing._build_telegram_briefing(
        [], [], "SIDEWAYS", "🟡", 24000, 987654,
        {"cash": 987654, "trades": [{"pnl": 12345}]},
    )

    assert "987,654" not in message
    assert "Portfolio" not in message
    assert "Your stats" not in message
    assert "/stop to unsubscribe" in message
    assert "not individualized financial advice" in message


def _seed_db(path):
    store = ReliabilityStore(path)
    manifest = store.register_manifest("nse-bundle", b"bundle", "2024-07-01T18:00:00Z")
    store.put_membership("TCS", "2024-01-01", "2024-01-02T03:00:00Z", manifest)
    store.put_bar("TCS", "2024-07-01", 100, 102, 99, 101, 1000,
                  "2024-07-01T18:00:00Z", manifest)
    store.put_halal_classification(
        "TCS", "2024-06-30", "GREEN", True, "aaoifi-v1",
        "2024-06-30T12:00:00Z", manifest,
    )
    store.close()
    return manifest


def test_unapproved_mode_blocks_direct_recommendation_delivery(monkeypatch):
    monkeypatch.delenv("BORO_RELIABILITY_MODE", raising=False)
    sent = []
    monkeypatch.setattr(daily_briefing, "_send", lambda text: sent.append(text) or True)

    result = daily_briefing._dispatch_briefing("hello", [], now=NOW)

    assert result["queued"] is False
    assert "RELEASE_GATE_NOT_APPROVED" in result["blockers"]
    assert sent == []


def test_private_mode_still_requires_current_release_approval(monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    sent = []
    monkeypatch.setattr(daily_briefing, "_send", lambda text: sent.append(text) or True)

    result = daily_briefing._dispatch_briefing("hello", [], now=NOW)

    assert result["queued"] is False
    assert "RELEASE_GATE_NOT_APPROVED" in result["blockers"]
    assert sent == []


def test_approved_private_mode_queues_each_consented_recipient(tmp_path, monkeypatch):
    db = tmp_path / "approved.db"
    _seed_db(db)
    with ReliabilityStore(db) as store:
        TelegramAudience(store.connection).subscribe("12345", "terms-v1", now=NOW)

    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(db))
    monkeypatch.setenv("TELEGRAM_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setattr(
        daily_briefing, "_release_gate",
        lambda: {"approved": True, "blockers": []},
    )
    monkeypatch.setattr(
        activation, "assess_shadow_readiness",
        lambda *args, **kwargs: {"ready": True, "blockers": [], "metrics": {}},
    )
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)
    monkeypatch.setattr(
        notify, "send_outbox_payload", lambda _payload: {"message_id": "tg-1"}
    )

    result = daily_briefing._dispatch_briefing(
        "BUY TCS", [{"ticker": "TCS"}], now=NOW
    )

    assert result["queued"] == 1
    assert result["created"] == 1
    assert result["delivery"]["delivered"] == 1
    with ReliabilityStore(db) as store:
        assert store.connection.execute(
            "SELECT COUNT(*) FROM delivery_outbox"
        ).fetchone()[0] == 1


def test_approved_private_mode_rejects_signal_outside_eligible_universe(tmp_path, monkeypatch):
    db = tmp_path / "approved.db"
    _seed_db(db)
    with ReliabilityStore(db) as store:
        TelegramAudience(store.connection).subscribe("12345", "terms-v1", now=NOW)

    monkeypatch.setenv("BORO_RELIABILITY_MODE", "private")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(db))
    monkeypatch.setattr(daily_briefing, "_release_gate",
                        lambda: {"approved": True, "blockers": []})
    monkeypatch.setattr(
        activation, "assess_shadow_readiness",
        lambda *args, **kwargs: {"ready": True, "blockers": [], "metrics": {}},
    )
    monkeypatch.setattr(notify, "_recommendation_delivery_approved", lambda: True)

    result = daily_briefing._dispatch_briefing(
        "BUY UNKNOWN", [{"ticker": "UNKNOWN"}], now=NOW
    )

    assert result["queued"] is False
    assert result["blockers"] == ["SIGNAL_NOT_IN_UNIVERSE"]
    with ReliabilityStore(db) as store:
        assert store.connection.execute(
            "SELECT COUNT(*) FROM delivery_outbox"
        ).fetchone()[0] == 0


def test_shadow_mode_fails_closed_when_database_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "shadow")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(tmp_path / "empty.db"))
    direct = []
    monkeypatch.setattr(daily_briefing, "_send", lambda text: direct.append(text) or True)

    result = daily_briefing._dispatch_briefing("hello", [], now=NOW)

    assert result["queued"] is False
    assert "UNIVERSE_EMPTY" in result["blockers"]
    assert direct == []


def test_shadow_mode_remains_blocked_without_verified_corporate_action_audit(tmp_path, monkeypatch):
    db = tmp_path / "ready.db"
    _seed_db(db)
    monkeypatch.setenv("BORO_RELIABILITY_MODE", "shadow")
    monkeypatch.setenv("BORO_RELIABILITY_DB", str(db))

    result = daily_briefing._dispatch_briefing(
        "BUY TCS", [{"ticker": "TCS", "entry": 101, "stop": 98, "target": 107}],
        now=NOW,
    )

    assert result["queued"] is False
    assert "CORPORATE_ACTION_REVIEW" in result["blockers"]
    with ReliabilityStore(db) as store:
        assert store.connection.execute(
            "SELECT COUNT(*) FROM signal_events"
        ).fetchone()[0] == 0
        assert store.connection.execute(
            "SELECT COUNT(*) FROM delivery_outbox"
        ).fetchone()[0] == 0
