"""Checks for src/prices.py (the IEX hook), with made-up market data. Run:  .venv/bin/python -m pytest"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from dispatch import load_demand
from prices import compare_prices, load_bid_areas, load_prices, to_bid_areas


def test_every_state_has_one_bid_area():
    b = load_bid_areas()
    assert set(b.State) == set(load_demand().columns) and b.State.is_unique
    assert set(b.Bid_area) <= {"A1", "A2", "E1", "E2", "N1", "N2", "N3", "S1", "S2", "S3", "W1", "W2", "W3"}


def test_model_prices_in_common_format():
    p = load_prices("model")
    assert list(p.columns) == ["Date", "Area", "Price", "Source"]
    assert {"National", "Kerala"} <= set(p.Area) and (p.Source == "model").all()


def test_iex_file_is_checked(tmp_path):
    f = tmp_path / "iex.csv"
    pd.DataFrame({"Date": ["2024-05-01", "2024-05-01"], "Bid_area": ["N1", "N1"], "Price": [3000, 3100]}).to_csv(f, index=False)
    with pytest.raises(ValueError):
        load_prices("iex", f)                                  # two rows for one day and area


def test_to_bid_areas_is_demand_weighted():
    day = pd.Timestamp("2024-05-01")
    prices = pd.DataFrame({"Date": day, "Area": ["Punjab", "Haryana"], "Price": [3000.0, 4000.0], "Source": "model"})
    demand = pd.DataFrame({"Punjab": [1000.0], "Haryana": [3000.0]}, index=[day])
    areas = pd.DataFrame({"State": ["Punjab", "Haryana"], "Bid_area": ["N3", "N1"]})
    assert to_bid_areas(prices, demand, areas).set_index("Area").Price.to_dict() == {"N1": 4000.0, "N3": 3000.0}
    areas["Bid_area"] = "N1"
    assert to_bid_areas(prices, demand, areas).Price.iloc[0] == pytest.approx(3750.0)   # (3000×1 + 4000×3) / 4


def test_compare_prices_hand_example():
    dates = pd.date_range("2024-05-01", periods=3)
    model = pd.DataFrame({"Date": dates, "Area": "N1", "Price": [3000.0, 3300.0, 3300.0]})
    market = pd.DataFrame({"Date": dates, "Area": "N1", "Price": [3100.0, 3500.0, 3200.0]})
    r = compare_prices(model, market).loc["N1"]
    assert r["MAE"] == pytest.approx(400 / 3) and r["bias (model − market)"] == pytest.approx(-200 / 3)
    assert (r["market jumps"], r["jumps matched"]) == (2, 1)    # +400 matched by +300; −300 not matched
