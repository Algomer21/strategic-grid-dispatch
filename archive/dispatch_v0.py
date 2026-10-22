"""
Merit-order dispatch for the Indian grid.

Generators are stacked from cheapest to most expensive marginal cost and
dispatched in that order until demand is met. The marginal cost of the last
(partly) dispatched unit sets the market clearing price. If available capacity
cannot cover demand, the remainder is reported as unserved and the price is
set to the value of lost load (VOLL).

Inputs
------
- india_generator_stack.csv : State, Fuel_Type, Capacity_MW, Marginal_Cost_Rs_per_MWh
- india_electricity_data_updated.csv : daily state data (Max Demand Met in MW,
  Energy Met in MU/day)
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Generator-stack names that differ from the demand dataset
STATE_NAME_MAP = {"DNH and DD": "DD & DNH"}

# Share of nameplate capacity assumed available at the time of dispatch.
# These are rough planning assumptions (RE capacity factors, planned/forced
# outages, gas supply constraints) -- override them to run sensitivities.
DEFAULT_AVAILABILITY = {
    "Solar": 0.25,
    "Wind": 0.30,
    "Large Hydro": 0.45,
    "Small Hydro": 0.40,
    "Coal": 0.75,
    "Lignite": 0.70,
    "Nuclear": 0.80,
    "Biopower": 0.50,
    "Gas": 0.30,
    "Diesel": 0.90,
}

# Value of lost load: price when demand exceeds available supply
DEFAULT_VOLL = 20000.0  # Rs/MWh (matches the exchange price ceiling ~Rs 20/kWh)


@dataclass
class DispatchResult:
    demand_mw: float
    dispatched_mw: float
    unserved_mw: float
    clearing_price: float        # Rs/MWh
    marginal_fuel: str           # fuel setting the price ("Unserved" if short)
    total_cost_rs_per_h: float   # sum of marginal cost x dispatch
    schedule: pd.DataFrame       # per-generator dispatch


def load_generator_stack(path="india_generator_stack.csv"):
    gen = pd.read_csv(path)
    gen["State"] = gen["State"].replace(STATE_NAME_MAP)
    return gen


def build_supply_stack(gen, state=None, availability=DEFAULT_AVAILABILITY):
    """
    Build the merit-order supply curve.

    state=None aggregates all states by fuel into a single national stack
    (India runs one synchronous grid). Pass a state name for a state-level
    stack. availability=None uses full nameplate capacity.
    """
    df = gen if state is None else gen[gen["State"] == state]
    if df.empty:
        raise ValueError(f"No generators found for state {state!r}")

    stack = (
        df.groupby(["Fuel_Type", "Marginal_Cost_Rs_per_MWh"], as_index=False)["Capacity_MW"]
        .sum()
    )
    factor = 1.0 if availability is None else stack["Fuel_Type"].map(availability).fillna(1.0)
    stack["Available_MW"] = stack["Capacity_MW"] * factor

    # Stable sort so equal-cost fuels keep a deterministic order
    stack = stack.sort_values(
        ["Marginal_Cost_Rs_per_MWh", "Fuel_Type"], kind="mergesort"
    ).reset_index(drop=True)
    stack["Cum_Available_MW"] = stack["Available_MW"].cumsum()
    return stack


def merit_order_dispatch(demand_mw, stack, voll=DEFAULT_VOLL):
    """Dispatch a single demand level (MW) against a supply stack."""
    if demand_mw < 0 or np.isnan(demand_mw):
        raise ValueError(f"Demand must be a non-negative number, got {demand_mw}")

    avail = stack["Available_MW"].to_numpy()
    cum_before = stack["Cum_Available_MW"].to_numpy() - avail

    # Each unit supplies whatever demand is left after cheaper units, up to its availability
    dispatch = np.clip(demand_mw - cum_before, 0.0, avail)
    dispatched = dispatch.sum()
    unserved = max(demand_mw - dispatched, 0.0)

    schedule = stack.assign(
        Dispatch_MW=dispatch,
        Utilisation=np.divide(dispatch, avail, out=np.zeros_like(avail), where=avail > 0),
    )

    if unserved > 1e-6:
        price, marginal = voll, "Unserved"
    elif dispatched <= 0:
        price, marginal = 0.0, "None"
    else:
        last = np.flatnonzero(dispatch > 0)[-1]
        price = float(stack["Marginal_Cost_Rs_per_MWh"].iat[last])
        marginal = stack["Fuel_Type"].iat[last]

    cost = float((dispatch * stack["Marginal_Cost_Rs_per_MWh"].to_numpy()).sum())

    return DispatchResult(
        demand_mw=float(demand_mw),
        dispatched_mw=float(dispatched),
        unserved_mw=float(unserved),
        clearing_price=price,
        marginal_fuel=marginal,
        total_cost_rs_per_h=cost,
        schedule=schedule,
    )


def _dispatch_series(demand, stack, voll):
    """Vectorised dispatch of many demand values against one stack."""
    demand = np.asarray(demand, dtype=float)
    avail = stack["Available_MW"].to_numpy()
    cost = stack["Marginal_Cost_Rs_per_MWh"].to_numpy()
    cum = stack["Cum_Available_MW"].to_numpy()
    fuels = stack["Fuel_Type"].to_numpy()

    # (n_demand, n_units) dispatch matrix
    dispatch = np.clip(demand[:, None] - (cum - avail)[None, :], 0.0, avail[None, :])
    dispatched = dispatch.sum(axis=1)
    unserved = np.maximum(demand - dispatched, 0.0)

    # Marginal unit = first unit whose cumulative capacity reaches demand
    idx = np.searchsorted(cum, demand, side="left")
    short = unserved > 1e-6
    idx_safe = np.minimum(idx, len(stack) - 1)

    price = np.where(short, voll, cost[idx_safe])
    marginal = np.where(short, "Unserved", fuels[idx_safe])
    zero = demand <= 0
    price[zero] = 0.0
    marginal[zero] = "None"

    out = pd.DataFrame({
        "Dispatched_MW": dispatched,
        "Unserved_MW": unserved,
        "Clearing_Price_Rs_per_MWh": price,
        "Marginal_Fuel": marginal,
        "Total_Cost_Rs_per_h": dispatch @ cost,
    })
    per_fuel = pd.DataFrame(dispatch, columns=[f"{f}_MW" for f in fuels])
    per_fuel = per_fuel.T.groupby(level=0, sort=False).sum().T  # merge duplicate fuel columns
    return pd.concat([out, per_fuel], axis=1)


def run_dispatch(
    demand_df,
    gen,
    demand_col="Max Demand Met",
    level="national",
    availability=DEFAULT_AVAILABILITY,
    voll=DEFAULT_VOLL,
):
    """
    Run merit-order dispatch over the full time series.

    demand_col : "Max Demand Met" (peak MW) or "Energy Met" (MU/day, converted
                 to average MW = MU * 1000 / 24).
    level      : "national" -> sum demand across states per date, one stack.
                 "state"    -> dispatch each state against its own stack.
                 States with no generator data are skipped with a warning.
    """
    df = demand_df[["Date", "State", demand_col]].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df["Demand_MW"] = df[demand_col] * (1000 / 24) if demand_col == "Energy Met" else df[demand_col]

    if level == "national":
        daily = df.groupby("Date", as_index=False)["Demand_MW"].sum()
        stack = build_supply_stack(gen, None, availability)
        res = _dispatch_series(daily["Demand_MW"], stack, voll)
        return pd.concat([daily.reset_index(drop=True), res], axis=1)

    if level == "state":
        have_gen = set(gen["State"])
        missing = sorted(set(df["State"]) - have_gen)
        if missing:
            print(f"Warning: no generator data for {missing}; skipped.")
        parts = []
        for state, grp in df[df["State"].isin(have_gen)].groupby("State"):
            stack = build_supply_stack(gen, state, availability)
            grp = grp[["Date", "State", "Demand_MW"]].reset_index(drop=True)
            parts.append(pd.concat([grp, _dispatch_series(grp["Demand_MW"], stack, voll)], axis=1))
        out = pd.concat(parts, ignore_index=True)
        fuel_cols = [c for c in out.columns if c.endswith("_MW") and c not in
                     ("Demand_MW", "Dispatched_MW", "Unserved_MW")]
        out[fuel_cols] = out[fuel_cols].fillna(0.0)
        return out.sort_values(["Date", "State"], ignore_index=True)

    raise ValueError("level must be 'national' or 'state'")


if __name__ == "__main__":
    demand = pd.read_csv("india_electricity_data_updated.csv")
    gen = load_generator_stack()

    stack = build_supply_stack(gen)
    print("National supply stack:\n", stack, "\n")

    r = merit_order_dispatch(200_000, stack)
    print(f"200 GW -> price Rs {r.clearing_price:.0f}/MWh, marginal = {r.marginal_fuel}, "
          f"unserved = {r.unserved_mw:.0f} MW\n")

    nat = run_dispatch(demand, gen, level="national")
    print(nat[["Date", "Demand_MW", "Clearing_Price_Rs_per_MWh", "Marginal_Fuel", "Unserved_MW"]].tail())
    print("\nMarginal fuel share:\n", nat["Marginal_Fuel"].value_counts(normalize=True).round(3))
