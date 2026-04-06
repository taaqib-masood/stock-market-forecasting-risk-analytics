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


def _last_thursday(year: int, month: int) -> pd.Timestamp:
    """Return the last Thursday of a given month (NSE F&O expiry day)."""
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    dt = pd.Timestamp(year, month, last_day)
    offset = (dt.dayofweek - 3) % 7  # 3 = Thursday
    return dt - pd.Timedelta(days=offset)


def _days_to_nse_expiry(date: pd.Timestamp) -> int:
    """Calendar days from `date` to the next NSE F&O expiry (last Thursday)."""
    expiry = _last_thursday(date.year, date.month)
    if expiry < date:
        # Roll to next month
        if date.month == 12:
            expiry = _last_thursday(date.year + 1, 1)
        else:
            expiry = _last_thursday(date.year, date.month + 1)
    return (expiry - date).days


# NSE holidays 2025–2026 (add more years as needed)
_NSE_HOLIDAYS = {
    pd.Timestamp("2025-01-26"),  # Republic Day
    pd.Timestamp("2025-02-26"),  # Mahashivratri
    pd.Timestamp("2025-03-14"),  # Holi
    pd.Timestamp("2025-03-31"),  # Id-Ul-Fitr (Ramzan Eid)
    pd.Timestamp("2025-04-10"),  # Shri Ram Navami
    pd.Timestamp("2025-04-14"),  # Dr. Baba Saheb Ambedkar Jayanti
    pd.Timestamp("2025-04-18"),  # Good Friday
    pd.Timestamp("2025-05-01"),  # Maharashtra Day
    pd.Timestamp("2025-08-15"),  # Independence Day
    pd.Timestamp("2025-08-27"),  # Ganesh Chaturthi
    pd.Timestamp("2025-10-02"),  # Mahatma Gandhi Jayanti / Dussehra
    pd.Timestamp("2025-10-20"),  # Diwali Laxmi Pujan
    pd.Timestamp("2025-10-21"),  # Diwali Balipratipada
    pd.Timestamp("2025-11-05"),  # Prakash Gurpurb Sri Guru Nanak Dev Ji
    pd.Timestamp("2025-12-25"),  # Christmas
    pd.Timestamp("2026-01-26"),  # Republic Day
    pd.Timestamp("2026-03-20"),  # Holi
    pd.Timestamp("2026-04-03"),  # Good Friday
    pd.Timestamp("2026-04-14"),  # Dr. Baba Saheb Ambedkar Jayanti
    pd.Timestamp("2026-08-15"),  # Independence Day
    pd.Timestamp("2026-10-02"),  # Mahatma Gandhi Jayanti
    pd.Timestamp("2026-11-14"),  # Diwali
    pd.Timestamp("2026-12-25"),  # Christmas
}


def _holiday_proximity(date: pd.Timestamp, window: int = 2) -> int:
    """Return 1 if `date` is within `window` calendar days of an NSE holiday."""
    for h in _NSE_HOLIDAYS:
        if abs((date - h).days) <= window:
            return 1
    return 0


