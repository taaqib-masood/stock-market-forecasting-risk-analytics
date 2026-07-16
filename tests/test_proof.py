"""
Tests for the proof aggregator (pooling per-ticker backtests into one verdict).
Pure/deterministic — no network. The real run lives in src.proof.run_india_halal_proof.

Run: pytest tests/test_proof.py -v
"""

import numpy as np
import pandas as pd

from src.proof import aggregate_proof


def _fake_result(pnls, closes, signals, confs):
    n = len(pnls)
    tl = pd.DataFrame({
        "pnl": pnls,
        "commission": [0.5] * n,
        "slippage_cost": [1.0] * n,
        "won": [p > 0 for p in pnls],
        "equity": [100_000 + sum(pnls[: i + 1]) for i in range(n)],
    })
    cidx = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    feats = pd.DataFrame({"Close": closes}, index=cidx)
    sig = pd.DataFrame({"signal": signals, "confidence": confs}, index=cidx)
    return {"trade_log": tl, "features": feats, "signals": sig}


def test_aggregate_proof_pools_and_reports():
    closes = list(1000 + np.arange(14) * 2.0)
    signals = [1, 0] * 7
    confs = [0.8 if s else 0.2 for s in signals]
    r1 = _fake_result([100.0, -50.0], closes, signals, confs)
    r2 = _fake_result([200.0, -30.0], closes, signals, confs)

    out = aggregate_proof([r1, r2], capital=100_000)
    assert out["total_trades"] == 4
    assert out["tickers_traded"] == 2
    assert "win_rate_pct" in out["net"] and "win_rate_pct" in out["gross"]
    # Costs reduce net: gross avg return per trade >= net avg return per trade.
    assert out["gross"]["avg_return_per_trade_pct"] >= out["net"]["avg_return_per_trade_pct"]
    assert "rank_ic" in out


def test_aggregate_proof_empty():
    out = aggregate_proof([], capital=100_000)
    assert out["total_trades"] == 0
    assert out["net"] == {}
    assert out["rank_ic"] is None
