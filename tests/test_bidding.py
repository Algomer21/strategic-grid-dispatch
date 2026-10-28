"""Checks for src/bidding.py. Run from the project root:  .venv/bin/python -m pytest"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from bidding import ROLES, firm_blocks
from dispatch import load_generators

TOY = pd.DataFrame({"State": ["A", "A", "B", "B"],
                    "Fuel_Type": ["Coal", "Solar", "Nuclear", "Large Hydro"],
                    "Capacity_MW": [100, 50, 30, 40]})


def test_toy_firms_and_roles():
    out = firm_blocks(TOY)
    assert out["Firm"].tolist() == ["A", "A", "B", "B"]
    assert out["Role"].tolist() == ["strategic", "must-run", "cost", "strategic"]
    assert out["Capacity_MW"].tolist() == [100, 50, 30, 40]


def test_unknown_fuel_raises():
    bad = pd.concat([TOY, pd.DataFrame({"State": ["C"], "Fuel_Type": ["Hydrogen"], "Capacity_MW": [10]})])
    with pytest.raises(ValueError, match="Hydrogen"):
        firm_blocks(bad)


def test_input_not_changed():
    before = TOY.copy()
    firm_blocks(TOY)
    pd.testing.assert_frame_equal(TOY, before)


def test_real_stack_roles():
    out = firm_blocks(load_generators())
    assert len(out) == 161
    assert out["Role"].value_counts().to_dict() == {"strategic": 85, "must-run": 41, "cost": 35}
    players = out.loc[out["Role"] == "strategic", "Firm"].unique()
    assert len(players) == 30
    assert set(out["Firm"]) - set(players) == {"Chandigarh", "DD & DNH"}


# Market structure, hand-solved: firms A, B, C control 50, 30, 20 MW of strategic
# supply; 10 MW of must-run belongs to nobody that can withhold it; the market must
# cover 90 MW (demand + losses). Total available = 110 MW.
from bidding import REGIONS, firm_supply, hhi, joint_rsi, rsi, shares

FIRM_MW = pd.DataFrame({"A": [50.0], "B": [30.0], "C": [20.0]}, index=["day 1"])
TOTAL = pd.Series([110.0], index=["day 1"])
NEED = pd.Series([90.0], index=["day 1"])


def test_toy_shares_and_hhi():
    s = shares(FIRM_MW)
    assert s.loc["day 1"].tolist() == pytest.approx([0.5, 0.3, 0.2])
    assert hhi(s).loc["day 1"] == pytest.approx(50**2 + 30**2 + 20**2)   # 3,800


def test_toy_rsi_and_pivotal():
    r = rsi(TOTAL, FIRM_MW, NEED).loc["day 1"]
    assert r["A"] == pytest.approx(60 / 90)    # 0.667: pivotal
    assert r["B"] == pytest.approx(80 / 90)    # 0.889: pivotal
    assert r["C"] == pytest.approx(1.0)        # exactly 1: not pivotal, but near-pivotal (< 1.1)
    assert (r < 1).tolist() == [True, True, False]
    assert (r < 1.1).tolist() == [True, True, True]


def test_toy_joint_rsi():
    assert joint_rsi(TOTAL, FIRM_MW, NEED, 2).loc["day 1"] == pytest.approx(30 / 90)   # A + B
    assert joint_rsi(TOTAL, FIRM_MW, NEED, 3).loc["day 1"] == pytest.approx(10 / 90)   # all three


def test_firm_supply_counts_only_strategic():
    available = pd.DataFrame({"Date": ["d"] * 4, "State": ["A", "A", "B", "B"],
                              "Fuel_Type": ["Coal", "Solar", "Nuclear", "Large Hydro"],
                              "Available_MW": [75.0, 12.5, 24.0, 18.0]})
    out = firm_supply(firm_blocks(TOY), available)
    assert out.loc["d"].to_dict() == {"A": 75.0, "B": 18.0}      # solar and nuclear left out


def test_firm_supply_unknown_block_raises():
    available = pd.DataFrame({"Date": ["d"], "State": ["Z"], "Fuel_Type": ["Coal"], "Available_MW": [1.0]})
    with pytest.raises(ValueError, match="no firm"):
        firm_supply(firm_blocks(TOY), available)


def test_every_state_has_a_region():
    assert set(firm_blocks(load_generators())["State"]) <= set(REGIONS)
    assert len(REGIONS) == 32


# ---------------------------------------------------------------------------
# Stage 2: bids inside the LP
# ---------------------------------------------------------------------------
import numpy as np
from bidding import (MAX_BID, consumer_cost, firm_profit, generation_cost,
                     make_availability, make_bids)
from dispatch import (AVAILABILITY, VOLL, LossDispatchModel, daily_availability_lookup,
                      load_coordinates, load_demand, loss_matrix)

# The plan's hand example: firm A (state A) owns 80 MW of coal at Rs 1,000; the rest
# of the market is 50 MW at Rs 2,000 in state B, bidding cost (nuclear: cost role).
# Demand is 100 MW, all in A; no losses between A and B. The fringe can't cover
# demand alone, so A is pivotal.
HAND_GEN = pd.DataFrame({"State": ["A", "B"], "Fuel_Type": ["Coal", "Nuclear"],
                         "Capacity_MW": [80.0, 50.0], "Marginal_Cost_Rs_per_MWh": [1000.0, 2000.0],
                         "Available_MW": [80.0, 50.0]})
HAND_LOSS = pd.DataFrame([[np.nan, 0.0], [0.0, np.nan]], index=["A", "B"], columns=["A", "B"])
HAND_DEMAND = pd.Series({"A": 100.0, "B": 0.0})


@pytest.fixture(scope="module")
def hand():
    return LossDispatchModel(HAND_GEN, HAND_LOSS, ["A", "B"]), firm_blocks(HAND_GEN)


def test_hand_example_bid_below_fringe(hand):
    model, blocks = hand
    out = model.solve(HAND_DEMAND, costs=make_bids(blocks, {"A": 500}))     # A bids 1,501
    assert out["states"].loc["A", "Price"] == pytest.approx(2000)
    assert firm_profit(out, blocks)["A"] == pytest.approx((2000 - 1000) * 80)   # 80,000


def test_hand_example_bid_at_cap(hand):
    model, blocks = hand
    out = model.solve(HAND_DEMAND, costs=make_bids(blocks, {"A": 20000}))   # capped at MAX_BID
    assert out["states"].loc["A", "Price"] == pytest.approx(MAX_BID)
    assert out["states"]["Unserved_MW"].sum() == pytest.approx(0)          # never a blackout
    gen = out["generation"].set_index("State")["Dispatch_MW"]
    assert gen["A"] == pytest.approx(50) and gen["B"] == pytest.approx(50)
    assert MAX_BID == 8990
    assert firm_profit(out, blocks)["A"] == pytest.approx((MAX_BID - 1000) * 50)   # 399,500
    assert consumer_cost(out) == pytest.approx(MAX_BID * 100)
    assert generation_cost(out) == pytest.approx(1000 * 50 + 2000 * 50)     # true cost, not bids


def test_bid_at_or_above_voll_raises(hand):
    model, _ = hand
    with pytest.raises(ValueError, match="below VOLL"):
        model.solve(HAND_DEMAND, costs={("A", "Coal"): VOLL})


def test_raised_bid_is_kept_off_round_costs():
    gen = pd.DataFrame({"State": ["X"], "Fuel_Type": ["Lignite"], "Marginal_Cost_Rs_per_MWh": [2300.0],
                        "Capacity_MW": [10.0]})
    assert make_bids(firm_blocks(gen), {"X": 500}) == {("X", "Lignite"): 2801}   # not 2,800
    assert make_bids(firm_blocks(gen), {"X": 0}) == {}                            # adder 0 = cost


def test_only_strategic_blocks_get_adders():
    gen = load_generators()
    bids = make_bids(firm_blocks(gen), {"NR UP": 500})
    assert {f for _, f in bids} <= {"Coal", "Lignite", "Gas", "Large Hydro", "Small Hydro"}
    assert {s for s, _ in bids} == {"NR UP"}


def test_withholding():
    blocks = firm_blocks(load_generators())
    assert make_availability(AVAILABILITY, blocks, {"NR UP": 0}) == AVAILABILITY       # 0 changes nothing
    out = make_availability(AVAILABILITY, blocks, {"NR UP": 0.3})
    assert out[("NR UP", "Coal")] == pytest.approx(AVAILABILITY["Coal"] * 0.7)
    assert ("NR UP", "Solar") not in out                                                # must-run untouched
    assert out["Coal"] == AVAILABILITY["Coal"]                                          # other states untouched
    with pytest.raises(ValueError):
        make_availability(AVAILABILITY, blocks, {"NR UP": 1.5})


@pytest.mark.parametrize("date", ["2024-05-30", "2024-07-21", "2025-02-10"])
def test_bids_equal_costs_reproduce_competitive_run(date):
    # Bidding true cost through costs= must give exactly the saved competitive (Part 2) prices
    gen = load_generators()
    demand = load_demand()
    states = list(demand.columns)
    model = LossDispatchModel(gen, loss_matrix(load_coordinates(), states), states)
    daily = pd.read_csv(Path(__file__).resolve().parent.parent / "data/processed/availability_daily.csv",
                        parse_dates=["Date"])
    avail = daily_availability_lookup(daily[daily["Date"] == date])[pd.Timestamp(date)]
    true_costs = {(s, f): c for s, f, c in zip(gen["State"], gen["Fuel_Type"], gen["Marginal_Cost_Rs_per_MWh"])
                  if c < VOLL}
    out = model.solve(demand.loc[date], avail, costs=true_costs)

    saved = pd.read_csv(Path(__file__).resolve().parent.parent / "data/processed/dispatch_weather_state_daily.csv",
                        parse_dates=["Date"])
    saved = saved[saved["Date"] == date].set_index("State")["Price"]
    assert np.allclose(out["states"]["Price"].reindex(saved.index), saved, atol=1e-6)
    assert out["total_cost"] == pytest.approx(model.solve(demand.loc[date], avail)["total_cost"])


def test_bid_at_cap_never_causes_a_blackout_on_the_real_grid():
    # Found in Step 23: with a cap of 9,990, UP bidding the cap on 30 Jan 2025 left
    # 14,390 MW unserved, because losses pushed the delivered price above VOLL
    date = pd.Timestamp("2025-01-30")
    gen = load_generators()
    blocks = firm_blocks(gen)
    demand = load_demand()
    states = list(demand.columns)
    model = LossDispatchModel(gen, loss_matrix(load_coordinates(), states), states)
    daily = pd.read_csv(Path(__file__).resolve().parent.parent / "data/processed/availability_daily.csv",
                        parse_dates=["Date"])
    avail = daily_availability_lookup(daily[daily["Date"] == date])[date]
    for firm in ["NR UP", "WR Maharashtra"]:
        out = model.solve(demand.loc[date], avail, costs=make_bids(blocks, {firm: 20000}))
        assert out["states"]["Unserved_MW"].sum() == pytest.approx(0, abs=1e-6)
        assert out["states"]["Price"].max() < VOLL


def test_lower_cap_keeps_bids_and_prices_under_5000():
    # Stage 7 what-if: a Rs 5,000 cap means bids stop at 5,000 x (1 - LOSS_MAX) - 10 = 4,490
    from dispatch import LOSS_MAX
    date = pd.Timestamp("2025-01-30")
    gen = load_generators()
    blocks = firm_blocks(gen)
    demand = load_demand()
    states = list(demand.columns)
    model = LossDispatchModel(gen, loss_matrix(load_coordinates(), states), states)
    daily = pd.read_csv(Path(__file__).resolve().parent.parent / "data/processed/availability_daily.csv",
                        parse_dates=["Date"])
    avail = daily_availability_lookup(daily[daily["Date"] == date])[date]
    cap_bid = 5000 * (1 - LOSS_MAX) - 10
    bids = make_bids(blocks, {"NR UP": 20000, "WR Maharashtra": 20000}, cap_bid)
    assert max(bids.values()) == cap_bid
    out = model.solve(demand.loc[date], avail, costs=bids)
    assert out["states"]["Unserved_MW"].sum() == pytest.approx(0, abs=1e-6)
    assert out["states"]["Price"].max() <= 5000



# ---------------------------------------------------------------------------
# Stage 3: one strategic firm
# ---------------------------------------------------------------------------
from bidding import best_response, bid_candidates


def test_best_response_pivotal_bids_the_cap(hand):
    model, blocks = hand
    br = best_response(model, blocks, "A", HAND_DEMAND, {"Coal": 1.0, "Nuclear": 1.0})
    assert br["best"]["generation"].set_index("State").loc["A", "Bid"] == pytest.approx(MAX_BID)
    assert br["profit"] == pytest.approx((MAX_BID - 1000) * 50)          # 399,500
    assert br["profit_at_cost"] == pytest.approx(80_000)


def test_best_response_not_pivotal_bids_just_below_rival():
    # Firm A: 80 MW at Rs 1,000. Rival (state B): 100 MW at Rs 3,000, bids cost. Demand 70.
    # The rival alone covers demand, so A is not pivotal; A covers demand alone, so it sets
    # the price while it undercuts. Best: bid 2,999 -> profit (2,999 - 1,000) x 70 = 139,930
    gen = pd.DataFrame({"State": ["A", "B"], "Fuel_Type": ["Coal", "Nuclear"],
                        "Capacity_MW": [80.0, 100.0], "Marginal_Cost_Rs_per_MWh": [1000.0, 3000.0],
                        "Available_MW": [80.0, 100.0]})
    model = LossDispatchModel(gen, HAND_LOSS, ["A", "B"])
    blocks = firm_blocks(gen)
    br = best_response(model, blocks, "A", pd.Series({"A": 70.0, "B": 0.0}), {"Coal": 1.0, "Nuclear": 1.0})
    assert br["best"]["states"].loc["A", "Price"] == pytest.approx(2999)
    assert br["profit"] == pytest.approx(1999 * 70)


def test_bid_candidates_include_cost_cap_and_rival_levels(hand):
    _, blocks = hand
    adders = bid_candidates(blocks, "A")
    assert adders[0] == 0                                   # bid cost
    assert MAX_BID - 1 - 1000 in adders                     # the cap
    assert 2000 - 2 - 1000 in adders                        # Rs 1 below the rival's 2,000


def test_best_response_never_below_bidding_cost(hand):
    model, blocks = hand
    for demand in [40.0, 100.0, 125.0]:
        br = best_response(model, blocks, "A", pd.Series({"A": demand, "B": 0.0}), {"Coal": 1.0, "Nuclear": 1.0})
        assert br["profit"] >= br["profit_at_cost"] - 1e-6


# ---------------------------------------------------------------------------
# Stage 5: equilibrium on a hand-solved two-firm case
# ---------------------------------------------------------------------------

def test_equilibrium_two_firms_hand_solved():
    """
    Demand 100. A: 80 MW coal at 1,000. B: 30 MW coal at 1,500. Fringe: 40 MW nuclear at 3,000
    (cost role). B + fringe = 70 < 100, so A is pivotal and bids the cap (8,990); A serves 30.
    B sells 30 at A's price whatever it bids below it, so it has no reason to move.
    Converges in round 2: profits A (8,990 - 1,000) x 30 = 239,700, B (8,990 - 1,500) x 30 = 224,700.
    """
    import numpy as np
    from bidding import MAX_BID, equilibrium, firm_profit
    from dispatch import LossDispatchModel

    g = pd.DataFrame({"State": ["A", "B", "C"], "Fuel_Type": ["Coal", "Coal", "Nuclear"],
                      "Capacity_MW": [80.0, 30.0, 40.0],
                      "Marginal_Cost_Rs_per_MWh": [1000.0, 1500.0, 3000.0],
                      "Available_MW": [80.0, 30.0, 40.0]})
    names = ["A", "B", "C"]
    loss = pd.DataFrame(np.where(np.eye(3, dtype=bool), np.nan, 0.0), index=names, columns=names)
    model, blocks = LossDispatchModel(g, loss, names), firm_blocks(g)
    eq = equilibrium(model, blocks, pd.Series({"A": 100.0, "B": 0.0, "C": 0.0}),
                     {"Coal": 1.0, "Nuclear": 1.0}, ["A", "B"])
    profit = firm_profit(eq["result"], blocks)
    assert eq["status"] == "converged" and eq["rounds"] == 2
    assert eq["adders"]["B"] == 0
    assert eq["result"]["states"].loc["A", "Price"] == pytest.approx(MAX_BID)
    assert profit["A"] == pytest.approx(239_700) and profit["B"] == pytest.approx(224_700)


def _toy_market(rows, demand):
    import numpy as np
    from dispatch import LossDispatchModel
    g = pd.DataFrame(rows, columns=["State", "Fuel_Type", "Capacity_MW", "Marginal_Cost_Rs_per_MWh"])
    g["Available_MW"] = g["Capacity_MW"]
    names = sorted(g["State"].unique())
    loss = pd.DataFrame(np.where(np.eye(len(names), dtype=bool), np.nan, 0.0), index=names, columns=names)
    d = pd.Series(0.0, index=names)
    d.update(pd.Series(demand))
    return LossDispatchModel(g, loss, names), firm_blocks(g), d


def test_players_real_stack():
    from bidding import players
    p = players(firm_blocks(load_generators()))
    assert len(p) == 24 and p[0] == "NR UP"


def test_candidates_follow_rival_bids():
    """When rival B marks up its 3,000 block by 500 (bid 3,501), A's candidates undercut 3,501, not 3,000."""
    from bidding import bid_candidates
    _, blocks, _ = _toy_market([("A", "Coal", 80, 1000), ("B", "Coal", 100, 3000)], {"A": 70})
    plain, marked = bid_candidates(blocks, "A"), bid_candidates(blocks, "A", others={"B": 500})
    assert 3000 - 2 - 1000 in plain and 3501 - 2 - 1000 in marked
    assert 3501 - 2 - 1000 not in plain


