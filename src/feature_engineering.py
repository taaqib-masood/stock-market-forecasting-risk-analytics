import pandas as pd
import numpy as np

def add_features(df):
    df = df.copy()

    # Returns
    df['return'] = df['Close'].pct_change()

    # Rolling volatility
    df['volatility_20'] = df['return'].rolling(window=20).std()

    # Moving averages
    df['sma_20'] = df['Close'].rolling(window=20).mean()
    df['ema_20'] = df['Close'].ewm(span=20, adjust=False).mean()

    # Lag features
    df['lag_1'] = df['Close'].shift(1)
    df['lag_2'] = df['Close'].shift(2)
    df['lag_3'] = df['Close'].shift(3)

    df.dropna(inplace=True)
    return df

