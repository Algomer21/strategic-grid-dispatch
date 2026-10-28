"""
Strategic bidding and market power (Part 3).

Developed step by step in notebooks/13_market_structure.ipynb, following the plan
in docs/part3_plan.md. Every generator block (one row per state and fuel) belongs
to a firm and has a role that says how it may bid.
"""

import numpy as np
import pandas as pd

from dispatch import LOSS_MAX, VOLL

# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------

# How each fuel may bid (plan, Decisions 2-3):
#   strategic  the firm chooses its bid (cost + adder) and may withhold capacity
#   must-run   solar and wind have must-run status in India: bid 0, never withheld,
#              still paid the clearing price
#   cost       always bids its true cost (nuclear runs flat out; biopower and diesel
#              are small)
ROLES = {
    "Coal": "strategic", "Lignite": "strategic", "Gas": "strategic",
    "Large Hydro": "strategic", "Small Hydro": "strategic",
    "Solar": "must-run", "Wind": "must-run",
    "Nuclear": "cost", "Biopower": "cost", "Diesel": "cost",
}


# ---------------------------------------------------------------------------
# Firms
# ---------------------------------------------------------------------------

def firm_blocks(gen, roles=ROLES):
    """
    Add a Firm and a Role to every generator block. One firm per state, so the
    firm is the block's state. Returns a copy; `gen` is not changed.
    """
    role = gen["Fuel_Type"].map(roles)
    if role.isna().any():
        missing = sorted(gen.loc[role.isna(), "Fuel_Type"].unique())
        raise ValueError(f"No role for fuel(s): {missing}")
    return gen.assign(Firm=gen["State"], Role=role)


# Part 1's five regions. There is no regional market while lines have no limits,
# so regional figures are descriptive only; they matter for the transmission-limits
# what-if (Stage 7).
REGIONS = {
    **{s: "North" for s in ["Punjab", "Haryana", "Delhi", "NR UP", "Rajasthan", "HP",
                            "J&K(UT) & Ladakh(UT)", "Chandigarh", "Uttarakhand"]},
    **{s: "West" for s in ["Gujarat", "MP", "Chhattisgarh", "WR Maharashtra", "Goa", "DD & DNH"]},
    **{s: "South" for s in ["Andhra Pradesh", "Telangana", "SR Karnataka", "Tamil Nadu",
                            "Kerala", "Puducherry"]},
    **{s: "East" for s in ["Bihar", "ER Odisha", "West Bengal", "Sikkim"]},
    **{s: "NorthEast" for s in ["Assam", "Arunachal Pradesh", "Manipur", "NER Meghalaya",
                                "Mizoram", "Nagaland", "Tripura"]},
}


# ---------------------------------------------------------------------------
# Market structure (Stage 1): no optimisation, capacity and demand only
# ---------------------------------------------------------------------------

def firm_supply(blocks, available, roles=("strategic",)):
    """
    Available MW per date and firm, counting only blocks with one of `roles`
    (default: strategic, what a firm can price high or withhold).

    blocks:    firm_blocks() output (State, Fuel_Type, Firm, Role)
    available: long table Date, State, Fuel_Type, Available_MW (forecast.available_by_fuel)
    Returns a date x firm table (MW), 0 where a firm has none of those blocks.
    """
    keys = blocks.drop_duplicates(["State", "Fuel_Type"])[["State", "Fuel_Type", "Firm", "Role"]]
    av = available.merge(keys, on=["State", "Fuel_Type"], how="left")
    if av["Firm"].isna().any():
        missing = av.loc[av["Firm"].isna(), ["State", "Fuel_Type"]].drop_duplicates().values.tolist()
        raise ValueError(f"Available MW for blocks with no firm: {missing}")
    av = av[av["Role"].isin(roles)]
    return av.pivot_table(index="Date", columns="Firm", values="Available_MW", aggfunc="sum", fill_value=0.0)


def shares(firm_mw):
    """Each firm's share (0-1) of the row total: a date x firm table."""
    return firm_mw.div(firm_mw.sum(axis=1), axis=0)


def hhi(share):
    """Herfindahl-Hirschman Index per row: sum of (share in %)^2, 0-10,000."""
    return ((share * 100) ** 2).sum(axis=1)


def rsi(total_mw, firm_mw, requirement):
    """
    Residual Supply Index per date and firm: (all available MW - firm's MW) / requirement.
    Below 1, the market cannot be served without the firm (it is pivotal).

    total_mw:    all available MW per date (every block, every role)
    firm_mw:     date x firm table of the MW each firm controls
    requirement: MW the market must cover per date (here demand + losses)
    """
    return firm_mw.rsub(total_mw, axis=0).div(requirement, axis=0)


