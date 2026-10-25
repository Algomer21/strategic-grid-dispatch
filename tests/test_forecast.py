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
