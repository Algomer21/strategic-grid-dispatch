"""
Dispatch models for the Indian grid: merit order, single-region LP, and a
state-level LP with distance-based transmission losses.

Developed and validated step by step in notebooks/02_merit_order.ipynb.
All modelling assumptions live in the constants below so they can be
reviewed and changed in one place.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------

# Share of nameplate capacity available at the daily peak. Used all year in the
# constant model; in the seasonal model, solar, wind and hydro are replaced month
# by month from data/raw/seasonal_availability.csv (same 12-month average) and
# every other fuel, including coal, keeps the value here.
AVAILABILITY = {
    "Solar": 0.25, "Wind": 0.30, "Large Hydro": 0.45, "Small Hydro": 0.40,
    "Coal": 0.75, "Lignite": 0.70, "Nuclear": 0.80, "Biopower": 0.50,
    "Gas": 0.30, "Diesel": 0.90,
}

VOLL = 10000  # Rs/MWh, price when demand cannot be met

# Transmission loss on a trade between two states:
#   loss = min(LOSS_FIXED + LOSS_PER_1000KM * ROUTING_FACTOR * distance_km / 1000, LOSS_MAX)
LOSS_FIXED = 0.005        # substation/transformer losses at each end
LOSS_PER_1000KM = 0.04    # high-voltage AC line losses
ROUTING_FACTOR = 1.2      # lines are longer than the straight-line distance
LOSS_MAX = 0.10           # cap for very long transfers

STATE_NAME_FIX = {"DNH and DD": "DD & DNH"}  # generator file -> demand file names
EXCLUDED_STATES = ["DVC"]                    # demand data but no generator data


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_generators(coal_tiers=True, availability=AVAILABILITY):
    """
    Generator stack: one row per state-fuel pair, with Available_MW.

    coal_tiers=True replaces the flat coal cost with the state's tier cost
    from data/raw/coal_cost_tiers.csv.
    """
    gen = pd.read_csv(RAW / "india_generator_stack.csv")
    gen["State"] = gen["State"].replace(STATE_NAME_FIX)

    if coal_tiers:
        tiers = pd.read_csv(RAW / "coal_cost_tiers.csv").set_index("State")
        is_coal = gen["Fuel_Type"] == "Coal"
        gen.loc[is_coal, "Marginal_Cost_Rs_per_MWh"] = (
            gen.loc[is_coal, "State"].map(tiers["Coal_Cost_Rs_per_MWh"])
        )
        missing = gen.loc[is_coal, "Marginal_Cost_Rs_per_MWh"].isna()
        if missing.any():
            raise ValueError(f"No coal tier for: {gen.loc[is_coal][missing]['State'].tolist()}")

    gen["Available_MW"] = gen["Capacity_MW"] * gen["Fuel_Type"].map(availability)
    return gen


def load_demand(column="Max Demand Met"):
    """Daily demand as a wide table: one row per date, one column per state."""
    demand = pd.read_csv(PROCESSED / "india_electricity_data_updated.csv")
    demand["Date"] = pd.to_datetime(demand["Date"])
    wide = demand.pivot(index="Date", columns="State", values=column)
    return wide.drop(columns=EXCLUDED_STATES, errors="ignore")


def load_coordinates():
    """State capital coordinates, indexed by state name."""
    return pd.read_csv(RAW / "state_coordinates.csv").set_index("State")


def load_seasonal_availability():
    """Monthly availability factors for weather-driven fuels: rows = month 1-12, columns = fuel."""
    return pd.read_csv(RAW / "seasonal_availability.csv").set_index("Month")


def availability_for_month(seasonal, month, base=AVAILABILITY):
    """Availability for every fuel in one month: seasonal fuels from `seasonal`, the rest from `base`."""
    return {**base, **seasonal.loc[month].to_dict()}


# ---------------------------------------------------------------------------
# Distances and losses
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between points given in degrees."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = np.sin(dlat / 2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2)**2
    return 2 * R * np.arcsin(np.sqrt(h))


def distance_matrix(coords, states):
    """Straight-line distance (km) between every pair of states."""
    c = coords.loc[states]
    lat, lon = c["Lat"].to_numpy(), c["Lon"].to_numpy()
    km = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    return pd.DataFrame(km, index=states, columns=states)


def loss_matrix(coords, states, fixed=LOSS_FIXED, per_1000km=LOSS_PER_1000KM,
                routing=ROUTING_FACTOR, cap=LOSS_MAX):
    """Loss factor for sending power from row state to column state (diagonal NaN)."""
    dist = distance_matrix(coords, states)
    loss = np.minimum(fixed + per_1000km * routing * dist / 1000, cap)
    return loss.mask(np.eye(len(states), dtype=bool))


# ---------------------------------------------------------------------------
# Single-market dispatch
# ---------------------------------------------------------------------------

def merit_order_dispatch(demand, plants, voll=VOLL):
    """
    Merit-order dispatch. `plants` has columns name, capacity_mw, cost.
    The last plant running sets the price; unmet demand is priced at VOLL.
    """
    # Arrange generators in increasing order of marginal cost
    plants = plants.sort_values("cost")

    remaining = demand
    total_cost = 0
    clearing_mc = None
    clearing_gen = None
    dispatch = {}

    for row in plants.itertuples():
        if remaining > row.capacity_mw:
            # Demand is bigger than this plant: run it at full capacity
            dispatch[row.name] = row.capacity_mw
            remaining -= row.capacity_mw
            total_cost += row.capacity_mw * row.cost
        else:
            # This plant covers what's left: it is the marginal plant
            dispatch[row.name] = remaining
            clearing_mc = row.cost
            clearing_gen = row.name
            total_cost += remaining * row.cost
            remaining = 0
            break

    surplus = plants["capacity_mw"].sum() - demand

    if remaining > 0:
        # Demand not met: scarcity price
        clearing_mc = voll
        clearing_gen = "Unserved"
        status = f"deficit of {remaining} MW"
    else:
        status = f"sufficient, surplus capacity {surplus} MW"

    return {
        "dispatch": dispatch,
        "clearing_gen": clearing_gen,
        "clearing_price": clearing_mc,
        "total_cost": total_cost,
        "status": status,
    }


def lp_dispatch(demand, plants, voll=VOLL):
    """
    Economic dispatch as a linear program.

    Variables : g_i = MW from each plant, u = unserved MW
    Objective : minimise  sum(cost_i * g_i) + voll * u
    Subject to: sum(g_i) + u = demand          (balance)
                0 <= g_i <= capacity_i         (plant limits)
                u >= 0
    """
    n = len(plants)
    c = list(plants["cost"]) + [voll]
    A_eq = [[1] * (n + 1)]
    bounds = [(0, cap) for cap in plants["capacity_mw"]] + [(0, None)]

    res = linprog(c=c, A_eq=A_eq, b_eq=[demand], bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"LP failed: {res.message}")

    g = res.x[:n]
    return {
        "dispatch": dict(zip(plants["name"], g)),
        "unserved_mw": res.x[n],
        "clearing_price": res.eqlin.marginals[0],  # shadow price of the balance constraint
        "fuel_cost": float(np.dot(plants["cost"], g)),
        "total_cost_incl_voll": res.fun,
    }


# ---------------------------------------------------------------------------
# State-level dispatch with transmission losses
# ---------------------------------------------------------------------------

class LossDispatchModel:
    """
    State-level dispatch with distance-based transmission losses, no line limits.

    Variables (in this order):
        g[k]     MW from plant k (one per state-fuel row of `gen`)
        u[s]     unserved MW in state s
        f[s->t]  MW sent from state s to state t, for every s != t
    Objective : minimise  sum c*g + VOLL * sum u
    Subject to (one row per state t):
        own generation + u_t + sum_s (1 - loss[s,t]) * f[s->t] - sum_k f[t->k] = D_t

    The constraint matrix depends only on the plants and losses, so it is built
    once; solve() then only swaps in each day's demand.
    """

    def __init__(self, gen, loss, states, voll=VOLL):
        self.states = list(states)
        self.gen = gen[gen["State"].isin(self.states)].reset_index(drop=True)
        self.loss = loss.loc[self.states, self.states]
        self.voll = voll

        nG, nS = len(self.gen), len(self.states)
        pos = {s: i for i, s in enumerate(self.states)}
        self.pairs = [(s, t) for s in self.states for t in self.states if s != t]
        nP = len(self.pairs)
        self.u_start, self.f_start = nG, nG + nS
        n_vars = nG + nS + nP

        # Objective: plant costs, VOLL for unserved, flows free
        self.c = np.zeros(n_vars)
        self.c[:nG] = self.gen["Marginal_Cost_Rs_per_MWh"]
        self.c[self.u_start:self.f_start] = voll

        # Sparse balance matrix, built from (row, column, value) triples
        rows, cols, vals = [], [], []
        for k, state in enumerate(self.gen["State"]):          # own generation
            rows.append(pos[state]); cols.append(k); vals.append(1.0)
        for s in range(nS):                                     # unserved
            rows.append(s); cols.append(self.u_start + s); vals.append(1.0)
        self.pair_loss = np.array([self.loss.loc[s, t] for s, t in self.pairs])
        for p, (s, t) in enumerate(self.pairs):                 # flows
            rows.append(pos[t]); cols.append(self.f_start + p); vals.append(1 - self.pair_loss[p])
            rows.append(pos[s]); cols.append(self.f_start + p); vals.append(-1.0)
        self.A_eq = coo_matrix((vals, (rows, cols)), shape=(nS, n_vars)).tocsr()

        self.bounds = ([(0, cap) for cap in self.gen["Available_MW"]] +
                       [(0, None)] * nS +
                       [(0, None)] * nP)

    def solve(self, demand, availability=None):
        """
        Dispatch one day. `demand` is a Series indexed by state (MW).

        `availability` (dict fuel -> factor) overrides the plant limits for this day
        only, e.g. a month's seasonal factors. None keeps the limits the model was
        built with. Only the bounds change; the constraint matrix is reused.
        """
        b_eq = demand.reindex(self.states).to_numpy(dtype=float)
        if np.isnan(b_eq).any():
            raise ValueError("Demand missing for some states")

        bounds = self.bounds
        if availability is not None:
            cap = self.gen["Capacity_MW"] * self.gen["Fuel_Type"].map(availability)
            if cap.isna().any():
                raise ValueError("Availability missing for some fuels")
            bounds = [(0, c) for c in cap] + self.bounds[len(self.gen):]

        res = linprog(c=self.c, A_eq=self.A_eq, b_eq=b_eq, bounds=bounds, method="highs")
        if not res.success:
            raise RuntimeError(f"LP failed: {res.message}")

        x = res.x
        generation = self.gen.assign(Available_MW=[ub for _, ub in bounds[:self.u_start]],
                                     Dispatch_MW=x[:self.u_start])

        sent = x[self.f_start:]
        used = sent > 1e-6
        flows = pd.DataFrame({
            "From": [s for (s, _), u in zip(self.pairs, used) if u],
            "To": [t for (_, t), u in zip(self.pairs, used) if u],
            "Sent_MW": sent[used],
            "Loss_pct": self.pair_loss[used] * 100,
        })
        flows["Received_MW"] = flows["Sent_MW"] * (1 - flows["Loss_pct"] / 100)
        flows = flows.sort_values("Sent_MW", ascending=False).reset_index(drop=True)

        states = pd.DataFrame(index=pd.Index(self.states, name="State"))
        states["Demand_MW"] = b_eq
        states["Generation_MW"] = generation.groupby("State")["Dispatch_MW"].sum().reindex(self.states).fillna(0)
        states["Unserved_MW"] = x[self.u_start:self.f_start]
        states["Imports_received_MW"] = flows.groupby("To")["Received_MW"].sum().reindex(self.states).fillna(0)
        states["Exports_sent_MW"] = flows.groupby("From")["Sent_MW"].sum().reindex(self.states).fillna(0)
        states["Price"] = res.eqlin.marginals  # lambda_t: shadow price of each state's balance

        return {"states": states, "flows": flows, "generation": generation, "total_cost": res.fun}


def run_all_days(model, demand_wide, seasonal=None):
    """
    Solve `model` for every date in `demand_wide`.

    seasonal=None uses the model's constant availability every day; pass the table
    from load_seasonal_availability() to use each date's monthly factors.

    Returns three tables: state_daily (date x state), flows_daily (date x trade)
    and national_daily (one row per date, incl. generation by fuel).
    """
    state_rows, flow_rows, national_rows = [], [], []

    for date, demand in demand_wide.iterrows():
        availability = None if seasonal is None else availability_for_month(seasonal, date.month)
        out = model.solve(demand, availability)
        st, fl, gn = out["states"], out["flows"], out["generation"]

        state_rows.append(st.reset_index().assign(Date=date))
        flow_rows.append(fl.assign(Date=date))

        lost = (fl["Sent_MW"] - fl["Received_MW"]).sum()
        row = {
            "Date": date,
            "Demand_MW": st["Demand_MW"].sum(),
            "Unserved_MW": st["Unserved_MW"].sum(),
            "Traded_MW": fl["Sent_MW"].sum(),
            "Losses_MW": lost,
            "Total_cost_Rs_per_h": out["total_cost"],
            "Price_min": st["Price"].min(),
            "Price_avg": np.average(st["Price"], weights=st["Demand_MW"]),  # demand-weighted
            "Price_max": st["Price"].max(),
        }
        row.update(gn.groupby("Fuel_Type")["Dispatch_MW"].sum().add_suffix("_MW").to_dict())
        national_rows.append(row)

    first = ["Date", "State"]
    state_daily = pd.concat(state_rows, ignore_index=True)
    state_daily = state_daily[first + [c for c in state_daily.columns if c not in first]]
    flows_daily = pd.concat(flow_rows, ignore_index=True)
    flows_daily = flows_daily[["Date"] + [c for c in flows_daily.columns if c != "Date"]]
    national_daily = pd.DataFrame(national_rows)
    return state_daily, flows_daily, national_daily
