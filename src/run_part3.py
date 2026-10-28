"""
Part 3 runs over many days (Stages 4-7). Each stage writes CSVs to data/processed/ and
the notebooks (15-17) read them; a notebook re-runs a stage only if its file is missing.

From the project root:   .venv/bin/python src/run_part3.py [stage4|stage5|stage6|stage7|all]
Run time on 9 worker processes: Stage 4 ~16 min (estimate), Stage 5 ~50-60 min (estimate, from
Stage 7's 300 24-firm days in 36 min), Stage 6 6.3 min, Stage 7 36 min.
"""

import sys
import time

import numpy as np
import pandas as pd

from availability import CAP
from bidding import (MAX_BID, firm_blocks, job_bid_on_forecast, job_equilibrium, job_single,
                     players, run_parallel)
from dispatch import PROCESSED, LOSS_MAX, daily_availability_lookup, load_demand, load_generators
from forecast import load_forecast_package

# Plan Decision 8: Part 2's scored period, so actual and forecast results cover the same days
DAYS_FILE = PROCESSED / "market_structure_national_daily.csv"

# Stage 6: the firms that bid on forecasts (the two largest)
FORECAST_FIRMS = ["NR UP", "WR Maharashtra"]

# Stage 7: a 60-day sample spread evenly over tightness (every 6.6th day when sorted by
# spare capacity), and the what-ifs
SAMPLE_DAYS = 60
LOW_CAP = 5000  # Rs/MWh, a lower price cap; bids then stop at 5,000 x (1 - LOSS_MAX) - 10
WHAT_IFS = {
    "Base": {},
    "Cap Rs 5,000": {"max_bid": LOW_CAP * (1 - LOSS_MAX) - 10},
    "Contracts 50%": {"contract_share": 0.5},
    "Coal -10%": {"coal_scale": 0.9},
    "Demand +5%": {"demand_scale": 1.05},
}


def inputs():
    """Days, actual demand, actual availability lookup and the players."""
    blocks = firm_blocks(load_generators())
    days = pd.read_csv(DAYS_FILE, parse_dates=["Date"])["Date"].tolist()
    daily = pd.read_csv(PROCESSED / "availability_daily.csv", parse_dates=["Date"])
    first = days[0] - pd.Timedelta(days=1)
    lookup = daily_availability_lookup(daily[daily["Date"].between(first, days[-1])])
    return days, load_demand(), lookup, players(blocks)


def stage4():
    """Each player alone, everyone else at cost, every day."""
    days, demand, lookup, firms = inputs()
    jobs = [{"date": d, "demand": demand.loc[d], "availability": lookup[d], "firms": firms} for d in days]
    rows = [r for day in run_parallel(job_single, jobs) for r in day]
    pd.DataFrame(rows).to_csv(PROCESSED / "strategic_single_daily.csv", index=False)


def _eq_jobs(days, demand, lookup, firms, what_if=None, state_prices=False):
    what_if = what_if or {}
    jobs = []
    for d in days:
        av = dict(lookup[d])
        if "coal_scale" in what_if:
            av = {k: (min(v * what_if["coal_scale"], CAP) if (k == "Coal" or (isinstance(k, tuple) and k[1] == "Coal")) else v)
                  for k, v in av.items()}
        jobs.append({"date": d, "demand": demand.loc[d] * what_if.get("demand_scale", 1.0),
                     "availability": av, "firms": firms, "state_prices": state_prices,
                     "max_bid": what_if.get("max_bid", MAX_BID),
                     "contract_share": what_if.get("contract_share", 0.0)})
    return jobs


def _long_prices(national):
    """Wide Pcost_/Peq_ columns -> long Date, State, Price_cost, Price_eq."""
    out = []
    for prefix, name in [("Pcost_", "Price_cost"), ("Peq_", "Price_eq")]:
        cols = [c for c in national.columns if c.startswith(prefix)]
        part = national[["Date"] + cols].melt(id_vars="Date", var_name="State", value_name=name)
        part["State"] = part["State"].str[len(prefix):]
        out.append(part.set_index(["Date", "State"]))
    return pd.concat(out, axis=1).reset_index()


