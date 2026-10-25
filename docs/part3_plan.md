# Part 3 plan — Strategic bidding and market power

Agreed 2026-10-25, written while Part 2 (forecasting) is still being built on branch `part2-forecasting`. Results and changes go into [`model_log.md`](model_log.md) as Part 3 steps once work starts; this file is the plan they follow.

---

## Goal

Measure what happens to prices, consumer cost and dispatch when large generators bid above their true cost (raise their bids or withhold capacity) instead of bidding at cost, as Part 1 assumes. Answer:

- **when:** which days
- **where:** which states and regions
- **who:** which firms can do it
- **how much:** what it costs consumers

Then use Part 2's forecasts as the firms' view of tomorrow: do forecast-tight days flag market-power days in advance?

This is research question 2 in the README: what happens when large generators bid strategically instead of at true marginal cost, where does market power show up, and how much does it cost consumers?

## Why this should show something

Coal sets the price on almost every day. Available coal at peak is 216 GW × 0.75 = 162 GW; the most coal dispatched over the 1,917 days is 152 GW (109 GW on average). Most days have plenty of spare coal, so no firm can raise prices, but peak days are tight. Step 9 showed that near a coal-tier step, +100 MW of demand moved the price by about Rs 600. **Market power should be concentrated in a small number of tight days.**

A rough first look (seasonal run, network ignored): the largest firm (UP, ~23.7 GW available) is pivotal on 29 of 1,917 days; spare supply ranges from 16 GW to 137 GW (average 73 GW).

## How Parts 1 and 2 feed Part 3

Part 3 needs, for each day, a **scenario**: demand by state + availability by (state, fuel). **Part 1 supplies the market; Part 2 supplies the scenarios.** Actual and forecast scenarios have the same table shapes, so Part 3's code does not change when a new scenario arrives.

| From | What | Used in Part 3 for | Status |
|---|---|---|---|
| Part 1 | `LossDispatchModel` (LP, losses, locational prices) | Clearing the market for every bid tried | Done |
| Part 1 | Generator stack + coal tiers (`load_generators`) | True costs; firms' blocks | Done |
| Part 1 | `seasonal_*_daily.csv` | Temporary competitive benchmark | Done |
| Part 2, Stage 2 | `availability_daily.csv` (`Date, State, Fuel_Type, Factor`), `daily_availability_lookup`, `solve()` with (state, fuel) keys | Actual supply each day; a firm withholds a share of its weather-based available MW | In progress (`part2-forecasting`) |
| Part 2, Stage 2 | `weather_{state,flows,national}_daily.csv` | **Competitive benchmark (M0)**, replacing `seasonal_*` | In progress |
| Part 2, O5 | Tightness index `(available − demand) / demand` | A firm is pivotal when its share of demand > tightness (RSI < 1) | Planned |
| Part 2, O1 + O4 | D+1 state demand forecast with a range | Stage 6: firms bid on the forecast, the market clears on actual | Planned |
| Part 2, O2 | D+1 availability forecast | Stage 6: forecast scenario | Planned |
| Part 2, O3 | D+1 price forecast | Stage 6: forecast competitive price vs strategic outcome | Planned |

**Requested Part 2 output formats** (an assumption, to confirm when Part 2 reaches forecasts):
- `demand_forecast_daily.csv`: `Date, State, Model, Demand_MW, Demand_lo_MW, Demand_hi_MW` (Date = the day forecast, D+1, made with information up to D)
- `availability_forecast_daily.csv`: the columns of `availability_daily.csv` + `Model`
- Prices in Part 2's format `Date, Area, Price, Source`

**Order of work:**
1. **Now:** Stages 0, 1 and the toy case of Stage 3 can start on Part 1's seasonal scenario
2. **After Part 2 Stage 2 is merged:** add `costs=` to `solve()` on top of Part 2's change to the same function (not before, so the function isn't edited in two places at once); switch the benchmark to `weather_*`; run Stages 2–5 on weather-based actuals
3. **After Part 2's forecasts (O1–O5):** Stage 6
4. **Feedback to Part 2:** Part 3's list of pivotal days is where forecast errors cost the most; Part 2's error analysis by situation should report errors on those days

## Decisions

