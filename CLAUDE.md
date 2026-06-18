# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A halal (Shariah-compliant) stock trading system for Indian (NSE) equities. It scans a
watchlist, generates BUY-only signals from an ensemble model, applies risk rules, paper-trades
them, and pushes alerts to Telegram. There is no web backend — `demo.html` is a single
self-contained dashboard and the Python `src/` package is run as CLI modules.

## Commands

All modules are run with `python -m src.<module>` from the repo root (relies on the package
layout — `PYTHONPATH` must include the repo root, which CI sets explicitly).

```bash
# Tests (only smoke/import tests + a few unit tests exist)
pytest tests/ -v
pytest tests/test_imports.py::test_ensemble_fit_predict -v   # single test

# Daily ops
python -m src.daily_briefing --capital 50000   # morning scan → Telegram
python -m src.auto_close                        # close positions at stop/target
python -m src.paper_trader                      # view portfolio (--scan, --buy, --sell, --reset)

# Train + backtest one ticker (writes to results/)
python -m src.pipeline --ticker RELIANCE --years 5            # default ticker is AAPL
python -m src.pipeline --ticker RELIANCE --years 5 --lstm     # enable LSTM (slow)

# Experiment tracking & monitoring
mlflow ui                                        # localhost:5000
python scripts/compare_models.py                 # compare MLflow runs
python -m src.drift_detector --ticker RELIANCE
```

Most `src/*.py` modules are independently runnable (`if __name__ == "__main__"`); run them
directly to exercise a single subsystem.

## Architecture

Pipeline flow (see `src/pipeline.py`, the canonical end-to-end path):

```
data_provider.load_bars → feature_engineering.add_features → base models
  → ensemble.EnsembleModel (stacking meta-learner) → risk_manager.backtest_with_risk
  → metrics.summarise + monte_carlo_backtest → results/ + mlflow_tracker
```

Key abstractions:

- **`data_provider.py`** — single source of OHLCV. Uses Alpaca REST if `ALPACA_API_KEY` is
  set, else silently falls back to yfinance. `load_market_context()` adds SPY trend + VIX
  regime columns. VIX always comes from yfinance (not on Alpaca free tier).
- **`feature_engineering.add_features(df, fetch_context=, add_sentiment=, add_macro=)`** —
  produces the ~52 features. Sentiment/macro are opt-in (network calls). Always emits a
  `target` column. Pass `fetch_context=False` to stay offline (tests rely on this).
- **Base models** — `arima_model.ArimaModel` (directional signal only), `tree_model.TreeModel`
  (LightGBM/RandomForest), `lstm_model.LSTMModel` (optional). Each exposes `predict_proba`.
- **`ensemble.EnsembleModel`** — logistic-regression meta-learner over base-model P(UP)
  estimates, isotonic-calibrated. `signals()` returns signal/confidence/size_factor;
  trades only fire when confidence ≥ `confidence_threshold` (default 0.62).
- **`risk_manager.backtest_with_risk`** — applies ATR stops, 2% max risk, R:R ≥ 2, position
  caps, consecutive-loss circuit breaker, and cost modeling (slippage + commission).
- **`scanner.py`** — lightweight standalone scorer over the watchlist (its own numpy TA
  helpers, no model). `daily_briefing.py` and `auto_close.py` are the scheduled entry points
  that wire scanner → notify.
- **`watchlist.py`** — the ~195 Shariah-screened NSE tickers, grouped into `DEFAULT_SCAN` /
  `EXTENDED_SCAN` / deep tiers plus thematic baskets (`HALAL_IT`, `HALAL_PHARMA`, etc.).

The remaining `src/` modules are largely independent analyzers feeding the dashboard or alerts
(`news_sentiment` FinBERT, `macro_indicators`, `explainer` SHAP+Groq, `moat_analyzer`,
`stock_screener`, `regime_detector`, `gtt_generator` for Zerodha orders, `notify` Telegram).

## Conventions & gotchas

- Currency is mixed by design: `pipeline.py` defaults to a US ticker (AAPL) and `$`, while the
  live trading path (`daily_briefing`, `paper_trader`, watchlist) is NSE/India and `₹`.
- Halal rules are enforced in code: **BUY-only, no shorting, no margin/leverage.** Don't add
  short-side logic.
- `.gitignore` excludes `results/`, `*.csv`, `*.png`, `.env` — runtime artifacts and secrets
  are never committed. CI caches `results/` between scheduled runs to persist paper-portfolio state.
- Tests are import/smoke-level. When adding a module, add a matching `test_import_*` to
  `tests/test_imports.py` and to the import-validation step in
  `.github/workflows/trading_pipeline.yml` — both must list it or CI fails.
- API keys come from `.env` (see `.env.example`): `ALPACA_*`, `TELEGRAM_TOKEN`,
  `TELEGRAM_CHAT_ID`, `GROQ_API_KEY`, `FRED_API_KEY`. In CI they're GitHub secrets.
- `matplotlib` uses the `Agg` backend (headless) — set in `pipeline.py`.
