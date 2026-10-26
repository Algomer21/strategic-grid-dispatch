"""Checks for src/dispatch.py. Run from the project root:  .venv/bin/python -m pytest"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from dispatch import (AVAILABILITY, LossDispatchModel, availability_for_month, daily_availability_lookup,
                      haversine_km,
                      load_coordinates, load_demand, load_generators, load_seasonal_availability,
                      loss_matrix, lp_dispatch, merit_order_dispatch)

TOY = pd.DataFrame({"name": ["Gas", "Solar", "Coal"],
                    "capacity_mw": [50, 40, 100],
                    "cost": [4500, 0, 2000]})

# demand: (price, fuel cost) -- the hand answers from notebook 02
HAND_ANSWERS = {
    0: (0, 0), 30: (0, 0), 40: (0, 0),
    120: (2000, 160000), 140: (2000, 200000),
    190: (4500, 425000), 200: (10000, 425000),
}


@pytest.mark.parametrize("demand,expected", HAND_ANSWERS.items())
def test_merit_order_hand_answers(demand, expected):
    r = merit_order_dispatch(demand, TOY)
    assert (r["clearing_price"], r["total_cost"]) == expected


@pytest.mark.parametrize("demand", [0, 30, 120, 140, 200])
def test_lp_matches_merit_order(demand):
    # 190 MW is excluded on purpose: at an exact capacity boundary the price is
    # not unique (merit order reports 4,500, the LP reports 10,000)
    lp = lp_dispatch(demand, TOY)
    mo = merit_order_dispatch(demand, TOY)
    assert lp["clearing_price"] == pytest.approx(mo["clearing_price"])
    assert lp["fuel_cost"] == pytest.approx(mo["total_cost"])


def test_haversine_delhi_mumbai():
    assert haversine_km(28.6139, 77.2090, 19.0760, 72.8777) == pytest.approx(1148, abs=5)


def test_every_coal_state_has_a_tier():
    gen = load_generators()
    assert gen["Marginal_Cost_Rs_per_MWh"].notna().all()


@pytest.fixture(scope="module")
def day():
    dem = load_demand()
    states = list(dem.columns)
    loss = loss_matrix(load_coordinates(), states)
    return dem.loc["2024-07-21"], states, loss


def test_loss_model_reference_result(day):
    # Flat coal cost, 21 Jul 2024. Notebook 02 validated Rs 296,732,641.83/h on the
    # data before the DD & DNH fix (demand frozen at 1,237 MW); with the corrected
    # 1,239 MW the same model gives the value below (see docs/model_log.md, step 9)
    demand, states, loss = day
    out = LossDispatchModel(load_generators(coal_tiers=False), loss, states).solve(demand)
    assert out["total_cost"] == pytest.approx(296_736_690.64, rel=1e-9)


def test_zero_loss_gives_one_price(day):
    # Copper plate: with no losses every state must clear at the same price
    demand, states, loss = day
    out = LossDispatchModel(load_generators(), loss * 0, states).solve(demand)
    assert out["states"]["Price"].round(6).nunique() == 1


def test_energy_balance_and_price_logic(day):
    demand, states, loss = day
    out = LossDispatchModel(load_generators(), loss, states).solve(demand)
    st, fl = out["states"], out["flows"]

    # Extra generation equals what is lost on the wires
    extra = st["Generation_MW"].sum() - st["Demand_MW"].sum() + st["Unserved_MW"].sum()
    assert extra == pytest.approx((fl["Sent_MW"] - fl["Received_MW"]).sum(), abs=1e-3)

    # On every used route: price_to = price_from / (1 - loss)
    p = st["Price"]
    expected = p[fl["From"]].to_numpy() / (1 - fl["Loss_pct"].to_numpy() / 100)
    assert np.allclose(p[fl["To"]].to_numpy(), expected)

    # No pair trades in both directions
    assert fl.merge(fl, left_on=["From", "To"], right_on=["To", "From"]).empty


def test_seasonal_factors_average_to_constant_factors():
    # Same yearly supply as the constant model, only timed differently
    seasonal = load_seasonal_availability()
    assert list(seasonal.index) == list(range(1, 13))
    for fuel in seasonal.columns:
        assert seasonal[fuel].mean() == pytest.approx(AVAILABILITY[fuel])


def test_availability_for_month_keeps_other_fuels_constant():
    july = availability_for_month(load_seasonal_availability(), 7)
    assert july["Large Hydro"] == 0.65
    assert july["Coal"] == AVAILABILITY["Coal"]
    assert set(july) == set(AVAILABILITY)


def test_constant_availability_override_changes_nothing(day):
    # Passing the default factors explicitly must give the same answer as no override
    demand, states, loss = day
    model = LossDispatchModel(load_generators(), loss, states)
    assert model.solve(demand, AVAILABILITY)["total_cost"] == pytest.approx(model.solve(demand)["total_cost"])



def test_state_fuel_override_changes_only_that_state(day):
    # A (state, fuel) key wins over its fuel; per-fuel keys for the same values change nothing
    demand, states, loss = day
    model = LossDispatchModel(load_generators(), loss, states)
    same = {**AVAILABILITY, ("Gujarat", "Wind"): AVAILABILITY["Wind"]}
    assert model.solve(demand, same)["total_cost"] == pytest.approx(model.solve(demand)["total_cost"])

    calm = {**AVAILABILITY, ("Gujarat", "Wind"): 0.0}
    gen = model.solve(demand, calm)["generation"].set_index(["State", "Fuel_Type"])["Available_MW"]
    assert gen[("Gujarat", "Wind")] == 0
    assert gen[("Tamil Nadu", "Wind")] > 0                    # other states keep their wind


def test_daily_availability_lookup_fills_other_fuels():
    daily = pd.DataFrame({"Date": pd.to_datetime(["2024-07-01"]), "State": ["Gujarat"],
                          "Fuel_Type": ["Wind"], "Factor": [0.6]})
    day = daily_availability_lookup(daily)[pd.Timestamp("2024-07-01")]
    assert day[("Gujarat", "Wind")] == 0.6
    assert day["Coal"] == AVAILABILITY["Coal"]