def _fetch_market_context(start, end):
    """Fetch SPY and VIX as market regime context via the data provider."""
    try:
        from src.data_provider import load_market_context
        years = max(1, (pd.Timestamp(end) - pd.Timestamp(start)).days // 365 + 1)
        return load_market_context(years=years)
    except Exception:
        return pd.DataFrame()


def add_features(
    df: pd.DataFrame,
    fetch_context: bool = True,
    add_sentiment: bool = False,
    add_macro: bool = False,
    ticker: str = "",
) -> pd.DataFrame:
    """
    Enrich OHLCV DataFrame with technical indicators, market context, and
    a binary classification target (1 = next-day close higher, 0 = lower).

    Parameters
    ----------
    df            : DataFrame with columns [Open, High, Low, Close, Volume] and DatetimeIndex
    fetch_context : If True, fetch SPY + VIX from yfinance for market regime features
    add_sentiment : If True, fetch FinBERT news sentiment (requires ticker, adds network call)
    add_macro     : If True, fetch macro indicators from FRED/yfinance (adds network call)
    ticker        : Stock symbol required when add_sentiment=True (e.g. "RELIANCE")

    Returns
    -------
    DataFrame with all engineered features and 'target' column (~50 features).
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
    # 200-day MA and regime features
    df["sma_200"] = df["Close"].rolling(200).mean()
    df["price_vs_sma200"] = df["Close"] / df["sma_200"] - 1
    df["golden_cross"] = (df["sma_50"] > df["sma_200"]).astype(int)
    df["sma200_slope"] = (df["sma_200"] - df["sma_200"].shift(10)) / df["sma_200"].shift(10)

    # ── Momentum ─────────────────────────────────────────────────────────────
    df["rsi_14"] = _rsi(df["Close"], 14)
    df["rsi_7"] = _rsi(df["Close"], 7)
    df["rsi_21"] = _rsi(df["Close"], 21)
    df["macd"], df["macd_signal"], df["macd_hist"] = _macd(df["Close"])
    df["roc_5"] = df["Close"].pct_change(5)
    df["roc_10"] = df["Close"].pct_change(10)
    df["roc_20"] = df["Close"].pct_change(20)
    # Williams %R (14-period): -100 = oversold, 0 = overbought
    high_14 = df["High"].rolling(14).max()
    low_14 = df["Low"].rolling(14).min()
    df["williams_r"] = (high_14 - df["Close"]) / (high_14 - low_14).replace(0, np.nan) * -100

    # ── Volatility ────────────────────────────────────────────────────────────
    df["atr_14"] = _atr(df, 14)
    df["atr_pct"] = df["atr_14"] / df["Close"]
    df["volatility_20"] = df["return_1d"].rolling(20).std()
    df["volatility_10"] = df["return_1d"].rolling(10).std()
    df["volatility_5"] = df["return_1d"].rolling(5).std()
    df["bb_width"], df["bb_pct_b"] = _bollinger(df["Close"], 20)

    # ── Volume ────────────────────────────────────────────────────────────────
    df["obv"] = _obv(df)
    df["volume_sma20"] = df["Volume"].rolling(20).mean()
    df["volume_ratio"] = df["Volume"] / df["volume_sma20"]
    vol_std = df["Volume"].rolling(20).std().replace(0, np.nan)
    df["volume_zscore"] = (df["Volume"] - df["volume_sma20"]) / vol_std
    # Money Flow Index (14-period)
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    raw_money_flow = typical_price * df["Volume"]
    tp_diff = typical_price.diff()
    pos_mf = raw_money_flow.where(tp_diff > 0, 0).rolling(14).sum()
    neg_mf = raw_money_flow.where(tp_diff <= 0, 0).rolling(14).sum()
    df["mfi_14"] = 100 - (100 / (1 + pos_mf / neg_mf.replace(0, np.nan)))
    # Chaikin Money Flow (20-period)
    hl_range = (df["High"] - df["Low"]).replace(0, np.nan)
    clv = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / hl_range
    df["cmf"] = (clv * df["Volume"]).rolling(20).sum() / df["Volume"].rolling(20).sum()

    # ── Calendar features ─────────────────────────────────────────────────────
    df["day_of_week"] = df.index.dayofweek
    df["month"] = df.index.month
    df["week_of_year"] = df.index.isocalendar().week.astype(int)
    # Days to NSE F&O expiry (last Thursday of each month)
    df["days_to_expiry"] = df.index.to_series().apply(_days_to_nse_expiry)
    # Binary: 1 if within 2 trading days of an NSE market holiday
    df["holiday_proximity"] = df.index.to_series().apply(_holiday_proximity)

    # ── Nifty relative strength ───────────────────────────────────────────────
    # stock 20d return vs Nifty 50 20d return (added from market context below)
    # populated after ctx join when available

    # ── Market context (SPY + VIX) ────────────────────────────────────────────
    if fetch_context and len(df) > 0:
        start = df.index.min().strftime("%Y-%m-%d")
        end = (df.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        ctx = _fetch_market_context(start, end)
        if not ctx.empty:
            df = df.join(ctx, how="left")
            df[["spy_return", "spy_above_sma50", "vix_close", "vix_regime"]] = (
                df[["spy_return", "spy_above_sma50", "vix_close", "vix_regime"]].ffill()
            )
            # Nifty relative strength vs stock's own 20d return
            if "nifty_return_20d" in df.columns:
                df["nifty_rel_strength"] = df["return_5d"] - df["nifty_return_20d"]

    # ── Optional: News Sentiment features ────────────────────────────────────
    if add_sentiment and ticker:
        try:
            from src.news_sentiment import get_sentiment_features
            sent = get_sentiment_features(ticker)
            df["sentiment_score"] = sent["sentiment_score"]
            df["sentiment_volume"] = sent["sentiment_volume"]
            df["sentiment_momentum"] = sent["sentiment_momentum"]
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Sentiment fetch failed: %s", e)

    # ── Optional: Macro features ─────────────────────────────────────────────
    if add_macro:
        try:
            from src.macro_indicators import get_macro_features
            macro = get_macro_features()
            df["macro_vix"] = macro["vix_level"]
            df["macro_dxy"] = macro["dxy_level"]
            df["yield_curve_spread"] = macro["yield_curve_spread"]
            df["market_breadth"] = macro["market_breadth"]
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Macro fetch failed: %s", e)

    # ── Classification target: 1 = next-day close > today, 0 = lower ─────────
    df["target"] = (df["Close"].shift(-1) > df["Close"]).astype(int)

    df.dropna(inplace=True)
    return df
