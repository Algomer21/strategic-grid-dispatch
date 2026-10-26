"""Checks for src/availability.py. Run from the project root:  .venv/bin/python -m pytest"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from availability import leaky_bucket, match_level, snowmelt, solar_index, wind_power_curve

DAYS = pd.date_range("2020-01-01", "2024-12-31")


# ---- wind power curve: hand answers -------------------------------------------------

@pytest.mark.parametrize("speed,expected", [
    (0, 0), (2.9, 0),                              # below cut-in
    (3, 0),                                        # cut-in: curve starts at 0
    (7.5, (7.5**3 - 27) / (12**3 - 27)),           # ≈ 0.232: cubic rise
    (12, 1), (20, 1),                              # rated: full output
    (25, 0), (30, 0),                              # storm shutdown
])
def test_wind_power_curve(speed, expected):
    assert wind_power_curve(speed) == pytest.approx(expected)


def test_average_of_curve_beats_curve_of_average():
    # the reason for hourly wind: a day of 2 m/s and 10 m/s averages 6 m/s
    hourly = wind_power_curve([2, 10]).mean()
    daily = wind_power_curve(6)
    assert hourly > 1.5 * daily


# ---- solar heat loss: hand answers --------------------------------------------------

def test_solar_heat_loss():
    # 21.6 MJ/m² over 10 h = 600 W/m² -> panel = air + 25 × 600/800 = air + 18.75 °C
    cool = solar_index(21.6, 6.25)           # panel exactly 25 °C: no loss
    hot = solar_index(21.6, 46.0)            # panel 64.75 °C: loss 0.004 × 39.75 = 15.9 %
    assert cool == pytest.approx(21.6)
    assert hot / cool == pytest.approx(1 - 0.004 * 39.75)


# ---- leaky bucket --------------------------------------------------------------------

def test_leaky_bucket_half_life():
    inflow = pd.Series([0.0] * 400 + [100.0] + [0.0] * 200)
    b = leaky_bucket(inflow, half_life_days=10, spin_up_days=0)
    peak = b.idxmax()
    assert b[peak + 10] == pytest.approx(b[peak] / 2)      # half gone after 10 days


def test_leaky_bucket_steady_rain_fills_to_rain():
    b = leaky_bucket(pd.Series([5.0] * 500), half_life_days=60)
    assert b.iloc[0] == pytest.approx(5.0)                 # spin-up: not empty on day 1


def test_slow_bucket_peaks_later_than_fast():
    # smooth seasonal rain peaking mid-July: a bucket lags its inflow, a slow one more
    rain = pd.Series(1 + np.cos(2 * np.pi * (DAYS.day_of_year - 196) / 365), index=DAYS)
    fast, slow = leaky_bucket(rain, 10), leaky_bucket(rain, 60)
    rain_peak = rain.loc["2023"].idxmax()
    assert rain_peak < fast.loc["2023"].idxmax() < slow.loc["2023"].idxmax()


# ---- snowmelt -------------------------------------------------------------------------

def test_snowmelt_share_and_threshold():
    tmean = pd.Series(np.where(DAYS.month.isin([4, 5, 6]), 25.0, 5.0), index=DAYS)
    rain = pd.Series(2.0, index=DAYS)
    melt = snowmelt(tmean, rain, threshold_c=15, share=0.5)
    assert (melt[tmean <= 15] == 0).all()                   # no melt on cold days
    assert melt.sum() == pytest.approx(rain.sum())         # 50 % share: melt = rain


# ---- level matching -------------------------------------------------------------------

def test_match_level_hits_target_and_cap():
    index = pd.Series(np.where(DAYS.month == 7, 10.0, 1.0), index=DAYS)   # very peaked
    f = match_level(index, target=0.45, cap=1.0)
    assert f.mean() == pytest.approx(0.45)
    assert f.max() <= 1.0
    assert (f == 1.0).any()                                # the cap was needed here


def test_match_level_keeps_shape():
    index = pd.Series(np.linspace(1, 2, len(DAYS)), index=DAYS)
    f = match_level(index, target=0.25)
    assert f.iloc[-1] / f.iloc[0] == pytest.approx(2.0)    # same ratios, new level


# ---- anchored forecasts ----------------------------------------------------------------

from availability import anchor_availability


def test_anchoring_cancels_a_constant_forecast_bias():
    dates = pd.date_range("2024-03-01", periods=10)
    actual = pd.DataFrame({"Date": dates, "State": "X", "Fuel_Type": "Solar",
                           "Factor": np.linspace(0.20, 0.30, 10)})
    biased = actual.assign(Factor=actual.Factor + 0.05)          # forecast always 0.05 too high
    out = anchor_availability(biased, actual).set_index("Date")["Factor"]
    assert np.allclose(out, actual.set_index("Date")["Factor"].loc[out.index])   # bias gone


def test_anchoring_leaves_hydro_alone_and_stays_in_range():
    dates = pd.date_range("2024-03-01", periods=3)
    actual = pd.DataFrame({"Date": list(dates) * 2, "State": "X", "Fuel_Type": ["Wind"] * 3 + ["Large Hydro"] * 3,
                           "Factor": [0.9, 0.9, 0.9, 0.5, 0.5, 0.5]})
    fcst = actual.assign(Factor=[0.1, 0.1, 0.6, 0.4, 0.4, 0.4])
    out = anchor_availability(fcst, actual).set_index(["Fuel_Type", "Date"])["Factor"]
    assert out[("Wind", dates[2])] == 1.0                       # 0.9 + 0.5 capped at 1
    assert out[("Large Hydro", dates[2])] == 0.4                # unchanged


def test_scale_availability_only_touches_chosen_fuels():
    from availability import scale_availability
    daily = pd.DataFrame({"Date": pd.Timestamp("2024-07-01"), "State": "X",
                          "Fuel_Type": ["Large Hydro", "Small Hydro", "Wind"], "Factor": [0.6, 0.9, 0.5]})
    out = scale_availability(daily, ["Large Hydro", "Small Hydro"], 0.7)
    assert np.allclose(out.Factor, [0.42, 0.63, 0.5])
    assert scale_availability(daily, ["Wind"], 3.0).Factor.iloc[2] == 1.0     # capped
