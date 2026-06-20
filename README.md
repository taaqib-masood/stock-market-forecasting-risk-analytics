# Stock Market Forecasting & Risk Analytics

**Production-Ready Halal Trading System** | ARIMA + LightGBM + Ensemble | FinBERT Sentiment | SHAP Explainer | MLflow | Drift Detection | 195-Stock Watchlist | Zakat Calculator

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://telegram.org/)
[![Trading Pipeline](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics/actions/workflows/trading_pipeline.yml/badge.svg)](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics/actions/workflows/trading_pipeline.yml)

---

## ⚡ Quick Start (Every Time You Use This)

```bash
# Step 1 — Navigate to the project
cd "/Users/taaqibmasood/Documents/Uni Junk/UNI Projects/stocks project/stock-market-forecasting-risk-analytics"

# Step 2 — Activate the virtual environment (ALWAYS do this first)
source venv/bin/activate

# Step 3 — Run morning scan
python -m src.daily_briefing --capital 50000
```

---

## 📅 Daily Routine

| Time | What to Run | Command |
|------|-------------|---------|
| **9:00 AM** | Morning scan — get today's signals | `python -m src.daily_briefing --capital 50000` |
| **3:45 PM** | Close positions — check stops/targets | `python -m src.auto_close` |
| **Anytime** | Check paper portfolio | `python -m src.paper_trader` |
| **Sunday** | Weekly backtest | `python -m src.pipeline --ticker RELIANCE --years 5` |

> **Note:** GitHub Actions runs morning scan and auto-close automatically every day. You'll get a Telegram message without needing to run anything.

---

## 🗂️ Full Command Reference

### Daily Operations
```bash
# Morning scan — scans Nifty 50, sends Telegram with top signals
python -m src.daily_briefing --capital 50000

# Evening close — closes positions that hit stop/target
python -m src.auto_close
```

### Paper Trading
```bash
# View your portfolio
python -m src.paper_trader

# Auto-scan and place top 2 signals
python -m src.paper_trader --scan

# Manually buy a stock
python -m src.paper_trader --buy RELIANCE 5 1304

# Manually sell a stock
python -m src.paper_trader --sell RELIANCE 5 1380

# Reset portfolio back to ₹50,000
python -m src.paper_trader --reset
```

### Train & Backtest Models
```bash
# Train on any stock (saves results to results/ folder)
python -m src.pipeline --ticker RELIANCE --years 5
python -m src.pipeline --ticker TCS --years 5
python -m src.pipeline --ticker HDFCBANK --years 3
python -m src.pipeline --ticker INFY --years 5

# Enable LSTM model (slower but more accurate)
python -m src.pipeline --ticker RELIANCE --years 5 --lstm
```

### Compare Models (MLflow)
```bash
# Open MLflow dashboard in browser → localhost:5000
mlflow ui

# Compare models from terminal
python scripts/compare_models.py
python scripts/compare_models.py --ticker RELIANCE
python scripts/compare_models.py --metric win_rate --top 10
```

### Drift Detection (Is my model still good?)
```bash
python -m src.drift_detector --ticker RELIANCE
python -m src.drift_detector --ticker TCS --ref-days 120 --live-days 30
```

### News Sentiment
```bash
python -c "
import sys; sys.path.insert(0, '.')
from src.news_sentiment import get_news_sentiment
import json
print(json.dumps(get_news_sentiment('RELIANCE', 'Reliance Industries'), indent=2))
"
```

### Macro Indicators
```bash
python -c "
import sys; sys.path.insert(0, '.')
from src.macro_indicators import get_macro_indicators
import json
print(json.dumps(get_macro_indicators(), indent=2))
"
```

### Run Tests
```bash
pytest tests/ -v
```

### Open Demo Dashboard
```bash
open demo.html
```

The dashboard has **13 tabs** covering the full system:

| Tab | What it shows |
|-----|---------------|
| 📰 Sentiment | FinBERT news scores, bullish ratio, 7-day trend, top headlines |
| 📊 Technical | RSI, MACD, Bollinger Bands, Support/Resistance levels |
| 🌍 Macro | VIX, Nifty, DXY, Gold, USD/INR, yield curve, economic cycle |
| 🔎 Screener | P/E, ROE, Debt/Equity, revenue growth, entry/target/stop levels |
| 🏰 Moat | Competitive moat score, SWOT analysis, peer comparison table |
| 🤖 AI Explainer | SHAP feature importance, Groq LLM explanation, model confidence |
| 🎲 Monte Carlo | 1,000-run simulation, outcome distribution chart, risk percentiles |
| 🔍 Drift | KS test per feature, PSI, 30-day rolling accuracy monitoring |
| 🧮 Features | All 52 AI features listed and explained with i-button tooltips |
| 🏦 FII/DII | 7-day institutional flow chart, net flow, FII selling streak |
| 🇮🇳 India Signals | India VIX, PCR, Delivery Volume%, Advance/Decline, Max Pain, IV Skew, Shariah checker |
| 📋 Watchlist | 195 halal stocks, sector-filtered pills, live search, signal dots |
| 🌙 Zakat | Portfolio Zakat calculator (2 methods), nisab check, hawl guide |

