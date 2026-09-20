import numpy as np

from src.arima_model import ArimaModel


def test_arima_accepts_array_backed_training_series_and_forecasts():
    values = np.linspace(100.0, 130.0, 40)
    model = ArimaModel(max_p=2, max_q=1)

    model.fit(values)

    forecast = model.forecast()
    assert forecast.shape == (1,)
    assert np.isfinite(forecast[0])


def test_arima_rejects_empty_training_series():
    model = ArimaModel()

    try:
        model.fit(np.array([]))
    except ValueError as error:
        assert str(error) == "ARIMA requires at least one observation"
    else:
        raise AssertionError("empty ARIMA input should fail clearly")
