"""Checks for src/weather.py (no internet needed). Run from the project root:  .venv/bin/python -m pytest"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from weather import (DAILY_VARIABLES, check_weather, combine_points, fetch_all, load_points,
                     load_population, parse_daily, point_weights)

START, END = "2024-05-28", "2024-05-30"


def fake_payload(days=("2024-05-28", "2024-05-29", "2024-05-30"), value=30.0):
    """The shape Open-Meteo answers with: {'daily': {'time': [...], var: [...]}}."""
    return {"daily": {"time": list(days), **{v: [value] * len(days) for v in DAILY_VARIABLES}}}


def test_parse_daily():
    df = parse_daily(fake_payload(), START, END)
    assert list(df.columns) == ["Date"] + DAILY_VARIABLES
    assert df["Date"].tolist() == list(pd.date_range(START, END))


def test_parse_daily_rejects_missing_day():
    with pytest.raises(ValueError):
        parse_daily(fake_payload(days=("2024-05-28", "2024-05-30")), START, END)


def test_parse_daily_rejects_empty_value():
    payload = fake_payload()
    payload["daily"]["temperature_2m_max"][1] = None
    with pytest.raises(ValueError):
        parse_daily(payload, START, END)


def test_parse_daily_rejects_error_answer():
    with pytest.raises(ValueError):
        parse_daily({"error": True, "reason": "bad request"}, START, END)


def test_fetch_all_downloads_each_location_once_and_caches(tmp_path):
    points = pd.DataFrame({"Point_ID": ["demand_a", "solar_a", "wind_b"],
                           "Lat": [10.0, 10.0, 20.0], "Lon": [70.0, 70.0, 80.0]})
    calls = []

    def fake_fetch(lat, lon):
        calls.append((lat, lon))
        return parse_daily(fake_payload(value=lat), START, END)

    w = fetch_all(points, cache_dir=tmp_path, fetch=fake_fetch, verbose=False)
    assert calls == [(10.0, 70.0), (20.0, 80.0)]                  # shared location fetched once
    assert len(w) == 3 * 3                                          # 3 points x 3 days
    assert (w.loc[w.Point_ID == "wind_b", "temperature_2m_max"] == 20.0).all()

    fetch_all(points, cache_dir=tmp_path, fetch=fake_fetch, verbose=False)
    assert len(calls) == 2                                          # second run: all from cache
    assert check_weather(w, points, START, END)


def test_check_weather_catches_impossible_values(tmp_path):
    points = pd.DataFrame({"Point_ID": ["p"], "Lat": [10.0], "Lon": [70.0]})
    w = fetch_all(points, cache_dir=tmp_path, verbose=False,
                  fetch=lambda lat, lon: parse_daily(fake_payload(value=60.0), START, END))
    with pytest.raises(ValueError):                                 # 60 °C max is impossible
        check_weather(w, points, START, END)


def test_points_file():
    p = load_points()
    assert p["Point_ID"].is_unique
    assert set(p["Purpose"]) == {"demand", "solar", "wind", "hydro"}
    assert p["Lat"].between(6, 37).all() and p["Lon"].between(68, 98).all()


# hand example: state A has two demand cities (population 3 : 1) and two solar points,
# state B has one demand point
POINTS = pd.DataFrame({"Point_ID": ["d_a1", "d_a2", "s_a1", "s_a2", "d_b"],
                       "State": ["A", "A", "A", "A", "B"],
                       "Purpose": ["demand", "demand", "solar", "solar", "demand"]})
POP = pd.DataFrame({"Point_ID": ["d_a1", "d_a2"], "Population_2011": [3_000_000, 1_000_000]})


def test_point_weights_hand_answers():
    w = point_weights(POINTS, POP).set_index("Point_ID")["Weight"]
    assert w["d_a1"] == pytest.approx(0.75) and w["d_a2"] == pytest.approx(0.25)   # 3 : 1
    assert w["s_a1"] == pytest.approx(0.5) and w["s_a2"] == pytest.approx(0.5)     # equal
    assert w["d_b"] == 1.0                                                          # single point


def test_point_weights_need_population_for_multi_city_states():
    with pytest.raises(ValueError):
        point_weights(POINTS, POP.iloc[:1])


def test_combine_points_hand_answer():
    temps = {"d_a1": 40.0, "d_a2": 20.0, "s_a1": 10.0, "s_a2": 30.0, "d_b": 25.0}
    weather = pd.DataFrame([{"Point_ID": pid, "Date": pd.Timestamp("2024-05-29"),
                             **{v: t for v in DAILY_VARIABLES}} for pid, t in temps.items()])
    out = combine_points(weather, POINTS, POP).set_index(["State", "Purpose"])["temperature_2m_max"]
    assert out[("A", "demand")] == pytest.approx(35.0)      # 0.75 x 40 + 0.25 x 20
    assert out[("A", "solar")] == pytest.approx(20.0)       # (10 + 30) / 2
    assert out[("B", "demand")] == pytest.approx(25.0)      # unchanged


def test_real_weights_sum_to_one():
    w = point_weights(load_points(), load_population())
    assert w.groupby(["State", "Purpose"])["Weight"].sum().round(12).eq(1).all()
