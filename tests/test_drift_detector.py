import pandas as pd

from src.drift_detector import DriftDetector


def test_drift_alert_uses_consent_bound_queue(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "src.notify.queue_audience_message",
        lambda text, signal_id: captured.update(text=text, signal_id=signal_id)
        or {"queued": 1, "created": 1, "blockers": []},
    )
    detector = DriftDetector(pd.DataFrame({"feature": [1.0, 2.0, 3.0]}))
    report = {
        "ticker": "RELIANCE",
        "data_drift": {"severity": "critical", "drifted_features": ["feature"], "feature_details": {}},
        "performance_drift": {"performance_drifted": True, "rolling_30_win_rate": 0.4,
                               "consecutive_loss_alert": False},
        "retrain_recommended": True,
    }

    result = detector._send_alert(report)

    assert result["queued"] == 1
    assert captured["signal_id"].startswith("drift:")
    assert "RELIANCE" in captured["text"]
