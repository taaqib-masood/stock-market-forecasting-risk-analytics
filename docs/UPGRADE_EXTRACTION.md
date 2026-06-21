# V-1.0 Upgrade Extraction — what to lift from 11 reference repos

Mapped to **our** modules. Deterministic (free-to-run) items are prioritized over LLM-agent items (token cost). Halal screening always sits *on top* — these improve data/models/backtesting; they don't replace the Shariah layer.

Verdict key: 🟢 implement · 🟡 borrow pattern · 🔴 reference/inspiration only

---

## Two killer insights first

1. **OpenBB fundamentals can AUTOMATE the halal screen.** Today the halal universe is hand-curated watchlists. OpenBB exposes debt/assets, interest-income, and financial statements per ticker across markets → apply the AAOIFI thresholds (debt <33%, impure income <5%) *programmatically* and the 🟢/🟡/🔴 tiering becomes data-driven and self-updating for India + US + Saudi. This is the single biggest connect to V-1.0.
2. **"Same strategy code in backtest and live" (nautilus + Lean principle).** Our project has a two-path divergence: `scanner.py` (live, rule-based) vs `pipeline.py` (backtest, ML ensemble). Both repos treat that as an anti-pattern — research and live run identical strategy code. Unifying via Lean's staged taxonomy (below) fixes it.

---

## Per-repo extraction

### 1. microsoft/qlib (MIT, Python) — the accuracy engine 🟢
- **Alpha158 / Alpha360 factor libraries** → expand `feature_engineering.py` from 52 hand-coded features to 158+ battle-tested factor expressions (momentum, volatility, volume, correlation, rank). Port the expression list.
- **Expression/data-handler pattern** → declarative factor definitions (`$close/Ref($close,5)-1`) instead of imperative pandas. Cleaner, testable, less leakage-prone.
- **Model zoo** (LightGBM, CatBoost, LSTM, GRU, Transformer, TFT, TabNet, GATs, ADD, DDG-DA) → drop-in alternatives to `TreeModel`/`LSTMModel`; benchmark against current ensemble.
- **`qrun` workflow + report** → IC, Rank IC, ICIR, Information Ratio, annualized return **with and without cost**, max drawdown → upgrade `metrics.py` to these standard quant metrics.
- **Rolling/walk-forward retrain** → replaces our single 80/20 split with proper rolling windows (less overfit).
- **TopkDropoutStrategy** (portfolio) → rank-and-select top-K instead of single-signal-at-a-time.
- 🔴 RL order execution (TWAP/PPO/OPDS) — overkill for daily/swing.

### 2. microsoft/RD-Agent (MIT, Python) — auto-research 🟡 (later)
- **Automated factor-mining loop**: propose factor → implement → backtest → keep if IC improves. LLM version is token-heavy; **a deterministic-lite version is cheap** — random/genetic search over factor expressions with an IC gate. Build the cheap version first.
- **Joint factor + model optimization loop** → continuous improvement engine; pairs with qlib. Phase-3.
- **Factor mining from reports** → parse research PDFs/earnings into candidate factors (feeds `news_sentiment`/`macro`).

### 3. freqtrade (GPLv3, Python — reimplement, don't copy code) 🟢
- **`lookahead-analysis` + `recursive-analysis`** → detect look-ahead bias / data leakage in features. **Add this — it's a credibility/accuracy must-have** for any backtest claim.
- **Hyperopt (use optuna)** → auto-tune `scanner.py` thresholds (`min_score`, bear threshold, RSI bands, ATR mult, RR) against a loss fn. Stops the hand-tuning.
- **Hyperopt loss functions** (Sharpe/Calmar/profit/expectancy) → reuse as optimization objectives.
- **Protections**: `StoplossGuard`, `MaxDrawdown`, `CooldownPeriod`, `LowProfitPairs` → add to `risk_manager.py` (max-DD circuit breaker, cooldown after losses, prune chronic losers). We already have `max_consecutive_losses` — extend.
- **Pairlist filters**: Volume/Age/Spread/Volatility/Shuffle → universe filters for `scanner.py` (liquidity, age, spread) — directly serves multi-market quality.
- **FreqAI** → adaptive rolling-retrain ML pattern.
- **Edge module** → expectancy-based position sizing (extends `volatility_sizing.py`).
- **Two-way Telegram control** (`/status /profit /forcebuy /stop`) → upgrade our one-way alerts to interactive.
- **REST API + webserver + FreqUI** → dashboard backend pattern.

### 4. TauricResearch/TradingAgents (Python, LLM) 🟡
- **Analyst structure** (Fundamental / Sentiment / News / Technical) → **we already have these** (`technical_analyzer`, `news_sentiment`, `macro_analyzer`, `moat_analyzer`). Reorganize into named analyst outputs feeding one decision.
- **Bull/Bear researcher debate** → before emitting a signal, build a bull case + bear case, score both, require net-positive. **Implementable deterministically** (no LLM) or with one cheap LLM call.
- **Trader agent** → synthesizes analyst reports → position.
- **Risk team (aggressive/conservative/neutral debate)** → evaluate each signal from multiple risk stances.
- **Portfolio-manager approve/reject gate** → final gate (mirrors our halal opt-in gate).
- **Reflection/memory** → log decisions + outcomes, feed back (extends `journal.py`).