def stage5():
    """All players together (best-response equilibrium), every day."""
    days, demand, lookup, firms = inputs()
    res = run_parallel(job_equilibrium, _eq_jobs(days, demand, lookup, firms, state_prices=True))
    national = pd.DataFrame([r["national"] for r in res])
    _long_prices(national).to_csv(PROCESSED / "strategic_eq_state_daily.csv", index=False)
    national[[c for c in national.columns if not c.startswith(("Pcost_", "Peq_"))]].to_csv(
        PROCESSED / "strategic_eq_national_daily.csv", index=False)
    pd.DataFrame([f for r in res for f in r["firms"]]).to_csv(PROCESSED / "strategic_eq_firms_daily.csv", index=False)


def forecast_scenarios(days):
    """
    Per day T, what a firm knows on day T-1: (demand, availability) for the median, 10% and
    90% demand forecasts (Part 2's package), with the best day-ahead availability forecast for
    solar, wind and hydro (coal, gas and the rest keep their constant factor, as in Part 2).
    """
    pkg = load_forecast_package()
    pkg = pkg[pkg["Area"] != "National"]
    fc = pd.read_csv(PROCESSED / "availability_forecast_test.csv", parse_dates=["Date"])
    fc = fc[fc["Model"] == "best day-ahead"].rename(columns={"Forecast": "Factor"})
    lookup_fc = daily_availability_lookup(fc[fc["Date"].isin(days)][["Date", "State", "Fuel_Type", "Factor"]])
    scen = {}
    for d in days:
        p = pkg[pkg["Date"] == d].set_index("Area")
        scen[d] = {q: (p[col], lookup_fc[d]) for q, col in
                   [("median", "Demand_forecast"), ("q10", "Demand_Q10"), ("q90", "Demand_Q90")]}
    return scen


def stage6():
    """The largest firms choose bids on forecasts; the market clears on the actual day."""
    days, demand, lookup, _ = inputs()
    scen = forecast_scenarios(days)
    yesterday = lambda d: d - pd.Timedelta(days=1)
    jobs = [{"date": d, "firm": f, "actual": (demand.loc[d], lookup[d]),
             "yesterday": (demand.loc[yesterday(d)], lookup[yesterday(d)]), **scen[d]}
            for d in days for f in FORECAST_FIRMS]
    rows = [r for job in run_parallel(job_bid_on_forecast, jobs) for r in job]
    pd.DataFrame(rows).to_csv(PROCESSED / "strategic_forecast_daily.csv", index=False)


def sample_days(n=SAMPLE_DAYS):
    """n days spread evenly over spare capacity (Stage 1's Tightness), in date order."""
    nat = pd.read_csv(DAYS_FILE, parse_dates=["Date"]).sort_values("Tightness").reset_index(drop=True)
    pick = np.linspace(0, len(nat) - 1, n).round().astype(int)
    return sorted(nat.loc[pick, "Date"].tolist())


def stage7():
    """Equilibrium on the 60-day sample under each what-if."""
    _, demand, lookup, firms = inputs()
    days = sample_days()
    out = []
    for name, what_if in WHAT_IFS.items():
        t0 = time.time()
        res = run_parallel(job_equilibrium, _eq_jobs(days, demand, lookup, firms, what_if))
        out.append(pd.DataFrame([r["national"] for r in res]).assign(What_if=name))
        print(f"  {name}: {time.time() - t0:.0f} s", flush=True)
    pd.concat(out, ignore_index=True).to_csv(PROCESSED / "strategic_whatif_daily.csv", index=False)


STAGES = {"stage4": stage4, "stage5": stage5, "stage6": stage6, "stage7": stage7}

if __name__ == "__main__":
    for name in (STAGES if sys.argv[1:] in ([], ["all"]) else sys.argv[1:]):
        t0 = time.time()
        STAGES[name]()
        print(f"{name} done in {(time.time() - t0) / 60:.1f} min", flush=True)
