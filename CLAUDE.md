# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- **Always activate the venv first:** `source venv/bin/activate`. Nothing works without it.
- Everything runs as a module from repo root: `python -m src.<module>` (relies on `src` being a package + `PYTHONPATH=.`). Don't run files by path (`python src/foo.py`) — relative imports break.
- Python 3.11. Secrets live in `.env` (git-ignored); `.env.example` documents the keys. Most modules degrade gracefully when a key/dep is missing rather than crashing.

## Common Commands

```bash
# Live daily signals (rule-based scan → Telegram). Capital in ₹.
python -m src.daily_briefing --capital 50000
python -m src.auto_close                      # close positions at stop/target
python -m src.paper_trader                    # view portfolio; --scan / --buy / --sell / --reset
python -m src.scanner                          # run the scanner standalone

# ML research / backtest pipeline (ARIMA + Tree + meta-learner). Capital in $.
python -m src.pipeline --ticker RELIANCE --years 5
python -m src.pipeline --ticker RELIANCE --years 5 --lstm   # enable LSTM (slow, needs tensorflow)

# Experiment tracking + drift
mlflow ui                                      # localhost:5000
python scripts/compare_models.py --metric win_rate --top 10
python -m src.drift_detector --ticker RELIANCE

# Tests (smoke/import tests only)
pytest tests/ -v
pytest tests/test_imports.py::test_monte_carlo -v   # single test

open demo.html                                 # static 13-tab dashboard (no server)
```

## Architecture — the two signal paths (most important thing to understand)

There are **two independent signal-generation systems** that do NOT share code. Conflating them is the easiest mistake to make here.

1. **Live daily path** — `daily_briefing.py` → `scanner.py`. This is what runs in production / GitHub Actions and sends Telegram alerts. It uses a **pure-NumPy rule-based technical scorer** (`scanner._score`, 7 bullish criteria → 0–100 score), **not** the ML ensemble. Data comes straight from **yfinance** with the `.NS` NSE suffix (`watchlist.nse()`). The scan applies staged gates in order: regime gate (`regime_detector`) → sector rotation (`sector_rotation`, top 2 sectors) → multi-timeframe (daily + weekly must agree) → backtest filter (`backtest_filter`, ≥52% historical win rate) → gap-risk filter (`gap_risk`). `daily_briefing` then layers `earnings_guard` → `gtt_generator` → `notify` (Telegram) → `paper_trader`.

2. **ML research/backtest path** — `pipeline.py`. data → `feature_engineering.add_features` (52 features) → base models (`ArimaModel`, `TreeModel`, optional `LSTMModel`) → `EnsembleModel` (LogisticRegression **stacking** meta-learner over base-model probabilities, isotonic-calibrated, confidence threshold filter) → `risk_manager.backtest_with_risk` → Monte Carlo + equity curve → MLflow via `mlflow_tracker`. Data comes from `data_provider.load_bars` (**Alpaca if `ALPACA_API_KEY` set, else yfinance fallback**); default ticker `AAPL`, context features SPY + `^VIX`.

So: the ensemble model drives **backtests/research**, not the daily alerts. If asked to change "the signals users get," that's path #1 (`scanner.py`), not the ensemble.

### Key cross-cutting facts

- **Two ticker universes / currencies.** Pipeline defaults to US tickers and `$`; the live scan uses Indian NSE tickers (`.NS`) and `₹`. Watchlist tiers in `watchlist.py`: `DEFAULT_SCAN` (~78), `EXTENDED_SCAN` (~165), `DEEP_SCAN` (~195), plus `SECTOR_BASKETS` and the `STOCK_SECTOR` map used by sector rotation.
- **Halal constraints are enforced in code, not just docs:** BUY signals only, no short selling (`scanner.scan` drops anything where `signal != "BUY"`), no margin/leverage.
- **`TreeModel` uses LightGBM when importable, else falls back to RandomForest** — despite `requirements.txt` listing `xgboost`/`tensorflow`, the active tree model is LightGBM and XGBoost isn't used. `tensorflow` is only needed for the opt-in `--lstm` path.
- **Standalone analyzer modules** (`technical_analyzer`, `moat_analyzer`, `macro_analyzer`, `stock_screener`, `pattern_finder`, `news_sentiment`, `macro_indicators`, `explainer`, `correlation`, etc.) are mostly self-contained and feed `demo.html`. They're invoked ad-hoc via `python -c "from src.X import ...; ..."` (see README for exact one-liners). `demo.html` is a single static file with no backend.
- **Optional heavy/networked deps degrade silently:** FinBERT sentiment (`transformers`+`torch`), SHAP/Groq explanations, FRED macro, news RSS. `feature_engineering.add_features` takes `fetch_context` / `add_sentiment` / `add_macro` flags — pass `False` for offline/no-network runs (the feature test relies on this).

## Tests & CI

- `tests/test_imports.py` is **smoke/import coverage plus a few logic checks** (Monte Carlo, ensemble fit/predict, offline feature engineering). There is no broad behavioral test suite — keep new tests network-free (synthetic OHLCV helper `_make_ohlcv` is the pattern).
- `.github/workflows/trading_pipeline.yml` runs: CI tests on every push to `main`; scheduled nightly scan (`daily_briefing` + drift), auto-close, and a Sunday backtest, all on IST cron times. Paper-portfolio state is persisted between runs via `actions/cache` on `results/`. Failures self-notify over Telegram.

## Notes for editing

- `results/` and `mlruns/` are auto-created output dirs; don't hand-edit.
- When you add a `src/` module that should be import-checked, add it to the import test and to the workflow's "Validate imports" step.
- This project has a `graphify-out/` knowledge graph and a code-review-graph MCP server — prefer those for structural/codebase questions before grepping (see the user-level CLAUDE.md instructions). After editing `src/`, the graph can be refreshed with `graphify update .`.
