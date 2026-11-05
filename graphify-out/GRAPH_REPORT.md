# Graph Report - stock-market-forecasting-risk-analytics  (2026-11-05)

## Corpus Check
- 99 files · ~116,436 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 12 file(s) not represented in the graph (top: .ipynb 4, (none) 3, .csv 3)

## Summary
- 1079 nodes · 2545 edges · 61 communities (49 shown, 12 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 80 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c53e2e5a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
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

## Communities (61 total, 12 thin omitted)

### Community 0 - "test_imports.py"
Cohesion: 0.05
Nodes (26): DriftDetector, _psi(), _build_prompt(), _call_groq(), _call_ollama(), explain_trade(), _fallback_explanation(), _get_shap_values() (+18 more)

### Community 1 - "pandas"
Cohesion: 0.11
Nodes (28): current_state(), explain(), format_card(), live_card(), apply_overlay(), basket_daily_returns(), drawdown_exposure(), _fetch_benchmark() (+20 more)

### Community 2 - "time"
Cohesion: 0.08
Nodes (27): fetch_one(), main(), _num(), _retry(), _cache_get(), _cache_set(), _classify_cycle(), _fred() (+19 more)

### Community 3 - "RiskManager"
Cohesion: 0.10
Nodes (20): backtest_with_risk(), RiskManager, _execute_alpaca(), WebhookHandler, _series(), test_backtest_losing_long_hits_stop(), test_backtest_no_signals_returns_empty(), test_backtest_winning_long_hits_target() (+12 more)

### Community 4 - "RuleStrategy"
Cohesion: 0.10
Nodes (18): RuleStrategy, RuleStrategyV2, detect_lookahead(), _df(), _row(), test_all_seven_pass_full_score_buy(), test_boundary_values_are_inclusive(), test_exactly_five_criteria_buys() (+10 more)

### Community 5 - "metrics.py"
Cohesion: 0.09
Nodes (19): annual_return(), avg_win_loss_ratio(), calmar_ratio(), directional_accuracy(), expected_value(), mae(), max_drawdown(), profit_factor() (+11 more)

### Community 6 - "test_backtest_runner.py"
Cohesion: 0.10
Nodes (23): cost_breakdown(), generate_live_signal(), passes_backtest(), run_backtest(), summarize_trades(), _AlwaysBuy, _ForcedBuyOnce, _make_ohlcv() (+15 more)

### Community 7 - "test_halal_screen.py"
Cohesion: 0.11
Nodes (23): classify(), portfolio_zakat_report(), purification_due(), purification_for_portfolio(), zakat_due(), test_clean_company_is_green(), test_get_fundamentals_staleness_and_missing(), test_high_debt_is_red() (+15 more)

### Community 8 - "yfinance"
Cohesion: 0.12
Nodes (10): analyse(), _beta(), _gap_series(), position_size_multiplier(), _scan_one(), rank_sectors(), _sector_score(), adjusted_shares() (+2 more)

### Community 9 - "paper_trader.py"
Cohesion: 0.14
Nodes (17): check_and_close(), run(), _telegram_summary(), _portfolio(), buy(), _fresh(), live_price(), live_prices() (+9 more)

### Community 10 - "walk_forward.py"
Cohesion: 0.12
Nodes (15): buy_and_hold_return(), compare_selection_universe(), compare_strategies_universe(), _costs(), criteria_correlation_universe(), _fetch_nifty(), _load(), main() (+7 more)

### Community 11 - "trade_dashboard.py"
Cohesion: 0.14
Nodes (16): close_trade(), load_all(), log_signal(), _next_id(), summary(), _bar(), full_render(), _pct_col() (+8 more)

### Community 12 - "add_features"
Cohesion: 0.12
Nodes (12): build_detector(), add_features(), _adx(), _atr(), _bollinger(), _days_to_nse_expiry(), _fetch_market_context(), _holiday_proximity() (+4 more)

### Community 13 - "technical_analyzer.py"
Cohesion: 0.14
Nodes (13): analyze(), _bollinger(), _confidence_rating(), _detect_chart_pattern(), _ema(), _fetch(), _fibonacci_levels(), _macd() (+5 more)

### Community 14 - "macro_indicators.py"
Cohesion: 0.15
Nodes (17): _classify_vix(), _classify_yield_curve(), _fetch_advance_decline_ratio(), _fetch_dxy(), _fetch_fed_funds_rate(), _fetch_gold(), _fetch_nifty50(), _fetch_nifty_bank() (+9 more)

### Community 15 - "dashboard.py"
Cohesion: 0.15
Nodes (12): _alpaca_get(), _alpaca_headers(), fetch_all(), get_account(), get_daily_bars(), get_latest_quote(), get_positions(), get_recent_orders() (+4 more)

### Community 16 - "test_walk_forward.py"
Cohesion: 0.16
Nodes (15): compare_strategies(), criteria_correlation(), walk_forward(), test_import_walk_forward(), _make_ohlcv(), test_compare_strategies_returns_verdict(), test_costs_change_results_not_crash(), test_criteria_correlation_empty() (+7 more)

### Community 17 - "datetime"
Cohesion: 0.13
Nodes (6): main(), main(), run(), _run_module(), run(), test_import_control_server()

### Community 18 - "halal_history.py"
Cohesion: 0.19
Nodes (13): compliance_changes(), format_timeline(), _history(), screen_as_of(), tier_timeline(), _year(), _cache(), test_compliance_changes_detects_the_crossing() (+5 more)

### Community 19 - "job"
Cohesion: 0.10
Nodes (21): job, ticker, years, default, description, options, required, type (+13 more)

### Community 20 - "web_dashboard.py"
Cohesion: 0.15
Nodes (6): portfolio_correlation_risk(), filter_cards(), _correlation(), Handler, _sectors(), _signals()

### Community 21 - "news_sentiment.py"
Cohesion: 0.17
Nodes (11): _analyze_sentiment(), _cache_key(), _fetch_google_news_headlines(), _fetch_reddit_headlines(), _fetch_yahoo_headlines(), _from_cache(), get_news_sentiment(), get_sentiment_features() (+3 more)

### Community 22 - "mlflow_tracker.py"
Cohesion: 0.17
Nodes (7): get_best_run(), _get_client(), log_dataset_hash(), log_feature_importance(), log_metrics(), log_model_artifact(), test_import_mlflow_tracker()

### Community 23 - "pipeline.py"
Cohesion: 0.20
Nodes (8): load_history(), main(), save_history(), get_feature_cols(), load_data(), monte_carlo_backtest(), run(), walk_forward_split()

### Community 24 - "EnsembleModel"
Cohesion: 0.19
Nodes (3): EnsembleModel, test_ensemble_fit_predict(), test_import_ensemble()

### Community 25 - "scan"
Cohesion: 0.20
Nodes (8): _market_regime(), run(), _telegram_briefing(), generate(), _pct(), print_gtt(), auto_scan_and_place(), scan()

### Community 26 - "tier_monitor.py"
Cohesion: 0.19
Nodes (9): check_and_snapshot(), current_tiers(), diff_tiers(), format_changes(), test_current_tiers_screens_all_cached(), test_diff_tiers_detects_transitions_worsened_first(), test_diff_tiers_ignores_newly_added_tickers(), test_format_changes_empty_and_nonempty() (+1 more)

### Community 27 - "export_dashboard.py"
Cohesion: 0.18
Nodes (6): _equity(), main(), _market(), _passive(), _portfolio(), _signals()

### Community 28 - "dynamic_stops.py"
Cohesion: 0.17
Nodes (3): recommend_stop(), StopManager, StopType

### Community 29 - "numpy"
Cohesion: 0.20
Nodes (7): _atr(), _ema(), _rsi(), _score(), _trade_card(), _weekly_trend(), stocks_in_sectors()

### Community 30 - "json"
Cohesion: 0.24
Nodes (7): build(), main(), get_fundamentals(), _is_stale(), _load(), screen_cached(), test_screen_cached_missing_ticker_is_yellow_no_data()

### Community 31 - "backtest_runner.py"
Cohesion: 0.22
Nodes (3): backtest_ticker(), filter_cards(), Strategy

### Community 33 - "steps"
Cohesion: 0.31
Nodes (13): steps, if, name, runs-on, steps, ci-tests, steps, steps (+5 more)

### Community 36 - "data_provider.py"
Cohesion: 0.28
Nodes (7): _alpaca_available(), _alpaca_headers(), _fetch_alpaca(), _fetch_yfinance(), load_bars(), load_market_context(), test_import_data_provider()

### Community 37 - "halal_lookup.py"
Cohesion: 0.29
Nodes (6): format_card(), lookup(), screen_ticker(), _cache(), test_format_card_cites_standard_source_and_disclaimer(), test_lookup_resolves_from_cache()

### Community 38 - "detect"
Cohesion: 0.29
Nodes (7): _adx(), _default_regime(), detect(), _fetch(), Regime, regime_emoji(), _regime()

### Community 39 - "dispatch.js"
Cohesion: 0.27
Nodes (8): ALLOWED, ALLOWED_ORIGINS, crypto, handler(), hits, rateOk(), resp(), validSecret()

### Community 41 - "correlation.py"
Cohesion: 0.24
Nodes (3): correlation_matrix(), is_too_correlated(), _returns()

### Community 42 - "research-backtest"
Cohesion: 0.22
Nodes (9): BT_TICKER, BT_YEARS, research-backtest, env, if, name, runs-on, steps (+1 more)

### Community 43 - "backtest_filter.py"
Cohesion: 0.28
Nodes (3): _backtest_ticker(), filter_cards(), passes_backtest()

### Community 44 - "earnings_guard.py"
Cohesion: 0.31
Nodes (4): _fetch_upcoming_results(), filter_cards(), has_earnings_soon(), _nse_get()

### Community 45 - "notify.py"
Cohesion: 0.33
Nodes (5): _card_text(), _send(), send_journal_summary(), send_trade_cards(), test_import_notify()

### Community 46 - "nightly-scan"
Cohesion: 0.25
Nodes (8): nightly-scan, if, name, permissions, runs-on, contents, permissions, permissions

### Community 47 - "nse"
Cohesion: 0.32
Nodes (5): _technicals(), one(), buy_and_hold_benchmark(), _bh(), nse()

### Community 48 - "jobs"
Cohesion: 0.29
Nodes (6): if, name, runs-on, jobs, auto-close, name

### Community 49 - "with"
Cohesion: 0.29
Nodes (7): with, key, name, path, python-version, restore-keys, retention-days

### Community 51 - "env"
Cohesion: 0.33
Nodes (6): env, FRED_API_KEY, GROQ_API_KEY, PYTHONPATH, TELEGRAM_CHAT_ID, TELEGRAM_TOKEN

### Community 53 - "quarterly-rescreen"
Cohesion: 0.40
Nodes (5): quarterly-rescreen, if, name, runs-on, timeout-minutes

### Community 54 - "weekly-backtest"
Cohesion: 0.40
Nodes (5): weekly-backtest, if, name, runs-on, timeout-minutes

## Knowledge Gaps
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

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

Graph health diagnostics: dangling_endpoint_edges=504, undirected_same_endpoint_collapsed_edges=211.
