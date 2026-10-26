"""
Features for day-ahead demand forecasting (Part 2, Stage 3).

One row per (state, target day T). The forecast is made on day D = T − 1, so every
feature uses only what is known on D: demand up to D, the calendar (known in
advance), and weather for T under one of two assumptions:
    "perfect"     — T's actual weather (an upper bound: a perfect weather forecast)
    "persistence" — D's weather stands in for T's (a lower bound: no weather forecast)

The target is the log of the change ratio, log(demand_T / demand_D); the forecast
is demand_D × exp(prediction). A prediction of 0 is persistence. Developed in
notebooks/08_demand_forecast.ipynb (model log Step 16).
"""

import numpy as np
import pandas as pd

from dispatch import RAW

# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------

CDD_BASE_C = 24.0   # cooling degree days: how far the daily mean is above 24 °C
HDD_BASE_C = 18.0   # heating degree days: how far it is below 18 °C
PADDY_END = (9, 30) # paddy-season flag runs from the start date to 30 September
WEATHER_CASES = ("perfect", "persistence")   # "day-ahead" also works when forecast weather is passed


# ---------------------------------------------------------------------------
# Calendar tables
# ---------------------------------------------------------------------------

def load_holidays():
    return pd.read_csv(RAW / "holidays.csv", parse_dates=["Date"])


def load_paddy():
    return pd.read_csv(RAW / "paddy_dates.csv", parse_dates=["First_allowed", "Main_start"])


def holiday_flags(dates, states, holidays):
    """Date × state table: 1 if the day is a national holiday or a holiday in that state."""
    flags = pd.DataFrame(0, index=pd.DatetimeIndex(dates), columns=list(states))
    for row in holidays.itertuples():
        if row.Date not in flags.index:
            continue
        targets = flags.columns if row.States == "all" else row.States.split(";")
        unknown = set(targets) - set(flags.columns)
        if unknown:
            raise ValueError(f"Unknown states in holidays.csv: {unknown}")
        flags.loc[row.Date, list(targets)] = 1
    return flags


def paddy_flags(dates, states, paddy):
    """Date × state table: 1 from each year's main transplanting start to 30 Sep (Punjab, Haryana)."""
    flags = pd.DataFrame(0, index=pd.DatetimeIndex(dates), columns=list(states))
    for row in paddy.itertuples():
        end = pd.Timestamp(row.Year, *PADDY_END)
        flags.loc[row.Main_start:end, row.State] = 1
    return flags


# ---------------------------------------------------------------------------
# Feature table
# ---------------------------------------------------------------------------

def degree_days(tmean):
    return (tmean - CDD_BASE_C).clip(lower=0), (HDD_BASE_C - tmean).clip(lower=0)