def joint_rsi(total_mw, firm_mw, requirement, k):
    """RSI of the k largest firms on each date taken together."""
    top_k = firm_mw.apply(lambda row: row.nlargest(k).sum(), axis=1)
    return (total_mw - top_k) / requirement


# ---------------------------------------------------------------------------
# Bids, withholding, profit (Stage 2)
# ---------------------------------------------------------------------------

# Highest bid a block may make (Step 23, decision 1). Power delivered over the longest
# route loses LOSS_MAX (10%), so a bid b costs up to b / (1 - LOSS_MAX) where it lands.
# Keeping that below VOLL (Rs 10,000, the price cap) means the LP never prefers leaving
# demand unserved to buying a firm's power, and no state's price goes above the cap:
# 10,000 x 0.9 = 9,000, minus Rs 10 to stay off an exact tie with VOLL -> Rs 8,990.
MAX_BID = VOLL * (1 - LOSS_MAX) - 10


def make_bids(blocks, adders, max_bid=MAX_BID):
    """
    Bids for solve(costs=...): {(state, fuel): Rs/MWh}.

    adders: {firm: adder in Rs/MWh}. Each listed firm's strategic blocks bid
    cost + adder + 1 when the adder is above 0 (the +1 keeps a bid off another
    block's round-number cost, Step 23 decision 2), capped at `max_bid`.
    Blocks not returned bid their true cost: must-run (0), cost role, and
    strategic blocks of firms with adder 0 or not listed.
    """
    bids = {}
    for row in blocks.itertuples():
        adder = adders.get(row.Firm, 0)
        if row.Role == "strategic" and adder > 0:
            bids[(row.State, row.Fuel_Type)] = min(row.Marginal_Cost_Rs_per_MWh + adder + 1, max_bid)
    return bids


def make_availability(base, blocks, withholding):
    """
    Availability for solve(availability=...) with withholding applied.

    base:        that day's availability dict (fuel or (state, fuel) keys)
    withholding: {firm: share 0-1}. Each listed firm's strategic blocks get
                 base factor x (1 - share). Must-run and cost blocks never change.
    Returns a new dict; `base` is not changed.
    """
    out = dict(base)
    for row in blocks.itertuples():
        w = withholding.get(row.Firm, 0)
        if row.Role == "strategic" and w > 0:
            if not 0 <= w <= 1:
                raise ValueError(f"Withholding share for {row.Firm} must be 0-1, got {w}")
            key = (row.State, row.Fuel_Type)
            out[key] = base.get(key, base.get(row.Fuel_Type)) * (1 - w)
    return out


def firm_profit(result, blocks):
    """
    Profit per firm (Rs per peak hour) from a solve() result:
    sum over its blocks of (home-state price - TRUE cost) x MW dispatched.
    Dispatch follows the bids; profit always uses true cost. Includes the firm's
    must-run solar and wind (true cost 0), which earn the price it helps set.
    """
    g = result["generation"]
    price = g["State"].map(result["states"]["Price"])
    margin = (price - g["Marginal_Cost_Rs_per_MWh"]) * g["Dispatch_MW"]
    firm = g.merge(blocks[["State", "Fuel_Type", "Firm"]], on=["State", "Fuel_Type"], how="left")["Firm"]
    return margin.groupby(firm.values).sum()


def consumer_cost(result):
    """What consumers pay at the peak (Rs per hour): sum over states of price x demand."""
    st = result["states"]
    return float((st["Price"] * st["Demand_MW"]).sum())


def generation_cost(result):
    """True cost of the generation dispatched (Rs per hour), ignoring bids."""
    g = result["generation"]
    return float((g["Marginal_Cost_Rs_per_MWh"] * g["Dispatch_MW"]).sum())


# ---------------------------------------------------------------------------
# One strategic firm (Stage 3)
# ---------------------------------------------------------------------------

def bid_levels(blocks, adders=None, max_bid=MAX_BID):
    """Each block's bid (Rs/MWh) when the firms in `adders` mark up and everyone else bids cost."""
    bids = make_bids(blocks, adders or {}, max_bid)
    return pd.Series([bids.get((s, f), c) for s, f, c in
                      zip(blocks["State"], blocks["Fuel_Type"], blocks["Marginal_Cost_Rs_per_MWh"])],
                     index=blocks.index)


