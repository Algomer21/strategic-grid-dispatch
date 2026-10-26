"""
Weather -> daily availability factors for solar, wind and hydro (Part 2, Stage 2).

Developed in notebooks/07_weather_availability.ipynb. Each fuel has a simple
physical rule that gives a daily *index* (its shape); the index is then scaled so
that each state's 2020-2024 average equals the Part 1 constant factor (its level).
So the yearly renewable supply of every state is the same as in Part 1 and only
the day-to-day timing comes from the weather (model log Step 15).
"""

import numpy as np
import pandas as pd

from dispatch import AVAILABILITY

# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------

WEATHER_FUELS = ["Solar", "Wind", "Large Hydro", "Small Hydro"]
MATCH_START, MATCH_END = "2020-01-01", "2024-12-31"   # full years; the level is matched here
CAP = 1.0                                             # a state can't use more than its capacity

# Solar: output ∝ radiation × (1 − loss per °C × (panel temp − 25 °C))
PANEL_LOSS_PER_C = 0.004    # crystalline silicon, ~0.4 % per °C
PANEL_REF_C = 25.0
PANEL_RISE_C = 25.0         # panel runs this much above air temperature at 800 W/m² (rule of thumb)
PANEL_RISE_AT_WM2 = 800.0
DAYLIGHT_HOURS = 10.0       # daily radiation is spread over ~10 sunlit hours

# Wind: generic modern turbine at 100 m
CUT_IN_MS = 3.0             # below: no output
RATED_MS = 12.0             # from here: full output
CUT_OUT_MS = 25.0           # from here: storm shutdown

# Hydro: leaky buckets of water (exponentially weighted mean of daily inflow)
HALF_LIFE_DAYS = {"Large Hydro": 60, "Small Hydro": 10}   # big reservoirs vs run-of-river
SPIN_UP_DAYS = 365          # the bucket is started with a year of data, so 1 Dec 2019 isn't "empty"

# Himalayan snowmelt (degree-day): melt ∝ max(daily mean temp at the dam − threshold, 0)
HIMALAYAN_STATES = ["HP", "Uttarakhand", "J&K(UT) & Ladakh(UT)", "Sikkim", "Arunachal Pradesh"]
MELT_THRESHOLD_C = 15.0     # snowfields are ~2-3 km above the dams, ~15-20 °C colder
MELT_SHARE = 0.5            # share of yearly water from snow and glacier melt (Sutlej estimate)


# ---------------------------------------------------------------------------
# Physical rules (each gives an index; only its shape matters)
# ---------------------------------------------------------------------------

def solar_index(radiation_mj, tmax_c):
    """Daily solar output index: radiation (MJ/m²) × panel heat loss on hot days."""
    irradiance = np.asarray(radiation_mj) * 1e6 / (DAYLIGHT_HOURS * 3600)   # average W/m² while sunny
    panel_c = np.asarray(tmax_c) + PANEL_RISE_C * irradiance / PANEL_RISE_AT_WM2
    return np.asarray(radiation_mj) * (1 - PANEL_LOSS_PER_C * (panel_c - PANEL_REF_C))


def wind_power_curve(speed_ms):
    """Share of rated output (0-1) at a wind speed in m/s: 0, cubic rise, 1, then 0 above cut-out."""
    v = np.asarray(speed_ms, dtype=float)
    rising = (v ** 3 - CUT_IN_MS ** 3) / (RATED_MS ** 3 - CUT_IN_MS ** 3)
    return np.select([v < CUT_IN_MS, v < RATED_MS, v < CUT_OUT_MS], [0.0, rising, 1.0], default=0.0)


def daily_wind_output(hourly, points):
    """
    Hourly wind (km/h) -> daily wind output index per state.

    The power curve is applied to every hour, then averaged over the day, then
    averaged over the state's wind points. (Applying it to a daily mean speed would
    understate output: the curve is not a straight line.)
    """
    h = hourly.merge(points[["Point_ID", "State"]], on="Point_ID")
    h["Output"] = wind_power_curve(h["wind_speed_100m"] / 3.6)
    h["Date"] = h["Time"].dt.normalize()
    per_point = h.groupby(["State", "Point_ID", "Date"], as_index=False)["Output"].mean()
    return per_point.groupby(["Date", "State"])["Output"].mean()


