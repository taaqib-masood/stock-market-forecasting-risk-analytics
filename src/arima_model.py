import warnings
import numpy as np
import pandas as pd

try:
    from pmdarima import auto_arima
    _PMDARIMA = True
except ImportError:
    _PMDARIMA = False
    from statsmodels.tsa.arima.model import ARIMA


class ArimaModel:
    """
    Auto-ARIMA wrapper.
    - Uses pmdarima.auto_arima to select optimal (p,d,q) order.
    - Falls back to statsmodels ARIMA(5,1,0) if pmdarima is not installed.
    - Produces a directional signal (1 = forecast > last close, 0 = lower).
    """

    def __init__(self, seasonal: bool = False, max_p: int = 5, max_q: int = 5):
        self.seasonal = seasonal
        self.max_p = max_p
        self.max_q = max_q
        self._model = None
        self._last_close = None

    def fit(self, series: pd.Series):
        self._last_close = float(series.iloc[-1])
        if _PMDARIMA:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self._model = auto_arima(
                    series,
                    seasonal=self.seasonal,
                    max_p=self.max_p,
                    max_q=self.max_q,
                    stepwise=True,
                    suppress_warnings=True,
                    error_action="ignore",
                )
        else:
            self._model = ARIMA(series, order=(5, 1, 0)).fit()

    def forecast(self, steps: int = 1) -> np.ndarray:
        if _PMDARIMA:
            result = self._model.predict(n_periods=steps)
            return np.atleast_1d(np.array(result, dtype=float))
        result = self._model.forecast(steps=steps)
        return np.atleast_1d(np.array(result, dtype=float))

    def signal(self) -> int:
        """1 = bullish forecast, 0 = bearish."""
        next_price = self.forecast(steps=1)[0]
        return 1 if next_price > self._last_close else 0