def bid_candidates(blocks, firm, max_bid=MAX_BID, step=250, others=None):
    """
    Adders to try for `firm` (Step 24, decision 1):
    - Rs 1 below every other block's bid level: a price-setting firm's profit rises with
      its bid until it passes a rival, so peaks sit just below rivals. For a firm block
      of cost c and a rival level L > c, the adder giving bid L - 1 is L - 2 - c
      (bids are cost + adder + 1)
    - the cap: an adder large enough to put every strategic block at `max_bid`
    - a regular grid every `step`, as a safety net (losses shift peaks between levels)
    `others` = {firm: adder} of rivals that mark up (Stage 5): their bids, not their costs,
    are the levels to undercut. Always includes 0 (bid cost). Returns a sorted list.
    """
    own = blocks[(blocks["Firm"] == firm) & (blocks["Role"] == "strategic")]
    if own.empty:
        raise ValueError(f"{firm} has no strategic blocks")
    own_costs = sorted(own["Marginal_Cost_Rs_per_MWh"].unique())
    rivals = {f: a for f, a in (others or {}).items() if f != firm}
    other_bids = bid_levels(blocks, rivals, max_bid)[blocks["Firm"] != firm]
    levels = sorted(l for l in other_bids.unique() if l <= max_bid)

    cap_adder = max_bid - 1 - own_costs[0]
    adders = {0, cap_adder}
    adders |= {l - 2 - c for c in own_costs for l in levels if l - 2 - c > 0}
    adders |= set(range(step, int(cap_adder), step))
    # A firm whose cheapest block already costs more than the cap can only bid cost
    return sorted({0} | {int(round(a)) for a in adders if 0 <= a <= cap_adder})


def contract_profit(result, blocks, firm, contracted_mw):
    """
    Profit change from a forward contract (Stage 7): the firm has sold `contracted_mw`
    at a fixed price agreed in advance, so on that volume it pays back the spot price
    (a contract for differences). Returns -(home-state price x contracted MW) summed over
    the firm's states; the fixed contract revenue is a constant and is left out, as it
    doesn't change which bid is best.
    """
    price = result["states"]["Price"]
    return -sum(price[s] * mw for s, mw in contracted_mw.items())


def evaluate(model, blocks, firm, demand, availability, adder, withholding, others=None,
             contracted_mw=None, max_bid=MAX_BID):
    """
    Run the market with `firm` playing (adder, withholding). Everyone else bids cost, or
    the adders in `others` (Stage 5). `contracted_mw` = {state: MW} sold forward by the
    firm (Stage 7); its profit then includes contract_profit().
    """
    adders = {**(others or {}), firm: adder}
    out = model.solve(demand, make_availability(availability, blocks, {firm: withholding}),
                      costs=make_bids(blocks, adders, max_bid))
    st = out["states"]
    profit = firm_profit(out, blocks).get(firm, 0.0)
    if contracted_mw:
        profit += contract_profit(out, blocks, firm, contracted_mw)
    return {"Adder": adder, "Withholding": withholding, "Profit": profit,
            "Price_avg": float((st["Price"] * st["Demand_MW"]).sum() / st["Demand_MW"].sum()),
            "Consumer_cost": consumer_cost(out), "Generation_cost": generation_cost(out),
            "Unserved_MW": float(st["Unserved_MW"].sum())}, out


def best_response(model, blocks, firm, demand, availability,
                  withholding_grid=(0.0, 0.1, 0.2, 0.3), max_withholding=0.3,
                  fine_step=25, fine_width=250, fine_withholding=0.05,
                  others=None, contracted_mw=None, max_bid=MAX_BID):
    """
    `firm`'s most profitable (adder, withholding) on one day, everyone else at cost
    or at the adders in `others` (Step 24, decisions 1-2):
    1. coarse: every bid_candidates() adder x every share in `withholding_grid`
    2. fine: around the best, adders every `fine_step` within +-`fine_width`,
       withholding +-`fine_withholding` (clipped to 0-`max_withholding`)
    Bidding cost (0, 0) is always tried, so the best never earns less than it.
    Bid only (Stages 4-7): withholding_grid=(0.0,), max_withholding=0.

    Returns a dict: best adder, withholding and profit, profit at cost, the solve()
    result of the best strategy and a table of every strategy tried.
    """
    tried = {}

    def run(a, w):
        key = (round(a), round(w, 4))
        if key not in tried:
            tried[key] = evaluate(model, blocks, firm, demand, availability, *key, others=others,
                                  contracted_mw=contracted_mw, max_bid=max_bid)
        return tried[key][0]["Profit"]

    candidates = bid_candidates(blocks, firm, max_bid=max_bid, others=others)
    for a in candidates:
        for w in withholding_grid:
            run(a, w)
    a0, w0 = max(tried, key=lambda k: tried[k][0]["Profit"])

    cap_adder = candidates[-1]
    for a in range(max(0, a0 - fine_width), min(cap_adder, a0 + fine_width) + 1, fine_step):
        for w in (w0 - fine_withholding, w0, w0 + fine_withholding):
            if 0 <= w <= max_withholding + 1e-9:
                run(a, w)

    best = max(tried, key=lambda k: tried[k][0]["Profit"])
    table = pd.DataFrame([v[0] for v in tried.values()]).sort_values(["Withholding", "Adder"]).reset_index(drop=True)
    return {"firm": firm, "adder": best[0], "withholding": best[1],
            "profit": tried[best][0]["Profit"], "profit_at_cost": tried[(0, 0.0)][0]["Profit"],
            "best": tried[best][1], "at_cost": tried[(0, 0.0)][1], "table": table}