1. **Plants = state × fuel blocks, one cost per block**, as in Part 1. No plant-level data. This gives a stepped supply curve, so prices jump at block edges, which is part of what Part 3 studies. Splitting blocks into cost tranches (−10% / 0 / +10%) or using plant-level data is a possible later check, not now.
2. **Firms: one firm per state** = that state's coal, lignite, gas and hydro blocks (~30 firms). Its must-run solar and wind also earn whatever price it sets. A national NTPC-like firm (25% of every state's coal; pivotal on ~193 days in the rough check) is kept as a possible later scenario.
3. **Realistic participation:** solar and wind are must-run, as in India. They bid 0 and cannot withhold, but are paid the clearing price (pay-as-clear), so they still earn price × MW. Coal, lignite, gas and hydro bid strategically. Hydro moving water between days is not modelled (one-day game).
4. **One bid per block for the whole market** (a single pool, like the IEX day-ahead market), not separate bids for home and other states. A plant is paid its home-state price; a high bid also raises importing states' prices through trade. With no line limits, other states' plants compete freely, so market power is mostly national, not local.
5. **Bid = cost + adder**, adder ∈ {0, 250, 500, … Rs/MWh}, plus a withholding share (0–30%). One adder and one share per firm, applied to all its strategic blocks. (A markup × cost would leave zero-cost blocks at 0.)
6. **Price cap = Rs 10,000/MWh**, the same as Part 1's VOLL (believed to equal the IEX day-ahead ceiling; to verify). A lower cap is tested in Stage 7.
7. **No long-term contracts at first**, so results are an upper bound (in India most power is sold under long-term contracts). A `contract_share` setting is added in Stage 7: a firm earns the market price only on its uncontracted output.
8. **Days:** the 456-day test period (1 Jan 2024 – 31 Mar 2025) first, then all 1,917 days.

## Method

A ladder, one change at a time (as in Part 2):

