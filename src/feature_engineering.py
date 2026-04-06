import pandas as pd
import numpy as np


def _rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df, period=14):
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _bollinger(series, period=20):
    sma = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    width = (upper - lower) / sma
    pct_b = (series - lower) / (upper - lower)
    return width, pct_b


def _macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _obv(df):
    direction = np.sign(df["Close"].diff()).fillna(0)
    return (direction * df["Volume"]).cumsum()


def _fetch_market_context(start, end):
    """Fetch SPY and VIX as market regime context via the data provider."""
    try:
        from src.data_provider import load_market_context
        years = max(1, (pd.Timestamp(end) - pd.Timestamp(start)).days // 365 + 1)
        return load_market_context(years=years)
    except Exception:
        return pd.DataFrame()


def add_features(df: pd.DataFrame, fetch_context: bool = True) -> pd.DataFrame:
    """
    Enrich OHLCV DataFrame with technical indicators, market context, and
    a binary classification target (1 = next-day close higher, 0 = lower).

    Parameters
    ----------
    df            : DataFrame with columns [Open, High, Low, Close, Volume] and DatetimeIndex
    fetch_context : If True, fetch SPY + VIX from yfinance to add market regime features

    Returns
    -------
    DataFrame with all engineered features and 'target' column.
    """
    df = df.copy()
    df.index = pd.to_datetime(df.index)

    # ── Price-based features ─────────────────────────────────────────────────
    df["return_1d"] = df["Close"].pct_change()
    df["return_3d"] = df["Close"].pct_change(3)
    df["return_5d"] = df["Close"].pct_change(5)

    # Lag features
    for lag in [1, 2, 3, 5]:
        df[f"lag_{lag}"] = df["Close"].shift(lag)
        df[f"return_lag_{lag}"] = df["return_1d"].shift(lag)

    # ── Moving averages & trend ───────────────────────────────────────────────
    for w in [5, 10, 20, 50]:
        df[f"sma_{w}"] = df["Close"].rolling(w).mean()
        df[f"ema_{w}"] = df["Close"].ewm(span=w, adjust=False).mean()

    df["price_vs_sma20"] = df["Close"] / df["sma_20"] - 1
    df["price_vs_sma50"] = df["Close"] / df["sma_50"] - 1
    df["sma5_vs_sma20"] = df["sma_5"] / df["sma_20"] - 1

    # ── Momentum ─────────────────────────────────────────────────────────────
    df["rsi_14"] = _rsi(df["Close"], 14)
    df["rsi_7"] = _rsi(df["Close"], 7)
    df["macd"], df["macd_signal"], df["macd_hist"] = _macd(df["Close"])
    df["roc_5"] = df["Close"].pct_change(5)
    df["roc_10"] = df["Close"].pct_change(10)

    # ── Volatility ────────────────────────────────────────────────────────────
    df["atr_14"] = _atr(df, 14)
    df["atr_pct"] = df["atr_14"] / df["Close"]
    df["volatility_20"] = df["return_1d"].rolling(20).std()
    df["volatility_5"] = df["return_1d"].rolling(5).std()
    df["bb_width"], df["bb_pct_b"] = _bollinger(df["Close"], 20)

    # ── Volume ────────────────────────────────────────────────────────────────
    df["obv"] = _obv(df)
    df["volume_sma20"] = df["Volume"].rolling(20).mean()
    df["volume_ratio"] = df["Volume"] / df["volume_sma20"]

    # ── Calendar features ─────────────────────────────────────────────────────
    df["day_of_week"] = df.index.dayofweek
    df["month"] = df.index.month
    df["week_of_year"] = df.index.isocalendar().week.astype(int)

    # ── Market context (SPY + VIX) ────────────────────────────────────────────
    if fetch_context and len(df) > 0:
        start = df.index.min().strftime("%Y-%m-%d")
        end = (df.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        ctx = _fetch_market_context(start, end)
        if not ctx.empty:
            df = df.join(ctx, how="left")
            df[["spy_return", "spy_above_sma50", "vix_close", "vix_regime"]] = (
                df[["spy_return", "spy_above_sma50", "vix_close", "vix_regime"]].fillna(method="ffill")
            )

    # ── Classification target: 1 = next-day close > today, 0 = lower ─────────
    df["target"] = (df["Close"].shift(-1) > df["Close"]).astype(int)

    df.dropna(inplace=True)
    return df
