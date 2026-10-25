# Model log

A dated record of every modelling and data step: what was done, why, the assumptions, how it was checked, and what came out. Newest entries at the bottom. Data files are described in [`data/README.md`](../data/README.md).

---

## Part 1: dispatch model

### Step 1 — Clean demand data (2026-09-26)
**What:** cleaned 5 years of daily state demand (`01_data_cleaning.ipynb`).
**Decisions:** dropped Essar steel (a company, not a state) and Jharkhand (mostly missing); merged DD and DNH into one entry; filled gaps forward then backward within each state.
**Result:** 33 states × 1,917 days, 0 nulls.
**Later found:** a zero null count did not mean clean data — see step 9.

### Step 2 — First dispatch attempt, retired (2026-09-26)
**What:** a full dispatch module written in one go (now `archive/dispatch_v0.py`).
**Result:** coal set the price on 99.6% of days at a flat Rs 2,000.
**Lesson:** audit what the data can produce before building the model. Restarted step by step.

### Step 3 — Toy merit order (2026-10-22)
**What:** 3-plant merit-order function, written from hand calculations (`02_merit_order.ipynb`).
**Checks:** hand answers at 30/120/200 MW plus boundary cases (0, 40, 140, 190 MW). A bug in the marginal plant's cost (`=` instead of `+=`, full capacity instead of the remaining MW) was found by tracing the code with real numbers.
**Decision:** unmet demand priced at VOLL = Rs 10,000/MWh.

### Step 4 — Real generator stack (2026-10-23)
**What:** national stack from `india_generator_stack.csv`.
**Problem:** with nameplate capacity, solar and wind alone covered most demand, so the price was Rs 0.
**Decision:** availability factors (share of nameplate available at peak): solar 0.25, wind 0.30, large hydro 0.45, small hydro 0.40, coal 0.75, lignite 0.70, nuclear 0.80, biopower 0.50, gas 0.30, diesel 0.90.
**Result:** coal became the marginal fuel. National peak day found as 30 May 2024 (255 GW summed state peaks), matching India's real record (~250 GW) on that day.

### Step 5 — State and regional analysis (2026-10-23)
**What:** state surplus/deficit and 5-region dispatch on 30 May 2024.
**Result:** North short ~16.7 GW, West ~23.9 GW spare. Counting states misleads (NorthEast has 5 deficit states but a net surplus); MW totals matter.

### Step 6 — LP dispatch (2026-10-23)
**What:** dispatch rewritten as a linear program (`scipy.optimize.linprog`, HiGHS). Price = shadow price of the supply = demand constraint.
**Checks:** matches merit order on all 1,917 days. At an exact capacity boundary the price is not unique (merit order reports the last MW's cost, the LP the next MW's); both are valid.

### Step 7 — Copper-plate trading (2026-10-23)
**What:** state-level LP with free trade, no losses or limits (21 Jul 2024).
**Result:** one price everywhere (Rs 2,000), as theory predicts. With every coal plant at the same cost, which state's coal ran (and so every state's imports) was arbitrary: a tie, not a meaningful answer.

### Step 8 — Distance-based losses (2026-10-23)
**What:** a flow variable for every pair of states, losing `min(0.5% + 4% × 1.2 × distance/1000 km, 10%)` of what is sent; distance between state capitals (haversine).
**Checks:** zero losses reproduces the copper plate exactly; extra generation equals losses; on every used route `price_to = price_from / (1 − loss)`; no two-way trades; every price confirmed by re-solving with +1 MW demand.
**Result:** locational prices (Rs 1,995–2,162 on 21 Jul 2024), 25 trades instead of arbitrary routing, realised loss 3.4% of traded power (India: ~3–4%).

### Step 8b — Coal tiers, src/, all days (2026-10-25)
**What:** coal cost by state tier (`coal_cost_tiers.csv`); models moved to `src/dispatch.py` with pytest checks; loss model run for all 1,917 days (`03_dispatch_all_days.ipynb`, 8.8 s).
**Result:** average price Rs 1,650–3,770 instead of a flat Rs 2,000; losses 3.8% of traded power; no unserved days.

---

### Step 9 — Fix DD & DNH and other corrupted rows (2026-10-25)
**Why:** while planning Part 2 we checked what the shifted-row bug from notebook 02 was doing to the processed data.

**Found:** 1,034 raw rows have `Max Demand Met` empty but `Shortage During Peak` filled. They are two problems:
- **DNH, 1,027 rows (June 2022 onward): shifted one column right.** From June 2022 DD stops reporting and DNH carries the merged UT total, but every value sits one column too far right.
- **HP, 7 rows: corrupted.** First treated as shifted, but un-shifting gave HP a demand of 2 MW. The values don't fit HP either way (energy 0, drawl 218–651 vs HP's ~35 MU/day), and they fall on the dates DD and DNH are missing.
- Plus 10 rows with `Energy Met = 0`, 16 with negative `Energy Shortage`, 1 with negative `Shortage During Peak` (Kerala, 29 Jan 2020, −75 MW between two zero days).

**Effect of the bug before the fix:** DD & DNH demand frozen at 1,237 MW (copied forward) for ~1,000 days, its `Energy Met` = 0, and its real demand counted as shortage. **62% of the national peak shortage figure was this bug:** 1,085 MW on average, real value 412 MW. (Earlier notes in this project quoted "~1 GW" — that was wrong.)

**Fix (in `01_data_cleaning.ipynb`, before merging DD + DNH):**
1. DNH flagged rows: shift one column left; set the lost `Energy Shortage` to 0 (DNH's shortage is 0 on 96% of days)
2. HP flagged rows: set all numbers to NaN
3. Impossible values (`Energy Met = 0`, negative shortages): set to NaN
4. The existing forward/backward fill then fills these gaps from neighbouring days

**Checks (asserted in notebook 01):** no flagged rows remain; no zero energy; no negative shortages; DD & DNH demand varies after mid-2022 (263 distinct values); DD & DNH shortage ~0 after mid-2022.

**Result:**
- DD & DNH peak demand now grows 1,161 → 1,314 MW (2022–2025) instead of a flat 1,237; lowest value 134 MW on 29 Mar 2020 is real (COVID lockdown; DD & DNH demand is mostly industrial)
- Average national peak shortage: **412 MW**
- Part 1 dispatch re-run: average price changes by Rs 0.77 on average. On two days (22 Jan and 24 Mar 2025) it jumped ~Rs 600 from only +100 MW of demand, because those days sit at the edge of a coal-tier step: **with a stepped supply curve, small demand changes near a step cause large price jumps.** Relevant for forecasting.
- Reference test value updated: 21 Jul 2024, flat coal → Rs 296,736,690.64/h (was 296,732,641.83 with the frozen 1,237 MW)