# ---------------------------------------------------------------------------
# Many days, several strategic firms (Stages 4-7)
# ---------------------------------------------------------------------------

# Firms with at least this much strategic capacity are players; smaller firms bid cost
# (plan, computing budget). 24 of 30 firms.
MIN_PLAYER_MW = 1000

# Stage 3 found raising the bid always beat withholding and the joint search never beat
# the best bid alone, so Stages 4-7 search the bid only (4x faster).
BID_ONLY = {"withholding_grid": (0.0,), "max_withholding": 0.0}


def players(blocks, min_mw=MIN_PLAYER_MW):
    """Firms with >= min_mw of strategic capacity, largest first."""
    mw = blocks[blocks["Role"] == "strategic"].groupby("Firm")["Capacity_MW"].sum()
    return mw[mw >= min_mw].sort_values(ascending=False).index.tolist()


def market_summary(result, blocks):
    """One-line summary of a solve() result: average price, consumer and true cost, profits."""
    st = result["states"]
    return {"Price_avg": float(np.average(st["Price"], weights=st["Demand_MW"])),
            "Price_max": float(st["Price"].max()),
            "Consumer_cost": consumer_cost(result), "Generation_cost": generation_cost(result),
            "Unserved_MW": float(st["Unserved_MW"].sum()),
            "Profit_total": float(firm_profit(result, blocks).sum())}


def equilibrium(model, blocks, demand, availability, firms, max_rounds=5, tol=1000.0,
                contracts=None, max_bid=MAX_BID):
    """
    Best-response iteration (plan, The game): start with everyone bidding cost; each round,
    every firm in `firms` in turn picks its best bid with the others' current bids fixed.
    A firm only moves if it gains more than `tol` Rs per peak hour, so ties between
    equally good bids don't count as a change.

    contracts: {firm: {state: MW}} sold forward (Stage 7), see contract_profit().
    Stops when no firm moves (status "converged"), a set of bids repeats ("cycle"), or
    after `max_rounds` ("round limit"). Returns the adders, status, rounds and the final
    market result.
    """
    contracts = contracts or {}
    adders = {f: 0 for f in firms}
    seen = {tuple(adders.values())}
    status = "round limit"
    for rnd in range(1, max_rounds + 1):
        changed = False
        for f in firms:
            others = {g: a for g, a in adders.items() if g != f and a > 0}
            kw = {"others": others, "contracted_mw": contracts.get(f), "max_bid": max_bid}
            br = best_response(model, blocks, f, demand, availability, **BID_ONLY, **kw)
            current = evaluate(model, blocks, f, demand, availability, adders[f], 0.0, **kw)[0]["Profit"]
            if br["profit"] > current + tol:
                adders[f] = br["adder"]
                changed = True
        state = tuple(adders.values())
        if not changed:
            status = "converged"
            break
        if state in seen:
            status = "cycle"
            break
        seen.add(state)
    result = model.solve(demand, availability, costs=make_bids(blocks, adders, max_bid))
    return {"adders": adders, "status": status, "rounds": rnd, "result": result}


# Parallel runs over many days. Each worker process builds the market once; a job is one
# day (demand, availability) plus what to do with it. Results are plain dicts.

_WORKER = {}


def _init_worker():
    from dispatch import LossDispatchModel, load_coordinates, load_demand, load_generators, loss_matrix
    gen = load_generators()
    states = list(load_demand().columns)
    _WORKER["model"] = LossDispatchModel(gen, loss_matrix(load_coordinates(), states), states)
    _WORKER["blocks"] = firm_blocks(gen)


def _state_prices(result, prefix):
    return {f"{prefix}{s}": p for s, p in result["states"]["Price"].items()}


