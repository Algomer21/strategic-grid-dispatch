# Part 3 plan — Strategic bidding and market power

Agreed 2026-10-25 while Part 2 was being built; updated 2026-10-26 after Part 2 was completed and merged (PR #3), to use its final outputs. Results and changes go into [`model_log.md`](model_log.md) as Part 3 steps once work starts; this file is the plan they follow.

---

## Goal

Measure what happens to prices, consumer cost and dispatch when large generators bid above their true cost (raise their bids or withhold capacity) instead of bidding at cost, as Parts 1 and 2 assume. Answer:

- **when:** which days
- **where:** which states and regions
- **who:** which firms can do it
- **how much:** what it costs consumers

Then use Part 2's forecasts as the firms' view of tomorrow: do forecast-tight days flag market-power days in advance?

This is research question 2 in the README: what happens when large generators bid strategically instead of at true marginal cost, where does market power show up, and how much does it cost consumers?

## Why this should show something

Coal sets the price on almost every day, and the supply curve has steps at the coal tiers (Part 2: prices jump between ~2,200, ~2,750 and ~3,450 Rs/MWh; 21% of days sit near a step).

A rough first look on Part 2's weather-based "actual" run (`dispatch_weather_*`; network ignored, firms = one per state, see Decisions):

| | All 1,917 days | Mar 2024 – Mar 2025 (396 days) |
|---|---|---|
| Days on which some firm is pivotal (market can't be served without it) | 67 | **53 (13%)** |
| Least / average spare capacity | 9.2 / 72.6 GW | 9.2 / 45.8 GW |

- **Nine firms are pivotal on at least one day** in the 396-day period: UP 53 days, Maharashtra 26, Chhattisgarh 21, MP 17, Gujarat 9, Tamil Nadu 5, Andhra Pradesh 4, Telangana 3, West Bengal 3
- Several firms are often pivotal on the same days, so **competition between strategic firms (Stage 5) is a main result**, not an extra
- The earlier look on the seasonal run found only 29 pivotal days in 1,917: weather-based availability makes tight days more frequent, and demand growth makes 2024–25 much tighter than earlier years

## How Parts 1 and 2 feed Part 3

Part 3 needs, for each day, a **scenario**: demand by state + availability by (state, fuel). **Part 1 supplies the market; Part 2 supplies the scenarios.** Actual and forecast scenarios have the same shape, so Part 3's code does not change between them.

| From | What | Used in Part 3 for | Status |
|---|---|---|---|
| Part 1 | `LossDispatchModel` (LP, losses, locational prices) | Clearing the market for every bid tried | Done |
| Part 1 | Generator stack + coal tiers (`load_generators`) | True costs; firms' blocks | Done |
| Part 2 | `solve()` with (state, fuel) availability keys, `daily_availability_lookup` | Daily supply; **withholding = factor × (1 − w)** for the firm's (state, fuel) keys, no new code | Done (PR #3) |
| Part 2 | `availability_daily.csv` | Actual availability per state, fuel and day | Done |
| Part 2 | `dispatch_weather_{state,flows,national}_daily.csv` | **Competitive benchmark (M0)**: the "actual" prices | Done |
| Part 2 | `available_by_fuel`, `available_capacity`, `tightness` (`src/forecast.py`) | Firm and national available MW, spare capacity, RSI | Done |
| Part 2 | `part3_forecast_package.csv` via `load_forecast_package()` | Forecast demand (median, 10% and 90%), forecast price with low/high, forecast tightness, near-step flag; actuals alongside | Done |
| Part 2 | `availability_forecast_test.csv`, rows `Model = "best day-ahead"` | Forecast availability per (state, fuel), needed to re-run the market (the package only has MW by fuel group, hydro combined) | Done |
| Part 2 | `scale_availability` (`src/availability.py`), Step 19 scenarios | Stress tests in Stage 7 | Done |
| Part 2 | `to_bid_areas`, `compare_prices` (`src/prices.py`) | Optional: report markups by IEX bid area; compare with real IEX prices later | Done |

**Feedback to Part 2:** Part 3's list of pivotal and high-markup days shows where forecast errors cost the most.

## Decisions

1. **Plants = state × fuel blocks, one cost per block**, as in Part 1. No plant-level data. The stepped supply curve is part of what Part 3 studies. Splitting blocks into cost tranches or plant-level data is a possible later check, not now.
2. **Firms: one firm per state** = that state's coal, lignite, gas and hydro blocks (~30 firms). Its must-run solar and wind also earn whatever price it sets. A national NTPC-like firm (25% of every state's coal, ~40.6 GW available) is kept as a possible later scenario.
3. **Realistic participation:** solar and wind are must-run, as in India. They bid 0 and cannot withhold, but are paid the clearing price (pay-as-clear). Coal, lignite, gas and hydro bid strategically. Nuclear, biopower and diesel bid cost. Hydro moving water between days is not modelled (one-day game).
4. **One bid per block for the whole market** (a single pool, like the IEX day-ahead market). A plant is paid its home-state price; a high bid also raises importing states' prices through trade. With no line limits, market power is mostly national, not local.
5. **Bid = cost + adder**, adder ∈ {0, 250, 500, … Rs/MWh}, plus a withholding share (0–30%). One adder and one share per firm for all its strategic blocks.
6. **Price cap = Rs 10,000/MWh**, Part 1's VOLL (believed to equal the IEX day-ahead ceiling; to verify). A lower cap is tested in Stage 7.
7. **No long-term contracts at first**, so results are an upper bound. A `contract_share` setting is added in Stage 7.
8. **Days: Part 2's scored period, 1 Mar 2024 – 31 Mar 2025 (396 days)**, so actual results (Stages 4–5) and forecast results (Stage 6) cover exactly the same days. All 1,917 days later, actual only.

## Method

A ladder, one change at a time (as in Part 2):

| Level | Method | Why |
|---|---|---|
| M0 | Competitive benchmark: every plant bids its cost (`dispatch_weather_*`) | Already validated; everything is measured against it |
| M1 | Market-structure indices: capacity shares, HHI, Residual Supply Index (RSI), pivotal-supplier test | No optimisation; shows where to look. RSI = (all available supply − firm's available supply) / demand; RSI < 1 means the market cannot be served without that firm |
| M2 | One strategic firm: try every (adder, withholding) on a grid, re-solve the LP each time, keep the most profitable | Reuses the LP with the network and losses; transparent and checkable by hand. Calculus-based methods (Cournot, supply function equilibrium) don't fit a stepped LP |
| M3 | Several strategic firms: best-response iteration until no firm wants to change (Nash equilibrium) | Several firms are pivotal on the same days, so they limit (or don't limit) each other |
| M4 | What-ifs: lower price cap, must-offer (no withholding), contracts, splitting the largest firm, transmission limits, Part 2's stress scenarios | Turns results into policy answers |

Out of scope: hourly bidding, learning (agent-based / reinforcement learning) bidders, plant-level unit commitment.

## The game

**Type:** non-cooperative, simultaneous, one-shot (each day on its own), complete information (Stage 6: firms only know a forecast → incomplete information).
- Bidding prices with limited capacity is a **Bertrand–Edgeworth** game: a pure equilibrium may not exist and firms can keep undercutting each other in a cycle, so the loop checks for cycles
- Withholding capacity is the **Cournot** idea (competing on quantity)
- One strategic firm against cost-bidding plants (M2) is an optimisation, not a game. Formally a **bilevel problem** (firm's profit on top, the market LP underneath), solved here by trying every bid on a grid instead of advanced methods (MPEC)

**Definition:**
- **Players:** firms i = 1…N; all other blocks bid their cost
- **Strategy:** adder aᵢ and withholding share wᵢ. For each strategic block k of firm i: bid bₖ = cₖ + aᵢ, availability factor × (1 − wᵢ)
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

**Computing budget.** One LP solve takes ~5 ms. A full grid (33 adders × 7 withholding shares ≈ 230 strategies) is ~1 s per firm per day, so one equilibrium round over ~30 firms is ~35 s per day. To keep runs in minutes:
- **Coarse, then fine:** search a coarse grid first, then refine around the best point
- **Small firms bid cost:** firms with less than ~1 GW of strategic capacity are not players
- **Time it first:** measure on the 60-day sample before running all 396 days

## Stages and tasks

Each task: write the expected result → solve a tiny case by hand → code it in a notebook → test hand answers and edge cases → move the working function to `src/`.

**Stage 0 — Firms**
- 0.1 `data/raw/firm_ownership.csv` (`Firm, State, Fuel_Type, Role`): one firm per state; Role = strategic (coal, lignite, gas, hydro), must-run (solar, wind) or cost (nuclear, biopower, diesel)
- 0.2 `firm_blocks(gen, ownership)`: attach a firm and role to every generator row. Check: every row has exactly one firm; capacities unchanged

**Stage 1 — Market structure (no optimisation)** — notebook `13_market_structure`
- 1.1 Each firm's share of available capacity, national and by region; HHI
- 1.2 RSI per firm per day, from `available_by_fuel` on `availability_daily.csv`; share of days each firm is pivotal (reproduce the 53-day preview)
- 1.3 RSI against Part 2's tightness, season and the **near-step flag**. Hypothesis written first: market power is largest on days that are both tight and near a coal-tier step (Part 2: near-step days cluster at 10–20% spare)

**Stage 2 — Bids inside the LP**
- 2.1 `LossDispatchModel.solve(..., costs=None)`: optional per-block bid prices, like `availability`
- 2.2 Tests: bids = costs reproduce `dispatch_weather_*` prices exactly; one block bidding higher on the toy case gives the hand-calculated price
- 2.3 `firm_profit(result, firm, true_costs)`: dispatch uses bids, profit uses true costs
- 2.4 Withholding through the existing (state, fuel) availability keys; test: w = 0 changes nothing

**Stage 3 — One strategic firm, one day** — notebook `14_strategic_bidding`
- 3.1 Toy case: solve the best bid by hand, then code `best_response(...)` (grid search, coarse then fine)
- 3.2 Real stack: UP on its tightest pivotal day and an ordinary day; profit vs adder curve; changes in price, consumer cost and dispatch
- 3.3 Withholding vs raising the bid: which pays more, and when
- 3.4 Time one best response; decide the grid and the minimum firm size from it

**Stage 4 — One strategic firm, 396 days**
- 4.1 UP (largest firm) alone, then each of the nine pivotal firms alone
- 4.2 Adder vs tightness / RSI / near-step; which states' prices move; consumer cost increase by month
- 4.3 Save `data/processed/strategic_{state,national}_daily.csv`

**Stage 5 — All firms, equilibrium**
- 5.1 Best-response loop with a round limit and cycle detection
- 5.2 Toy two-firm test with a hand-solved equilibrium
- 5.3 ~60 days chosen across tightness levels and near-step / not first, then all 396 days
- 5.4 Compare with Stage 4: do rival pivotal firms limit each other's markups?

**Stage 6 — Bidding on Part 2's forecasts** — notebook `15_bidding_with_forecasts`
- 6.1 Forecast scenario for day T = package demand + "best day-ahead" availability factors
- 6.2 Firms choose bids on the forecast; the market clears on actual T → realised profit and prices
- 6.3 **Bidding under uncertainty:** a firm picks the bid with the best average profit over the 10%, median and 90% demand forecasts, vs bidding on the median alone
- 6.4 Value of forecasts to a firm: perfect information vs Part 2 forecast vs persistence
- 6.5 Do forecast tightness, forecast RSI < 1 and the forecast near-step flag predict actual market-power days? (precision / recall)

**Stage 7 — What-ifs and write-up**
- 7.1 Lower price cap, must-offer, contracts, splitting the largest firm, transmission limits
- 7.2 **Market power under stress:** Part 2's Step 19 scenarios (coal shortage, drought, demand +5%) with `scale_availability`. Does market power grow faster than the shock?
- 7.3 Optional: markups by IEX bid area (`to_bid_areas`)
- 7.4 Report `reports/part3_strategic_bidding.md`; README progress log; model log entries

## Files

- `src/bidding.py`: firm blocks, HHI, RSI, profit, best response, equilibrium loop (reusing `available_by_fuel`, `tightness`, `scale_availability`)
- `src/dispatch.py`: only the optional `costs` argument (Stage 2)
- `tests/test_bidding.py`: hand-calculated checks
- `notebooks/13_market_structure.ipynb`, `14_strategic_bidding.ipynb`, `15_bidding_with_forecasts.ipynb` (and `16_` for Stage 7 if needed)
- `data/raw/firm_ownership.csv`; `data/processed/strategic_*_daily.csv`
- Docs each step: `docs/model_log.md` (Part 3 section), `data/README.md` (new files), README notebooks table and progress log, notebook markdown

## Tests (hand answers first)

- HHI and RSI on a 3-firm toy market
- `firm_blocks`: every block has exactly one firm; total capacity unchanged; unknown states raise an error
- Bids = costs → same prices and total cost as `dispatch_weather_*` (and the 21 Jul 2024 Part 1 reference day)
- Toy merit order: the firm with the price-setting block raises its bid → price = its bid, profit as hand-calculated
- Pivotal firm (hand example above) → best bid = the price cap, profit 450,000
- Non-pivotal firm with a competitor just above it → best bid stops just below the competitor's cost
- Must-run blocks always bid 0 and never withhold; withholding 0 changes nothing
- Best-response loop on a toy two-firm case reaches the hand-solved equilibrium
- The chosen strategy's profit is never below the profit from bidding cost (bidding cost is always an option)
- Forecast scenario: actual inputs fed in as the "forecast" give the actual-scenario result

## Metrics

- Price markup vs competitive: Rs/MWh and %, by state and day; Lerner index (P − MC) / P
- Consumer cost increase: Σ price × demand (Rs per peak hour, as `Total_cost_Rs_per_h`)
- Firms' extra profit: the transfer from consumers to firms
- Efficiency loss: increase in true generation cost (expensive plants run because cheap ones bid high or withhold)
- Unserved MW caused by withholding
- Share of days with a markup above 5%; link with RSI, tightness and the near-step flag (correlation; precision / recall in Stage 6)
- Equilibrium: rounds to converge; share of days that cycle
- Stage 6: realised vs planned profit; profit gained from better forecasts

## Still to check

- The IEX day-ahead price ceiling (assumed Rs 10,000/MWh)
- Whether the 60-day sample timing allows all ~30 firms as players, or only those above the size threshold