### 5. nautechsystems/nautilus_trader (LGPLv3, Rust+Python) 🟡 / 🔴
- **Advanced order types & TIF**: IOC, FOK, GTC, GTD, DAY, AT_THE_OPEN/CLOSE; post-only, reduce-only, iceberg; **OCO/OUO/OTO contingency orders** → `gtt_generator.py` + `auto_close.py` can support OCO (stop+target as one-cancels-other) and GTD — directly useful for Zerodha GTT.
- **"Identical strategy research↔live"** → the principle to unify our scanner/pipeline divergence.
- 🔴 Event-driven engine (message bus, cache, nanosecond backtest) — heavy; only if we ever go true intraday execution.

### 6. QuantConnect/Lean (Apache-2.0, C# core) — architecture taxonomy 🟡
- **5-stage Algorithm Framework**: Universe Selection → Alpha Model → Portfolio Construction → Risk Management → Execution. **Refactor `scanner.py` into these clean stages** (watchlist/sector-rotation = Universe; scoring = Alpha; sizing = Portfolio; `risk_manager` = Risk; gtt/auto_close = Execution). Unifies the two-path divergence.
- **Portfolio construction models** (equal-weight, mean-variance, Black-Litterman, risk-parity) → upgrade position sizing beyond fixed 2% risk.
- **Risk models** (MaxDrawdownPerSecurity, TrailingStop, MaxSectorExposure) → add to `risk_manager`.
- 🔴 Don't adopt the C# engine — ecosystem mismatch.

### 7. OpenBB (⚠️ AGPL-style — check before SaaS, Python) — the data layer 🟢
- **Unified data SDK** (equity, fundamentals, news, economy/macro, options) across 100+ providers → replace the `data_provider.py` yfinance/Alpaca patchwork; one interface for India/US/Saudi.
- **Fundamentals** (ratios, statements, estimates) → powers automated halal screening (see killer insight #1) + `stock_screener.py`.
- **Economy/macro** (FRED etc.) → feeds `macro_indicators.py`.
- **News/sentiment** → feeds `news_sentiment.py`.
- **OpenBB Workspace** → dashboard integration option.

### 8. AI4Finance/FinRobot (Python, LLM) 🔴/🟡
- **Document Analyst** (parse 10-K/earnings) → extract for **halal fundamentals** (debt, interest income from filings) + report analysis.
- **Market Forecaster / Trade Strategist / Smart Scheduler (router)** → conceptual roles; overlaps TradingAgents (pick one). FinGPT sentiment.

### 9. HKUDS/AI-Trader (Python, research) 🔴
- Fully-automated agent-native trading + **benchmark methodology** → read the paper for the autonomous-loop and evaluation design. Reference only.

### 10. TraderAlice/OpenAlice (Python, app) 🔴/🟡
- **"One-person Wall Street" lifecycle**: research → entry → ongoing management → exit → product framing for our solo system; extract position-management/exit ideas for `auto_close`/`dynamic_stops`.
- **TraderHub hosted data (zero API keys, cross-asset)** → 🟡 evaluate as an alt free data source — **especially for UAE where yfinance is thin** (Phase-2 unblock candidate).
- Cross-asset symbol search + indicator calculator → utilities.

### 11. Fincept-Corporation/FinceptTerminal (Python+Qt, app) 🔴
- Terminal/TUI dashboard + data connectors + analytics modules → UX inspiration for a richer front-end than `demo.html`; multi-source connector pattern.

---

## Prioritized roadmap (deduped, by value/effort)

**Tier A — do these (high value, deterministic, low/med effort):**
1. freqtrade **lookahead/recursive analysis** → kill data leakage (credibility). [`metrics`/new `validation.py`]
2. qlib **Alpha158 factor set** → richer features. [`feature_engineering.py`]
3. qlib **standard metrics** (IC/ICIR/IR/with-cost) → [`metrics.py`]
4. freqtrade **hyperopt (optuna)** → auto-tune thresholds. [`scanner.py` + new `optimize.py`]
5. freqtrade **protections** + Lean **risk models** → [`risk_manager.py`]
6. OpenBB **fundamentals** → automate the AAOIFI halal screen + multi-market data. [`data_provider.py`, `stock_screener.py`, halal engine]
7. Lean **5-stage taxonomy** → refactor `scanner.py`; unify backtest/live. [architecture]

**Tier B — next (med value/effort):**
8. qlib model zoo benchmark · 9. TradingAgents deterministic bull/bear debate · 10. freqtrade 2-way Telegram · 11. nautilus OCO/GTD orders → `gtt_generator` · 12. Lean portfolio-construction sizing.

**Tier C — later / token-heavy:**
13. RD-Agent deterministic-lite factor mining · 14. LLM agent layer (TradingAgents/FinRobot) · 15. nautilus/Lean event-driven engine (only if intraday) · 16. OpenAlice TraderHub for UAE data.

**Tier D — inspiration:** FinceptTerminal / OpenBB Workspace / OpenAlice (dashboard UX); AI-Trader (benchmark methodology).

---

## Sequencing note
Per the council: the **`risk_manager` regression tests (build step 0)** come *before* any of this touches money code. Tier A items 1–3 (validation + features + metrics) are safe to start early since they're research-side, not execution-side.
