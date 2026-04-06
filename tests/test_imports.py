"""
Smoke tests — verify all modules import cleanly and core classes instantiate.
Run: pytest tests/ -v
"""

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------

def test_import_ensemble():
    from src.ensemble import EnsembleModel
    m = EnsembleModel(confidence_threshold=0.62)
    assert m.threshold == 0.62


def test_import_risk_manager():
    from src.risk_manager import RiskManager
    assert RiskManager is not None


def test_import_feature_engineering():
    from src.feature_engineering import add_features
    assert callable(add_features)


def test_import_data_provider():
    from src.data_provider import load_bars
    assert callable(load_bars)


def test_import_news_sentiment():
    from src.news_sentiment import get_news_sentiment, get_sentiment_features
    assert callable(get_news_sentiment)
    assert callable(get_sentiment_features)


def test_import_macro_indicators():
    from src.macro_indicators import get_macro_indicators, get_macro_features
    assert callable(get_macro_indicators)
    assert callable(get_macro_features)


def test_import_explainer():
    from src.explainer import explain_trade
    assert callable(explain_trade)


def test_import_mlflow_tracker():
    from src.mlflow_tracker import log_metrics, get_best_run
    assert callable(log_metrics)
    assert callable(get_best_run)


def test_import_drift_detector():
    from src.drift_detector import DriftDetector
    assert DriftDetector is not None


def test_import_scanner():
    from src.scanner import scan
    assert callable(scan)


def test_import_notify():
    from src.notify import _send, send_trade_cards
    assert callable(_send)
    assert callable(send_trade_cards)


# ---------------------------------------------------------------------------
# Feature engineering smoke test (no network calls)
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 300) -> pd.DataFrame:
    """Create synthetic OHLCV DataFrame with a DatetimeIndex."""
    np.random.seed(42)
    close = 1000 + np.cumsum(np.random.randn(n) * 5)
    high = close + np.abs(np.random.randn(n) * 3)
    low = close - np.abs(np.random.randn(n) * 3)
    open_ = close + np.random.randn(n) * 2
    volume = np.random.randint(100_000, 5_000_000, n).astype(float)
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


def test_add_features_no_network():
    from src.feature_engineering import add_features

    df = _make_ohlcv(300)
    result = add_features(df, fetch_context=False, add_sentiment=False, add_macro=False)

    assert isinstance(result, pd.DataFrame)
    assert len(result) > 0
    assert "rsi_14" in result.columns
    assert "macd" in result.columns
    assert "bb_width" in result.columns
    assert "obv" in result.columns
    assert "target" in result.columns
    # Should have at least 30 feature columns
    feature_cols = [c for c in result.columns if c != "target"]
    assert len(feature_cols) >= 30, f"Only {len(feature_cols)} features: {feature_cols}"


def test_import_technical_analyzer():
    from src.technical_analyzer import analyze
    assert callable(analyze)


def test_import_stock_screener():
    from src.stock_screener import screen_stock, screen_all
    assert callable(screen_stock)
    assert callable(screen_all)


def test_import_pattern_finder():
    from src.pattern_finder import full_pattern_report
    assert callable(full_pattern_report)


def test_import_moat_analyzer():
    from src.moat_analyzer import analyze_moat
    assert callable(analyze_moat)


def test_import_macro_analyzer():
    from src.macro_analyzer import full_macro_analysis
    assert callable(full_macro_analysis)


def test_monte_carlo():
    from src.pipeline import monte_carlo_backtest
    import numpy as np
    np.random.seed(1)
    rets = np.random.randn(30) * 0.01  # 30 random daily returns
    result = monte_carlo_backtest(rets, capital=100_000, n_simulations=200)
    assert "median_outcome" in result
    assert "probability_profit" in result
    assert result["n_simulations"] == 200


def test_ensemble_fit_predict():
    from src.ensemble import EnsembleModel

    n = 200
    np.random.seed(0)
    base_probas = {
        "arima": np.random.rand(n),
        "tree": np.random.rand(n),
    }
    y = np.random.randint(0, 2, n)

    model = EnsembleModel(confidence_threshold=0.55)
    model.fit(base_probas, y)

    proba = model.predict_proba(base_probas)
    assert proba.shape == (n,)
    assert proba.min() >= 0.0
    assert proba.max() <= 1.0
