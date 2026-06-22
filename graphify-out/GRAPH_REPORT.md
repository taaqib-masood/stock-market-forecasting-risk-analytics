# Graph Report - /Users/taaqibmasood/Documents/Uni Junk/UNI Projects/stocks project/V-1.0  (2026-06-21)

## Corpus Check
- 73 files · ~163,337 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 929 nodes · 1658 edges · 40 communities detected
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 456 edges (avg confidence: 0.73)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]

## God Nodes (most connected - your core abstractions)
1. `RuleStrategy` - 72 edges
2. `RiskManager` - 37 edges
3. `Strategy` - 35 edges
4. `run()` - 25 edges
5. `add_features()` - 23 edges
6. `nse()` - 20 edges
7. `walk_forward()` - 20 edges
8. `classify()` - 16 edges
9. `_load()` - 16 edges
10. `EnsembleModel` - 15 edges

## Surprising Connections (you probably didn't know these)
- `Multi-stock scanner. Scans the NSE watchlist, scores each stock, returns ranked` --uses--> `RuleStrategy`  [INFERRED]
  src/scanner.py → /Users/taaqibmasood/Documents/Uni Junk/UNI Projects/stocks project/V-1.0/src/strategy.py
- `Score a stock 0–100 on 7 criteria.     Returns score, signal, individual indicat` --uses--> `RuleStrategy`  [INFERRED]
  src/scanner.py → /Users/taaqibmasood/Documents/Uni Junk/UNI Projects/stocks project/V-1.0/src/strategy.py
- `Build an actionable trade card from a score dict.` --uses--> `RuleStrategy`  [INFERRED]
  src/scanner.py → /Users/taaqibmasood/Documents/Uni Junk/UNI Projects/stocks project/V-1.0/src/strategy.py
- `Returns 'UP', 'DOWN', or 'NEUTRAL' based on weekly chart.     UP   = price > wee` --uses--> `RuleStrategy`  [INFERRED]
  src/scanner.py → /Users/taaqibmasood/Documents/Uni Junk/UNI Projects/stocks project/V-1.0/src/strategy.py
- `Produce a unified live BUY signal for one ticker. None on failure/no-signal.` --uses--> `RuleStrategy`  [INFERRED]
  src/scanner.py → /Users/taaqibmasood/Documents/Uni Junk/UNI Projects/stocks project/V-1.0/src/strategy.py

## Hyperedges (group relationships)
- **Two-Signal-Path Architecture (live scan vs ML pipeline)** — claude_two_signal_paths, claude_live_daily_path, claude_ml_pipeline_path, readme_two_signal_paths, v1_plan_unify_code_paths [INFERRED 0.85]
- **Halal Screening System (AAOIFI + watchlist + Zakat overlay)** — readme_aaoifi_screen, readme_halal_watchlist_195, readme_zakat_calculator, demo_tab_watchlist, upgrade_openbb_halal_automation, claude_halal_in_code [INFERRED 0.80]
- **Proof → Survivorship Downgrade → Passive Overlay Pivot** — proof_rule_strategy, proof_survivorship, proof_revised_verdict, proof_passive_overlay, proof_drawdown_overlay [INFERRED 0.85]

## Communities

