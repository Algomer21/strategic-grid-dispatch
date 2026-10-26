"""Checks for src/forecast.py. Run from the project root:  .venv/bin/python -m pytest"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from forecast import mae, mape, persistence, rmse, skill, time_split

# hand example: errors are +10, -20, 0, +30
ACTUAL = [100, 200, 300, 400]
FORECAST = [90, 220, 300, 370]


def test_metrics_hand_answers():
    assert mae(ACTUAL, FORECAST) == pytest.approx(15)                            # (10+20+0+30)/4
    assert mape(ACTUAL, FORECAST) == pytest.approx((10 + 10 + 0 + 7.5) / 4)     # % per day
    assert rmse(ACTUAL, FORECAST) == pytest.approx(np.sqrt((100 + 400 + 0 + 900) / 4))


def test_perfect_forecast_scores_zero():
    assert mae(ACTUAL, ACTUAL) == 0
    assert mape(ACTUAL, ACTUAL) == 0
    assert rmse(ACTUAL, ACTUAL) == 0


def test_skill():
    assert skill(4, 5) == pytest.approx(0.20)   # 20% better than the baseline
    assert skill(5, 5) == 0                     # same as the baseline
    assert skill(6, 5) < 0                      # worse than the baseline


def test_metrics_reject_bad_input():
    with pytest.raises(ValueError):
        mae([1, 2], [1, np.nan])        # NaN, e.g. the first day of a shifted series
    with pytest.raises(ValueError):
        mae([1, 2], [1, 2, 3])          # different lengths
    with pytest.raises(ValueError):
        mape([0, 2], [1, 2])            # division by zero


def test_time_split_has_no_overlap():
    s = pd.Series(range(10), index=pd.date_range("2023-12-27", periods=10))
    train, test = time_split(s)
    assert train.index.max() == pd.Timestamp("2023-12-31")
    assert test.index.min() == pd.Timestamp("2024-01-01")
    assert len(train) + len(test) == len(s)


def test_persistence_uses_only_the_past():
    s = pd.Series([10, 20, 30, 40], index=pd.date_range("2024-01-01", periods=4))
    p = persistence(s)
    assert np.isnan(p.iloc[0])               # nothing known before day 1
    assert p.iloc[1:].tolist() == [10, 20, 30]
    assert persistence(s, lag=2).iloc[2] == 10


# ---- demand models -------------------------------------------------------------------

from forecast import LastWeek, Persistence, Profile, training_rows, walk_forward


def toy_features(n_days=120):
    dates = pd.date_range("2023-11-01", periods=n_days)
    rows = []
    for s, base in [("A", 1000.0), ("B", 50.0)]:
        for d in dates:
            sunday = d.day_of_week == 6
            rows.append(dict(State=s, Date=d, Base=base, Actual=base * (0.9 if sunday else 1.0),
                             y=np.log(0.9) if sunday else 0.0, weekday_T=d.day_of_week, month_T=d.month,
                             r_D_vs_Dm1=0.0, r_D_vs_Dm7=0.0, r_lastweek=np.log(0.9) if sunday else 0.0))
    return pd.DataFrame(rows)


def test_persistence_model_forecasts_base():
    f = toy_features()
    out = walk_forward(f, Persistence, start="2024-01-01")
    assert np.allclose(out["Forecast"], out["Base"])


def test_profile_learns_the_sunday_dip():
    f = toy_features()
    out = walk_forward(f, Profile, start="2024-01-01")
    sun = out[out.Date.dt.day_of_week == 6]
    assert np.allclose(sun["Forecast"], sun["Actual"])         # learned −10% on Sundays


def test_last_week_reproduces_the_lag7_value():
    # y = r_lastweek − r_D_vs_Dm7 = log(d_(T−7)/d_(D−7)) − log(d_D/d_(D−7)) = log(d_(T−7)/d_D)
    f = pd.DataFrame({"r_lastweek": [np.log(1.2)], "r_D_vs_Dm7": [np.log(1.5)]})
    assert LastWeek().predict(f)[0] == pytest.approx(np.log(1.2 / 1.5))


def test_walk_forward_never_trains_on_the_month_it_predicts():
    f = toy_features()
    seen = []

    class Spy(Persistence):
        def fit(self, train):
            seen.append(train["Date"].max())
            return self

    out = walk_forward(f, Spy, start="2024-01-01")
    months = sorted(out["Date"].dt.to_period("M").unique())
    assert [m.to_timestamp() - pd.Timedelta(days=1) for m in months] == seen


def test_lockdown_days_are_not_used_for_training():
    f = pd.DataFrame({"Date": pd.to_datetime(["2020-03-24", "2020-03-25", "2020-06-01", "2020-06-02"])})
    assert training_rows(f)["Date"].dt.strftime("%m-%d").tolist() == ["03-24", "06-02"]


def test_availability_forecast_stays_between_0_and_1():
    from forecast import factor_from_prediction
    rows = pd.DataFrame({"Pred": [-0.2, 0.5, 1.3]})
    assert factor_from_prediction(rows).tolist() == [0.0, 0.5, 1.0]


def test_walk_forward_can_predict_other_rows_than_it_trains_on():
    # perfect-prog: train on rows built from actual weather, predict rows built from forecasts
    from forecast import Profile
    f = toy_features()
    test_f = f.assign(Base=f["Base"] * 2)          # different inputs for the same days
    out = walk_forward(f, Persistence, start="2024-01-01", test_f=test_f)
    assert np.allclose(out["Forecast"], out["Base"]) and out["Base"].iloc[0] == 2 * f["Base"].iloc[0]
