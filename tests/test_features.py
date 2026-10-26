"""Checks for src/features.py, mainly that no feature can see the future. Run:  .venv/bin/python -m pytest"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from features import build_features, holiday_flags, paddy_flags

DATES = pd.date_range("2024-06-01", periods=30)
STATES = ["Punjab", "Kerala"]
FEATURES_ONLY = ["Base", "r_D_vs_Dm1", "r_D_vs_Dm7", "r_lastweek", "hol_T", "hol_D", "paddy_T", "paddy_D",
                 "d_cdd", "d_hdd", "cdd_T", "hdd_T", "rain_T", "rain_3d", "tmax_T", "tmean_T", "tmin_T", "d_tmax"]


def toy_inputs(seed=0):
    rng = np.random.default_rng(seed)
    demand = pd.DataFrame(rng.uniform(900, 1100, (len(DATES), len(STATES))), index=DATES, columns=STATES)
    wdates = pd.date_range(DATES[0] - pd.Timedelta(days=7), DATES[-1])
    weather = pd.DataFrame([{"Date": d, "State": s, "Purpose": "demand",
                             "temperature_2m_max": rng.uniform(25, 45), "temperature_2m_mean": rng.uniform(15, 38),
                             "temperature_2m_min": rng.uniform(10, 30), "precipitation_sum": rng.uniform(0, 20)}
                            for d in wdates for s in STATES])
    holidays = pd.DataFrame({"Date": pd.to_datetime(["2024-06-10", "2024-06-17"]), "Name": ["X", "Y"],
                             "Scope": ["national", "regional"], "States": ["all", "Kerala"], "Source": ["", ""]})
    paddy = pd.DataFrame({"State": ["Punjab"], "Year": [2024], "First_allowed": pd.to_datetime(["2024-06-11"]),
                          "Main_start": pd.to_datetime(["2024-06-11"]), "Schedule": [""], "Source": [""]})
    return demand, weather, holidays, paddy


def row(f, date, state):
    return f[(f.Date == date) & (f.State == state)].iloc[0]


@pytest.mark.parametrize("weather", ["perfect", "persistence"])
def test_future_demand_cannot_change_features(weather):
    demand, w, hol, pad = toy_inputs()
    T = pd.Timestamp("2024-06-20")
    before = build_features(demand, w, hol, pad, weather)
    changed = demand.copy()
    changed.loc[T:, "Punjab"] *= 3                          # change demand on T and after
    after = build_features(changed, w, hol, pad, weather)
    assert row(before, T, "Punjab")[FEATURES_ONLY].equals(row(after, T, "Punjab")[FEATURES_ONLY])
    assert row(after, T, "Punjab")["Actual"] != row(before, T, "Punjab")["Actual"]   # only the answer moved


def test_weather_after_T_cannot_change_features():
    demand, w, hol, pad = toy_inputs()
    T = pd.Timestamp("2024-06-20")
    later = w["Date"] > T
    w2 = w.copy()
    w2.loc[later, ["temperature_2m_max", "temperature_2m_mean", "temperature_2m_min", "precipitation_sum"]] += 10
    a = row(build_features(demand, w, hol, pad, "perfect"), T, "Punjab")[FEATURES_ONLY]
    b = row(build_features(demand, w2, hol, pad, "perfect"), T, "Punjab")[FEATURES_ONLY]
    assert a.equals(b)


def test_persistence_does_not_use_weather_on_T():
    demand, w, hol, pad = toy_inputs()
    T = pd.Timestamp("2024-06-20")
    w2 = w.copy()
    w2.loc[w2["Date"] == T, "temperature_2m_mean"] += 10
    a = row(build_features(demand, w, hol, pad, "persistence"), T, "Punjab")[FEATURES_ONLY]
    b = row(build_features(demand, w2, hol, pad, "persistence"), T, "Punjab")[FEATURES_ONLY]
    assert a.equals(b)
    assert a["d_cdd"] == 0 and a["d_hdd"] == 0              # tomorrow assumed the same as today


def test_hand_values():
    demand, w, hol, pad = toy_inputs()
    f = build_features(demand, w, hol, pad)
    T = pd.Timestamp("2024-06-20")
    D, d = T - pd.Timedelta(days=1), demand["Punjab"]
    r = row(f, T, "Punjab")
    assert r["Base"] == d[D] and r["Actual"] == d[T]
    assert r["y"] == pytest.approx(np.log(d[T] / d[D]))
    assert r["r_lastweek"] == pytest.approx(np.log(d[T - pd.Timedelta(days=7)] / d[D - pd.Timedelta(days=7)]))
    assert r["r_D_vs_Dm7"] == pytest.approx(np.log(d[D] / d[D - pd.Timedelta(days=7)]))


def test_holiday_and_paddy_flags():
    demand, w, hol, pad = toy_inputs()
    h = holiday_flags(DATES, STATES, hol)
    assert h.loc["2024-06-10"].tolist() == [1, 1]           # national: every state
    assert h.loc["2024-06-17"].tolist() == [0, 1]           # regional: Kerala only
    p = paddy_flags(DATES, STATES, pad)
    assert p.loc["2024-06-10", "Punjab"] == 0 and p.loc["2024-06-11", "Punjab"] == 1
    assert p["Kerala"].sum() == 0


def test_unknown_state_in_holidays_is_an_error():
    _, _, hol, _ = toy_inputs()
    hol.loc[1, "States"] = "Atlantis"
    with pytest.raises(ValueError):
        holiday_flags(DATES, STATES, hol)
