# Repository Guidelines

## Project Structure & Module Organization

Core Python code lives in `src/`. The production signal path runs through `daily_briefing.py` and `scanner.py`; the separate ML research path starts in `pipeline.py` and combines ARIMA, tree, and optional LSTM models. Shared portfolio, risk, alpha, and execution logic is under `src/engine/`. Keep these two signal paths distinct.

Tests live in `tests/` and mirror module names as `test_<module>.py`. Research notebooks are in `notebooks/`, operational utilities in `scripts/`, cached inputs and exported snapshots in `data/`, and static dashboard assets are stored at the repository root. Treat `results/`, `mlruns/`, `graphify-out/`, and generated `*_data.js` files as outputs unless a task explicitly targets them.

## Build, Test, and Development Commands

Use Python 3.11 from the repository root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=.
pytest tests/ -v
python -m src.daily_briefing --capital 50000
python -m src.pipeline --ticker RELIANCE --years 5
```

Install `requirements-lstm.txt` only for `python -m src.pipeline ... --lstm`. Run modules with `python -m src.<module>`; direct file execution can break relative imports. Open `demo.html` directly to inspect the static dashboard.

## Coding Style & Naming Conventions

Follow PEP 8 with four-space indentation. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; and uppercase names for constants. Prefer focused modules and explicit imports. Add short comments only where trading rules, risk calculations, or fallback behavior are not obvious. No repository-wide formatter is configured, so keep changes consistent with nearby code.

## Testing Guidelines

Use `pytest`. Keep tests deterministic and network-free; use synthetic OHLCV data and disable optional context, sentiment, or macro fetching. Add regression tests for risk limits, signal gates, execution behavior, and model input/output contracts. Run a focused test during development, then `pytest tests/ -v` before submitting.

## Commit & Pull Request Guidelines

Write concise, imperative commit subjects such as `Add gap-risk regression tests`. Keep each commit scoped to one behavior. Pull requests should explain the affected signal path, list verification commands, note configuration changes, and include screenshots for dashboard updates. Link relevant issues and call out changes to trading, compliance, or capital-risk behavior.

## Security & Configuration

Store API keys and Telegram credentials in `.env`; update `.env.example` for new variables. Never commit credentials, broker tokens, portfolio state, or private trading data. Preserve graceful fallbacks when optional services are unavailable.
