from statsmodels.tsa.arima.model import ARIMA

class ArimaModel:
    def __init__(self, order=(5,1,0)):
        self.order = order
        self.model = None

    def fit(self, train_series):
        self.model = ARIMA(train_series, order=self.order).fit()

    def predict(self, steps):
        return self.model.forecast(steps=steps)