def build_features(demand, state_weather, holidays, paddy, weather="perfect", forecast_weather=None):
    """
    Long feature table, one row per (state, target day T).

    demand        : wide table, date × state (MW)
    state_weather : weather_state_daily.csv; the "demand" purpose rows are used
    weather       : "perfect" or "persistence" (see module docstring), or "day-ahead": T's weather
                    from `forecast_weather` (forecast_weather_state_daily.csv, issued on D)

    Columns: State, Date (= T), Base (demand on D), Actual (demand on T), y (log ratio)
    and the features. Rows without enough history (first week) are dropped.
    """
    if weather not in WEATHER_CASES + ("day-ahead",):
        raise ValueError(f"weather must be one of {WEATHER_CASES + ('day-ahead',)}")
    if (weather == "day-ahead") != (forecast_weather is not None):
        raise ValueError("forecast_weather is needed for, and only for, weather='day-ahead'")
    dates = demand.index
    states = list(demand.columns)

    w = state_weather[state_weather.Purpose == "demand"].drop(columns="Purpose").pivot(index="Date", columns="State")
    w = w.reindex(pd.date_range(dates.min() - pd.Timedelta(days=7), dates.max()))
    hol = holiday_flags(dates, states, holidays)
    pad = paddy_flags(dates, states, paddy)

    def lag(table, k):
        """Value k days before the target day (k=1 is day D)."""
        return table.shift(k)

    if forecast_weather is not None:
        fw = forecast_weather[forecast_weather.Purpose == "demand"].drop(columns="Purpose").pivot(
            index="Date", columns="State").reindex(w.index)

    def weather_on_T(var):
        # perfect: T's own weather; persistence: D's weather stands in for T's; day-ahead: the forecast for T
        if weather == "day-ahead":
            return fw[var].reindex(columns=states)
        table = w[var].reindex(columns=states)
        return table if weather == "perfect" else table.shift(1)

    tmean_T, tmean_D = weather_on_T("temperature_2m_mean"), w["temperature_2m_mean"].reindex(columns=states).shift(1)
    cdd_T, hdd_T = degree_days(tmean_T)
    cdd_D, hdd_D = degree_days(tmean_D)
    rain = w["precipitation_sum"].reindex(columns=states)

    cols = {
        "Base": lag(demand, 1),                                  # demand on D
        "Actual": demand,                                        # demand on T (the answer)
        # recent demand ratios, all known on D
        "r_D_vs_Dm1": np.log(lag(demand, 1) / lag(demand, 2)),   # today vs yesterday
        "r_D_vs_Dm7": np.log(lag(demand, 1) / lag(demand, 8)),   # today vs a week ago
        "r_lastweek": np.log(lag(demand, 7) / lag(demand, 8)),   # same step last week (T−7 vs D−7)
        # calendar (known in advance)
        "hol_T": hol, "hol_D": hol.shift(1),
        "paddy_T": pad, "paddy_D": pad.shift(1),
        # weather
        "d_cdd": cdd_T - cdd_D, "d_hdd": hdd_T - hdd_D,
        "cdd_T": cdd_T, "hdd_T": hdd_T,
        "rain_T": weather_on_T("precipitation_sum"),
        "rain_3d": rain.shift(1).rolling(3).sum(),               # D, D−1, D−2
        "tmax_T": weather_on_T("temperature_2m_max"),
        "tmean_T": tmean_T,
        "tmin_T": weather_on_T("temperature_2m_min"),
        "d_tmax": weather_on_T("temperature_2m_max") - w["temperature_2m_max"].reindex(columns=states).shift(1),
    }
    long = []
    for name, table in cols.items():
        long.append(table.reindex(dates).stack(future_stack=True).rename(name))
    f = pd.concat(long, axis=1).rename_axis(["Date", "State"]).reset_index()

    f["y"] = np.log(f["Actual"] / f["Base"])
    f["weekday_T"] = f["Date"].dt.day_of_week          # 0 = Monday
    f["month_T"] = f["Date"].dt.month
    f["d_hol"] = f["hol_T"] - f["hol_D"]
    f["d_paddy"] = f["paddy_T"] - f["paddy_D"]
    f["trend"] = (f["Date"] - pd.Timestamp("2020-01-01")).dt.days / 365.25
    f = f.dropna(subset=["Base", "r_D_vs_Dm7", "r_lastweek", "rain_3d"] +
                    (["tmean_T", "rain_T", "tmax_T"] if weather == "day-ahead" else [])).reset_index(drop=True)
    return f[["State", "Date"] + [c for c in f.columns if c not in ("State", "Date")]]


# ---------------------------------------------------------------------------
# Availability features (Stage 4: solar and wind)
# ---------------------------------------------------------------------------

def build_availability_features(avail, state_weather, fuel):
    """
    One row per (state, target day T) for one fuel ("Solar" or "Wind"), forecast on D = T − 1.

    Target y = tomorrow's availability factor (0-1). Features use only what is known on D:
    today's factor, its 3- and 7-day averages, the season of T, and today's weather at the
    fuel's points (solar: radiation, cloud; wind: 100 m wind speed).
    """
    purpose = fuel.lower()
    a = avail[avail.Fuel_Type == fuel].pivot(index="Date", columns="State", values="Factor")
    w = state_weather[state_weather.Purpose == purpose].drop(columns="Purpose").pivot(
        index="Date", columns="State").reindex(a.index)
    weather_vars = (["shortwave_radiation_sum", "cloud_cover_mean"] if fuel == "Solar"
                    else ["wind_speed_100m_mean"])
    cols = {
        "Base": a.shift(1), "Actual": a,
        "f_D": a.shift(1), "f_3d": a.shift(1).rolling(3).mean(), "f_7d": a.shift(1).rolling(7).mean(),
        **{f"{v}_D": w[v].reindex(columns=a.columns).shift(1) for v in weather_vars},
    }
    f = pd.concat([t.stack(future_stack=True).rename(n) for n, t in cols.items()], axis=1)
    f = f.rename_axis(["Date", "State"]).reset_index().dropna().reset_index(drop=True)
    f["y"] = f["Actual"]
    f["month_T"] = f["Date"].dt.month
    doy = f["Date"].dt.day_of_year
    f["season_sin"], f["season_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    f["weekday_T"] = f["Date"].dt.day_of_week          # for the Profile model's fallback; no real effect
    f["Fuel_Type"] = fuel
    return f
