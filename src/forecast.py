"""
Day-ahead forecasting helpers: time split, error metrics and naive baselines.

Developed in notebooks/05_forecast_setup.ipynb. A forecast for day D+1 may only
use information known on day D, so every baseline here is built with
`.shift()` on the full series before the test dates are selected.
"""

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------

TRAIN_END = "2023-12-31"   # last training day
TEST_START = "2024-01-01"  # first test day (test runs to the end of the data, 31 Mar 2025)


# ---------------------------------------------------------------------------
# Time split
# ---------------------------------------------------------------------------

def time_split(data, train_end=TRAIN_END, test_start=TEST_START):
    """Split a date-indexed Series/DataFrame by time. Never shuffled."""
    if pd.Timestamp(test_start) <= pd.Timestamp(train_end):
        raise ValueError("test_start must be after train_end")
    return data.loc[:train_end], data.loc[test_start:]


# ---------------------------------------------------------------------------
# Error metrics
# ---------------------------------------------------------------------------

def _errors(actual, forecast):
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    if actual.shape != forecast.shape:
        raise ValueError("actual and forecast have different shapes")
    if np.isnan(actual).any() or np.isnan(forecast).any():
        raise ValueError("NaN in actual or forecast")
    return actual, actual - forecast


def mae(actual, forecast):
    """Mean absolute error, in the units of the data (MW, Rs/MWh)."""
    _, err = _errors(actual, forecast)
    return np.abs(err).mean()


def mape(actual, forecast):
    """Mean absolute percentage error, in %."""
    actual, err = _errors(actual, forecast)
    if (actual == 0).any():
        raise ValueError("MAPE undefined when actual is 0")
    return (np.abs(err) / np.abs(actual)).mean() * 100


def rmse(actual, forecast):
    """Root mean squared error: punishes big misses more than MAE."""
    _, err = _errors(actual, forecast)
    return np.sqrt((err ** 2).mean())


def skill(mae_model, mae_baseline):
    """1 - MAE_model / MAE_baseline. 0 = no better than the baseline, < 0 = worse."""
    return 1 - mae_model / mae_baseline


def score(actual, forecast, baseline_mae=None):
    """All metrics as a dict; adds skill when the baseline MAE is given."""
    out = {"MAE": mae(actual, forecast), "MAPE_%": mape(actual, forecast),
           "RMSE": rmse(actual, forecast)}
    if baseline_mae is not None:
        out["Skill"] = skill(out["MAE"], baseline_mae)
    return out


# ---------------------------------------------------------------------------
# Naive baselines (L0)
# ---------------------------------------------------------------------------

def persistence(series, lag=1):
    """Forecast for each day = the value `lag` days earlier (1 = yesterday, 7 = last week)."""
    return series.shift(lag)
