# Graph Report - stock-market-forecasting-risk-analytics  (2026-11-05)

## Corpus Check
- 99 files · ~116,436 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 12 file(s) not represented in the graph (top: .ipynb 4, (none) 3, .csv 3)

## Summary
- 1079 nodes · 2545 edges · 61 communities (all shown)
- Extraction: 96.9% EXTRACTED · 3.1% INFERRED · 0.0% AMBIGUOUS · INFERRED: 80 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c953ce5e`
- Source-aware freshness check (stale only if this command prints paths; documentation-only and graph-only commits do not count):

```sh
git diff --name-only c953ce5e5f7237780ba888b2499d58c1fb2bb405 HEAD -- ':(glob)**/*.js' ':(glob)**/*.json' ':(glob)**/*.py' ':(glob)**/*.yml' ':(exclude)graphify-out/**'
```
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- test_imports.py
- pandas
- time
- RiskManager
- RuleStrategy
- metrics.py
- test_backtest_runner.py
- test_halal_screen.py
- yfinance
- paper_trader.py
- walk_forward.py
- trade_dashboard.py
- add_features
- technical_analyzer.py
- macro_indicators.py
- dashboard.py
- test_walk_forward.py
- datetime
- halal_history.py
- job
- web_dashboard.py
- news_sentiment.py
- mlflow_tracker.py
- pipeline.py
- EnsembleModel
- scan
- tier_monitor.py
- export_dashboard.py
- dynamic_stops.py
- numpy
- json
- backtest_runner.py
- TreeModel
- steps
- ArimaModel
- LSTMModel
- data_provider.py
- halal_lookup.py
- detect
- dispatch.js
- Handler
- correlation.py
- research-backtest
- backtest_filter.py
- earnings_guard.py
- notify.py
- nightly-scan
- nse
- jobs
- with
- start_run
- env
- watchlist.py
- quarterly-rescreen
- weekly-backtest
- halal_screen.py

## God Nodes (most connected - your core abstractions)
1. `nse()` - 40 edges
2. `RuleStrategy` - 38 edges
3. `add_features()` - 36 edges
4. `run()` - 32 edges
5. `RiskManager` - 27 edges
6. `walk_forward()` - 24 edges
7. `Strategy` - 23 edges
8. `scan()` - 22 edges
9. `classify()` - 18 edges
10. `summarise()` - 18 edges

## Surprising Connections (you probably didn't know these)
- `test_import_feature_engineering()` --indirect_call--> `add_features()`  [INFERRED]
  tests/test_imports.py → src/feature_engineering.py
- `test_import_pattern_finder()` --indirect_call--> `full_pattern_report()`  [INFERRED]
  tests/test_imports.py → src/pattern_finder.py
- `test_import_risk_manager()` --uses--> `RiskManager`  [INFERRED]
  tests/test_imports.py → src/risk_manager.py
- `test_import_scanner()` --indirect_call--> `scan()`  [INFERRED]
  tests/test_imports.py → src/scanner.py
- `test_import_control_server()` --indirect_call--> `_portfolio()`  [INFERRED]
  tests/test_imports.py → src/control_server.py

## Import Cycles
- None detected.

## Communities (61 total; all shown)

### Community 0 - "test_imports.py"
Cohesion: 0.05
Nodes (58): DriftDetector, .check_data_drift(), .check_performance_drift(), .__init__(), .run_full_check(), ._send_alert(), _psi(), DataFrame (+50 more)

### Community 1 - "pandas"
Cohesion: 0.11
Nodes (51): pandas, pytest, drawdown_guard.py, current_state(), explain(), format_card(), live_card(), Series (+43 more)

### Community 2 - "time"
Cohesion: 0.08
Nodes (47): logging, math, pathlib, refresh_fundamentals.py, fetch_one(), main(), _num(), Quarterly fundamentals refresh (decoupled from the trading runtime). WHY… (+39 more)

### Community 3 - "RiskManager"
Cohesion: 0.10
Nodes (42): risk_manager.py, backtest_with_risk(), DataFrame, Series, Manually reset the consecutive-loss counter (e.g. start of new week)., Walk through signals chronologically applying RiskManager rules. Applies…, Fractional Kelly (25% Kelly for safety)., Hard rules applied to every trade signal. Rules enforced: 1. Max risk per trade… (+34 more)

### Community 4 - "RuleStrategy"
Cohesion: 0.10
Nodes (40): DataFrame, Track-A candidate: the base 7 criteria PLUS daily-bar additions, to be GATED…, Returns a DataFrame indexed like `features` with columns: - score : 0-100…, 7-criteria bullish score, computed from engineered feature columns so live and…, The 7 per-bar boolean criteria — the single source of truth used by both the…, RuleStrategy, .criteria(), .generate_signals() (+32 more)

### Community 5 - "metrics.py"
Cohesion: 0.09
Nodes (39): concurrent_futures, scipy_stats, metrics.py, annual_return(), avg_win_loss_ratio(), calmar_ratio(), directional_accuracy(), expected_value() (+31 more)

### Community 6 - "test_backtest_runner.py"
Cohesion: 0.10
Nodes (37): cost_breakdown(), generate_live_signal(), passes_backtest(), DataFrame, Historical-viability gate (replaces src.backtest_filter.passes_backtest).…, Latest-bar live BUY trade card, using the SAME Strategy + RiskManager as the…, Win rate / profit factor / P&L summary from a backtest_with_risk trade log., Backtest `strategy` on raw OHLCV `df` through the unified pipeline. Returns… (+29 more)

### Community 7 - "test_halal_screen.py"
Cohesion: 0.11
Nodes (32): classify(), Classify a company into 🟢/🟡/🔴 from its AAOIFI ratios + sector flags., zakat.py, portfolio_zakat_report(), purification_due(), purification_for_portfolio(), Zakat + dividend-purification ledger. Current-portfolio computations with no…, Full annual halal-wealth report for a portfolio: Zakat (on total market value… (+24 more)

### Community 8 - "yfinance"
Cohesion: 0.12
Nodes (30): contextlib, io, gap_risk.py, analyse(), _beta(), _gap_series(), position_size_multiplier(), ndarray (+22 more)

### Community 9 - "paper_trader.py"
Cohesion: 0.14
Nodes (30): dotenv, auto_close.py, check_and_close(), Auto Stop-Loss & Target Checker ================================= Run every…, Send Telegram message with close outcomes + portfolio update., Fetch live prices for all open positions. Close any that hit stop or target.…, run(), _telegram_summary() (+22 more)

### Community 10 - "walk_forward.py"
Cohesion: 0.12
Nodes (30): walk_forward.py, buy_and_hold_return(), compare_selection_universe(), compare_strategies_universe(), _costs(), criteria_correlation_universe(), _fetch_nifty(), _load() (+22 more)

### Community 11 - "trade_dashboard.py"
Cohesion: 0.14
Nodes (28): csv, journal.py, close_trade(), load_all(), log_signal(), _next_id(), Trade Journal — auto-tracks every signal and outcome. Stored as a simple CSV:…, Log a new trade signal. Returns the journal row. (+20 more)

### Community 12 - "add_features"
Cohesion: 0.12
Nodes (26): scipy, drift_detector.py, build_detector(), _print_report(), UPGRADE 6: Model & Data Drift Detection Monitors two types of drift: 1. Data…, Build a DriftDetector using historical data as the reference distribution.…, feature_engineering.py, add_features() (+18 more)

### Community 13 - "technical_analyzer.py"
Cohesion: 0.14
Nodes (25): functools, technical_analyzer.py, analyze(), _bollinger(), _confidence_rating(), _detect_chart_pattern(), _ema(), _fetch() (+17 more)

### Community 14 - "macro_indicators.py"
Cohesion: 0.15
Nodes (25): macro_indicators.py, _classify_vix(), _classify_yield_curve(), _fetch_advance_decline_ratio(), _fetch_dxy(), _fetch_fed_funds_rate(), _fetch_gold(), _fetch_nifty50() (+17 more)

### Community 15 - "dashboard.py"
Cohesion: 0.15
Nodes (23): dashboard.py, _alpaca_get(), _alpaca_headers(), fetch_all(), run(), get_account(), get_daily_bars(), get_latest_quote() (+15 more)

### Community 16 - "test_walk_forward.py"
Cohesion: 0.16
Nodes (23): compare_strategies(), criteria_correlation(), DataFrame, Evaluate `strategy` on `n_splits` contiguous out-of-sample windows of `df`. For…, Run both strategies through identical walk-forward windows and report the…, Pairwise correlation of the strategy's boolean criteria, pooled across every…, walk_forward(), test_import_walk_forward() (+15 more)

### Community 17 - "datetime"
Cohesion: 0.13
Nodes (22): collections, datetime, hmac, http_server, os, compare_models.py, main(), _fmt() (+14 more)

### Community 18 - "halal_history.py"
Cohesion: 0.19
Nodes (22): re, halal_history.py, compliance_changes(), format_timeline(), _history(), Point-in-time halal screening — "was this stock compliant back THEN?" The…, Extract the 4-digit year from 'FY 2021' / 'FY2021' / '2021' / 2021., Classify `ticker` using the fundamentals it reported for `period` (a fiscal… (+14 more)

### Community 19 - "job"
Cohesion: 0.10
Nodes (21): job, ticker, years, default, description, options, required, type (+13 more)

### Community 20 - "web_dashboard.py"
Cohesion: 0.15
Nodes (20): secrets, portfolio_correlation_risk(), Evaluate the correlation risk of the current portfolio. Returns avg_corr,…, filter_cards(), Filter trade cards by gap risk. HIGH gap risk → blocked (if block_high=True) or…, web_dashboard.py, _correlation(), Handler (+12 more)

### Community 21 - "news_sentiment.py"
Cohesion: 0.17
Nodes (19): feedparser, news_sentiment.py, _analyze_sentiment(), _cache_key(), _fetch_google_news_headlines(), _fetch_reddit_headlines(), _fetch_yahoo_headlines(), _from_cache() (+11 more)

### Community 22 - "mlflow_tracker.py"
Cohesion: 0.17
Nodes (19): hashlib, pickle, mlflow_tracker.py, get_best_run(), _get_client(), log_dataset_hash(), log_feature_importance(), log_metrics() (+11 more)

### Community 23 - "pipeline.py"
Cohesion: 0.20
Nodes (18): matplotlib, matplotlib_pyplot, export_backtest.py, load_history(), main(), Run a src.pipeline backtest for one ticker and append the result to the…, save_history(), pipeline.py (+10 more)

### Community 24 - "EnsembleModel"
Cohesion: 0.19
Nodes (17): sklearn_calibration, sklearn_linear_model, ensemble.py, EnsembleModel, .fit(), .__init__(), .predict(), .predict_proba() (+9 more)

### Community 25 - "scan"
Cohesion: 0.20
Nodes (17): daily_briefing.py, _market_regime(), Daily Briefing — runs every morning at 9 AM…, Returns (regime_str, emoji, nifty_price)., Build and send the full Telegram morning message., run(), _telegram_briefing(), gtt_generator.py (+9 more)

### Community 26 - "tier_monitor.py"
Cohesion: 0.19
Nodes (17): tier_monitor.py, check_and_snapshot(), current_tiers(), diff_tiers(), format_changes(), Path, Halal tier-change monitor. After each fundamentals refresh, diff today's 🟢/🟡/🔴…, Screen every cached ticker → {ticker: {tier, debt_to_assets,… (+9 more)

### Community 27 - "export_dashboard.py"
Cohesion: 0.18
Nodes (16): argparse, glob, export_dashboard.py, _equity(), main(), _market(), _passive(), _portfolio() (+8 more)

### Community 28 - "dynamic_stops.py"
Cohesion: 0.17
Nodes (16): dataclasses, Enum, dynamic_stops.py, Dynamic & Trailing Stop Loss ============================= Replaces fixed ATR…, Recommend stop type based on R:R and target distance., Given entry, ATR and regime, return recommended stop and type., Update stop based on current price and ATR. Returns dict with new_stop, action,…, recommend_stop() (+8 more)

### Community 29 - "numpy"
Cohesion: 0.20
Nodes (16): numpy, scanner.py, _atr(), _ema(), ndarray, Multi-stock scanner. Scans the NSE watchlist, scores each stock, returns ranked…, Build an actionable trade card from a score dict., Returns 'UP', 'DOWN', or 'NEUTRAL' based on weekly chart. UP = price > weekly… (+8 more)

### Community 30 - "json"
Cohesion: 0.24
Nodes (15): json, build_halal_dashboard_data.py, build(), main(), Build the dashboard's halal data file from the fundamentals cache. demo.html is…, fundamentals.py, get_fundamentals(), _is_stale() (+7 more)

### Community 31 - "backtest_runner.py"
Cohesion: 0.22
Nodes (14): ABC, backtest_runner.py, backtest_ticker(), filter_cards(), Unified backtest runner — the single path that backtests *exactly what we…, Fetch wrapper: load `years` of NSE daily data and run the unified backtest.…, Unified per-stock historical gate (drop-in for…, strategy.py (+6 more)

### Community 32 - "TreeModel"
Cohesion: 0.19
Nodes (14): lightgbm, sklearn_ensemble, tree_model.py, DataFrame, ndarray, Series, Directional classifier. Uses LightGBM if available (faster, better on tabular…, Returns probability of class 1 (UP). (+6 more)

### Community 33 - "steps"
Cohesion: 0.31
Nodes (13): steps, if, name, runs-on, steps, ci-tests, steps, steps (+5 more)

### Community 34 - "ArimaModel"
Cohesion: 0.17
Nodes (13): pmdarima, arima_model.py, ArimaModel, .fit(), .forecast(), .__init__(), .signal(), ndarray (+5 more)

### Community 35 - "LSTMModel"
Cohesion: 0.26
Nodes (13): sklearn_preprocessing, lstm_model.py, LSTMModel, ._build_model(), .fit(), .__init__(), ._make_sequences(), .predict() (+5 more)

### Community 36 - "data_provider.py"
Cohesion: 0.28
Nodes (13): data_provider.py, _alpaca_available(), _alpaca_headers(), _fetch_alpaca(), _fetch_yfinance(), load_bars(), load_market_context(), DataFrame (+5 more)

### Community 37 - "halal_lookup.py"
Cohesion: 0.29
Nodes (12): halal_lookup.py, format_card(), lookup(), "Is this stock halal?" lookup — the shareable, single-ticker verdict. Cache-…, Unified halal verdict for `ticker`: cached fundamentals first, else live…, Best-effort screen of a live ticker from yfinance current fundamentals., screen_ticker(), test_halal_lookup.py (+4 more)

### Community 38 - "detect"
Cohesion: 0.29
Nodes (11): regime_detector.py, _adx(), _default_regime(), detect(), _fetch(), Advanced Market Regime Detector ================================ Detects 5…, Simplified ADX (trend strength 0-100)., Detect current market regime. Cached for 30 minutes. (+3 more)

### Community 39 - "dispatch.js"
Cohesion: 0.27
Nodes (10): dispatch.js, ALLOWED, ALLOWED_ORIGINS, crypto, handler(), hits, rateOk(), resp() (+2 more)

### Community 40 - "Handler"
Cohesion: 0.38
Nodes (10): Handler, ._authed(), ._cors(), .do_GET(), .do_OPTIONS(), .do_POST(), ._json(), .log_message() (+2 more)

### Community 41 - "correlation.py"
Cohesion: 0.24
Nodes (10): correlation.py, correlation_matrix(), is_too_correlated(), DataFrame, Series, Correlation & Portfolio Risk ============================= Computes a…, Daily returns series for a ticker., Compute pairwise correlation matrix for a list of tickers. Returns a DataFrame… (+2 more)

### Community 42 - "research-backtest"
Cohesion: 0.22
Nodes (9): BT_TICKER, BT_YEARS, research-backtest, env, if, name, runs-on, steps (+1 more)

### Community 43 - "backtest_filter.py"
Cohesion: 0.28
Nodes (9): backtest_filter.py, _backtest_ticker(), ema(), filter_cards(), passes_backtest(), Per-Stock Backtest Filter ========================= Before recommending a…, Returns (True, stats) if stock passes historical backtest. Returns (False,…, Filter trade cards by historical backtest. Returns (passed_cards, failed_cards). (+1 more)

### Community 44 - "earnings_guard.py"
Cohesion: 0.31
Nodes (9): earnings_guard.py, _fetch_upcoming_results(), filter_cards(), has_earnings_soon(), _nse_get(), Earnings Calendar Guard ======================= Checks if a stock has…, Fetch tickers with board meetings / earnings announced on NSE within the next…, Returns (True, reason) if the stock has earnings within `days` days. Returns… (+1 more)

### Community 45 - "notify.py"
Cohesion: 0.33
Nodes (9): notify.py, _card_text(), Telegram notifier — sends daily trade cards to your phone. Setup (free, 2…, _send(), send_journal_summary(), send_trade_cards(), test_import_notify(), urllib_error (+1 more)

### Community 46 - "nightly-scan"
Cohesion: 0.25
Nodes (8): nightly-scan, if, name, permissions, runs-on, contents, permissions, permissions

### Community 47 - "nse"
Cohesion: 0.32
Nodes (8): Per-ticker indicators for the Technical drill-down (real bars → scanner._score)., _technicals(), one(), buy_and_hold_benchmark(), _bh(), Equal-weight buy-and-hold return of the universe over the window = the pure…, nse(), Convert NSE ticker to yfinance format (append .NS).

### Community 48 - "jobs"
Cohesion: 0.29
Nodes (7): trading_pipeline.yml, if, name, runs-on, jobs, auto-close, name

### Community 49 - "with"
Cohesion: 0.29
Nodes (7): with, key, name, path, python-version, restore-keys, retention-days

### Community 50 - "start_run"
Cohesion: 0.29
Nodes (7): _ensure_experiment(), Create experiment if it doesn't exist; return experiment_id., Context manager that wraps a training run with MLflow tracking. Usage: with…, start_run, .__enter__(), .__exit__(), .__init__()

### Community 51 - "env"
Cohesion: 0.33
Nodes (6): env, FRED_API_KEY, GROQ_API_KEY, PYTHONPATH, TELEGRAM_CHAT_ID, TELEGRAM_TOKEN

### Community 52 - "watchlist.py"
Cohesion: 0.33
Nodes (6): watchlist.py, get_sector(), get_tickers_by_sector(), NSE Halal Watchlist — Shariah-compliant stocks only. Expanded to ~200 stocks…, Return sector for a ticker, or 'Unknown'., Return all halal tickers in a given sector.

### Community 53 - "quarterly-rescreen"
Cohesion: 0.40
Nodes (5): quarterly-rescreen, if, name, runs-on, timeout-minutes

### Community 54 - "weekly-backtest"
Cohesion: 0.40
Nodes (5): weekly-backtest, if, name, runs-on, timeout-minutes

### Community 55 - "halal_screen.py"
Cohesion: 0.40
Nodes (5): halal_screen.py, _clean_ratio(), AAOIFI halal screening + tiering (🟢 / 🟡 / 🔴). Encodes the locked policy: - 🟢…, Coerce None/NaN/non-numeric to None (a missing ratio is 'unknown', not 0)., _worst()

### Community 56 - "backtest_data.js"
Cohesion: 1.00
Nodes (1): backtest_data.js

### Community 57 - "dashboard_data.js"
Cohesion: 1.00
Nodes (1): dashboard_data.js

### Community 58 - "halal_data.js"
Cohesion: 1.00
Nodes (1): halal_data.js

### Community 59 - "info_data.js"
Cohesion: 1.00
Nodes (1): info_data.js

### Community 60 - "__init__.py"
Cohesion: 1.00
Nodes (1): __init__.py

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `nse()` connect `nse` to `test_imports.py`, `pandas`, `time`, `halal_lookup.py`, `metrics.py`, `yfinance`, `correlation.py`, `paper_trader.py`, `backtest_filter.py`, `walk_forward.py`, `technical_analyzer.py`, `watchlist.py`, `halal_screen.py`, `export_dashboard.py`, `numpy`, `backtest_runner.py`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `add_features()` (e.g. with `_days_to_nse_expiry()` and `_holiday_proximity()`) actually correct?**
  _`add_features()` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Should `test_imports.py` be split into smaller, more focused modules?**
  _Cohesion score 0.05021173623714459 - nodes in this community are weakly interconnected._
- **Why does `run()` connect `pipeline.py` to `TreeModel`, `pandas`, `ArimaModel`, `LSTMModel`, `RiskManager`, `metrics.py`, `add_features`, `start_run`, `mlflow_tracker.py`, `EnsembleModel`, `numpy`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Should `pandas` be split into smaller, more focused modules?**
  _Cohesion score 0.10509803921568628 - nodes in this community are weakly interconnected._
- **Why does `scan()` connect `scan` to `test_imports.py`, `detect`, `yfinance`, `paper_trader.py`, `trade_dashboard.py`, `web_dashboard.py`, `export_dashboard.py`, `numpy`, `backtest_runner.py`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Should `time` be split into smaller, more focused modules?**
  _Cohesion score 0.08325624421831637 - nodes in this community are weakly interconnected._
## Build scope

AST-only extraction of 81 code files. Documents and media were not semantically extracted. Community names use deterministic hub labels. No LLM or paid API calls were made.

Raw pre-build extraction diagnostics (not exported-graph counts): dangling_endpoint_edges=504, undirected_same_endpoint_collapsed_edges=211. During build, endpoints may be resolved or external import stubs created; edges whose endpoints remain unresolved are dropped and are absent from `graph.json`. The exported graph has no dangling endpoints.