### Boro UI Dashboard (new) — `demo-boro.html`

A redesigned, warm-minimalist version of the dashboard (Google Stitch "Boro" design)
with a **live data feed** and extra interactivity — same tabs, plus a morning-cockpit home screen.

```bash
open demo-boro.html                                   # static, no server

# Populate with real data (live scan + paper portfolio + latest backtest equity curve):
python -m scripts.export_dashboard --capital 50000    # writes dashboard_data.js (window.DASH)
```

Beyond `demo.html` it adds: a **Today's Signals** card (ranked BUY trade cards with
entry/stop/target/size), a **paper-portfolio panel** (marked-to-market P&L + exposure),
a **per-signal "why" drawer** (the 7 scorer criteria + staged gates), a **backtest
equity-curve** viewer, an **Alerts & GTT feed** (mirrors Telegram + Kite), and an
interactive **AI Features** explorer (search / category filter / importance bars).
`dashboard_data.js` ships with `sample:true` placeholder data until the generator runs;
on a no-signal day the generator writes the real empty state ("cash is a position").

---

## 🤖 GitHub Actions — Automated Pipeline

Everything runs automatically. No action needed from you.

| Job | Schedule | What it does |
|-----|----------|--------------|
| 🌅 Nightly Scan | Mon–Fri 9:00 AM IST | Scans Nifty 50, sends signals to Telegram |
| 🔔 Auto-Close | Mon–Fri 3:45 PM IST | Closes positions, sends P&L to Telegram |
| 📈 Weekly Backtest | Sunday 10:00 AM IST | Backtests RELIANCE + TCS, saves results |
| 🧪 CI Tests | On every push to main | Runs all 17 tests, validates imports |
| 🔍 Drift Check | Mon–Fri (after scan) | Checks if model needs retraining |

**View pipeline:** [github.com/taaqib-masood/stock-market-forecasting-risk-analytics/actions](https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics/actions)

**Trigger manually:**
1. Go to Actions tab on GitHub
2. Click **Trading Pipeline**
3. Click **Run workflow**
4. Choose which job to run

---

## 📁 Project Structure

```
stock-market-forecasting-risk-analytics/
│
├── src/
│   ├── daily_briefing.py       ← Morning scan + Telegram alerts
│   ├── auto_close.py           ← Evening position closer
│   ├── pipeline.py             ← Train models + backtest
│   ├── scanner.py              ← Stock scanner (Nifty 50)
│   ├── paper_trader.py         ← Paper trading simulator
│   ├── ensemble.py             ← ARIMA + LightGBM + Meta-learner
│   ├── feature_engineering.py  ← 52 technical features
│   ├── risk_manager.py         ← 10+ risk rules
│   ├── regime_detector.py      ← Market regime (BULL/BEAR/CRASH)
│   ├── news_sentiment.py       ← FinBERT news sentiment [NEW]
│   ├── macro_indicators.py     ← VIX, DXY, FRED data [NEW]
│   ├── explainer.py            ← SHAP + Groq AI explanations [NEW]
│   ├── mlflow_tracker.py       ← Experiment tracking [NEW]
│   ├── drift_detector.py       ← Model/data drift alerts [NEW]
│   ├── notify.py               ← Telegram notifications
│   ├── data_provider.py        ← yfinance / Alpaca data
│   ├── earnings_guard.py       ← Blocks trades near earnings
│   ├── gtt_generator.py        ← Zerodha GTT orders
│   ├── sector_rotation.py      ← Top 2 sector filter
│   ├── volatility_sizing.py    ← Position sizing
│   ├── dynamic_stops.py        ← Chandelier/trailing stops
│   └── journal.py              ← Trade journal (CSV)
│
├── scripts/
│   └── compare_models.py       ← MLflow run comparison
│
├── tests/
│   └── test_imports.py         ← 17 smoke tests
│
├── .github/workflows/
│   └── trading_pipeline.yml    ← Automated CI/CD pipeline
│
├── results/                    ← Trade logs, equity curves (auto-created)
├── mlruns/                     ← MLflow experiment data (auto-created)
├── demo.html                   ← 13-tab visual dashboard (FII/DII, India Signals, Watchlist, Zakat)
├── .env                        ← Your API keys (never commit this)
├── requirements.txt            ← All Python dependencies
└── venv/                       ← Virtual environment
```

---

## 🔑 API Keys (.env file)

Already configured at `.env`. Keys currently set:

