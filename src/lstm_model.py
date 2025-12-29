import numpy as np
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense
from sklearn.preprocessing import MinMaxScaler

class LSTMModel:
    def __init__(self, units=50, epochs=20):
        self.units = units
        self.epochs = epochs
        self.scaler = MinMaxScaler()
        self.model = Sequential([
            LSTM(units, input_shape=(1, 1)),
            Dense(1)
        ])
        self.model.compile(optimizer='adam', loss='mse')

    def fit(self, series):
        scaled = self.scaler.fit_transform(series.reshape(-1, 1))
        X = scaled[:-1].reshape(-1, 1, 1)
        y = scaled[1:]
        self.model.fit(X, y, epochs=self.epochs, verbose=0)

    def predict(self, last_value, steps):
        preds = []
        current = self.scaler.transform([[last_value]])
        for _ in range(steps):
            pred = self.model.predict(current.reshape(1,1,1), verbose=0)
            preds.append(pred[0,0])
            current = pred
        return self.scaler.inverse_transform(
            np.array(preds).reshape(-1,1)
        ).flatten()