| Level | Method | Why |
|---|---|---|
| M0 | Competitive benchmark: every plant bids its cost (Part 1's LP) | Already validated; everything is measured against it |
| M1 | Market-structure indices: capacity shares, HHI, Residual Supply Index (RSI), pivotal-supplier test | No optimisation; shows where to look. RSI = (all available supply − firm's available supply) / demand; RSI < 1 means the market cannot be served without that firm |
| M2 | One strategic firm: try every (adder, withholding) on a grid, re-solve the LP each time, keep the most profitable | Reuses the LP with the network and losses; transparent and checkable by hand. Calculus-based methods (Cournot, supply function equilibrium) don't fit a stepped LP |
| M3 | Several strategic firms: best-response iteration until no firm wants to change (Nash equilibrium) | Shows whether rival firms limit each other's markups |
| M4 | What-ifs: lower price cap, must-offer (no withholding), contracts, splitting the largest firm, transmission limits | Turns results into policy answers |

Out of scope: hourly bidding, learning (agent-based / reinforcement learning) bidders, plant-level unit commitment.

## The game

**Type:** non-cooperative, simultaneous, one-shot (each day on its own), complete information (Stage 6: firms only know a forecast → incomplete information).
- Bidding prices with limited capacity is a **Bertrand–Edgeworth** game: a pure equilibrium may not exist and firms can keep undercutting each other in a cycle, so the loop checks for cycles
- Withholding capacity is the **Cournot** idea (competing on quantity)
- One strategic firm against cost-bidding plants (M2) is an optimisation, not a game. Formally a **bilevel problem** (firm's profit on top, the market LP underneath), solved here by trying every bid on a grid instead of advanced methods (MPEC)

**Definition:**
- **Players:** firms i = 1…N; all other blocks bid their cost
- **Strategy:** adder aᵢ and withholding share wᵢ. For each strategic block k of firm i: bid bₖ = cₖ + aᵢ, available MW = (1 − wᵢ) × capₖ
- **Market clearing:** the LP with bids instead of costs → dispatch gₖ, state prices λₛ
- **Payoff:** πᵢ = Σ over firm i's blocks of (λ at the block's state − cₖ) × gₖ, using **true** cost cₖ. Includes its must-run solar and wind (cost 0)
- **Nash equilibrium:** no firm can raise its profit by changing only its own strategy

**Best-response iteration:**
```
start: every firm bids cost (adder 0, withholding 0)
repeat up to N rounds:
    for each firm i:
        try every (adder, withholding) with the others fixed → run LP → profit
        set firm i's strategy to the most profitable
    if no firm changed → equilibrium, stop
    if a set of strategies repeats → cycle, report it, stop
```

**Hand example** (becomes a test): demand 100 MW; firm A has 80 MW at Rs 1,000; the rest (fringe) has 50 MW at Rs 2,000, bidding cost. The fringe cannot cover demand, so A is pivotal.

| A bids | Runs | Price | A sells | A's profit |
|---|---|---|---|---|
| below Rs 2,000 | A 80, fringe 20 | Rs 2,000 | 80 MW | (2,000 − 1,000) × 80 = 80,000 |
| Rs 10,000 (cap) | fringe 50, A 50 | Rs 10,000 | 50 MW | (10,000 − 1,000) × 50 = 450,000 |

A sells less but earns more than five times as much. Grid bids are kept off exact ties with other blocks' costs, because the LP price is not unique at a tie (Step 6).

## Stages and tasks

Each task: write the expected result → solve a tiny case by hand → code it in a notebook → test hand answers and edge cases → move the working function to `src/`.

**Stage 0 — Firms**
- 0.1 `data/raw/firm_ownership.csv` (`Firm, State, Fuel_Type, Role`): one firm per state; Role = strategic (coal, lignite, gas, hydro) or must-run (solar, wind); nuclear, biopower and diesel bid cost
- 0.2 `firm_blocks(gen, ownership)`: attach a firm and role to every generator row. Check: every row has exactly one firm; capacities unchanged

**Stage 1 — Market structure (no optimisation)**
- 1.1 Each firm's share of available capacity, national and by region; HHI
- 1.2 RSI per firm per day (network ignored first); share of days each firm is pivotal
- 1.3 RSI against tightness and season. Hypothesis written first: pivotal days ≈ the tightest few percent of days, mostly summer and winter peaks

**Stage 2 — Bids inside the LP** (after Part 2 Stage 2 is merged)
- 2.1 `LossDispatchModel.solve(..., costs=None)`: optional per-block bid prices, like `availability`
- 2.2 Tests: bids = costs reproduce Part 1 prices exactly; one block bidding higher on the toy case gives the hand-calculated price
- 2.3 `firm_profit(result, firm, true_costs)`: dispatch uses bids, profit uses true costs

**Stage 3 — One strategic firm, one day**
- 3.1 Toy case: solve the best bid by hand, then code `best_response(...)` (grid search)
- 3.2 Real stack: UP on the peak day (30 May 2024) and an ordinary day; profit vs adder curve; changes in price, consumer cost and dispatch
- 3.3 Withholding vs raising the bid: which pays more, and when

**Stage 4 — One strategic firm, many days**
- 4.1 Test period first, then all days
- 4.2 Adder vs tightness / RSI; which states' prices move; consumer cost increase by month
- 4.3 Save `data/processed/strategic_{state,national}_daily.csv`

**Stage 5 — All firms, equilibrium**
- 5.1 Best-response loop with a round limit and cycle detection
- 5.2 Toy two-firm test with a hand-solved equilibrium
- 5.3 A sample of ~60 days chosen across tightness levels first, then the test period

**Stage 6 — With Part 2's forecasts**
- 6.1 Firms choose bids on the D+1 forecast; the market clears on actual D+1 → realised profit
- 6.2 Value of forecasts to a firm: perfect information vs Part 2 forecast vs persistence
- 6.3 Does forecast tightness / forecast RSI < 1 predict actual market-power days? (precision / recall)

**Stage 7 — What-ifs and write-up**
- 7.1 Lower price cap, must-offer, contracts, splitting the largest firm, transmission limits
- 7.2 Report in `reports/`; README progress log; model log entries

## Files

- `src/bidding.py`: firm blocks, HHI, RSI, profit, best response, equilibrium loop
- `src/dispatch.py`: only the optional `costs` argument (Stage 2)
- `tests/test_bidding.py`: hand-calculated checks
- Notebooks (numbered after Part 2's last notebook when Part 3 starts): market structure, strategic bidding, bidding with forecasts
- `data/raw/firm_ownership.csv`; `data/processed/strategic_*_daily.csv`
- Docs each step: `docs/model_log.md` (Part 3 section), `data/README.md` (new files), README notebooks table and progress log, notebook markdown

## Tests (hand answers first)

- HHI and RSI on a 3-firm toy market
- `firm_blocks`: every block has exactly one firm; total capacity unchanged; unknown states raise an error
- Bids = costs → same prices and total cost as Part 1 (21 Jul 2024 reference day)
- Toy merit order: the firm with the price-setting block raises its bid → price = its bid, profit as hand-calculated
- Pivotal firm (hand example above) → best bid = the price cap, profit 450,000
- Non-pivotal firm with a competitor just above it → best bid stops just below the competitor's cost
- Must-run blocks always bid 0 and never withhold
- Best-response loop on a toy two-firm case reaches the hand-solved equilibrium
- The chosen strategy's profit is never below the profit from bidding cost (bidding cost is always an option)

## Metrics

- Price markup vs competitive: Rs/MWh and %, by state and day; Lerner index (P − MC) / P
- Consumer cost increase: Σ price × demand (Rs per peak hour, as Part 1's `Total_cost_Rs_per_h`)
- Firms' extra profit: the transfer from consumers to firms
- Efficiency loss: increase in true generation cost (expensive plants run because cheap ones bid high or withhold)
- Unserved MW caused by withholding
- Share of days with a markup above 5%; link with RSI and tightness (correlation; precision / recall in Stage 6)
- Equilibrium: rounds to converge; share of days that cycle

## Still to check

- The IEX day-ahead price ceiling (assumed Rs 10,000/MWh)
- The Part 2 output formats above, when Part 2 reaches forecasts
- Notebook numbers, once Part 2's notebook list is final