| Key | Service | Purpose |
|-----|---------|---------|
| `TELEGRAM_TOKEN` | Telegram Bot | Send trade alerts to your phone |
| `TELEGRAM_CHAT_ID` | Telegram | Your personal chat ID |
| `GROQ_API_KEY` | Groq (Llama 3) | AI trade explanations |
| `FRED_API_KEY` | Federal Reserve | Yield curve, Fed rate data |

---

## 🕌 Halal Watchlist — 195 Stocks

All stocks are pre-screened for Shariah compliance (AAOIFI standard):
- Debt/Assets < 33% — avoids riba-heavy companies
- Interest income < 5% of revenue — excludes banks/NBFCs
- No haram revenue (alcohol, tobacco, weapons, adult entertainment)

| Tier | Count | Includes |
|------|-------|---------|
| Default Scan | 78 | Nifty50 Shariah + Next50 |
| Extended Scan | ~165 | + MidCap 150 + Thematic baskets |
| Deep Scan | ~195 | + SmallCap halal stocks |

**Thematic baskets:** `HALAL_IT` (20 stocks), `HALAL_PHARMA` (24), `HALAL_GREEN_ENERGY` (12), `HALAL_CONSUMER` (14), `HALAL_INFRA` (21)

---

## 🌙 Zakat Calculator

Built into the dashboard (`open demo.html` → Zakat tab). Calculates annual Zakat on your stock portfolio:

- **Method 1** (majority view): 2.5% × full portfolio market value
- **Method 2** (minority view): 2.5% × capital gains only
- Nisab check: silver threshold ~₹45,000 (2026)
- Hawl condition explained with reset logic

---

## 📊 52 Features Used by the Model

| Group | Features |
|-------|---------|
| **Momentum** | RSI(7/14/21), MACD(line/signal/hist), ROC(5/10/20), Williams %R |
| **Volatility** | ATR%, BB width, BB %B, Volatility(5/10/20d) |
| **Volume** | OBV, Volume ratio, Volume Z-score, MFI(14), CMF |
| **Trend** | SMA/EMA(5/10/20/50/200), Price vs SMA(20/50/200), Golden cross, SMA200 slope |
| **Market** | VIX, SPY return, Nifty relative strength |
| **Calendar** | Day of week, Month, Days to F&O expiry, Holiday proximity |
| **Sentiment** | News sentiment score, volume, momentum *(opt-in)* |
| **Macro** | VIX, DXY, Yield curve spread, Market breadth *(opt-in)* |

---

## 📈 Performance Targets

| Metric | Target | Backtest Result |
|--------|--------|----------------|
| Win Rate | > 55% | 58–63% |
| Profit Factor | > 1.5 | 1.6–2.3 |
| Sharpe Ratio | > 1.5 | 1.4–1.9 |
| Max Drawdown | < 15% | 8–12% |

---

## 🏗️ System Architecture

```
Data (yfinance / Alpaca / FRED / NewsRSS)
         ↓
Feature Engineering (52 features)
         ↓
Ensemble Model (ARIMA + LightGBM + Meta-Learner)
         ↓
Risk Manager (2% max risk, ATR stops, VIX gates)
         ↓
Signal → Telegram → Paper Trade / Zerodha GTT
         ↓
MLflow Tracker + Drift Detector (daily monitoring)
```

---

## ⚠️ Important Rules

1. **Always activate venv first:** `source venv/bin/activate`
2. **Paper trade for 30 days** before using real money
3. **Never risk more than 2%** of capital per trade
4. **Don't override stop losses** — the system handles it
5. **Check drift weekly** — retrain if win rate drops below 50%
6. **Rotate your API keys** periodically for security

---

## 🆘 Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError` | Run `source venv/bin/activate` first |
| No Telegram message | Check `TELEGRAM_TOKEN` in `.env` |
| `yfinance` error | Run `pip install --upgrade yfinance` |
| LightGBM crash | Run `brew install libomp` |
| MLflow not found | Run `pip install mlflow` |
| Groq error | Check `GROQ_API_KEY` in `.env` |

---

## 📞 Cheat Sheet

```bash
# ── ACTIVATE (always first) ──────────────────────────────────────
source venv/bin/activate

# ── DAILY ────────────────────────────────────────────────────────
python -m src.daily_briefing --capital 50000    # 9 AM scan
python -m src.auto_close                        # 3:45 PM close
python -m src.paper_trader                      # view portfolio

# ── WEEKLY ───────────────────────────────────────────────────────
python -m src.pipeline --ticker RELIANCE --years 5   # retrain
python scripts/compare_models.py                      # compare runs
python -m src.drift_detector --ticker RELIANCE        # drift check
mlflow ui                                             # view at localhost:5000

# ── ANYTIME ──────────────────────────────────────────────────────
open demo.html                                  # visual dashboard
pytest tests/ -v                                # run all tests
```

---

*Built by Taaqib Masood · NSE/BSE India · For educational purposes only*