def test_contract_removes_incentive_to_bid_cap():
    """
    Pivotal toy (A 80 MW at 1,000; fringe 50 MW at 2,000; demand 100). Without a contract A bids
    the cap. With 50 MW sold forward at its own state, A pays back the spot price on 50 MW:
      bid <= 2,000: A sells 80 at 2,000 -> 80,000 - 2,000 x 50 = -20,000
      bid at cap:   A sells 50 at 8,990 -> 399,500 - 8,990 x 50 = -50,000
    so A's best is to bid at or below the fringe: price stays 2,000.
    """
    from bidding import BID_ONLY, best_response
    model, blocks, d = _toy_market([("A", "Coal", 80, 1000), ("B", "Nuclear", 50, 2000)], {"A": 100})
    av = {"Coal": 1.0, "Nuclear": 1.0}
    free = best_response(model, blocks, "A", d, av, **BID_ONLY)
    tied = best_response(model, blocks, "A", d, av, **BID_ONLY, contracted_mw={"A": 50.0})
    assert free["profit"] == pytest.approx(399_500)
    assert tied["profit"] == pytest.approx(-20_000)
    assert tied["best"]["states"].loc["A", "Price"] == pytest.approx(2000)


def test_firm_above_cap_can_still_bid_cost():
    """With a cap below a firm's cheapest cost (gas at 4,500, cap bid 4,490), the only candidate is cost."""
    from bidding import bid_candidates
    _, blocks, _ = _toy_market([("A", "Gas", 50, 4500), ("B", "Coal", 100, 2000)], {"A": 70})
    assert bid_candidates(blocks, "A", max_bid=4490) == [0]