### Community 0 - "Community 0"
Cohesion: 0.03
Nodes (129): ABC, backtest_ticker(), cost_breakdown(), filter_cards(), generate_live_signal(), passes_backtest(), Unified backtest runner — the single path that backtests *exactly what we trade*, Historical-viability gate (replaces src.backtest_filter.passes_backtest).     Op (+121 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (43): ArimaModel, Auto-ARIMA wrapper.     - Uses pmdarima.auto_arima to select optimal (p,d,q) ord, 1 = bullish forecast, 0 = bearish., EnsembleModel, Parameters         ----------         base_probas : dict mapping model name → 1-, Returns a DataFrame with:           - confidence : meta-model P(UP)           -, Meta-learner (stacking ensemble).      Base models feed probability estimates in, _stack() (+35 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (64): Update stop based on current price and ATR.         Returns dict with new_stop,, get_fundamentals(), _is_stale(), _load(), Reader for the fundamentals cache produced by scripts/refresh_fundamentals.py., Latest cached AAOIFI ratios for `ticker`, or None if not cached.     Pass `cache, compliance_changes(), format_timeline() (+56 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (66): Halal constraints enforced in code (BUY only), Live Daily Path (scanner._score), ML Research/Backtest Path (pipeline.py), TreeModel uses LightGBM not XGBoost, CLAUDE.md: Two Signal Paths Architecture, AI Explainer Tab, Drift Tab, Features Tab (52 features) (+58 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (46): check_and_close(), Auto Stop-Loss & Target Checker ================================= Run every even, Send Telegram message with close outcomes + portfolio update., Fetch live prices for all open positions.     Close any that hit stop or target., run(), _telegram_summary(), correlation_matrix(), is_too_correlated() (+38 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (34): _backtest_ticker(), filter_cards(), passes_backtest(), Per-Stock Backtest Filter ========================= Before recommending a stock,, Returns (True, stats) if stock passes historical backtest.     Returns (False, s, Filter trade cards by historical backtest.     Returns (passed_cards, failed_car, Simulate 2 years of daily signals on `ticker`.     Entry: when score >= 70 (5/7, BaseHTTPRequestHandler (+26 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (45): _cache_get(), _cache_set(), day_of_week_patterns(), earnings_behaviour(), _fetch_daily(), full_pattern_report(), FEATURE 2: Pattern Finder Finds seasonal patterns, day-of-week tendencies, earni, Analyse pre-earnings run and post-earnings gap. (+37 more)

### Community 7 - "Community 7"
Cohesion: 0.09
Nodes (27): annual_return(), avg_win_loss_ratio(), calmar_ratio(), directional_accuracy(), expected_value(), max_drawdown(), profit_factor(), % of time the predicted direction matches actual direction. (+19 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (28): close_trade(), load_all(), log_signal(), _next_id(), Trade Journal — auto-tracks every signal and outcome. Stored as a simple CSV: re, Log a new trade signal. Returns the journal row., Mark a trade as closed and calculate P&L., Return win rate, profit factor, total P&L for closed trades. (+20 more)

### Community 9 - "Community 9"
Cohesion: 0.14
Nodes (24): backtest_with_risk(), Manually reset the consecutive-loss counter (e.g. start of new week)., Walk through signals chronologically applying RiskManager rules.     Applies rea, Fractional Kelly (25% Kelly for safety)., Hard rules applied to every trade signal.      Rules enforced:     1. Max risk p, Evaluate a potential trade and return:           - approved   : bool — whether t, RiskManager, Golden-path regression tests for the risk manager + paper-P&L engine.  These are (+16 more)

### Community 10 - "Community 10"
Cohesion: 0.09
Nodes (22): _alpaca_available(), _alpaca_headers(), _fetch_alpaca(), _fetch_yfinance(), load_bars(), load_market_context(), Data provider — Alpaca Markets (free account, no download needed).  Why Alpaca i, Load SPY (market trend) and VIX (volatility regime) as context features.     Sam (+14 more)

### Community 11 - "Community 11"
Cohesion: 0.1
Nodes (26): generate(), _pct(), print_gtt(), Zerodha GTT Order Generator ============================ Converts scanner trade, Print a single GTT order card., _adx(), _default_regime(), detect() (+18 more)

### Community 12 - "Community 12"
Cohesion: 0.14
Nodes (26): apply_overlay(), basket_daily_returns(), drawdown_exposure(), _fetch_benchmark(), _fetch_close(), Passive halal core + regime overlay.  After the proof showed an active daily-sig, Compare buy-and-hold of the halal basket vs the same basket with a regime     (b, Equal-weight daily return of a basket (daily-rebalanced).      `min_coverage` gu (+18 more)

### Community 13 - "Community 13"
Cohesion: 0.12
Nodes (23): current_state(), explain(), format_card(), live_card(), Drawdown-guard "why I de-risked" explainer.  The passive overlay (`passive.drawd, Today's drawdown-guard state from a benchmark close series.      Mirrors `passiv, One-paragraph reason for today's exposure, grounded in the state., Shareable card: status, the why, and the rupee split if capital is given. (+15 more)

### Community 14 - "Community 14"
Cohesion: 0.16
Nodes (23): _classify_vix(), _classify_yield_curve(), _fetch_advance_decline_ratio(), _fetch_dxy(), _fetch_fed_funds_rate(), _fetch_gold(), _fetch_nifty50(), _fetch_nifty_bank() (+15 more)

### Community 15 - "Community 15"
Cohesion: 0.15
Nodes (20): analyze(), _bollinger(), _confidence_rating(), _detect_chart_pattern(), _ema(), _fetch(), _fibonacci_levels(), _macd() (+12 more)

### Community 16 - "Community 16"
Cohesion: 0.14
Nodes (19): _alpaca_get(), _alpaca_headers(), fetch_all(), get_account(), get_daily_bars(), get_latest_quote(), get_positions(), get_recent_orders() (+11 more)

### Community 17 - "Community 17"
Cohesion: 0.14
Nodes (17): build(), main(), Build the dashboard's halal data file from the fundamentals cache.  demo.html is, Tests for the halal tier-change monitor. Pure logic, no network.  Run: pytest te, test_current_tiers_screens_all_cached(), test_diff_tiers_detects_transitions_worsened_first(), test_diff_tiers_ignores_newly_added_tickers(), test_format_changes_empty_and_nonempty() (+9 more)

### Community 18 - "Community 18"
Cohesion: 0.19
Nodes (16): _analyze_sentiment(), _cache_key(), _fetch_google_news_headlines(), _fetch_reddit_headlines(), _fetch_yahoo_headlines(), _from_cache(), get_news_sentiment(), get_sentiment_features() (+8 more)

### Community 19 - "Community 19"
Cohesion: 0.22
Nodes (13): _cached(), _fetch_fundamentals(), _moat_rating(), FEATURE 3: Fundamental Stock Screener Screens stocks on valuation, growth, debt,, Risk score 1 (safe) – 10 (very risky)., Screen a single halal stock on fundamentals.     Returns a beginner-friendly rep, Screen multiple stocks and return top picks ranked by overall score., Simple moat proxy based on margins and ROE. (+5 more)

### Community 20 - "Community 20"
Cohesion: 0.23
Nodes (11): analyse(), _beta(), filter_cards(), _gap_series(), position_size_multiplier(), Gap Risk Protection ==================== Detects stocks with high overnight gap, Estimate beta vs Nifty over last `period` days., Return size adjustment based on gap risk. (+3 more)

### Community 21 - "Community 21"
Cohesion: 0.2
Nodes (7): Dynamic & Trailing Stop Loss ============================= Replaces fixed ATR st, Recommend stop type based on R:R and target distance., Given entry, ATR and regime, return recommended stop and type., recommend_stop(), StopManager, StopType, Enum

### Community 22 - "Community 22"
Cohesion: 0.27
Nodes (10): _build_prompt(), _call_groq(), _call_ollama(), explain_trade(), _fallback_explanation(), _get_shap_values(), UPGRADE 3: AI-Powered Trade Explanations (SHAP + LLM)  Uses SHAP to find feature, Call a locally running Ollama instance. (+2 more)

### Community 23 - "Community 23"
Cohesion: 0.38
Nodes (9): analyze_moat(), _compare_peers(), _get_info(), _moat_score(), FEATURE 5: Competitive Moat Analyzer Compares a stock against its top competitor, Full competitive moat analysis for a stock., Return (score 0-5, moat_type, reasons)., _safe() (+1 more)

### Community 24 - "Community 24"
Cohesion: 0.42
Nodes (8): _cache_get(), _cache_set(), _classify_cycle(), _fred(), full_macro_analysis(), FEATURE 6: Macro Impact Assessment Fetches macro data and explains how it impact, Fetch all macro indicators and produce a portfolio impact report., _yf_price()

### Community 25 - "Community 25"
Cohesion: 0.53
Nodes (5): fetch_one(), main(), _num(), Quarterly fundamentals refresh (decoupled from the trading runtime).  WHY decoup, _retry()

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (2): Distribution = liability (SEBI RA / religious rulings), Self-authored fiqh has no governance

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (0): 

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (0): 

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (0): 

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (0): 

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Returns a DataFrame indexed like `features` with columns:           - score

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): Return the last Thursday of a given month (NSE F&O expiry day).

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (1): Calendar days from `date` to the next NSE F&O expiry (last Thursday).

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): Return 1 if `date` is within `window` calendar days of an NSE holiday.

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (1): Fetch SPY and VIX as market regime context via the data provider.

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (1): Enrich OHLCV DataFrame with technical indicators, market context, and     a bina

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (1): MLflow Experiment Tracker

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (1): GitHub Actions Automated Pipeline

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (1): Performance Targets (WinRate/PF/Sharpe/MaxDD)

