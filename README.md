# stock-market-forecasting-risk-analytics
Time-series forecasting and portfolio risk analytics using ARIMA, XGBoost, and LSTM



## Overview

This project focuses on analysing historical stock market data to forecast future prices
and evaluate portfolio risk metrics. The objective is to support data-driven investment
decisions using a combination of classical time-series models and machine learning
techniques.

The project is designed from a **financial analytics perspective**, emphasising
forecast accuracy, risk assessment, and interpretability rather than speculative trading.

---

## Business Use Case

Financial institutions, analysts, and investors require reliable forecasts and risk
measures to manage portfolios effectively. This project demonstrates how historical
price data can be transformed into actionable insights such as expected returns,
volatility, and downside risk.

---

## Data Source

- Historical stock price data retrieved using the **yfinance** library
- OHLCV data (Open, High, Low, Close, Volume)
- Initial analysis performed on a single equity (extendable to portfolios)

---

## Feature Engineering

The following features were engineered:

- Daily returns
- Rolling volatility
- Simple and exponential moving averages
- Lagged price features
- Volume-based indicators

These features enable both statistical and machine learning models to capture
temporal and nonlinear patterns.

---

## Models Used

- **ARIMA / SARIMAX** – Baseline time-series forecasting
- **XGBoost / Random Forest** – Nonlinear regression and feature importance
- **LSTM** – Deep learning model for sequential dependencies

---

## Evaluation Metrics

### Forecast Accuracy
- Mean Absolute Error (MAE)
- Root Mean Squared Error (RMSE)

### Risk Metrics
- Volatility
- Maximum Drawdown
- Sharpe Ratio

---

## Key Insights

- Classical models provide strong baselines with high interpretability
- Tree-based models capture nonlinear effects in price movements
- LSTM improves performance during volatile market regimes
- Risk metrics are essential for decision-making beyond raw predictions

---

## Limitations

- Forecasts are based solely on historical data
- External macroeconomic variables are not included
- Performance may degrade under extreme market events

---

## Future Work

- Multi-asset portfolio analysis
- Sector-level risk aggregation
- Power BI dashboard for executive reporting
- Integration of macroeconomic indicators

---

## Author

**Taaqib Masood**  
B.Tech Computer Science  
Specialization: Data Analytics & Artificial Intelligence
