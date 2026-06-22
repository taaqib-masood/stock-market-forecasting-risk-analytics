# Halal Trading & Compliance Platform

**Stop guessing if a stock is halal. Know — with a citation.**

A Python system that screens Indian (NSE) equities against the AAOIFI Shariah standard, automates Zakat + purification math, runs an ARIMA + LightGBM ensemble for trade signals, and wraps every trade in real risk management (2% max risk, ATR stops, regime gates). Live signals ship to Telegram + a paper-trading ledger; everything is also wired into two static dashboards.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-118%20passing-brightgreen.svg)](#testing--validation)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://telegram.org/)
[![Trading Pipeline](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics/actions/workflows/trading_pipeline.yml/badge.svg)](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics/actions/workflows/trading_pipeline.yml)
[![Netlify Status](https://api.netlify.com/api/v1/badges/c2d7b0e6-4805-45ec-a2f5-700ee30f5537/deploy-status)](https://app.netlify.com/projects/splendid-gingersnap-a7ae5a/deploys)

**[Live Dashboard](https://splendid-gingersnap-a7ae5a.netlify.app) · [How it works](#-architecture) · [Run it yourself](#-quick-start)**

---

## Table of Contents

<details>
<summary><strong>Click to expand</strong></summary>

- [The Problem](#the-problem)
- [What This Actually Does](#what-this-actually-does)
- [Who This Is For](#who-this-is-for--use-cases)
- [The Honest Track Record](#the-honest-track-record-what-we-actually-found)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Daily Routine](#-daily-routine)
- [Full Command Reference](#%EF%B8%8F-full-command-reference)
- [Dashboards](#-dashboards)
- [Halal Screening Engine](#-halal-screening-engine)
- [Zakat & Purification](#-zakat--purification)
- [Risk Management](#%EF%B8%8F-risk-management)
- [The 195→171 Watchlist](#-watchlist)
- [Models & Features](#-models--features)
- [GitHub Actions Automation](#-github-actions--automated-pipeline)
- [Deployment (Netlify + GitHub Actions)](#-deployment-netlify--github-actions)
- [Project Structure](#-project-structure)
- [Testing & Validation](#testing--validation)
- [API Keys / Environment](#-environment-variables)
- [Troubleshooting](#-troubleshooting)
- [Roadmap](#-roadmap)
- [Disclaimer](#%EF%B8%8F-disclaimer)

</details>

---

## The Problem

Practicing Muslim retail investors in India face three unsolved problems every single year:

1. **"Is this stock actually halal?"** has no good answer. Hand-curated watchlists are built off reputation and sector ("it's an IT company, should be fine") — not the AAOIFI debt-ratio and impure-income tests a scholar would actually run. We proved this is a real gap: running the real screening math against our own 85-stock "halal" core watchlist flagged **10 names that fail outright** (BHARTIARTL, TVSMOTOR, M&M, ADANIPORTS, NTPC, POWERGRID, TITAN, ASHOKLEY, PRESTIGE, INDIGO) — reputation said yes, the balance sheet said no.
2. **Halal status changes over time**, and nobody checks. A stock can be 🟢 compliant in 2019 and 🔴 non-compliant in 2024 as debt creeps up — TITAN is the textbook case (🟢 FY19-20 → 🟡 FY21-23 → 🔴 FY24, debt ballooned to 49% of assets). If you bought it in 2019 and never re-checked, you're holding something you'd never have bought today.
3. **Zakat on a stock portfolio is a manual, error-prone calculation** most people either skip, approximate, or pay someone for — every single year, and twice if you've got assets split across two countries.

This project answers all three with code, not vibes — and is honest with itself about the fourth question everyone actually wants answered ("can this also make me money trading"), which is covered below.

---

## What This Actually Does

| Capability | What it means in practice |
|---|---|
| **AAOIFI Shariah screening** | `classify()` checks debt/assets < 33% and interest income < 5% of revenue against real fundamentals, tiers every stock 🟢/🟡/🔴, and computes the exact purification % for impure income |
| **Point-in-time halal history** | Re-runs the same classification over 8 years of historical financials per stock — answers "was this halal when I actually bought it," not just "is it halal today" |
| **Zakat & purification calculator** | Computes annual Zakat (full-value or capital-gains method), nisab check, hawl logic, and auto-purification of impure income — across a whole portfolio in one call |
| **"Is this stock halal?" lookup** | Cache-first/live-fallback card citing the AAOIFI standard, the source, and the as-of date — a citation layer, not a fatwa engine |
| **Tier-change alerts** | Diffs your portfolio's compliance tiers run-over-run and flags anything that just crossed 🟢→🟡 or 🟡→🔴 |
| **ARIMA + LightGBM ensemble** | A stacked meta-learner (logistic regression over calibrated base-model probabilities) trained on 52 technical/sentiment/macro features, for the research/backtest path |
| **Live rule-based daily scanner** | A separate, production NumPy scorer (7 bullish criteria, staged regime/sector/multi-timeframe/backtest/gap-risk gates) that actually drives the daily Telegram alert — see [Architecture](#-architecture) for why these are two different engines |
| **Drawdown-guard overlay** | A graded Nifty-drawdown-based de-risking band with a plain-English "why I de-risked" explainer, denominated in real rupees against your capital |
| **Risk management (10+ rules)** | 2% max-risk position sizing, ATR-based stops, regime gates, gap-risk filter, earnings blackout, sector rotation caps |
| **Paper trading + Zerodha GTT** | Every signal can be paper-traded with mark-to-market P&L, or pushed as a real GTT order on Zerodha |
| **Walk-forward validation harness** | Every new rule/indicator must clear a quantified out-of-sample gate (≥2pp win-rate lift + higher net PnL) before it's allowed near the live scanner — see [the honest track record](#the-honest-track-record-what-we-actually-found) |
| **MLflow + drift detection** | Every backtest run is tracked; a KS-test/PSI drift monitor flags when a model needs retraining |

---

## Who This Is For — Use Cases

**1. A practicing Muslim retail investor in India who wants a halal core portfolio.**
Run the screener once against your holdings, get a 🟢/🟡/🔴 tier with the actual ratio and a citation — not "trust me, it's halal." Catch positions that quietly went non-compliant. Run the Zakat calculator every year at hawl instead of estimating.

**2. Someone with cross-border Zakat obligations** (e.g. assets split between India and abroad, different lunar-year timing).
`portfolio_zakat_report()` takes any list of holdings — it doesn't care where the custody sits — and gives you one combined Zakat + purification number with the math shown, not just a total.

**3. A halal investor who also wants to trade tactically, with eyes open.**
The live scanner + risk manager give you a disciplined, rule-based entry/exit process with real position sizing and stop-loss enforcement instead of emotional trading — paired with the drawdown guard so you know exactly when and why exposure is being cut.

**4. A developer who wants a reusable halal-fintech or risk-management template.**
The screening engine (`halal_screen.py`), Zakat engine (`zakat.py`), risk manager (`risk_manager.py`), and the unified backtest/live strategy seam (`strategy.py` + `backtest_runner.py`) are decoupled, independently tested modules — fork what you need.

**5. A quant/researcher who wants a worked example of validation discipline.**
The [walk-forward harness](#the-honest-track-record-what-we-actually-found) below is a real case study in catching an overfitting/curve-fitting trap (adding indicators made every variant *worse*, the harness said so, none shipped) and in not lying to yourself about a "found" edge.

---

## The Honest Track Record (What We Actually Found)

This section exists because the project's own rule is **no self-deception** — every claim below is from a real walk-forward run on real NSE data, including the ones that don't flatter the product.

- **The AAOIFI screen is real and it works:** classifying the hand-curated 85-stock halal watchlist against actual debt/interest fundamentals flagged **10 of 85 names as non-compliant** that reputation-based curation had wrongly approved. This is the single strongest proof point in the project — automated screening beat manual curation on real data.
- **Active daily trading signals show a thin, conditional edge — not a money machine.** A multi-split walk-forward across the full 85-stock universe (3 years, net of NSE delivery costs) found the base rule strategy alone is *unprofitable* (PF 0.82–0.99). Adding a **regime gate** (only trade when Nifty is above its 200-day SMA) flips it to **profitable (PF 1.04, net +₹4,485 across 1,838 OOS trades)** — that gate is now load-bearing in the live scanner. A relative-strength filter was tested and **rejected** (it hurt results). Every fancier indicator we tried on top (ADX gate, Donchian breakout, BB squeeze) made things *worse* — the harness caught it, none shipped.
- **Passive beats active, in absolute terms.** Buy-and-hold of the halal universe over the same window returned **+28%** (NIFTY) while the best-validated active variant nets a thin edge on top of costs. The project's conclusion, stated plainly: **the durable value here is the halal screening + risk/Zakat layer, not entry signals.** Active trading is positioned as a disciplined tactical overlay, not the core thesis.
- **The crash-protection overlay does its one job, honestly reported.** A Nifty-drawdown-based de-risking overlay cuts max drawdown (−37% → −16% to −13% across different live runs) but *costs* total return — it's insurance against a crash, not a return enhancer, and the dashboard says so instead of cherry-picking the one window where it also happened to raise Sharpe.
- **We fixed a real bug the hard way.** The backtest used to exit positions on any signal flip, causing 87% of exits to be tiny churn trades that bled to costs. Root-caused, fixed to exit only on stop/target/genuine reversal (matching what the live system already did) — PF went 0.82 → 0.97 and trade count halved. Documented as a correctness fix, not a tuning trick.
- **118 automated tests** cover the screening engine, Zakat math, risk manager, walk-forward harness, look-ahead/leakage detection, and the unified live==backtest strategy path. No broad UI test suite — this is backend/quant logic coverage, not end-to-end.

If you came here looking for a guaranteed-win signal bot, this isn't it, and the project is built specifically to refuse to pretend otherwise. If you came here looking for a transparent, tested halal-compliance and risk layer with a legitimately validated tactical edge on top — that's exactly what's shipped.

---

## ⚡ Quick Start

```bash
# 1. Clone and enter the repo
git clone https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics.git
cd stock-market-forecasting-risk-analytics
git checkout V-1.0

# 2. Activate the virtual environment (ALWAYS do this first — nothing works without it)
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Set up your .env (see API Keys section below — every key degrades gracefully if missing)
cp .env.example .env

# 4. Run the morning scan
python -m src.daily_briefing --capital 50000
```

> Everything runs as a module from the repo root (`python -m src.<module>`) because of internal relative imports. Don't run files by path — `python src/foo.py` will break.

---

## 📅 Daily Routine

| Time | What to Run | Command |
|---|---|---|
| **9:00 AM** | Morning scan — today's signals | `python -m src.daily_briefing --capital 50000` |
| **3:45 PM** | Close positions — check stops/targets | `python -m src.auto_close` |
| Anytime | Check paper portfolio | `python -m src.paper_trader` |
| Anytime | "Is this stock halal?" | `python -c "from src.halal_lookup import lookup, format_card; print(format_card(lookup('RELIANCE')))"` |
| Anytime | Drawdown-guard check | `python -m src.drawdown_guard --capital 50000` |
| Annually (hawl) | Zakat report | see [Zakat & Purification](#-zakat--purification) |
| Sunday | Weekly backtest | `python -m src.pipeline --ticker RELIANCE --years 5` |

> GitHub Actions runs the morning scan and auto-close automatically every weekday — you get a Telegram message without running anything yourself.

---

## 🗂️ Full Command Reference

<details>
<summary><strong>Daily Operations</strong></summary>

```bash
# Morning scan — scans the halal watchlist, sends Telegram with top signals
python -m src.daily_briefing --capital 50000

# Evening close — closes positions that hit stop/target
python -m src.auto_close
```
</details>

<details>
<summary><strong>Paper Trading</strong></summary>

```bash
python -m src.paper_trader                      # view portfolio
python -m src.paper_trader --scan                # auto-scan + place top signals
python -m src.paper_trader --buy RELIANCE 5 1304  # manual buy
python -m src.paper_trader --sell RELIANCE 5 1380 # manual sell
python -m src.paper_trader --reset                # reset to ₹50,000
```
</details>

<details>
<summary><strong>Halal Screening, Zakat, Drawdown Guard</strong></summary>

```bash
# Screen one stock (live yfinance fundamentals)
python -c "from src.halal_screen import screen_ticker; import json; print(json.dumps(screen_ticker('RELIANCE'), indent=2))"

# Cache-based "is this halal?" card (citation + source + as-of date)
python -c "from src.halal_lookup import lookup, format_card; print(format_card(lookup('TITAN')))"

# Point-in-time halal history — was it halal back then?
python -c "from src.halal_history import tier_timeline, format_timeline; print(format_timeline(tier_timeline('TITAN')))"

# Tier-change alerts vs last snapshot
python -m src.tier_monitor

# Zakat + purification report for a portfolio
python -c "
from src.zakat import portfolio_zakat_report
holdings = [{'ticker': 'RELIANCE', 'qty': 10, 'price': 1300, 'cost_basis': 1100}]
import json; print(json.dumps(portfolio_zakat_report(holdings), indent=2))
"

# Drawdown-guard "why I de-risked" card
python -m src.drawdown_guard --capital 50000
```
</details>

<details>
<summary><strong>Train, Backtest & Validate Models</strong></summary>

```bash
# Train on any stock (saves to results/)
python -m src.pipeline --ticker RELIANCE --years 5
python -m src.pipeline --ticker RELIANCE --years 5 --lstm   # enable LSTM (slow, needs tensorflow)

# Walk-forward validation gate (the harness new strategies must clear before shipping)
python -m src.walk_forward --ticker RELIANCE --years 5 --splits 4
python -m src.walk_forward --portfolio --years 3            # full-universe pooled OOS stats
```
</details>

<details>
<summary><strong>MLflow, Drift Detection, Sentiment, Macro</strong></summary>

```bash
mlflow ui                                              # localhost:5000
python scripts/compare_models.py --metric win_rate --top 10

python -m src.drift_detector --ticker RELIANCE

python -c "from src.news_sentiment import get_news_sentiment; import json; print(json.dumps(get_news_sentiment('RELIANCE', 'Reliance Industries'), indent=2))"

python -c "from src.macro_indicators import get_macro_indicators; import json; print(json.dumps(get_macro_indicators(), indent=2))"
```
</details>

<details>
<summary><strong>Tests & Dashboards</strong></summary>

```bash
pytest tests/ -v                  # 118 tests
open demo-boro.html               # current dashboard (recommended)
open demo.html                    # legacy dashboard
python -m scripts.export_dashboard --capital 50000   # refresh demo-boro.html's live data feed
```
</details>

---

## 🖥️ Dashboards

Two static, no-backend, single-file dashboards (open directly in a browser, or deploy as-is to Netlify):

| | `demo-boro.html` (current) | `demo.html` (legacy) |
|---|---|---|
| Design | Warm-minimalist "Boro" redesign | Original |
| Live data | Yes — `scripts/export_dashboard.py` writes real scan/portfolio/equity-curve data into `dashboard_data.js` (`window.DASH`) | Static only |
| Home screen | Morning-cockpit: Today's Signals card, paper-portfolio panel, per-signal "why" drawer, Alerts/GTT feed | — |
| Halal tooling | Halal Screen + Zakat tab, Risk Guard tab (live drawdown slider) | Halal Screen + Zakat tab only |

Tabs (15 total): **Sentiment · Technical · Macro · Screener · Moat · AI Explainer · Monte Carlo · Drift · Features · FII/DII · India Signals · Watchlist · Halal & Zakat · Risk Guard · Telegram/GTT**

```bash
python -m scripts.export_dashboard --capital 50000    # populate dashboard_data.js with real data
open demo-boro.html
```

Ships with `sample:true` placeholder data until the generator runs against real signals (and on a genuine no-signal day, writes the honest empty state — "cash is a position").

---

## 🕌 Halal Screening Engine

Based on the AAOIFI / Mufti Taqi Usmani screening standard — **pragmatic, not zero-tolerance** ("barakah, not extreme"):

| Tier | Criteria |
|---|---|
| 🟢 Compliant | Debt/Assets < 33% **and** interest income < 5% of revenue, confirmed |
| 🟡 Narrow-fail / unconfirmed | Fails narrowly, or fundamentals data (esp. interest income) unavailable — purify the impure % |
| 🔴 Not tradeable | **Vice sectors** (alcohol, gambling, tobacco, pork, adult, defense) — zero-tolerance, no profit case, full stop. **Riba-financials** (banks/NBFC/insurance) — off by default; gated as a deliberate, loudly-badged opt-in, not "less haram," just a real liquidity case in India (~1/3 of Nifty by weight) |

Every result carries the **standard cited, the data source, and the as-of date** — this is a citation layer over a recognized standard, not an independent fatwa engine, and every card says so.

**Known limitation, stated plainly:** free `yfinance` data lacks interest-income for most NSE names, so most names cap at 🟡 (debt confirmed, interest income unknown) on the live path. Full 🟢 certification runs through a separately-cached fundamentals pipeline (`scripts/refresh_fundamentals.py`, an isolated venv pulling 8-year balance-sheet/income history from Tickertape) — that's also what powers the point-in-time history feature.

---

## 🌙 Zakat & Purification

```bash
python -c "
from src.zakat import portfolio_zakat_report
holdings = [{'ticker': 'RELIANCE', 'qty': 10, 'price': 1300, 'cost_basis': 1100}]
import json; print(json.dumps(portfolio_zakat_report(holdings), indent=2))
"
```

- **Method 1** (majority view): 2.5% × full portfolio market value
- **Method 2** (minority view): 2.5% × capital gains only
- Nisab check (silver threshold) and hawl-condition logic built in
- **Auto-purification**: looks up each holding's impure-income ratio from the fundamentals cache and computes the exact rupee amount to give away, combined into one report with Zakat
- Built into `demo-boro.html`'s Halal & Zakat tab as a guided flow with a shareable PDF certificate

---

## 🛡️ Risk Management

```
Data (yfinance / Alpaca / FRED / NewsRSS)
        ↓
Feature Engineering (52 features)
        ↓
Ensemble Model (ARIMA + LightGBM + Meta-Learner)        [research/backtest path]
   — or —
Rule-Based Scanner (7 criteria + staged gates)            [live daily path]
        ↓
Risk Manager (2% max risk/trade, ATR stops, regime gates, gap-risk filter)
        ↓
Signal → Telegram → Paper Trade / Zerodha GTT
        ↓
MLflow Tracker + Drift Detector (continuous monitoring)
```

**These are two separate engines that don't share code** — conflating them is the single easiest mistake when reading this repo:

1. **Live daily path** (`daily_briefing.py` → `scanner.py`): a pure-NumPy rule scorer (7 bullish criteria, 0–100 score), gated by regime → sector rotation (top 2 sectors) → multi-timeframe agreement → backtest filter (≥52% historical win rate) → gap-risk filter. This is what actually drives Telegram alerts.
2. **ML research/backtest path** (`pipeline.py`): the ARIMA+LightGBM ensemble, used for backtesting and model research — not what fires live alerts today.

**Risk rules enforced in code, not just docs:**
- Max 2% of capital risked per trade
- ATR-based stop-loss and chandelier/trailing exits
- Regime gate (only trade when Nifty > 200-day SMA — the one rule [proven to add real edge](#the-honest-track-record-what-we-actually-found))
- Gap-risk filter, earnings blackout window, sector-rotation cap
- Halal constraint enforced at the code level: BUY-only, no shorting, no margin/leverage, no F&O

---

## 📋 Watchlist

| Tier | Count | Includes |
|---|---|---|
| Default Scan | 85 | Nifty 50 Shariah + Next 50 |
| Extended Scan | 141 | + MidCap halal + thematic baskets |
| Deep Scan | 171 | + SmallCap halal stocks |

**Thematic baskets:** IT (20) · Pharma (24) · Green Energy (12) · Consumer (14) · Infra (21)

Curated by sector/reputation, then **independently re-validated** by the AAOIFI screening engine — which is how the 10 mislabeled names mentioned above were caught.

---

## 📊 Models & Features

52 features feed the ensemble model:

| Group | Features |
|---|---|
| Momentum | RSI(7/14/21), MACD(line/signal/hist), ROC(5/10/20), Williams %R |
| Volatility | ATR%, BB width, BB %B, Volatility(5/10/20d) |
| Volume | OBV, Volume ratio, Volume Z-score, MFI(14), CMF |
| Trend | SMA/EMA(5/10/20/50/200), Price vs SMA(20/50/200), Golden cross, SMA200 slope |
| Market | VIX, SPY return, Nifty relative strength |
| Calendar | Day of week, Month, Days to F&O expiry, Holiday proximity |
| Sentiment | News sentiment score, volume, momentum *(opt-in, FinBERT)* |
| Macro | VIX, DXY, Yield curve spread, market breadth *(opt-in)* |

`TreeModel` uses LightGBM when importable, else falls back to RandomForest — despite `requirements.txt` listing XGBoost, it isn't used in the active path. `tensorflow` is only needed for the opt-in `--lstm` flag.

---

## 🤖 GitHub Actions — Automated Pipeline

| Job | Schedule | What it does |
|---|---|---|
| 🌅 Nightly Scan | Mon–Fri 9:00 AM IST | Scans the halal watchlist, sends signals to Telegram, regenerates `dashboard_data.js` |
| 🔔 Auto-Close | Mon–Fri 3:45 PM IST | Closes positions, sends P&L to Telegram |
| 📈 Weekly Backtest | Sunday 10:00 AM IST | Backtests RELIANCE + TCS, saves results |
| 🧪 CI Tests | Every push to `main` | Runs all 118 tests, validates imports |
| 🔍 Drift Check | Mon–Fri (after scan) | Flags if a model needs retraining |

Paper-portfolio state persists between runs via `actions/cache` on `results/`. Failures self-notify over Telegram.

**Trigger manually:** Actions tab → **Trading Pipeline** → **Run workflow** → choose the job. Or from the deployed dashboard's "Run controls" panel, which calls a Netlify Function that fires the same `workflow_dispatch` — see below.

---

## 🚀 Deployment (Netlify + GitHub Actions)

`demo-boro.html` is a pure static file with **no server at view-time** — data freshness comes entirely from GitHub Actions committing a fresh `dashboard_data.js`, which triggers a Netlify redeploy.

```toml
# netlify.toml (already committed)
[build]
  publish = "."
  command = ""
  functions = "netlify/functions"
```

**Setup:**
1. Connect this repo to Netlify, branch `V-1.0`. Build command: empty. Publish directory: `.`.
2. The dashboard's "Run controls" buttons POST to a Netlify Function (`netlify/functions/dispatch.js`) instead of talking to an always-on server — it holds a GitHub token server-side and fires `workflow_dispatch` on `trading_pipeline.yml`. Set these in **Site settings → Environment variables**:

   | Variable | Value | Purpose |
   |---|---|---|
   | `GH_DISPATCH_TOKEN` | a fine-grained GitHub PAT, repo-scoped, **Actions: read/write** | Authenticates the dispatch call — never exposed to the browser |
   | `GH_OWNER` | `taaqib-masood` | Repo owner for the dispatch URL |
   | `GH_REPO` | `stock-market-forecasting-risk-analytics` | Repo name for the dispatch URL |

   Optional: `GH_WORKFLOW` (default `trading_pipeline.yml`), `GH_REF` (default `V-1.0`).
3. Push to `V-1.0` → auto-redeploys. Clicking a dashboard control button → fires the workflow → Actions commits fresh data → site redeploys → dashboard shows it, end to end, with zero always-on servers.

> No secrets are exposed by `publish = "."` — `.env` is git-ignored and never deployed; only committed files ship.

---

## 📁 Project Structure

```
stock-market-forecasting-risk-analytics/
│
├── src/
│   ├── daily_briefing.py        ← Morning scan + Telegram alerts (live path entry point)
│   ├── scanner.py                ← 7-criteria rule scorer + staged gates (drives live signals)
│   ├── auto_close.py             ← Evening position closer
│   ├── paper_trader.py           ← Paper trading simulator
│   ├── pipeline.py                ← Train ensemble + backtest (research path entry point)
│   ├── ensemble.py                ← ARIMA + LightGBM + meta-learner stacking
│   ├── strategy.py                ← RuleStrategy — single unified signal source
│   ├── backtest_runner.py         ← Unified live==backtest engine
│   ├── validation.py              ← Look-ahead / leakage detection
│   ├── walk_forward.py            ← OOS validation harness + strategy-comparison gate
│   ├── proof.py                   ← Aggregate edge-proof runner
│   ├── feature_engineering.py     ← 52 technical/sentiment/macro features
│   ├── risk_manager.py            ← 10+ risk rules, position sizing, stops
│   ├── regime_detector.py         ← Market regime (BULL/BEAR/CRASH)
│   ├── halal_screen.py            ← AAOIFI classify() / screen_ticker() / screen_cached()
│   ├── halal_history.py           ← Point-in-time halal tier timeline
│   ├── halal_lookup.py            ← "Is this stock halal?" citation card
│   ├── tier_monitor.py            ← Compliance tier-change diff alerts
│   ├── fundamentals.py            ← Cached fundamentals reader (debt/interest ratios)
│   ├── zakat.py                   ← Zakat + purification calculator
│   ├── drawdown_guard.py          ← Graded drawdown de-risking + "why" explainer
│   ├── passive.py                 ← Passive halal-core + regime overlay
│   ├── news_sentiment.py          ← FinBERT news sentiment
│   ├── macro_indicators.py        ← VIX, DXY, FRED data
│   ├── explainer.py               ← SHAP + Groq AI trade explanations
│   ├── mlflow_tracker.py          ← Experiment tracking
│   ├── drift_detector.py          ← Model/data drift alerts
│   ├── notify.py                  ← Telegram notifications
│   ├── data_provider.py           ← yfinance / Alpaca data
│   ├── earnings_guard.py          ← Blocks trades near earnings
│   ├── gtt_generator.py           ← Zerodha GTT orders
│   ├── sector_rotation.py         ← Top-2-sector filter
│   ├── gap_risk.py                ← Overnight gap-risk filter
│   ├── backtest_filter.py         ← ≥52% historical win-rate gate
│   ├── control_server.py          ← Token-gated HTTP API for dashboard buttons
│   ├── watchlist.py               ← Tiered halal watchlists + sector baskets
│   └── ... (technical/moat/macro analyzers, journal, dynamic stops, etc.)
│
├── scripts/
│   ├── export_dashboard.py        ← Generates dashboard_data.js (live feed)
│   ├── refresh_fundamentals.py    ← Isolated-venv fundamentals cache refresh
│   └── compare_models.py          ← MLflow run comparison
│
├── tests/                          ← 118 tests: screening, Zakat, risk, walk-forward, leakage
├── .github/workflows/trading_pipeline.yml
├── netlify/functions/dispatch.js  ← Serverless GitHub Actions trigger
├── netlify.toml
├── demo-boro.html                 ← Current dashboard (15 tabs, live data)
├── demo.html                       ← Legacy dashboard
├── results/ · mlruns/              ← Auto-created output dirs, don't hand-edit
└── requirements.txt
```

---

## Testing & Validation

```bash
pytest tests/ -v        # 118 tests
```

Coverage: import/smoke tests, halal screening + Zakat math, risk manager rules, the unified strategy/backtest path, look-ahead/leakage detection, walk-forward harness, drawdown guard, point-in-time halal history. There is **no broad end-to-end UI test suite** — this is backend/quant-logic coverage, stated honestly rather than implied to be more than it is.

---

## 🔑 Environment Variables

All keys are optional — every module degrades gracefully when a key is missing rather than crashing. See `.env.example` for the full list.

| Key | Service | Purpose |
|---|---|---|
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram | Trade alerts to your phone |
| `GROQ_API_KEY` | Groq (Llama 3) | AI trade explanations |
| `FRED_API_KEY` | Federal Reserve | Yield curve, Fed rate data |
| `ALPACA_API_KEY` / secret | Alpaca | US-market data for the ML research path (falls back to yfinance if unset) |

---

## 🆘 Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Run `source venv/bin/activate` first, and run via `python -m src.<module>` from repo root |
| No Telegram message | Check `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` in `.env` |
| `yfinance` error | `pip install --upgrade yfinance` |
| LightGBM crash on macOS | `brew install libomp` |
| MLflow not found | `pip install mlflow` |
| Groq error | Check `GROQ_API_KEY` in `.env` |
| Dashboard shows `sample:true` data | Run `python -m scripts.export_dashboard --capital 50000` to populate real data |

---

## 🗺️ Roadmap

- Point-in-time halal universe in the live backtest path (avoid look-ahead-halal-bias — currently flagged, not yet fully eliminated)
- Multi-market support: India NSE ✅ and US ✅ and Saudi Tadawul ✅ already work on free data; UAE deferred pending a real DFM/ADX feed and a licensing review
- Paid fundamentals API for full 🟢 certification at scale (current free pipeline is personal-use-grade, rate-limited and fragile against scraper blocks)
- Demo-boro.html promoted to the default dashboard (pending final review)

---

## ⚠️ Disclaimer

Educational project. Not financial advice, not a fatwa, not a substitute for a qualified scholar's ruling on your specific situation. Halal screening cites the AAOIFI standard and shows its sources, but is not an independent religious authority. Paper-trade for at least 30 days before risking real capital. Past backtest performance — including the validated regime-gate edge described above — is not a guarantee of future results.

---

*Built by Taaqib Masood · NSE/BSE India · MIT Licensed*
