"""
Day-ahead forecasting: time split, error metrics, naive baselines (notebook 05)
and the demand model ladder L0-L6 with a monthly walk-forward test (notebook 08).

A forecast for day D+1 may only use information known on day D, so every
baseline here is built with `.shift()` on the full series before the test dates
are selected, and the models use features from src/features.py.
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


# ---------------------------------------------------------------------------
# Demand models (Stage 3, model log Step 16)
# ---------------------------------------------------------------------------
# Every model predicts y = log(demand_T / demand_D); forecast = demand_D × exp(y).
# y = 0 is persistence, so the models learn corrections to "same as yesterday".

LOCKDOWN = ("2020-03-25", "2020-06-01")   # target days not used for fitting (D or T in the lockdown)

CALENDAR = ["hol_T", "hol_D", "d_hol", "paddy_T", "d_paddy"]
RECENT = ["r_D_vs_Dm1", "r_D_vs_Dm7", "r_lastweek"]
WEATHER = ["d_cdd", "d_hdd", "rain_T", "rain_3d", "d_tmax"]
WEATHER_LEVELS = ["cdd_T", "hdd_T", "tmax_T", "tmean_T", "tmin_T"]

FEATURE_SETS = {
    "L2": RECENT + CALENDAR,
    "L3": RECENT + CALENDAR + WEATHER,
    "L4": RECENT + CALENDAR + WEATHER + WEATHER_LEVELS + ["weekday_T", "month_T", "trend"],
}
ONE_HOT = ["weekday_T", "month_T", "State"]   # categories for the linear models

# tuned on 2023 (trained on 2020-22), never on the test period; the grid is in notebook 08
LGBM_PARAMS = dict(n_estimators=800, learning_rate=0.03, num_leaves=31, min_child_samples=100,
                   subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1, random_state=0)


def training_rows(f):
    """Rows usable for fitting: drop target days whose D or T falls in the 2020 lockdown."""
    return f[~f["Date"].between(*LOCKDOWN)]


class LastWeek:
    """L0b: tomorrow = the same day last week, i.e. y = log(demand_(T−7) / demand_D)."""
    def fit(self, f):
        return self

    def predict(self, f):
        return (f["r_lastweek"] - f["r_D_vs_Dm7"]).to_numpy()


class Persistence:
    """L0: tomorrow = today (y = 0)."""
    def fit(self, f):
        return self

    def predict(self, f):
        return np.zeros(len(f))


class Profile:
    """L1: average change by state, weekday of T and month (falls back to state × weekday)."""
    def fit(self, f):
        self.fine = f.groupby(["State", "weekday_T", "month_T"])["y"].mean()
        self.coarse = f.groupby(["State", "weekday_T"])["y"].mean()
        return self

    def predict(self, f):
        fine = self.fine.reindex(pd.MultiIndex.from_frame(f[["State", "weekday_T", "month_T"]])).to_numpy()
        coarse = self.coarse.reindex(pd.MultiIndex.from_frame(f[["State", "weekday_T"]])).to_numpy()
        return np.where(np.isnan(fine), coarse, fine)


class Linear:
    """L2/L3: ridge regression on numeric features + one-hot weekday, month and state."""
    def __init__(self, features, alpha=1.0):
        self.features, self.alpha = features, alpha

    def _design(self, f):
        x = f[self.features].astype(float)
        dummies = pd.get_dummies(f[[c for c in ONE_HOT if c in f]].astype(str), dtype=float)
        return pd.concat([x, dummies], axis=1)

    def fit(self, f):
        from sklearn.linear_model import Ridge
        x = self._design(f)
        self.columns = x.columns
        self.mean, self.std = x.mean(), x.std().replace(0, 1)
        self.model = Ridge(alpha=self.alpha).fit((x - self.mean) / self.std, f["y"])
        return self

    def predict(self, f):
        x = self._design(f).reindex(columns=self.columns, fill_value=0.0)
        return self.model.predict((x - self.mean) / self.std)


class Trees:
    """L4: LightGBM on all features, state as a category. quantile=None fits the mean."""
    def __init__(self, features, params=None, quantile=None):
        self.features = features
        self.params = {**LGBM_PARAMS, **(params or {})}
        if quantile is not None:
            self.params.update(objective="quantile", alpha=quantile)

    def _x(self, f):
        x = f[self.features].copy()
        if self.states is not None:                      # pooled model: state is a feature
            x["State"] = pd.Categorical(f["State"], categories=self.states)
        return x

    def fit(self, f):
        from lightgbm import LGBMRegressor
        self.states = sorted(f["State"].unique()) if f["State"].nunique() > 1 else None
        self.model = LGBMRegressor(**self.params).fit(self._x(f), f["y"])
        return self

    def predict(self, f):
        return self.model.predict(self._x(f))


class PerState:
    """L5: one separate model per state instead of one pooled model."""
    def __init__(self, make_model):
        self.make_model = make_model

    def fit(self, f):
        self.models = {s: self.make_model().fit(g) for s, g in f.groupby("State")}
        return self

    def predict(self, f):
        out = np.empty(len(f))
        for s, idx in f.groupby("State").indices.items():
            out[idx] = self.models[s].predict(f.iloc[idx])
        return out


def demand_from_ratio(rows):
    """Forecast MW from a predicted log change ratio: today × exp(y)."""
    return rows["Base"] * np.exp(rows["Pred"])


def walk_forward(f, make_model, start=TEST_START, end=None, test_f=None, to_forecast=demand_from_ratio):
    """
    Refit each month on everything before it, then predict that month.

    test_f      : rows to predict, if different from the training rows (e.g. features built from
                  day-ahead forecast weather, while training uses actual weather: "perfect-prog")
    to_forecast : turns the predicted y into the forecast (default: demand from a change ratio)

    Returns the test rows with column Pred (predicted y) and Forecast.
    """
    keys = [c for c in ("Date", "State", "Fuel_Type") if c in f]
    f = f.sort_values(keys).reset_index(drop=True)
    test_f = f if test_f is None else test_f.sort_values(keys).reset_index(drop=True)
    end = end or test_f["Date"].max()
    out = []
    for month_start in pd.date_range(start, end, freq="MS"):
        month_end = month_start + pd.offsets.MonthEnd(0)
        train = training_rows(f[f["Date"] < month_start])
        test = test_f[test_f["Date"].between(month_start, month_end)]
        if test.empty:
            continue
        model = make_model().fit(train)
        out.append(test.assign(Pred=model.predict(test)))
    out = pd.concat(out, ignore_index=True)
    out["Forecast"] = to_forecast(out)
    return out


def national_features(f, demand):
    """
    One "National" row per day for the direct national yardstick model.

    Demand ratios come from the national total; calendar and weather features are
    averaged over states weighted by each state's demand on D (known on D), so
    e.g. hol_T = share of India's load in states on holiday tomorrow.
    """
    national = demand.sum(axis=1)
    g = f.copy()
    g["w"] = g["Base"] / g.groupby("Date")["Base"].transform("sum")
    cols = CALENDAR + WEATHER + WEATHER_LEVELS
    avg = g[cols].mul(g["w"], axis=0).groupby(g["Date"]).sum()
    first = f.groupby("Date")[["weekday_T", "month_T", "trend"]].first()
    lag = lambda k: national.shift(k).reindex(avg.index)
    out = pd.concat([avg, first], axis=1).assign(
        Base=lag(1), Actual=national.reindex(avg.index),
        r_D_vs_Dm1=np.log(lag(1) / lag(2)), r_D_vs_Dm7=np.log(lag(1) / lag(8)),
        r_lastweek=np.log(lag(7) / lag(8)))
    out["y"] = np.log(out["Actual"] / out["Base"])
    return out.rename_axis("Date").reset_index().assign(State="National").dropna()


# ---------------------------------------------------------------------------
# Availability models (Stage 4, model log Step 17): y = tomorrow's factor (0-1)
# ---------------------------------------------------------------------------

AVAIL_FEATURES = {
    "Solar": ["f_D", "f_3d", "f_7d", "shortwave_radiation_sum_D", "cloud_cover_mean_D",
              "season_sin", "season_cos", "month_T"],
    "Wind": ["f_D", "f_3d", "f_7d", "wind_speed_100m_mean_D", "season_sin", "season_cos", "month_T"],
}


class Today:
    """L0 for availability: tomorrow's factor = today's."""
    def fit(self, f):
        return self

    def predict(self, f):
        return f["f_D"].to_numpy()


class MonthProfile:
    """L1 for availability: the state's average factor in that month."""
    def fit(self, f):
        self.mean = f.groupby(["State", "month_T"])["y"].mean()
        return self

    def predict(self, f):
        return self.mean.reindex(pd.MultiIndex.from_frame(f[["State", "month_T"]])).to_numpy()


def factor_from_prediction(rows):
    """Forecast availability factor: the prediction, kept within 0-1."""
    return rows["Pred"].clip(0, 1)