def leaky_bucket(inflow, half_life_days, spin_up_days=SPIN_UP_DAYS):
    """
    Water in a bucket that is topped up by `inflow` every day and loses a fixed share:
    bucket_t = (1 − a) × bucket_(t−1) + a × inflow_t, with half the water gone after
    `half_life_days`. The first `spin_up_days` of inflow are run once beforehand so
    the bucket doesn't start empty.
    """
    s = pd.Series(inflow, dtype=float)
    warm = pd.concat([s.iloc[:spin_up_days], s], ignore_index=True)
    out = warm.ewm(halflife=half_life_days, adjust=False).mean().iloc[spin_up_days:]
    return pd.Series(out.to_numpy(), index=s.index)


def melt_scale(tmean_c, rain_mm, threshold_c=MELT_THRESHOLD_C, share=MELT_SHARE,
               match=(MATCH_START, MATCH_END)):
    """mm of melt per degree day, so melt is `share` of all water (rain + melt) over `match`."""
    degree_days = (pd.Series(tmean_c, dtype=float) - threshold_c).clip(lower=0)
    total_dd = degree_days.loc[match[0]:match[1]].sum()
    if total_dd == 0:
        raise ValueError("Never warmer than the melt threshold")
    melt_total = pd.Series(rain_mm, dtype=float).loc[match[0]:match[1]].sum() * share / (1 - share)
    return melt_total / total_dd


def snowmelt(tmean_c, rain_mm, threshold_c=MELT_THRESHOLD_C, share=MELT_SHARE,
             match=(MATCH_START, MATCH_END), scale=None):
    """
    Degree-day melt (mm-equivalent), scaled so melt is `share` of all water
    (rain + melt) over the matching period. Pass `scale` (from melt_scale on actual
    weather) to apply a fixed scale, e.g. to forecast temperatures.
    """
    degree_days = (pd.Series(tmean_c, dtype=float) - threshold_c).clip(lower=0)
    if scale is None:
        scale = melt_scale(tmean_c, rain_mm, threshold_c, share, match)
    return degree_days * scale


# ---------------------------------------------------------------------------
# Index -> availability factor
# ---------------------------------------------------------------------------

def match_level(index, target, cap=CAP, match=(MATCH_START, MATCH_END), iterations=100, return_scale=False):
    """
    Scale a daily index so its mean over `match` equals `target`, with no value above `cap`.
    Capping lowers the mean, so scale and cap are repeated until the mean fits.
    return_scale=True also returns the scale, so it can be reused on forecast indices.
    """
    index = pd.Series(index, dtype=float)
    period = index.loc[match[0]:match[1]]
    if period.mean() <= 0:
        raise ValueError("Index has no positive values to scale")
    if target > cap:
        raise ValueError("Target above the cap")
    scale = target / period.mean()
    for _ in range(iterations):
        mean = (period * scale).clip(upper=cap).mean()
        if abs(mean - target) < 1e-9:
            break
        scale *= target / mean
    factor = (index * scale).clip(upper=cap)
    return (factor, scale) if return_scale else factor


def hydro_inflow(w, state, melt_k=None):
    """Daily water into a state's hydro buckets: rain, plus snowmelt in Himalayan states."""
    inflow = w["precipitation_sum"]
    if state in HIMALAYAN_STATES:
        inflow = inflow + snowmelt(w["temperature_2m_mean"], w["precipitation_sum"], scale=melt_k)
    return inflow


def weather_pairs(gen):
    """(state, fuel) pairs with capacity of a weather-driven fuel."""
    cap = gen.groupby(["State", "Fuel_Type"])["Capacity_MW"].sum()
    return [k for k in cap[cap > 0].index if k[1] in WEATHER_FUELS]


def build_availability(state_weather, wind_output, gen, base=AVAILABILITY, return_scales=False):
    """
    Daily availability factor for every (state, weather fuel) with capacity.

    state_weather : data/processed/weather_state_daily.csv (Date, State, Purpose, ...)
    wind_output   : daily_wind_output() result (Series indexed by Date, State)
    gen           : generator stack (State, Fuel_Type, Capacity_MW)

    Returns a long table: Date, State, Fuel_Type, Factor. With return_scales=True also
    returns the fitted scales: {(state, fuel): scale, ("melt", state): mm per degree day}.
    """
    sw = state_weather.set_index(["Purpose", "State", "Date"]).sort_index()
    out, scales = [], {}
    for (state, fuel) in weather_pairs(gen):
        if fuel == "Solar":
            w = sw.loc[("solar", state)]
            index = pd.Series(solar_index(w["shortwave_radiation_sum"], w["temperature_2m_max"]), index=w.index)
        elif fuel == "Wind":
            index = wind_output.xs(state, level="State")
        else:
            w = sw.loc[("hydro", state)]
            if state in HIMALAYAN_STATES:
                scales[("melt", state)] = melt_scale(w["temperature_2m_mean"], w["precipitation_sum"])
            index = leaky_bucket(hydro_inflow(w, state, scales.get(("melt", state))), HALF_LIFE_DAYS[fuel])
        factor, scales[(state, fuel)] = match_level(index, base[fuel], return_scale=True)
        out.append(pd.DataFrame({"Date": factor.index, "State": state, "Fuel_Type": fuel,
                                 "Factor": factor.to_numpy()}))
    table = pd.concat(out, ignore_index=True)
    return (table, scales) if return_scales else table


