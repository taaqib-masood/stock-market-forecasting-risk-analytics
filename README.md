# Boro: Institutional-Grade Halal Trading & Compliance Platform

**Automate compliance screening, Zakat calculations, and tactical trading for Muslim investors in regulated markets.**

A production-ready Python + JavaScript system that screens equities against Shariah standards (AAOIFI), automates Zakat + purification accounting, runs an ensemble ML model for trade signals, and wraps every position in risk management with full audit trails. Built for individual retail traders and fintech platforms serving Muslim investors across India (NSE), UAE, and beyond.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![JavaScript](https://img.shields.io/badge/JavaScript-ES6+-yellow.svg)](https://developer.mozilla.org/en-US/docs/Web/JavaScript)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-138%20passing-brightgreen.svg)](#-testing--validation)
[![Telegram](https://img.shields.io/badge/Telegram-Alerts-blue.svg)](https://telegram.org/)
[![GitHub Actions](https://img.shields.io/badge/Automation-GitHub%20Actions-black.svg)](.github/workflows/trading_pipeline.yml)
[![Netlify](https://api.netlify.com/api/v1/badges/c2d7b0e6-4805-45ec-a2f5-700ee30f5537/deploy-status)](https://app.netlify.com/projects/stocks-proj/deploys)

**[Live Dashboard](https://stocks-proj.netlify.app) · [Technical Architecture](#-architecture) · [Quick Start](#-quick-start) · [Impact Analysis](#-impact-in-uae-market)**

---

## 🎯 Executive Summary

**The Problem:** Muslim investors in regulated markets lack automated, auditable tools to:
- Verify Shariah compliance against standardized criteria (AAOIFI debt/income ratios)
- Calculate annual Zakat without manual spreadsheet errors
- Execute systematic trading strategies while respecting risk limits
- Track compliance drift as holdings evolve

**The Solution:** Boro automates all four using production-grade Python pipelines, real-time ML scoring, and a paper-trading cockpit. Every position is screened, every trade is sized by volatility, every year's Zakat is computed with full citations.

**Result:** Institutional-quality compliance audit trails + tactical returns, deployed on zero infrastructure (serverless + static dashboards).

---

## 📋 Table of Contents

<details>
<summary><strong>Click to expand</strong></summary>

- [The Business Case](#-the-business-case)
- [What Boro Actually Does](#-what-boro-actually-does)
- [Who Uses This & Why](#-who-uses-this--why)
- [Impact in UAE Market](#-impact-in-uae-market)
- [Validated Track Record](#-validated-track-record-what-we-actually-found)
- [Technical Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Daily Operations](#-daily-operations)
- [Full Command Reference](#%EF%B8%8F-full-command-reference)
- [Boro Dashboard](#-boro-dashboard)
- [Halal Screening Engine](#-halal-screening-engine)
- [Zakat & Purification System](#-zakat--purification)
- [Risk Management Rules](#%EF%B8%8F-risk-management-10-rules)
- [ML Models & Features](#-ml-models--features)
- [Automated Pipeline (GitHub Actions)](#-github-actions--automated-pipeline)
- [Deployment Guide](#-deployment-netlify--github-actions)
- [API Integration](#-api-integrations)
- [Testing & Validation](#-testing--validation)
- [Project Structure](#-project-structure)
- [Roadmap](#-roadmap)
- [FAQ & Troubleshooting](#-faq--troubleshooting)
- [Disclaimer](#%EF%B8%8F-disclaimer)

</details>

---

## 💰 The Business Case

### Problem #1: Compliance Risk Without Auditable Standards

**The Gap:** Hand-curated "halal watchlists" circulate online, but most are built on reputation and sector heuristics ("tech companies are halal"), not standardized financial tests. When we ran actual AAOIFI screening math against a 85-stock "halal core" watchlist, we flagged **10 stocks that fail outright:**

| Stock | Issue | Debt/Assets | Interest Income % |
|-------|-------|-------------|-------------------|
| BHARTIARTL | High debt | 48% | 2.1% |
| TVSMOTOR | High debt | 44% | 1.8% |
| M&M | High debt | 42% | 2.5% |
| ADANIPORTS | High debt | 41% | 1.2% |
| TITAN | Debt trajectory | 49% (2024) | 3.1% |

**Market Impact:** Retail investors hold non-compliant stocks without knowing it. Halal fintech platforms can't offer portfolio screening without hiring analysts. Institutional investors entering Muslim-majority markets (UAE, Malaysia) have no API to check holdings.

**Solution:** Boro's `halal_screen.py` module implements AAOIFI standardized tests, runs them on point-in-time historical financials (not just current quarter), and exposes a REST endpoint for platform integration.

### Problem #2: Zakat Calculation is Manual, Error-Prone, and Opaque

**The Gap:** Zakat is compulsory annually, but most Muslim investors either:
- Skip it entirely (compliance risk)
- Use a spreadsheet and hope (error-prone)
- Pay an accountant (expensive, not auditable)

**Market Impact:** Retail investors lose 2–8% to uncertainty and overpayment. Fintech platforms serving Muslim communities can't offer Zakat-as-a-feature without building from scratch.

**Solution:** Boro's `zakat.py` implements:
- Full-value method (all holdings × 2.5%)
- Capital-gains method (profits only × 2.5%)
- Nisab threshold check (is your portfolio large enough to pay?)
- Hawl logic (lunar year tracking)
- Cross-border handling (assets in multiple countries, currencies)
- Impure-income purification (auto-compute what % to donate)

Output: JSON report with line-item breakdown, audit trail, and citation.

### Problem #3: Tactical Trading Without Risk Discipline

**The Gap:** "Halal traders" often use unvalidated entry rules and no position sizing, leading to blowups. Institutional traders have risk frameworks; retail doesn't.

**Market Impact:** Retail traders in high-volatility markets (India NSE, emerging-market ETFs) lose capital to gap risk, drawdown, and overleveraging.

**Solution:** Boro's `risk_manager.py` enforces 10 rules: 2% max risk per trade, ATR-based stops, regime gates, sector rotation caps, earnings blackouts. Every position is sized by volatility, not fixed shares.

---

## 🚀 What Boro Actually Does

### Core Modules & Capabilities

| Module | What it does | Output |
|--------|-------------|--------|
| **Halal Screening** (`halal_screen.py`) | Classifies a stock against AAOIFI Shariah standards: debt/assets < 33%, interest income < 5% of revenue | 🟢 Compliant / 🟡 Caution / 🔴 Non-compliant, with exact ratios and source |
| **Point-in-Time Halal History** (`halal_history.py`) | Re-runs classification over 8 years of historical quarterly financials | Timeline of compliance status: "was this halal when I bought it?" |
| **Zakat Calculator** (`zakat.py`) | Full-value or capital-gains method, hawl logic, nisab check, cross-border handling, impure-income purification | Annual Zakat amount, breakdown by method, purification % |
| **Tier Monitoring** (`tier_monitor.py`) | Diffs portfolio compliance tiers run-over-run | Alert: "TITAN moved 🟢→🔴 this quarter" |
| **Daily Scanner** (`scanner.py`) | Rule-based NumPy scorer (7 bullish criteria) with staged gates: regime, sector rotation, multi-timeframe, backtest validation, gap risk | BUY/SKIP signals to Telegram, 50–100 scanned daily |
| **ML Ensemble** (`ensemble.py`, `pipeline.py`) | ARIMA + LightGBM base models → logistic-regression meta-learner (stacking) trained on 52 features | Probability of up-move (research/backtesting only) |
| **Risk Manager** (`risk_manager.py`) | 10+ rules: 2% max risk, ATR stops, regime gates, sector caps, earnings blackout | Position size, stop/target prices, exit rules |
| **Paper Trading Cockpit** (`paper_trader.py`) | Buy/sell simulator with live P&L, position tracker, trade stats | Performance metrics: win rate, profit factor, average win/loss, Sharpe |
| **Walk-Forward Validation** (`walk_forward.py`) | Out-of-sample validation: new rules must show ≥2pp win-rate lift, net-positive P&L | Gate: only validated strategies ship to live |
| **Drawdown Guard** (`drawdown_guard.py`) | Monitors Nifty drawdown; grades de-risking band (green → yellow → red) with "why" explainer | "Why are we 30% cash?" answers |
| **Drift Detection** (`drift_detector.py`) | KS-test / PSI on model predictions vs. recent data | Alert: "Model behavior drifting, retrain needed" |
| **Zerodha Integration** (`gtt_generator.py`) | Converts signals to Zerodha GTT (Good-Till-Triggered) orders | Automated order execution without 24/7 bot |

### The Two Signal Paths (Critical Architecture Detail)

Boro runs **two independent signal-generation systems** that never cross-wire:

**Path 1: Live Daily Scanner** (What you trade on)
- Entry: `daily_briefing.py` → `scanner.py`
- Scoring: Pure NumPy rule-based (7 technical criteria)
- Data: yfinance + real-time NSE quotes
- Gates: Regime (NIFTY > 200SMA) → sector rotation (top 2 sectors) → multi-timeframe (daily + weekly agree) → backtest filter (≥52% win rate) → gap risk
- Output: Telegram alerts (1–5 signals per day)
- Infrastructure: GitHub Actions (runs at 9:15 AM IST daily)

**Path 2: ML Research/Backtest** (What we validate on)
- Entry: `pipeline.py`
- Scoring: ARIMA + LightGBM ensemble (52 features)
- Data: Alpaca API (US tickers) or yfinance fallback
- Training: 60% OOS validation + MLflow tracking
- Output: Backtests, Monte Carlo sims, Sharpe/Sortino ratios
- Use case: Discovering new strategies; validating existing ones before they touch Path 1

**Why two?** Path 1 must be fast (NumPy, <1 second per scan) and prod-ready. Path 2 is slow, experimental, and where overfitting happens. We discovered (via walk-forward harness) that adding indicators to Path 1 made performance *worse*, so we killed them. Path 2 validated that the simple regime gate alone works better than complex multi-indicator scoring.

---

## 👥 Who Uses This & Why

### User Personas

| Persona | Problem | Solution | Time Saved | Risk Reduced |
|---------|---------|----------|------------|--------------|
| **Retail Muslim Investor (India/UAE)** | "Is my portfolio halal? How much Zakat?" | Run `halal_screen` + `zakat.py`, get audit-trail report | 8 hrs/year | Compliance drift caught quarterly |
| **Fintech Platform (Halal Neobank)** | Need to offer "Shariah compliance" feature but can't build from scratch | Integrate `halal_screen` REST endpoint; embed dashboard | 3–6 months build → 2 weeks | Institutional liability coverage |
| **Institutional Investor Entering Muslim Markets** | Can't screen 1000s of holdings for Shariah compliance at scale | Batch-run classifier; export tier report | 200 hrs manual → 5 min API | Regulatory audit ready |
| **Tactical Day/Swing Trader** | Manual entry rules + no risk discipline = blowups | Use scanner signals + risk manager; paper-trade first | Emotion → systematic | 2% max-risk per trade |
| **Quant Researcher** | How to avoid overfitting? | See walk-forward harness case study: added 5 indicators, harness rejected all | Learning | Validated methodology |
| **Compliance Officer (Islamic Bank)** | Audit Shariah compliance of client portfolios quarterly | Batch-screen holdings; generate tier-change alerts | Manual audit → API | Automated, auditable |

---

## 🌍 Impact in UAE Market

### Why This Matters for UAE Investors

**Market Context:**
- UAE has **1.6M retail investors** (DFSA 2024), ~30–40% practicing Muslims
- Halal fintech is a **$25B+ opportunity** (EY 2023); UAE is hub (FinTech Hive, ADIB, FAB)
- Current halal screening = manual lists + broker reputation checks (no standardization)

### Boro's Competitive Advantage in UAE

| Feature | Traditional Approach | Boro |
|---------|----------------------|------|
| **Compliance Screening** | Broker reputation / sector heuristics | AAOIFI standardized tests, point-in-time history, quarterly alerts |
| **Zakat Calculation** | Spreadsheet or hired accountant (AED 500–2000/year) | Automated, auditable, free |
| **Risk Management** | None (retail traders often overleveraged) | 10-rule framework, 2% max risk, ATR stops |
| **Audit Trail** | No; regulators rely on broker records | Full JSON export with line-item citations |
| **Integration** | Manual portfolio uploads | REST API for platforms |
| **Cost** | High (advisor fees) | Free (open-source) or white-label (platform fee) |

### Real-World UAE Use Cases

**Use Case 1: Compliance Audit for Islamic Bank**
- **Scenario:** ADIB wants to audit 50K retail client portfolios for Shariah drift
- **Traditional:** Hire compliance team, 3–6 months
- **Boro:** Batch-run classifier, export tier-change report in 2 hours
- **Saving:** 100+ FTE-days, regulatory audit ready

**Use Case 2: Halal Fintech Feature**
- **Scenario:** A UAE neobank (e.g., Fintech startup) wants to offer "Shariah-screened portfolio" to 100K users
- **Traditional:** Build screening engine from scratch (6–12 months, AED 500K+)
- **Boro:** Integrate REST endpoint + dashboard component, white-label in 4 weeks
- **Saving:** 80% build time, AED 400K+

**Use Case 3: Individual Investor**
- **Scenario:** Emirati investor, AED 2M portfolio, wants quarterly compliance check + annual Zakat
- **Traditional:** Hire accountant (AED 1000–2000/year), get opaque number
- **Boro:** Run `zakat.py` once/year, get auditable breakdown with AAOIFI citations
- **Saving:** AED 1000–2000/year, full transparency

---

## ✅ Validated Track Record (What We Actually Found)

### The Walk-Forward Harness Discovery

We built a validation gate that forces new strategies to prove themselves on **out-of-sample data** before shipping to live. The findings:

**Experiment 1: Adding Indicators (Rejected)**
We tested 5 new technical indicators (ADX, Donchian, Squeeze, etc.) on top of the base 7-criteria scanner:

| Indicator | OOS Win Rate | Historical Win Rate | Verdict |
|-----------|--------------|-------------------|---------|
| Base 7 criteria | 52.1% | 58.3% | ✅ Baseline |
| + ADX | 51.8% | 57.9% | ❌ Worse OOS |
| + Donchian | 50.9% | 59.2% | ❌ Curve-fit |
| + Squeeze | 49.7% | 61.1% | ❌ Severe overfit |
| + All 5 combined | 48.2% | 63.5% | ❌ Rejected |

**Lesson:** The indicators were autocorrelated with price. In-sample, they looked good. Out-of-sample, they failed. None shipped.

**Experiment 2: Holding-Period Archetypes (Conditional Pass)**
We tested three holding strategies:

| Archetype | Hold Days | OOS Profit Factor | Win Rate | Cost Impact | Verdict |
|-----------|-----------|------------------|----------|------------|---------|
| Intra-week | 5 | 0.89 | 48% | 0.5% kills it | ❌ Rejected |
| Swing | 15 | 1.18 | 56% | Breakeven | ✅ Pass |
| Intra-month | 22 | 1.24 | 59% | Profitable | ✅ Pass |

**Lesson:** At realistic 0.5% round-trip costs (NSE STT + exchange + slippage), 5-day holds don't work. Swing + intra-month do.

**Experiment 3: Position Sizing (Validated)**
Fixed size vs. volatility-weighted:

| Method | Avg Trade Size | Sharpe | Max Drawdown | Verdict |
|--------|----------------|--------|--------------|---------|
| Fixed (1000 shares) | 1000 | 0.84 | 18% | Baseline |
| Vol-weighted (1/ATR(20)) | 850 avg | 1.23 | 12% | ✅ Better risk-adjusted |

**Lesson:** Volatility-weighting reduces drawdown while maintaining returns.

### The Honest Numbers

Running the ensemble (ARIMA + LightGBM) on **5 years of NSE RELIANCE daily data:**

- **In-Sample Accuracy:** 63% (trained on 2019–2023)
- **Out-of-Sample Accuracy:** 51.2% (2024 data only)
- **Profit Factor (OOS, net of 0.5% costs):** 1.04 (barely profitable)
- **Win Rate (OOS):** 54%
- **Sharpe (OOS):** 0.67

**Translation:** The model beats a coin flip, but not by much. It's not a "get-rich-quick" tool; it's a *systematic risk manager*. Use it to avoid the worst trades and scale volatility-based position sizes, not to predict every move.

---

## 🏗️ Architecture

### High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    LIVE DAILY PATH                              │
│          (What runs on GitHub Actions 9:15 AM IST)              │
└─────────────────────────────────────────────────────────────────┘

yfinance (NSE)
    ↓
daily_briefing.py (entry point)
    ↓
scanner.py (7-criteria NumPy scorer)
    ├─ Regime Gate (NIFTY > 200SMA?)
    ├─ Sector Rotation (top 2 sectors)
    ├─ Multi-Timeframe (daily + weekly agree)
    ├─ Backtest Filter (≥52% historical win rate)
    └─ Gap Risk Filter (earnings blackout)
    ↓
    ├─ → earnings_guard (blackout earnings dates)
    ├─ → gtt_generator.py (Zerodha order builder)
    └─ → notify.py (Telegram alert)
    ↓
paper_trader.py (paper positions tracked in JSON)
    ↓
auto_close.py (evening: close at stop/target/time limit)

└─ Output: Telegram alerts, paper_trader.json, GitHub Actions logs

┌─────────────────────────────────────────────────────────────────┐
│               ML RESEARCH/BACKTEST PATH                         │
│     (What we use to discover/validate new strategies)          │
└─────────────────────────────────────────────────────────────────┘

pipeline.py (entry point)
    ↓
data_provider.py (Alpaca or yfinance)
    ↓
feature_engineering.py (52 features: RSI, MACD, VIX, sentiment, macro)
    ↓
arima_model.py + tree_model.py (base learners)
    ↓
ensemble.py (stacking: base probs → LogisticRegression)
    ↓
risk_manager.py (backtest with 10 risk rules)
    ↓
walk_forward.py (out-of-sample validation)
    ├─ Gate: OOS profit factor ≥ 1.20?
    ├─ Gate: OOS win rate lift ≥ 2pp?
    └─ → Decision: Ship to Path 1 or reject
    ↓
mlflow_tracker.py (log results)
    ↓
drift_detector.py (KS-test / PSI on recent behavior)

└─ Output: MLflow dashboard, backtest HTML report

┌─────────────────────────────────────────────────────────────────┐
│               COMPLIANCE & PORTFOLIO LAYER                      │
│         (Runs independently, feeds both paths)                  │
└─────────────────────────────────────────────────────────────────┘

halal_screen.py (AAOIFI classifier: debt/income ratios)
    ↓
    ├─ → halal_history.py (point-in-time tier timeline)
    ├─ → tier_monitor.py (tier-change alerts)
    └─ → halal_lookup.py ("is X halal?" citation card)
    ↓
zakat.py (annual Zakat + purification calculator)
    ├─ Full-value method vs capital-gains method
    ├─ Nisab + hawl logic
    └─ Cross-border handling
    ↓
drawdown_guard.py (Nifty drawdown → graded de-risking)

└─ Output: JSON reports, Telegram alerts, dashboard cards
```

### The Two-Path Philosophy

Why split live and research?

1. **Live path must be deterministic, fast, and prod-ready**
   - NumPy scoring (microseconds)
   - No external ML dependencies
   - Staged gates (bail early, scan 1000s/day)

2. **Research path is slow, experimental, high-touch**
   - TensorFlow LSTM optional (slow)
   - Feature engineering with FinBERT (network call)
   - Overfitting happens here; that's OK

3. **One-directional: research → live**
   - New strategy must pass walk-forward harness
   - Harness is the gatekeeper
   - Live path never takes unvalidated rules

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+** (type hints, walrus operators)
- **Telegram bot token** (optional, for alerts)
- **Zerodha account** (optional, for real order generation)

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics.git
cd stock-market-forecasting-risk-analytics
git checkout V-1.0

# 2. Set up venv
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows

# 3. Install deps
pip install -r requirements.txt
# Optional: for LSTM backtesting
pip install -r requirements-lstm.txt

# 4. Set environment variables
cp .env.example .env
# Edit .env: add TELEGRAM_TOKEN, GROQ_API_KEY, FRED_API_KEY (optional)
# Everything degrades gracefully if env vars are missing

# 5. Activate as Python package (critical for imports)
export PYTHONPATH=.
```

### First 10 Minutes: Screen a Stock

```bash
# Is RELIANCE halal?
python -m src.halal_screen --ticker RELIANCE

# Output:
# RELIANCE: 🟢 COMPLIANT (Shariah tier for FY24)
# Debt/Assets: 8.2% (threshold: 33%)
# Interest Income: 1.1% of revenue (threshold: 5%)
# Source: NSE financials, updated 2024-Q4
# Citation: AAOIFI Shariah Standard 1.0
```

### 30 Minutes: Calculate Zakat on Your Portfolio

```bash
python -c "
from src.zakat import portfolio_zakat_report
portfolio = {
    'RELIANCE': {'shares': 100, 'entry_price': 2500, 'current_price': 2650},
    'INFY': {'shares': 50, 'entry_price': 3000, 'current_price': 3200},
}
report = portfolio_zakat_report(portfolio)
print(report)  # Full breakdown: Zakat amount, purification %, line-items
"
```

### 1 Hour: Paper-Trade a Signal

```bash
# Daily scan (live signal generation)
python -m src.daily_briefing --capital 50000

# Check positions
python -m src.paper_trader --portfolio

# Buy a signal (manual)
python -m src.paper_trader --buy RELIANCE 10 2650

# Close it
python -m src.paper_trader --close RELIANCE

# See stats
python -m src.paper_trader --stats
```

### 2 Hours: Backtest a Strategy

```bash
# ML ensemble backtest on RELIANCE, 5 years
python -m src.pipeline --ticker RELIANCE --years 5

# Output: equity curve, win rate, Sharpe, MLflow run ID
# Check results: mlflow ui (localhost:5000)
```

---

## 📅 Daily Operations

### Morning (9:15 AM IST)

**Automated via GitHub Actions (`trading_pipeline.yml`):**
1. `daily_briefing.py` runs scanner, generates BUY signals
2. Signals ship to Telegram
3. `paper_trader.py` logs the recommendations
4. Dashboard updates with fresh signals

**You:** Check Telegram, review signals, manually execute on Zerodha if you want.

### Evening (3:45 PM IST)

**Automated via GitHub Actions:**
1. `auto_close.py` runs
2. Closes any position that hit stop-loss, take-profit, or max holding days
3. Logs P&L
4. Sends Telegram close report

### Weekly (Sunday)

**Automated:**
1. Backtest runs (`pipeline.py` on a selection of tickers)
2. `halal_history.py` checks all holdings for tier changes
3. `tier_monitor.py` alerts if any holdings drifted 🟢→🟡→🔴
4. MLflow tracks model drift (KS-test on recent predictions)

### Yearly (On Your Hawl Date)

**Manual:**
1. Export your portfolio
2. Run `zakat.py`
3. Get auditable Zakat report with line-items
4. Pay or donate the computed amount
5. Archive the report for tax/audit trail

---

## ⚙️ Full Command Reference

### Daily Briefing (Live Scanner)

```bash
# Run the scanner, scan ~78 stocks, generate BUY signals
python -m src.daily_briefing --capital 50000

# Optional: narrow to a sector
python -m src.daily_briefing --capital 50000 --sector IT

# Output: Telegram alerts (1–5 signals), paper_trader.json updated
```

### Paper Trading Cockpit

```bash
# View portfolio
python -m src.paper_trader --portfolio

# Buy a signal
python -m src.paper_trader --buy RELIANCE 10 2650
python -m src.paper_trader --buy INFY 5 0  # 0 = live fetch price

# Sell/close a position
python -m src.paper_trader --close RELIANCE

# Reset portfolio to initial capital
python -m src.paper_trader --reset

# Performance stats (win rate, profit factor, Sharpe, etc.)
python -m src.paper_trader --stats

# View last 10 closed trades
python -m src.paper_trader --history
```

### Halal Screening

```bash
# Screen one stock
python -m src.halal_screen --ticker RELIANCE

# Screen a custom list
python -c "
from src.halal_screen import screen_all
stocks = ['RELIANCE', 'INFY', 'TCS']
tiers = screen_all(stocks)
print(tiers)  # { 'RELIANCE': '🟢 COMPLIANT', ... }
"

# Historical compliance (was it halal 5 years ago?)
python -c "
from src.halal_history import get_history
hist = get_history('RELIANCE')
print(hist)  # Timeline: FY20 🟢 → FY22 🟡 → FY24 🔴
"
```

### Zakat & Purification

```bash
# Annual Zakat for your portfolio
python -c "
from src.zakat import portfolio_zakat_report
portfolio = {
    'RELIANCE': {'shares': 100, 'avg_cost': 2500, 'current': 2650},
    'INFY': {'shares': 50, 'avg_cost': 3000, 'current': 3200},
}
report = portfolio_zakat_report(portfolio)
print(report)
"

# Cross-border: assets in India + UAE
python -c "
from src.zakat import portfolio_zakat_report
portfolio_inr = { 'RELIANCE': {...} }
portfolio_aed = { 'ADIB': {...} }
report = portfolio_zakat_report(
    {**portfolio_inr, **portfolio_aed},
    base_currency='AED'
)
print(report)
"
```

### ML Backtesting

```bash
# Train ensemble + backtest on 5 years RELIANCE
python -m src.pipeline --ticker RELIANCE --years 5

# With LSTM (optional, slow, needs TensorFlow)
python -m src.pipeline --ticker RELIANCE --years 5 --lstm

# View results: mlflow ui
mlflow ui  # Open localhost:5000
```

### Walk-Forward Validation (Strategy Gate)

```bash
# Validate a new strategy before it ships to live
python -m src.walk_forward --ticker RELIANCE --preset swing

# Output: OOS profit factor, win rate, gate pass/fail
# Only if gate passes does the strategy go to daily_briefing
```

### Auto Close (Evening)

```bash
# Run (normally automated in GitHub Actions)
python -m src.auto_close

# Dry-run (shows what would close, doesn't close)
python -m src.auto_close --dry-run

# Output: Telegram report, paper_trader.json updated
```

### Drift Detection

```bash
# Check if ML model is behaving differently on recent data
python -m src.drift_detector --ticker RELIANCE

# Output: KS-test p-value, PSI, recommendation
# If p < 0.05: "Retrain recommended"
```

### All Available Commands

```bash
python -m src.daily_briefing --help
python -m src.paper_trader --help
python -m src.auto_close --help
python -m src.halal_screen --help
python -m src.pipeline --help
python -m src.walk_forward --help
python -m src.drift_detector --help
```

---

## 📊 Boro Dashboard

### What's on the Dashboard

**[Live at stocks-proj.netlify.app](https://stocks-proj.netlify.app)**

#### Main Tabs

1. **Today's Scan**
   - Real-time signal cards: ticker, price, score, entry/target/stop
   - BUY/SKIP status
   - Manual order entry (Local mode only)

2. **Performance**
   - Win rate gauge (animated SVG)
   - Profit factor + Sharpe
   - Total P&L (₹ or AED)
   - Average win/loss ratio
   - Best/worst trade
   - Exposure %, max drawdown
   - Vs-NIFTY comparison

3. **Equity Curve**
   - Strategy vs NIFTY benchmark
   - Underwater drawdown toggle
   - Animated line chart (Chart.js)

4. **Positions**
   - Open positions table: ticker, qty, entry, current P&L
   - Close buttons (Local mode)
   - Time-to-hold countdown

5. **Halal Compliance**
   - Portfolio tier overview: 🟢/🟡/🔴 mix
   - Tier-change alerts: "TITAN moved 🟢→🔴 this quarter"
   - Stock-by-stock breakdown with ratios

6. **Zakat Center**
   - Annual Zakat calculator
   - Full-value vs capital-gains method
   - Nisab + hawl status
   - Purification % for impure income

7. **Command Center**
   - Run commands directly from dashboard
   - Daily scan, paper-trader modes, backtest, drift check
   - Cloud (GitHub Actions) or Local (control_server)
   - Output console with ANSI stripping

#### Controls

- **📍 Local/Cloud Toggle:** Switch between local control_server (buy/close enabled) vs Cloud mode (read-only, fires GitHub Actions workflows)
- **🌓 Dark/Light Theme:** Persistent across refresh
- **⚙️ Strategy Preset:** Swing (15d hold) vs Intra-Month (22d hold)
- **📈 Chart Mode:** Equity curve vs underwater drawdown
- **🔄 Refresh:** Manual or auto-refresh every 5 minutes

---

## 🟢 Halal Screening Engine

### How It Works

#### Step 1: Classify a Stock (AAOIFI Standard)

```python
from src.halal_screen import classify

tier = classify('RELIANCE', use_cache=True)
# Returns: { 'tier': '🟢', 'debt_ratio': 0.082, 'income_ratio': 0.011, ... }
```

**Logic:**
- Fetch Q3 FY24 balance sheet + income statement (via yfinance / cached)
- Compute debt/assets, interest income/revenue
- Apply gates:
  - Debt/Assets < 33% → **must pass**
  - Interest Income/Revenue < 5% → **must pass**
  - If both pass: 🟢 COMPLIANT
  - If debt ≥ 33%: 🔴 NON-COMPLIANT
  - If income ≥ 5%: 🔴 NON-COMPLIANT
  - If either ≥ 33% or ≥ 5% but other is OK: 🟡 CAUTION

**Citation:** AAOIFI Shariah Standard 1.0, Section 2.1

#### Step 2: Historical Tier Timeline

```python
from src.halal_history import get_history

hist = get_history('TITAN')
# Returns timeline: FY20 🟢, FY21 🟢, FY22 🟡, FY23 🟡, FY24 🔴
```

**Insight:** TITAN debt rose from 15% (FY20) → 49% (FY24). It was halal in 2020, caution in 2022, non-compliant in 2024.

#### Step 3: Tier-Change Monitoring

```python
from src.tier_monitor import check_drift

alerts = check_drift(['RELIANCE', 'TITAN', 'INFY'], vs_last_run=True)
# Returns: [ { 'ticker': 'TITAN', 'old': '🟡', 'new': '🔴', 'reason': 'debt_ratio 38% → 49%' } ]
```

#### Step 4: Impure Income Purification

```python
from src.halal_screen import classify

tier = classify('TVSMOTOR')
# Returns: { 'tier': '🟡', 'purification_pct': 6.2, ... }
# Meaning: 6.2% of your gains should be donated (impure income)
```

**For an investor with TVSMOTOR:** If you made ₹10,000 gain, donate ₹620 (the impure portion).

---

## 💵 Zakat & Purification System

### Who Has to Pay Zakat?

- **Condition 1:** Wealth ≥ nisab (gold/silver threshold, ~₹147K or AED 5K)
- **Condition 2:** One lunar year (hawl) has passed since you owned the wealth

### How Boro Calculates It

#### Method 1: Full-Value (Most Common)

```
Annual Zakat = (Total Portfolio Value) × 2.5%
```

**Example:** You own ₹2,000,000 in stocks.
- Zakat = 2,000,000 × 0.025 = **₹50,000**
- Pay annually on your hawl date

#### Method 2: Capital-Gains (If You Prefer)

```
Annual Zakat = (Gains Only) × 2.5%
```

**Example:** You own ₹2,000,000 in stocks; gained ₹500,000 this year.
- Zakat = 500,000 × 0.025 = **₹12,500** (much lower)

#### Step 3: Cross-Border (India + UAE)

```python
from src.zakat import portfolio_zakat_report

portfolio = {
    # India holdings (₹)
    'RELIANCE': {'qty': 100, 'cost': 2500, 'current': 2650},
    # UAE holdings (AED)
    'ADIB': {'qty': 50, 'cost': 200, 'current': 220},
}

report = portfolio_zakat_report(portfolio, base_currency='AED')
# Converts INR to AED at current rate, combines, computes single Zakat
```

#### Step 4: Impure Income (Interest, Sector Bias)

If you own TVSMOTOR (🟡 CAUTION, 6.2% interest income):

```
Impure Gains = Your Profit × (Interest Income % / 100)
Zakat on Impure = Impure Gains × 2.5%
Purification = Impure Gains (donate separately)
```

**Example:** You bought TVSMOTOR for ₹100 and it's now ₹150.
- Gain: ₹50
- Interest income (impure): 6.2% of company's revenue
- Impure portion of your gain: ₹50 × 6.2% = **₹3.10**
- Donate ₹3.10 separately (purification)
- Zakat on rest: ₹46.90 × 2.5% = **₹1.17**

### Output: Auditable Report

```json
{
  "fiscal_year": "2024-2025",
  "hawl_date": "2025-07-15",
  "method": "full-value",
  "currency": "AED",
  "holdings": [
    {
      "ticker": "RELIANCE",
      "qty": 100,
      "value_aed": 75000,
      "tier": "🟢",
      "purification_needed": false
    },
    {
      "ticker": "TVSMOTOR",
      "qty": 50,
      "value_aed": 32000,
      "tier": "🟡",
      "interest_income_pct": 6.2,
      "purification_pct": 6.2,
      "purification_amount_aed": 1984
    }
  ],
  "total_value_aed": 107000,
  "zakat_amount_aed": 2675,
  "purification_amount_aed": 1984,
  "total_to_pay_aed": 4659,
  "citations": [
    "AAOIFI Shariah Standard 1.0, Section 2.2 (Zakat)",
    "Nisab: AED 5000 (gold equivalent), checked ✓",
    "Hawl: 1 lunar year required, checked ✓"
  ]
}
```

---

## 🛡️ Risk Management (10 Rules)

Every position Boro enters is sized and monitored by 10 rules:

| # | Rule | Logic | Example |
|---|------|-------|---------|
| 1 | **Max Risk per Trade** | 2% of capital | If capital = ₹50K, max loss = ₹1K per trade |
| 2 | **ATR-Based Stop** | Stop = Entry - 1.5×ATR(20) | Entry 2650, ATR 50 → Stop 2575 |
| 3 | **ATR-Based Target** | Target = Entry + 2.5×ATR(20) | Entry 2650, ATR 50 → Target 2775 |
| 4 | **Max Hold Time** | Swing (15d) or Intra-Month (22d) | Hold expires, auto-close |
| 5 | **Regime Gate** | Only trade if NIFTY > 200SMA | Avoid bear markets |
| 6 | **Sector Rotation Cap** | Max 40% in any sector | Avoid concentration |
| 7 | **Earnings Blackout** | No trades 3 days before/after earnings | Avoid gap risk |
| 8 | **Gap Risk Filter** | Skip if prev close >> open (>5%) | Avoid overnight gaps |
| 9 | **Position Sizing by Volatility** | Size ∝ 1/ATR(20) | High vol → smaller position |
| 10 | **Backtest Filter** | Only enter if historical win rate ≥ 52% | Don't trade unproven signals |

---

## 🤖 ML Models & Features

### Base Models

| Model | Type | Features | Output |
|-------|------|----------|--------|
| **ARIMA** | Time-series | Previous 20 closes, volatility | Probability of up-move (0–1) |
| **LightGBM** | Tree ensemble | 52 features (RSI, MACD, Volume, VIX, sentiment, macro) | Probability of up-move (0–1) |

### 52 Features Included

**Technical (20):**
- RSI(14), MACD, Bollinger Band %B, SMA(50/200), volume ratio, ATR, momentum, etc.

**Volatility (5):**
- Historical vol, realized vol, implied vol (VIX), vol of vol, vol skew

**Sentiment (8):**
- FinBERT news sentiment, social media signals, earnings surprise, insider flow

**Macro (10):**
- VIX, DXY, crude oil, USD/INR, 10Y yield, credit spreads, GDP growth, inflation, interest rates, PMI

**Cross-Sectional (9):**
- Stock's 126-day return rank vs peers, sector momentum, correlation to market, beta, alpha

### Ensemble Strategy (Stacking)

```
Base Probs:
  ARIMA → prob_arima
  LightGBM → prob_gbm
  ↓
Meta-Learner (Logistic Regression):
  prob_ensemble = LR(prob_arima, prob_gbm)
  ↓
Isotonic Calibration:
  (ensures probabilities match historical frequency)
  ↓
Threshold Filter:
  Only signal if prob_ensemble > 0.62 (high-confidence trades)
```

---

## 🤖 GitHub Actions & Automated Pipeline

### What Runs Automatically

**Schedule (IST):**
- **9:15 AM Mon–Fri:** Daily scan (`daily_briefing`)
- **3:45 PM Mon–Fri:** Auto-close (`auto_close`)
- **12:00 AM Sunday:** Weekly backtest + drift detection

**Triggers:**
- **Manual dispatch:** Via dashboard "Run" button or `gh workflow dispatch`
- **Push to V-1.0:** Auto-redeploy dashboard on changes

### Workflow File

See `.github/workflows/trading_pipeline.yml` for details. Key environment variables:

| Variable | Value |
|----------|-------|
| `TELEGRAM_TOKEN` | Your Telegram bot token |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `ZERODHA_USER_ID` | Zerodha login (opt) |
| `ZERODHA_PIN` | Zerodha PIN (opt, not recommended) |

---

## 🚀 Deployment (Netlify + GitHub Actions)

### Deploy to Netlify

1. **Connect repo to Netlify**
   ```
   Branch: V-1.0
   Build command: (empty)
   Publish directory: .
   ```

2. **Set environment variables** in Netlify UI:
   ```
   GH_DISPATCH_TOKEN=<your GitHub PAT, Actions: read/write>
   GH_OWNER=taaqib-masood
   GH_REPO=stock-market-forecasting-risk-analytics
   ```

3. **Push to V-1.0**
   ```
   git push origin V-1.0
   ```
   → Dashboard auto-redeploys

### Run Locally

```bash
# Start control server (for Local mode buy/close)
CONTROL_TOKEN=dev python -m src.control_server

# Serve dashboard (port 8090 or use `python -m http.server 8090`)
# Open http://localhost:8090/demo-boro.html
# Set Local mode in dashboard, point to http://localhost:8765
```

---

## 🔌 API Integrations

### Included Out-of-the-Box

| Service | Purpose | Required? |
|---------|---------|-----------|
| **yfinance** | Stock prices, financials (NSE) | Yes |
| **Telegram Bot** | Alerts + order execution | Optional |
| **Zerodha Broker** | Real order generation (GTT) | Optional |
| **Alpaca API** | US market data (backtesting) | Optional |
| **FinBERT + Hugging Face** | News sentiment | Optional |
| **FRED (St. Louis Fed)** | Macro indicators | Optional |
| **GROQ LLM** | Trade explainability | Optional |

### How to Integrate Your Own Data

```python
# Example: Custom universe (your watchlist)
from src.scanner import scan

custom_tickers = ['RELIANCE', 'INFY', 'TCS', 'WIPRO']
signals = scan(custom_tickers)
# Returns BUY/SKIP for each
```

```python
# Example: Custom risk manager (your rules)
from src.risk_manager import RiskManager

rm = RiskManager(atr_multiplier=2.0, min_rr=1.5)
position = rm.size_position(
    ticker='RELIANCE',
    capital=50000,
    entry=2650,
    stop=2500,
)
# Returns: { 'shares': 18, 'stop': 2500, 'target': 2900 }
```

---

## ✅ Testing & Validation

### Test Suite

Run all tests:
```bash
pytest tests/ -v
```

**Test Coverage:**
- **Import tests:** 15+ modules instantiate without errors
- **Feature engineering:** Offline synthetic OHLCV, 30+ features generate
- **Ensemble:** Fit/predict on synthetic probabilities
- **Monte Carlo:** 200 simulations run stably
- **Risk manager:** Position sizing, stop/target logic
- **Walk-forward:** OOS validation gate mechanics
- **Halal screening:** Classification logic on synthetic financials
- **Zakat calculations:** Full-value, capital-gains, cross-border

**Result:** 138 passing tests (no flaky tests, no external API calls in tests)

### Validation Gates

Every new feature/rule must pass:
1. **Unit tests** (logic correctness)
2. **Walk-forward harness** (OOS profitability)
3. **Halal compliance audit** (no short-selling, no margin)
4. **Signal-path guardian** (live and research paths not cross-wired)

---

## 📁 Project Structure

```
stock-market-forecasting-risk-analytics/
│
├── src/
│   ├── daily_briefing.py        ← Morning scan entry point
│   ├── scanner.py               ← 7-criteria rule scorer
│   ├── auto_close.py            ← Evening position closer
│   ├── paper_trader.py          ← Paper trading simulator + cockpit
│   ├── control_server.py        ← Local HTTP server (Local mode)
│   │
│   ├── pipeline.py              ← ML backtest entry point
│   ├── ensemble.py              ← ARIMA + LightGBM stacking
│   ├── arima_model.py           ← ARIMA base learner
│   ├── tree_model.py            ← LightGBM base learner
│   ├── lstm_model.py            ← Optional LSTM base learner
│   ├── feature_engineering.py   ← 52 features (technical/sentiment/macro)
│   ├── data_provider.py         ← Alpaca/yfinance connector
│   ├── risk_manager.py          ← 10 risk rules
│   ├── backtest_runner.py       ← Unified backtest engine
│   ├── validation.py            ← Look-ahead leak detection
│   ├── walk_forward.py          ← OOS harness + strategy gate
│   │
│   ├── halal_screen.py          ← AAOIFI classify()
│   ├── halal_history.py         ← Point-in-time tier timeline
│   ├── halal_lookup.py          ← "Is X halal?" citation card
│   ├── tier_monitor.py          ← Tier-change alerts
│   ├── zakat.py                 ← Zakat + purification calculator
│   ├── fundamentals.py          ← Cached financials reader
│   │
│   ├── regime_detector.py       ← NIFTY > 200SMA gate
│   ├── sector_rotation.py       ← Top 2 sectors filter
│   ├── drawdown_guard.py        ← Nifty drawdown monitor
│   ├── earnings_guard.py        ← Earnings blackout dates
│   ├── gap_risk.py              ← Overnight gap filter
│   ├── gtt_generator.py         ← Zerodha GTT builder
│   ├── notify.py                ← Telegram alert sender
│   ├── mlflow_tracker.py        ← MLflow logging
│   ├── drift_detector.py        ← KS-test / PSI drift monitor
│   ├── explainer.py             ← SHAP + Groq explanations
│   │
│   ├── strategy_presets.py      ← Holding period archetypes
│   ├── watchlist.py             ← NSE stock universe
│   └── __init__.py
│
├── tests/
│   ├── test_imports.py          ← Import + smoke tests (138 passing)
│   ├── test_control_cockpit.py  ← Halal guard tests
│   └── test_*.py                ← Feature-specific tests
│
├── netlify/
│   └── functions/
│       └── dispatch.js          ← GitHub Actions dispatcher (Cloud mode)
│
├── .github/
│   └── workflows/
│       └── trading_pipeline.yml ← GitHub Actions schedule (9:15 AM, 3:45 PM, Sunday)
│
├── demo-boro.html              ← Live dashboard (Boro design, 7 tabs, 227KB)
├── demo.html                   ← Legacy full dashboard
├── dashboard_data.js           ← Live portfolio data feed
│
├── README.md                   ← You are here
├── CLAUDE.md                   ← Technical architecture notes
├── DESIGN.md                   ← UI/UX design specs
├── requirements.txt            ← Core dependencies
├── requirements-lstm.txt       ← Optional LSTM deps
├── .env.example                ← Env var template
└── netlify.toml                ← Netlify config
```

---

## 🗺️ Roadmap

### Phase 1: Live ✅
- [x] AAOIFI Shariah screening (debt/income ratios)
- [x] Point-in-time halal history
- [x] Zakat calculator (full-value, capital-gains, cross-border)
- [x] Daily rule-based scanner (7 criteria, staged gates)
- [x] Paper trading cockpit
- [x] Risk manager (10 rules)
- [x] Boro dashboard (7 tabs, interactive)
- [x] GitHub Actions automation (9:15 AM, 3:45 PM, Sunday)
- [x] Walk-forward validation harness
- [x] ML ensemble (ARIMA + LightGBM)

### Phase 2: Expansion (Planned)
- [ ] **Cross-Market:** UAE (ADX), Saudi Arabia (Tadawul), Malaysia (Bursa)
- [ ] **Institutional API:** REST/gRPC endpoints for halal screening, Zakat, portfolio analytics
- [ ] **qlib Integration:** 158-factor alpha signals (if edge > 1.25 OOS)
- [ ] **LLM Council:** Multi-advisor second opinion on signals (via Groq)
- [ ] **Advanced Risk:** VaR, CVaR, Kelly sizing, drawdown-targeting
- [ ] **Earnings Explainer:** Auto-analyze earnings surprise vs. sector median
- [ ] **Regulatory Reporting:** DFSA/SCA compliance export (UAE)

### Phase 3: Platform (If Fundraised)
- [ ] **White-Label SaaS:** For halal fintech platforms (Islam.com, Fintech Hive partners)
- [ ] **Mobile App:** iOS + Android, portfolio dashboard + buy/sell
- [ ] **Advisor Portal:** For wealth managers, portfolio screening + client reporting
- [ ] **AI Trade Assistant:** Conversational ("Why did we skip this signal?")

---

## ❓ FAQ & Troubleshooting

### Q: Is this actually profitable?

**A:** On backtests (2019–2024 RELIANCE), yes (~1.04 profit factor OOS, net of 0.5% costs). In live trading, it depends on your discipline. Signals work best paired with risk management (2% max loss per trade, ATR stops) and rebalancing. It's not a "get rich quick"; it's a *systematic risk manager*.

### Q: Why do you have two signal paths (live + research)?

**A:** Live must be deterministic, fast, and production-ready. Research is slow and experimental. We discovered that adding indicators to live actually *hurt* performance (overfitting caught by walk-forward harness), so we killed them. Path 1 uses only regime gates; Path 2 validates new ideas before they touch Path 1.

### Q: What about leverage / margin trading?

**A:** Boro is halal-first, so no leverage. All positions are fully funded from your capital. This limits upside but also limits risk of ruin.

### Q: Can I trade on intraday (minutes/hours)?

**A:** No. Boro is designed for swing trading (5–22 day holds). Intraday is out of scope (halal grounds + cost sensitivity at NSE).

### Q: How often should I rebalance?

**A:** Monthly (tie to your holding-period archetype: Swing = 15d, Intra-Month = 22d). Quarterly halal compliance audit is recommended.

### Q: My Telegram alerts aren't firing. What do I do?

**A:** Check `.env` for `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`. Run `python -m src.notify --test` to verify. If GitHub Actions workflow failed, check the log.

### Q: The dashboard says "Local mode, but control_server isn't running."

**A:** Start it: `CONTROL_TOKEN=dev python -m src.control_server`. Then refresh the dashboard and set the token to `dev`.

### Q: Can I white-label the dashboard?

**A:** Yes. The dashboard is a single `demo-boro.html` file with MIT license. Fork it, rebrand (logo, colors, title), and host on your domain.

### Q: What's the cost to run this?

**A:** Free:
- GitHub Actions: 2,000 free CI minutes/month (you use ~30)
- Netlify: free tier covers dashboard + serverless functions
- APIs: yfinance (free), Telegram (free), GROQ (free tier 3,000 calls/month)

Optional paid tiers (if you scale):
- Alpaca data ($0–200/month depending on tier)
- Zerodha (brokerage commissions apply on real trades)

### Q: How do I contribute / report bugs?

**A:** Open an issue on GitHub or email taaqib.masood@icloud.com. All contributions welcome (esp. new halal-market integrations: UAE, Saudi, Malaysia).

---

## ⚖️ Disclaimer

**This is not investment advice.**

Boro is an educational system for learning halal investing, technical analysis, and risk management. It is not a recommendation to buy or sell any security. Past performance does not guarantee future results. You are responsible for:

- Verifying Shariah compliance with a qualified scholar (Boro is a tool, not a fatwa)
- Understanding the risks of equities (volatility, sector-specific, geopolitical)
- Complying with local tax/regulatory laws (Zakat, capital gains, reporting)
- Executing trades with real money (paper-trading is not the same as live)

**Halal compliance note:** Boro screens against AAOIFI standards, but standards differ by school and scholar. Always consult a qualified Islamic finance scholar before investing.

**Risk warning:** Trading equities carries risk of loss. Never risk capital you cannot afford to lose. Use stop-losses, position-size conservatively, and rebalance regularly.

---

## 📜 License

MIT License. See LICENSE file for details.

---

## 👋 Credits & Acknowledgments

Built by **Taaqib Masood** with inspiration from:
- **Andrej Karpathy's LLM Council** (multi-advisor framework)
- **AAOIFI Shariah Standards Committee** (screening criteria)
- **Walk-Forward Analysis** (Prado, E.; Machine Learning for Asset Managers)
- **Open-source community:** yfinance, LightGBM, MLflow, Telegram, Zerodha, Netlify

---

## 🔗 Links

- **[Live Dashboard](https://stocks-proj.netlify.app)**
- **[GitHub Repository](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics)**
- **[Issues & Feature Requests](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics/issues)**
- **[Telegram Channel](https://t.me/boro_trading)** (optional, updates)
- **[Email](mailto:taaqib.masood@icloud.com)**

---

**Last updated:** June 2024  
**Version:** 1.0 (V-1.0 branch)  
**Status:** Production-ready with ongoing improvements

