import json

from scripts import queue_telegram_notice


def test_notice_script_uses_consent_bound_queue(monkeypatch, capsys):
    captured = {}

    def fake_queue(text, signal_id):
        captured.update(text=text, signal_id=signal_id)
        return {"queued": 2, "created": 2, "blockers": []}

    monkeypatch.setattr(queue_telegram_notice, "queue_audience_message", fake_queue)

    assert queue_telegram_notice.main([
        "--signal-id", "github:failure:123",
        "--text", "workflow failed",
    ]) == 0
    assert captured == {"text": "workflow failed", "signal_id": "github:failure:123"}
    assert json.loads(capsys.readouterr().out)["queued"] == 2


def test_notice_script_returns_nonzero_when_delivery_is_gated(monkeypatch):
    monkeypatch.setattr(
        queue_telegram_notice,
        "queue_audience_message",
        lambda text, signal_id: {"queued": 0, "created": 0,
                                 "blockers": ["RELEASE_GATE_NOT_APPROVED"]},
    )

    assert queue_telegram_notice.main([
        "--signal-id", "github:failure:456", "--text", "blocked",
    ]) == 1