def job_single(job):
    """Stage 4: each firm in job["firms"] alone (everyone else at cost). One row per firm."""
    model, blocks = _WORKER["model"], _WORKER["blocks"]
    rows = []
    for f in job["firms"]:
        br = best_response(model, blocks, f, job["demand"], job["availability"], **BID_ONLY,
                           max_bid=job.get("max_bid", MAX_BID))
        best, cost = market_summary(br["best"], blocks), market_summary(br["at_cost"], blocks)
        rows.append({"Date": job["date"], "Firm": f, "Adder": br["adder"],
                     "Profit_best": br["profit"], "Profit_cost": br["profit_at_cost"],
                     **{f"{k}_cost": v for k, v in cost.items()},
                     **{f"{k}_best": v for k, v in best.items()}})
    return rows


def job_equilibrium(job):
    """Stage 5 / 7: all firms in job["firms"] play; returns one national row and the adders."""
    model, blocks = _WORKER["model"], _WORKER["blocks"]
    max_bid = job.get("max_bid", MAX_BID)
    at_cost = model.solve(job["demand"], job["availability"])
    contracts = None
    if job.get("contract_share"):
        # Each firm has sold this share of its at-cost output forward, at its home state
        g = at_cost["generation"].merge(blocks[["State", "Fuel_Type", "Firm"]], on=["State", "Fuel_Type"])
        sold = g.groupby(["Firm", "State"])["Dispatch_MW"].sum() * job["contract_share"]
        contracts = {f: sold.loc[f].to_dict() for f in job["firms"] if f in sold.index.get_level_values(0)}
    eq = equilibrium(model, blocks, job["demand"], job["availability"], job["firms"],
                     max_rounds=job.get("max_rounds", 5), contracts=contracts, max_bid=max_bid)
    cost, best = market_summary(at_cost, blocks), market_summary(eq["result"], blocks)
    profit_cost, profit_eq = firm_profit(at_cost, blocks), firm_profit(eq["result"], blocks)
    row = {"Date": job["date"], "Status": eq["status"], "Rounds": eq["rounds"],
           "Firms_marking_up": sum(a > 0 for a in eq["adders"].values()),
           **{f"{k}_cost": v for k, v in cost.items()}, **{f"{k}_eq": v for k, v in best.items()}}
    if job.get("state_prices"):
        row.update(_state_prices(at_cost, "Pcost_")); row.update(_state_prices(eq["result"], "Peq_"))
    firms = [{"Date": job["date"], "Firm": f, "Adder": eq["adders"][f],
              "Profit_cost": profit_cost.get(f, 0.0), "Profit_eq": profit_eq.get(f, 0.0)} for f in job["firms"]]
    return {"national": row, "firms": firms}


def job_bid_on_forecast(job):
    """
    Stage 6: `firm` chooses its adder on information known the day before, then the market
    clears on the actual day with that adder (everyone else at cost). Strategies:
      perfect      best response on the actual day (upper bound)
      forecast     best response on the median forecast scenario
      robust       the bid_candidates() adder with the best average profit over the
                   10% / median / 90% demand forecast scenarios
      persistence  best response on yesterday's actual scenario
      cost         adder 0
    job: firm, actual (demand, availability), median / q10 / q90 / yesterday scenarios.
    """
    model, blocks = _WORKER["model"], _WORKER["blocks"]
    f = job["firm"]
    d_act, a_act = job["actual"]
    chosen = {"cost": 0,
              "perfect": best_response(model, blocks, f, d_act, a_act, **BID_ONLY)["adder"],
              "forecast": best_response(model, blocks, f, *job["median"], **BID_ONLY)["adder"],
              "persistence": best_response(model, blocks, f, *job["yesterday"], **BID_ONLY)["adder"]}
    scen = [job["q10"], job["median"], job["q90"]]
    avg = {a: np.mean([evaluate(model, blocks, f, d, av, a, 0.0)[0]["Profit"] for d, av in scen])
           for a in bid_candidates(blocks, f)}
    chosen["robust"] = max(avg, key=avg.get)
    rows = []
    for name, a in chosen.items():
        res = evaluate(model, blocks, f, d_act, a_act, a, 0.0)[0]
        rows.append({"Date": job["date"], "Firm": f, "Strategy": name, "Adder": a,
                     "Profit": res["Profit"], "Price_avg": res["Price_avg"],
                     "Consumer_cost": res["Consumer_cost"], "Unserved_MW": res["Unserved_MW"]})
    return rows


def run_parallel(fn, jobs, workers=None):
    """Run fn(job) for every job in worker processes (each builds the market once)."""
    import os
    from concurrent.futures import ProcessPoolExecutor
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        return list(pool.map(fn, jobs, chunksize=1))
