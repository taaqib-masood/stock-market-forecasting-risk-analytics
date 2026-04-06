import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler


class LSTMModel:
    """
    LSTM classifier for directional prediction (UP / DOWN).
    Architecture:
      - 2 stacked LSTM layers with dropout
      - Batch normalisation
      - Sigmoid output (binary classification)
    Lazy import of TensorFlow to avoid startup cost when not used.
    """

    def __init__(
        self,
        lookback: int = 20,
        units: int = 64,
        dropout: float = 0.3,
        epochs: int = 50,
        batch_size: int = 32,
    ):
        self.lookback = lookback
        self.units = units
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.scaler = StandardScaler()
        self.model = None

    def _build_model(self, n_features: int):
        from tensorflow.keras.models import Sequential
        from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
        from tensorflow.keras.optimizers import Adam

        model = Sequential([
            LSTM(self.units, input_shape=(self.lookback, n_features),
                 return_sequences=True),
            Dropout(self.dropout),
            BatchNormalization(),
            LSTM(self.units // 2),
            Dropout(self.dropout),
            BatchNormalization(),
            Dense(32, activation="relu"),
            Dense(1, activation="sigmoid"),
        ])
        model.compile(optimizer=Adam(1e-3), loss="binary_crossentropy",
                      metrics=["accuracy"])
        return model

    def _make_sequences(self, X: np.ndarray, y: np.ndarray = None):
        Xs, ys = [], []
        for i in range(self.lookback, len(X)):
            Xs.append(X[i - self.lookback: i])
            if y is not None:
                ys.append(y[i])
        Xs = np.array(Xs)
        return (Xs, np.array(ys)) if y is not None else Xs

    def fit(self, X: pd.DataFrame, y: pd.Series):
        from tensorflow.keras.callbacks import EarlyStopping

        X_scaled = self.scaler.fit_transform(X.values)
        y_arr = y.values
        X_seq, y_seq = self._make_sequences(X_scaled, y_arr)

        if self.model is None:
            self.model = self._build_model(X.shape[1])

        es = EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True)
        self.model.fit(
            X_seq, y_seq,
            epochs=self.epochs,
            batch_size=self.batch_size,
            validation_split=0.1,
            callbacks=[es],
            verbose=0,
        )

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        X_scaled = self.scaler.transform(X.values)
        X_seq = self._make_sequences(X_scaled)
        probs = self.model.predict(X_seq, verbose=0).flatten()
        # Pad with 0.5 (neutral) for the first `lookback` rows
        return np.concatenate([np.full(self.lookback, 0.5), probs])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X) >= 0.5).astype(int)