## Knowledge Gaps
- **250 isolated node(s):** `Tests for the proof aggregator (pooling per-ticker backtests into one verdict).`, `Tests for the halal tier-change monitor. Pure logic, no network.  Run: pytest te`, `Tests for point-in-time halal screening (cache history; no network).  Run: pytes`, `Tests for the passive core + regime overlay math (pure, no network).  Run: pytes`, `Tests for AAOIFI screening (classify) + Zakat/purification ledger. Pure logic, n` (+245 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 26`** (2 nodes): `Distribution = liability (SEBI RA / religious rulings)`, `Self-authored fiqh has no governance`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (1 nodes): `halal_data.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (1 nodes): `dashboard_data.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (1 nodes): `info_data.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (1 nodes): `Returns a DataFrame indexed like `features` with columns:           - score`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 32`** (1 nodes): `Return the last Thursday of a given month (NSE F&O expiry day).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `Calendar days from `date` to the next NSE F&O expiry (last Thursday).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `Return 1 if `date` is within `window` calendar days of an NSE holiday.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `Fetch SPY and VIX as market regime context via the data provider.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): `Enrich OHLCV DataFrame with technical indicators, market context, and     a bina`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `MLflow Experiment Tracker`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `GitHub Actions Automated Pipeline`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `Performance Targets (WinRate/PF/Sharpe/MaxDD)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `nse()` connect `Community 6` to `Community 0`, `Community 2`, `Community 4`, `Community 5`, `Community 12`, `Community 15`, `Community 19`, `Community 20`, `Community 23`?**
  _High betweenness centrality (0.218) - this node is a cross-community bridge._
- **Why does `add_features()` connect `Community 0` to `Community 1`, `Community 18`, `Community 10`, `Community 14`?**
  _High betweenness centrality (0.183) - this node is a cross-community bridge._
- **Why does `RuleStrategy` connect `Community 0` to `Community 11`, `Community 6`, `Community 7`?**
  _High betweenness centrality (0.133) - this node is a cross-community bridge._
- **Are the 65 inferred relationships involving `RuleStrategy` (e.g. with `Tests for the walk-forward + criteria-correlation harness.  Network-free: synthe` and `Walk-forward evaluation, criteria-correlation, and marginal-lift gate.  This is`) actually correct?**
  _`RuleStrategy` has 65 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `RiskManager` (e.g. with `Smoke tests — verify all modules import cleanly and core classes instantiate. Ru` and `Create synthetic OHLCV DataFrame with a DatetimeIndex.`) actually correct?**
  _`RiskManager` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `Strategy` (e.g. with `Walk-forward evaluation, criteria-correlation, and marginal-lift gate.  This is` and `Resolve a cost preset name (or pass a dict through).`) actually correct?**
  _`Strategy` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `run()` (e.g. with `start_run` and `.__enter__()`) actually correct?**
  _`run()` has 20 INFERRED edges - model-reasoned connections that need verification._