# ---------- Stage 6: bidding on forecasts ----------

def test_actual_day_as_forecast_matches_perfect_foresight():
    """If every forecast equals the actual day, forecast and persistence bids must equal perfect foresight."""
    import bidding
    bidding._init_worker()
    d = pd.Timestamp("2024-08-25")
    daily = pd.read_csv(Path(__file__).resolve().parent.parent / "data/processed/availability_daily.csv",
                        parse_dates=["Date"])
    actual = (load_demand().loc[d], daily_availability_lookup(daily[daily["Date"] == d])[d])
    rows = {r["Strategy"]: r for r in bidding.job_bid_on_forecast(
        {"date": d, "firm": "NR UP", "actual": actual, "median": actual,
         "q10": actual, "q90": actual, "yesterday": actual})}
    perfect = rows["perfect"]
    assert perfect["Adder"] > 0                                   # UP marks up on this slack day (Stage 3)
    for s in ["forecast", "persistence"]:
        assert rows[s]["Adder"] == perfect["Adder"]
        assert rows[s]["Profit"] == pytest.approx(perfect["Profit"])
    for s in ["robust", "cost"]:                                  # robust has no refinement step: never above perfect
        assert rows[s]["Profit"] <= perfect["Profit"] + 1
    assert all(r["Unserved_MW"] == 0 for r in rows.values())