def forecast_availability(actual_weather, tomorrow_weather, tomorrow_wind, gen, scales):
    """
    Availability for each day T as forecast on day D = T − 1.

    actual_weather   : actual state weather (weather_state_daily.csv): fills hydro buckets up to D
    tomorrow_weather : the weather assumed for T, same layout (a day-ahead forecast, or the
                       actual weather shifted one day for the persistence case)
    tomorrow_wind    : daily wind output index for T from the same weather (Series by Date, State)
    scales           : from build_availability(..., return_scales=True) on actual weather: the
                       levels are frozen, never re-fitted on forecasts

    Hydro: bucket_T = (1 − a) × bucket_D (actual) + a × inflow_T (assumed weather).
    Days where the assumed weather is missing are dropped. Returns Date, State, Fuel_Type, Factor.
    """
    act = actual_weather.set_index(["Purpose", "State", "Date"]).sort_index()
    tom = tomorrow_weather.set_index(["Purpose", "State", "Date"]).sort_index()
    out = []
    for (state, fuel) in weather_pairs(gen):
        if fuel == "Solar":
            w = tom.loc[("solar", state)]
            index = pd.Series(solar_index(w["shortwave_radiation_sum"], w["temperature_2m_max"]), index=w.index)
        elif fuel == "Wind":
            index = tomorrow_wind.xs(state, level="State")
        else:
            a_w, t_w = act.loc[("hydro", state)], tom.loc[("hydro", state)]
            melt_k = scales.get(("melt", state))
            bucket = leaky_bucket(hydro_inflow(a_w, state, melt_k), HALF_LIFE_DAYS[fuel])
            a = 1 - 0.5 ** (1 / HALF_LIFE_DAYS[fuel])
            index = (1 - a) * bucket.shift(1).reindex(t_w.index) + a * hydro_inflow(t_w, state, melt_k)
        factor = (index * scales[(state, fuel)]).clip(upper=CAP).dropna()
        out.append(pd.DataFrame({"Date": factor.index, "State": state, "Fuel_Type": fuel,
                                 "Factor": factor.to_numpy()}))
    return pd.concat(out, ignore_index=True)


def anchor_availability(forecast, actual, fuels=("Solar", "Wind")):
    """
    Anchored availability forecast for `fuels`: tomorrow = today's actual factor +
    (forecast factor for tomorrow − forecast factor for today), kept within 0-1.
    Cancels the weather-forecast bias that persists from day to day (model log Step 17).
    Other fuels (hydro: the rolled bucket) are returned unchanged.
    """
    keys = ["State", "Fuel_Type"]
    fc_ = forecast.set_index(keys + ["Date"])["Factor"]
    act = actual.set_index(keys + ["Date"])["Factor"]
    previous_day = lambda t: t.rename(index=lambda d: d + pd.Timedelta(days=1), level="Date")
    anchored = (previous_day(act).reindex(fc_.index) + fc_ - previous_day(fc_).reindex(fc_.index)).clip(0, 1)
    use = fc_.index.get_level_values("Fuel_Type").isin(fuels)
    out = fc_.where(~use, anchored).dropna()
    return out.rename("Factor").reset_index()


def scale_availability(daily, fuels, factor, cap=CAP):
    """
    What-if helper: multiply the daily factors of `fuels` by `factor` (a number, or a Series
    aligned with `daily`), keeping them within 0-cap. Other rows are unchanged.
    """
    out = daily.copy()
    rows = out["Fuel_Type"].isin(fuels)
    scale = factor[rows] if isinstance(factor, pd.Series) else factor
    out.loc[rows, "Factor"] = (out.loc[rows, "Factor"] * scale).clip(0, cap)
    return out
