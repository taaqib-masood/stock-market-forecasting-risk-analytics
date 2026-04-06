# Stock Market Forecasting & Risk Analytics

**Production-Ready Trading System** | ARIMA + XGBoost + LSTM Ensemble | Real-time Web Dashboard | Automated Risk Management

[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![TradingView](https://img.shields.io/badge/TradingView-Webhook-orange.svg)](https://www.tradingview.com/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://telegram.org/)

---

## 📊 Overview

A **complete, production-ready trading system** that combines classical time-series models, machine learning, and deep learning to generate high-conviction trade signals with institutional-grade risk management.

**What makes this different:**
- ✅ **Live data** – No CSV files, real-time from Alpaca/NSE
- ✅ **Ensemble confidence scores** – 3 models voting before any signal
- ✅ **Hard risk rules** – 2% max risk, ATR stops, VIX gates, daily limits
- ✅ **Earnings guard** – Automatically blocks trades during earnings/board meetings
- ✅ **Telegram alerts** – Real-time signals to your phone
- ✅ **Web dashboard** – Monitor portfolio from any device
- ✅ **Auto backtesting** – Validates every signal before recommending

---

## 🏗️ System Architecture
┌─────────────────────────────────────────────────────────────────┐
│ DATA LAYER │
│ Alpaca API → Real-time prices | NSE API → Corporate actions │
└────────────────────────────┬────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────────┐
│ FEATURE ENGINEERING │
│ 25+ features: RSI, MACD, ATR, Bollinger Bands, VIX, Calendar │
└────────────────────────────┬────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────────┐
│ MODEL ENSEMBLE │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│ │ ARIMA │ │ XGBoost │ │ LSTM │ │ Meta-Learner │ │
│ │ (auto) │ │ (tuned) │ │ (2-layer)│ │ (Logistic) │ │
│ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘ │
│ └─────────────┴─────────────┴────────────────┘ │
│ ↓ │
│ Confidence Score (0-100%) │
└────────────────────────────┬────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────────┐
│ RISK MANAGEMENT │
│ • Position sizing (Kelly/Fixed %) │
│ • ATR-based stop loss (dynamic) │
│ • VIX gates (halt at >35, half at >25) │
│ • Correlation filter (>0.7 = skip) │
│ • Daily trade limit (max 3) │
│ • Earnings blackout (5 days) │
│ • Consecutive loss halt │
└────────────────────────────┬────────────────────────────────────┘
↓
┌─────────────────────────────────────────────────────────────────┐
│ EXECUTION │
│ • GTT orders for Zerodha (Indian market) │
│ • Webhook → Alpaca (US market) │
│ • Telegram alerts → Manual execution │
│ • Auto close at 3:45 PM │
└─────────────────────────────────────────────────────────────────┘

text

---


---

## 🚀 Quick Start

### Installation

# Clone repository
git clone https://github.com/taaqib-masood/stock-market-forecasting-risk-analytics.git
cd stock-market-forecasting-risk-analytics

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

###

# Morning scan (also runs automatically at 9 AM)
python -m src.daily_briefing --capital 50000

# Generate GTT orders for Zerodha
python -m src.gtt_generator --symbol RELIANCE --price 1285 --capital 50000

# Check stops/targets (runs at 3:45 PM)
python -m src.auto_close

# View paper portfolio
python -m src.paper_trader

# Launch web dashboard
python -m src.dashboard --port 5000
