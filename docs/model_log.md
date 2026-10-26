# Model log

A dated record of every modelling and data step: what was done, why, the assumptions, how it was checked, and what came out. Newest entries at the bottom. Data files are described in [`data/README.md`](../data/README.md).

Part 3 (strategic bidding) follows the plan in [`part3_plan.md`](part3_plan.md), agreed 2026-10-25 and updated 2026-10-26 to use Part 2's final outputs; its steps will be logged here when work starts.

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

### Step 10 — Seasonal availability (2026-10-25)
**Why:** in Part 1, solar, wind and hydro have the same availability every day, so the model has no seasonal supply pattern: the monthly price pattern was weak and only followed demand.

**What:** monthly availability factors for solar, wind, large hydro and small hydro (`data/raw/seasonal_availability.csv`), applied day by day (`03`'s model, run in `04_seasonal_availability.ipynb`). `LossDispatchModel.solve()` takes an optional per-day availability; only the plant limits change, the constraint matrix is reused.

**Assumptions:**
- Factor shapes follow typical Indian patterns: wind peaks Jun–Aug (0.55 in Jul), hydro peaks Jul–Sep (0.72 in Aug) and is lowest Mar (0.27), solar dips Jul–Aug (0.18) and peaks Apr (0.31)
- **Each fuel's 12-month average equals its constant factor** (0.25, 0.30, 0.45, 0.40), so the comparison isolates *timing*: same yearly renewable supply
- **Coal and all other fuels kept constant all year, on purpose**, to isolate the renewable effect. In reality coal availability also dips in the monsoon (wet coal, planned maintenance); not modelled
- Monthly factors ignore the time of day of the peak (afternoon in summer, evening in winter/monsoon)
- Not measured data; can be refined against CEA monthly generation reports

**Checks:** factor averages equal the constants (test); a constant override gives the same answer as no override (test); energy balance every day; demand identical to the baseline; July large-hydro availability = 0.65 of nameplate as intended; no negative prices or unserved days; losses 3.81% of traded power.

**Result (monthly averages over full years 2020–2024):**
- **Monsoon (Jun–Sep): prices −120 to −170 Rs/MWh** — wind and hydro push 9–13 GW of coal off
- **Winter (Dec–Feb): prices +110 to +245 Rs/MWh** — 9–14 GW more coal
- Summer (Mar–May): −95 to +72 — low hydro offset by strong solar and May wind. **The hypothesis that summer prices would rise was wrong**; winter is the expensive season in this model
- All states move together (winter ≈ +200, monsoon ≈ −150) because prices are linked by trade
- HP exports 6.4 GW in the monsoon vs 2.2 GW in winter (constant model: ~4 GW all year); Uttarakhand imports outside the monsoon
- Yearly system cost changes by −0.1% to +0.7% (as designed); price standard deviation rises 324 → 356 Rs/MWh

**Outputs:** `data/processed/seasonal_{state,flows,national}_daily.csv`. The constant-availability results (`dispatch_*`) are kept as the baseline.

---

## Part 2 — Day-ahead forecasting

### Step 11 — Part 2 plan and objective (2026-10-25)
**Objective:** on day D, forecast each state's peak demand and the renewable/hydro availability for day D+1, run them through the Part 1 dispatch model to get D+1 locational prices, and measure how much better this is than simple baselines, and when and why it fails. Mirrors a day-ahead market (IEX clears tomorrow's market today).

**Sub-objectives:**
- O1: state peak demand for D+1. Target: skill score ≥ 20% vs persistence (`1 − MAE_model / MAE_persistence`)
- O2: solar, wind and hydro availability for D+1, from weather
- O3: D+1 prices through dispatch (Route B), compared with a direct price model (Route A) and persistence
- O4: uncertainty (prediction intervals) and error by situation
- O5: a forecast package for Part 3: demand, availability, price (with ranges) and a tightness index `(available supply − demand) / demand`. Part 3's strategic bidders use it as their view of tomorrow; market power is expected on tight days

**Decisions:**
1. Availability becomes weather-based (daily, from Open-Meteo). A new dispatch run with weather-based availability becomes the "actual" price that forecasts are scored against, replacing `seasonal_*` as the truth
2. D+1 weather: start with a perfect forecast (actual D+1 weather, upper bound) and persistence (day D weather, lower bound). Real archived weather forecasts later, if they cover the test period
3. Solar and wind from **daily-average** weather, not the peak hour. Simpler and consistent with Part 1. Known limitation: the peak is in the evening for much of the year, when solar is near zero, so daily-average solar overstates supply at the peak and can understate peak prices. Can be tested later as a scenario
4. Prices go in one format (`Date, Area, Price, Source`) so real IEX day-ahead prices can replace model prices later (IEX prices are by bid area, so a state → bid-area map will be needed)

**Set-up:**
- Train: 1 Jan 2020 – 31 Dec 2023. Test: 1 Jan 2024 – 31 Mar 2025. Split by time, never shuffled; later a walk-forward backtest (retrain monthly)
- No leakage: a forecast for D+1 uses only information known on day D (rolling features shifted)
- Metrics: MAE, MAPE, RMSE, skill score vs persistence
- 32 states (DVC excluded, as in Part 1)

**Model ladder (one change per step):** L0 persistence / last week → L1 month × weekday average → L2 linear regression (lags + calendar) → L3 + weather (ridge) → L4 LightGBM → L5 pooled vs per-state → L6 quantile ranges

**Situations to test:** seasons, weekday/weekend, holidays/festivals, May 2024 heatwave, COVID 2020–21, monsoon onset/withdrawal, coal-tier step-edge days, state groups, horizons 1/7/30 days, weather-forecast quality, training length, what-ifs (demand +5%, drought, low wind)

**External factors, first round:** heat index / cooling degree days, rainfall, irradiance, cloud cover, wind speed at 100 m, farming-season flags, holidays. Later only if the error analysis asks for them: state festivals, COVID stringency index, reservoir storage, coal stocks, outages

### Step 12 — Forecast set-up and naive baselines (2026-10-25)
**What:** `src/forecast.py` (time split, MAE / MAPE / RMSE / skill, persistence baseline) with 6 pytest checks (`tests/test_forecast.py`, hand-calculated answers); `05_forecast_setup.ipynb` scores the two naive baselines on the test period (1 Jan 2024 – 31 Mar 2025, 456 days).

**Checks:** 32 states × 1,917 days, no gaps or NaN; train and test don't overlap and cover every day; baselines are shifted on the full series, so the forecast for 1 Jan 2024 is the real 31 Dec 2023 value (no missing first test day); metrics raise errors on NaN, mismatched lengths and MAPE with zero demand.

**Result (national peak demand, test period):**

| Baseline | MAE (MW) | MAPE | RMSE (MW) | Skill |
|---|---|---|---|---|
| Persistence (yesterday) | 4,929 | 2.26% | 6,662 | 0 (reference) |
| Last week | 6,917 | 3.17% | 9,263 | −0.40 |

- **Target for the models:** skill ≥ 0.20 → national MAE below ≈ 3,940 MW
- Persistence error by weekday: Monday 10.4 GW, Sunday 8.4 GW, other days ~3 GW. It ignores the weekday effect
- Persistence error grows with the lag (4.9 GW at 1 day → 7.9 GW at 5) and only partly recovers at 7 days (6.9 GW): a week of weather/seasonal drift costs more than the weekday effect. Next models should combine yesterday's level with a weekday correction
- **States are harder:** persistence MAPE 2.4% (Chhattisgarh) to ~6–7% (small UTs, North-East); Punjab, Haryana and Tamil Nadu 5.4–5.8% (farm load, rainfall). Sum of state MAEs = 1.65 × the national MAE (state errors partly cancel)
- Price baselines deferred to Stage 2, when the "actual" price is re-made with weather-based availability

> **Updated in Step 16a** (spike fix): persistence MAE 4,842 MW, MAPE 2.22%, RMSE 6,501 → target MAE below ≈ 3,870 MW; last week MAPE 3.14%. **Correction:** the state range above was read from a cut-off table; the hardest states are Mizoram (9.2%) and Sikkim (10.3%), not ~6–7%.

### Step 13 — Weather points and weather data (2026-10-25)
**Why:** demand depends on heat, and solar, wind and hydro depend on sun, wind and rain. Part 2 forecasts both, so it needs daily weather where the load and the plants are, not just at state capitals.

**Decisions (Stage 1, asked one at a time):**
1. Points chosen **by purpose**: demand, solar, wind, hydro (`data/raw/weather_points.csv`, 151 points, 139 unique locations)
2. Demand: the 12 states with mean peak ≥ 8,000 MW use their 3 largest cities at least 100 km apart, **population-weighted** (Census 2011, `city_population.csv`); other states use the capital
3. Variables: max/mean/min temperature, rainfall, solar radiation, cloud cover, wind at 100 m. **No humidity / feels-like** for now (add if humid states forecast badly)
4. Supply points for **every state with any capacity** of that fuel (32 solar, 9 wind, 28 hydro)
5. 2–3 points (simple average) where a state has ≥ 5,000 MW of the fuel, otherwise 1
6. Period 1 Dec 2019 – 31 Mar 2025, Indian time, Open-Meteo historical archive

**Code:** `src/weather.py`: `parse_daily` (checks every answer: all days, no empty values), `fetch_point` (retries rate limits, server errors and garbled answers), `fetch_all` (each unique location once, cached in `data/cache/weather/`), `check_weather` (all points × all days, physical ranges). 7 tests with fake answers, no internet needed (33 tests in total).

**Problems met:** the first full run stopped at location 2 on a garbled (non-JSON) answer → added retries. Then the free API's **hourly limit** stopped it after 107 of 139 locations (a 5-year download counts as many requests) → waited and resumed from the cache.

**Checks:** 294,148 rows = 151 × 1,948, no NaN, all values in physical ranges; Jaipur 46.0 °C on 29 May 2024; the five hottest demand-point days are all 26–29 May 2024 (Jodhpur 48.3 °C).

**Results (`06_weather_data.ipynb`):**
- **Wind:** weather shape (speed³) matches the assumed Step 10 shape well (correlation 0.94, both peak in July; weather slightly more peaked)
- **Solar:** correlation 0.61. Weather radiation dips much less in the monsoon (0.92–0.96 of average vs assumed 0.72) and more in winter (0.79–0.84 vs ~1.0). The assumed shape overstates winter solar, so Part 1's winter prices may be too low
- **Hydro:** rain peaks in July at 2.7× average; the assumed hydro shape peaks in August at 1.6×. Reservoirs store and smooth rain, so Stage 2 needs a rainfall running total, not daily rain
- **Kerala monsoon:** rain builds through late May–June; pre-monsoon showers from mid-May mean onset isn't detectable with a simple rule (not needed)
- **Delhi demand vs max temperature: U-shaped.** Lowest ~3,740 MW at 25–30 °C, ~6,530 MW above 40 °C, ~4,700–4,850 MW below 20 °C. Straight-line correlation only 0.45 because of the curve → Stage 3 needs cooling and heating degree-day features

**Still to do in Stage 1:** combine points into one value per state and purpose → `data/processed/weather_state_daily.csv`.

### Step 14 — Weather points combined into states (2026-10-25)
**What:** `point_weights` and `combine_points` in `src/weather.py`. One weather row per date, state and purpose = the weighted average of its points that day. Demand points are weighted by city population (Census 2011); solar, wind and hydro points equally (no plant-level capacity data); single-point groups unchanged. Section 5 of `06_weather_data.ipynb`.

**Checks:** 4 new tests (37 in total), including the hand example: cities of 3 M and 1 M people at 40 °C and 20 °C → 35 °C; weights sum to 1 in every group; every combined value lies between its points' min and max every day; Delhi's demand weather equals the New Delhi point.

**Result:** `data/processed/weather_state_daily.csv`: 101 groups (32 demand, 32 solar, 9 wind, 28 hydro) × 1,948 days = 196,748 rows.
- The largest city carries 41% (MP, Indore) to 88% (Telangana, Hyderabad) of its state's demand weight; Mumbai 69%, Chennai 77%
- Population weighting vs a simple average changes daily max temperature by ~1 °C on average in Tamil Nadu (1.01) and Maharashtra (0.95), where coastal Chennai and Mumbai dominate; under 0.2 °C in UP and MP, where the cities have similar weather

**Stage 1 complete.** Next, Stage 2: weather → daily availability factors for solar, wind and hydro, and a new dispatch run for the "actual" prices.

### Step 15 — Weather-based availability and the new "actual" prices (2026-10-25)
**Why:** Part 2 forecasts supply as well as demand, and Step 10's monthly factors have nothing to forecast. Availability now follows each state's daily weather, and the dispatch re-run with it becomes the "actual" price that forecasts are scored against (Step 11, decision 1).

**Decisions (Stage 2, asked one at a time):**
1. **Physics-shaped** rules give each fuel's daily shape
2. **Level matched to Part 1:** scaled so the long-run average equals the Part 1 factor (solar 0.25, wind 0.30, large hydro 0.45, small hydro 0.40); capped at 1.0
3. Hydro: **two-speed leaky buckets** of water: half-life 60 days (large hydro), 10 days (small hydro); started with a year of data (spin-up)
4. **Degree-day snowmelt** for HP, Uttarakhand, J&K, Sikkim, Arunachal: melt ∝ max(dam mean temp − 15 °C, 0), scaled to 50% of yearly water
5. Solar includes **panel heat loss:** −0.4%/°C above 25 °C; panel = air max + 25 °C × (sunlight / 800 W/m²), daily radiation over 10 sunlit hours
6. Wind: **hourly 100 m wind** for the 17 wind points; generic power curve (cut-in 3, rated 12, cut-out 25 m/s, cubic rise) applied per hour, averaged per day, then over the state's points
7. Level matched **per state** (each state's 2020–24 mean = Part 1 factor), not as an India average

**Code:** `src/availability.py` (rules, `match_level`, `build_availability`), 10 tests with hand answers (power curve at 7.5 m/s = 0.232; 46 °C + 600 W/m² → 15.9% heat loss; half-life; melt share; cap). `src/weather.py`: hourly download (`fetch_all_hourly`, cache `data/cache/wind_hourly/`). `src/dispatch.py`: `solve()` accepts (state, fuel) keys, `daily_availability_lookup`, `run_all_days(daily=...)`; 2 tests incl. "same values per state change nothing". 55 tests in total.

**Problems met:** (1) a test I wrote was wrong: with a flat block of monsoon rain every bucket peaks on the last rainy day, so it couldn't show the lag; replaced by a smooth seasonal inflow. (2) **The first run overwrote `weather_state_daily.csv`** (the Stage 1 weather) because the dispatch outputs were named `weather_{state,flows,national}_daily.csv`. Restored from git; the dispatch outputs are now `dispatch_weather_*`.

**Checks:** factors exist for exactly the 93 state-fuel pairs with capacity; all between 0 and 1; every state's 2020–24 mean equals its Part 1 factor (< 1e-6); HP melt share 50%; dispatch: no unserved days, demand identical to the data, generation = demand + losses every day; losses 3.77% of traded power.

**Results (`07_weather_availability.ipynb`):**
- Cap binds on 3% of days (large hydro), 5% (wind), 14% (small hydro), never for solar
- Wind: hourly curve gives 13% more output than the curve on the daily mean
- Solar heat loss ~16% on heatwave days, ~4% in January, but **no heatwave dip** in availability: May 2024's clear skies and strong sun offset it (my expectation was wrong)
- India large hydro lowest Mar–May (0.23–0.25 vs Step 10's 0.27–0.35), **peaks in September (0.75)**, a month later than Step 10; solar higher in the monsoon (0.23–0.24 vs 0.18), lower in winter (0.20–0.22 vs 0.25–0.26)
- **Prices vs the seasonal run (2020–24):** average almost unchanged (Rs 2,667 vs 2,658/MWh), system cost +0.5%. **April +156, May +136** (low reservoirs, 7–10 GW more coal); **Aug −185, Sep −88, Oct −92** (full reservoirs, monsoon solar, 5–12 GW less coal); Dec +100, Jan +56 (weak winter solar)
- **Day-to-day volatility up ~40%:** mean daily change 74 vs 53 Rs/MWh, std 422 vs 356; prices jump between coal-tier levels (~2,200 / ~2,750 / ~3,450)
- **Price baselines (test 2024 – Mar 2025, deferred from Step 12):** persistence MAE 142 Rs/MWh, **MAPE 4.58%**, RMSE 261; last week MAPE 6.92%. Price is about twice as hard as national demand, and RMSE/MAE = 1.8 shows the errors come as jumps

> **Updated in Step 16a** (spike fix): price persistence MAE 139 Rs/MWh, MAPE 4.48%, RMSE 255; mean daily change 73 Rs/MWh; other results unchanged to the reported precision.

**Outputs:** `data/processed/availability_daily.csv`; `data/processed/dispatch_weather_{state,flows,national}_daily.csv` — the "actual" prices for Part 2. Constant (`dispatch_*`) and seasonal (`seasonal_*`) runs are kept for comparison.

**Limitations:** the shapes are physical rules, not fitted to measured generation (CEA data could calibrate them); snowmelt share and threshold are single values for five states; hydro buckets ignore reservoir operating rules and pumped storage; daily averages, not the peak hour (Step 11, decision 3).

---

### Step 16a — One-day demand spikes fixed at source (2026-10-25)
**Why:** building the Stage 3 features showed daily demand ratios up to e^4 (×50): a few days in the cleaned data were typos (Telangana 236 MW on 1 Oct 2023 between ~12,400 MW days; Tamil Nadu 933 MW; Sikkim 1,700 MW vs ~90; HP 4,309 vs ~1,700). They were also in Part 1's dispatch: Telangana "used" 236 MW that day.

**Rule (`01_data_cleaning.ipynb`, before the gap fill):** `Max Demand Met` more than 65% away from its 7-day centred median (|log(value / median)| > 0.5) → missing → filled from the previous day like other gaps.

**Exceptions — real events kept:** 4 flagged dips fall on cyclone landfalls: Goa 17 May 2021 (Tauktae), Bihar 28 May 2021 (Yaas), Mizoram 28 May 2024 (Remal), Puducherry 1 Dec 2024 (Fengal). Each flagged day was looked at with its week. Of the 21 fixed, a few small-state dips (Sikkim, Tripura, Chandigarh, Arunachal) and Rajasthan on 4 Feb 2024 (7,976 vs ~17,000 MW) could be real local outages; none matches a known event, so they are treated as errors. `Energy Met` is not cleaned this way: several of its dips are real cyclone days and no model uses it.

**Checks:** 25 flagged → 21 set to missing, 4 kept; after the fill no spike is left except the 4 events (asserted). Goa's three "64 MW" days in Aug 2020 were one raw bad day plus copies made by the fill: fixed together.

**Re-run:** notebooks 03, 04, 05, 07 (06 unaffected: none of its states changed). 22–23 days change price per run; largest change Rs 649/MWh (weather run, a coal-tier step). All 55 tests pass, including the 21 Jul 2024 reference value. Updated numbers are noted in Steps 12 and 15.

**Lesson:** read the *whole* output before writing a conclusion: Step 12's state range was taken from a table cut off at 1,800 characters.

### Step 16 — Day-ahead demand forecasting, L0–L6 (2026-10-25)
**Why:** Part 2's O1: forecast every state's peak demand for tomorrow, better than "same as yesterday" by at least 20% (national skill ≥ 0.20).

**Decisions (Stage 3, asked one at a time):**
1. **Bottom-up:** 32 states, national = sum; a direct national model as a yardstick
2. **Target = change ratio**, as y = log(demand_T / demand_D); forecast = demand_D × exp(y); y = 0 is persistence. (Trees can't predict above past records, so the level is carried by "today")
3. **Degree days with fixed bases:** cooling above 24 °C, heating below 18 °C (daily mean), as tomorrow − today; trees also get raw temperatures
4. **Holidays:** national gazetted + 8 major regional festivals (`holidays.csv`, 152 rows, sources per row; researched 2026-10-25, reviewed by the user)
5. **Paddy flags** for Punjab and Haryana from each year's main transplanting start (`paddy_dates.csv`)
6. **COVID:** target days 25 Mar – 1 Jun 2020 not used for fitting (still used as lag history)

**Defaults:** walk-forward with monthly refits over Jan 2024 – Mar 2025 (15 months); two weather cases, *perfect* (tomorrow's actual weather) and *persistence* (today's weather); LightGBM tuned on 2023 only (trained on 2020–22; 24-setting grid, all within 2,411–2,598 MW, best: 31 leaves, learning rate 0.03, 800 trees, ≥ 100 rows per leaf); L2/L3 are ridge regressions (alpha 1) with one-hot weekday, month and state.

**Setup problems:** pip could not reach PyPI (read timeouts, also from the user's own terminal, while curl worked), so scikit-learn 1.9.1 and LightGBM 4.7.0 wheels were downloaded with curl, checked against PyPI's SHA-256 digests and installed offline. Building the features exposed the one-day demand typos fixed in Step 16a.

**Code:** `src/features.py` (feature table; 7 tests, incl. "changing demand on or after T, or weather after T, changes no feature of T" and "persistence weather never reads T's weather"); `src/forecast.py` (Persistence, LastWeek, Profile, Linear, Trees, PerState, walk_forward, national_features; 5 tests, incl. "walk-forward never trains on the month it predicts" and the lockdown exclusion). 67 tests in total. Persistence through the new code reproduces notebook 05 exactly (4,842 MW).

**Results (`08_demand_forecast.ipynb`, national, perfect weather):**

| Step | MAE | MAPE | Skill |
|---|---|---|---|
| L0 persistence | 4,842 MW | 2.22% | 0 |
| L0 last week | 6,841 | 3.14% | −0.41 |
| L1 profile | 3,344 | 1.54% | 0.31 |
| L2 linear | 3,101 | 1.42% | 0.36 |
| L3 linear + weather | 2,834 | 1.30% | 0.42 |
| L4 LightGBM | 2,542 | 1.17% | 0.48 |
| L5 linear per state | 2,726 | 1.25% | 0.44 |
| L5 LightGBM per state | 2,508 | 1.16% | 0.48 |
| **L6 LightGBM median** | **2,416** | **1.11%** | **0.50** |

- **Target met from L1 upward.** Each step added something
- Weather worth ~10%: with persistence weather L4 is 2,793 MW (skill 0.42), L6 2,711 (0.44)
- Per-state linear beats pooled linear; per-state LightGBM ≈ pooled nationally but worse for states (MAPE 3.64% vs 3.43%) and 8× slower → pooled LightGBM preferred
- Bottom-up ≥ direct national (L4: 2,542 vs 2,646 MW)
- L6 10–90% range covers 75% of actuals (target 80%), width 9.4% of demand: slightly overconfident
- L3 coefficients: 23% of last week's same-weekday change repeats; 16% of today's jump reverses; holiday tomorrow −2.2%; first paddy day +3.8%; +1 cooling degree day +1.6%; rain −0.07%/mm
- Fixed: Mondays 10.2 → 2.9 GW, Sundays 8.2 → 2.3 GW, **heatwave (17 May – 19 Jun 2024) 4.8 → 2.2 GW**
- **Still weak: national holidays** (7.4 GW vs 2.3 GW on other days). Under-forecast drops on Holi 2025 (19.9 GW) and Diwali 2024 (15.3 GW); predicted dips that didn't happen on Maha Shivratri 2025 (14.6 GW) and Good Friday 2024 (10.9 GW). All holidays are treated alike → a major/minor holiday feature is the next improvement
- Every state improves on persistence: most Tamil Nadu (0.52), least J&K (0.05), Odisha (0.07), Manipur (0.08)

**Output:** `data/processed/demand_forecast_test.csv` (206,112 rows: 11 models × weather cases × 32 states + National, every test day; L6 rows carry the 10–90% range). **For Stage 5:** L6 LightGBM median (pooled) as the main forecast, L4 as the alternative.

**Not done here (Stage 6):** forecast horizons of 7 and 30 days, training-length tests, what-ifs.

### Step 17 — Forecasting availability; demand with real weather forecasts (2026-10-26)
**Why:** Part 2's O2 (forecast tomorrow's solar, wind and hydro availability), and a realistic weather case for O1: Stage 3 had only the bounds "perfect" and "persistence" weather.

**Decisions (Stage 4, asked one at a time):**
1. **Both approaches:** the Stage 2 physical rules run on real weather forecasts, and a statistical ladder; compared
2. **True day-ahead forecasts:** Open-Meteo's previous-runs archive (`*_previous_day1`: each hour as forecast the day before). Complete from March 2024 → **every case scored on Mar 2024 – Mar 2025 (13 months)**
3. Ladder for **solar and wind**; hydro forecast by **rolling the bucket forward** one day
4. Score = national error in **available MW** per fuel; target skill ≥ 0.20 vs persistence for solar and wind
5. **Anchoring** (decided after the first run, see below): tomorrow = today's actual + (forecast for tomorrow − forecast for today)

**Defaults:** all 139 locations downloaded hourly (temperature, rain, radiation, cloud, 100 m wind), turned into the archive's daily variables (a day with any missing hour stays empty) and combined into states with the Stage 1 weights; each state's availability scale **frozen** from the actual-weather fit; demand models trained on actual weather and fed forecasts at test time ("perfect-prog").

**Change from the plan:** "L5 = LightGBM + forecast weather" was dropped: trained on actual weather it would re-learn the Stage 2 rule (actual availability *is* that rule on actual weather). Replaced by the average of physics-on-forecasts and LightGBM.

**Code:** `src/weather.py` (`fetch_all_previous_runs`, `hourly_to_daily`, `anchor_forecast`); `src/availability.py` (`build_availability(return_scales=True)`, `melt_scale`, `forecast_availability`, `anchor_availability`); `src/features.py` (`weather="day-ahead"`, `build_availability_features`); `src/forecast.py` (`walk_forward(test_f=..., to_forecast=...)`, `Today`, `MonthProfile`). 6 new tests (73 in total), incl. "anchoring cancels a constant bias" and "availability features can't see tomorrow". Checks: the refactor reproduces `availability_daily.csv`; actual weather fed in as the "forecast" reproduces actual availability exactly (validates the hydro roll-forward).

**First run, raw forecasts — a surprise:** solar availability from forecasts was **worse than "same as today"** (skill −0.58), and demand with forecasts was no better than with today's weather. Cause: the forecast model's **seasonal bias**, not random error: solar +1 to +3.8 GW too high in the hazy dry months, −1.5 to −4.3 GW too low in the monsoon; wind mostly too low (to −4.0 GW in May), too high in Dec–Jan (+2.8 GW). Mixing forecast (tomorrow) and archive (today) in one "change" feature turned that bias into fake changes. **Anchoring** cancels it; raw results are kept in the notebook.

**Results (`09_availability_forecast.ipynb`, Mar 2024 – Mar 2025):**

| Fuel | Same as today | Raw forecast | Anchored | LightGBM (no forecast) | Average anchored + LightGBM |
|---|---|---|---|---|---|
| Solar | 1,375 MW | 2,171 (−0.58) | 1,155 (0.16) | 1,276 (0.07) | **921 (0.33)** |
| Wind | 3,203 MW | 2,326 (0.27) | **1,647 (0.49)** | 3,175 (0.01) | 1,919 (0.40) |
| Large hydro | 89 MW | — | **64 (0.28)** | — | — |
| Small hydro | 39 MW | — | **27 (0.32)** | — | — |

- **Best per fuel ("best day-ahead", saved for Stage 5):** solar = average, wind = anchored, hydro = rolled bucket. All renewables together: **1,937 MW, skill 0.45**. Targets met for solar and wind
- Without a weather forecast, renewable output barely beats persistence (solar +7%, wind +1%); a monthly profile is far worse (−54%, −84%)
- Wind is the largest supply uncertainty: 1.6 GW typical error even when forecast; Gujarat largest (1.0 GW), Rajasthan gains most (skill 0.40)
- **Demand, real forecasts anchored:** L6 national MAE **2,623 MW, skill 0.48** (perfect 0.50, today's weather 0.43, raw forecasts 0.44). **0.48 is the realistic demand headline**
- Forecast quality vs archive: temperature correlation 0.97–0.98 (MAE ~1 °C), wind 0.90, radiation 0.84, cloud 0.87, rain 0.59 (and 20% too little)

**Outputs:** `data/raw/forecast_weather_daily.csv`; `data/processed/forecast_weather_state_daily.csv`, `availability_forecast_test.csv`, `demand_forecast_dayahead.csv`.

**Limitations:** 13 scored months; anchoring was chosen after seeing the first run on the same months (a standard method; raw results kept); "actual" availability is our weather model, not measured generation; the hourly forecast cache (~1.6 M rows) is not in git and takes ~1–2 h to re-download.

### Step 18 — Forecasting tomorrow's prices: Route B (dispatch) vs Route A (direct) (2026-10-26)
**Why:** Part 2's O3: forecast tomorrow's locational prices through the dispatch model, compare with a direct price model and persistence; plus O4's price ranges and O5's tightness index for Part 3.

**Decisions (Stage 5, asked one at a time):**
1. Route B runs: **actual, realistic** (L6 demand with anchored day-ahead weather + "best day-ahead" availability), **demand error only, supply error only, persistence**
2. Route A: **national and pooled-state** direct models on the change ratio log(price_T / price_D): persistence → profile → linear + weather → LightGBM (mean, median); trained on actual weather, fed anchored day-ahead weather; monthly walk-forward
3. Scoring: MAE and skill vs persistence (target 0.20) **+ jump detection** (national moves ≥ 200 Rs/MWh: recall, precision)
4. Ranges: dispatch at the **L6 10% and 90% demand** forecasts (day-ahead weather)

**Defaults:** scored Mar 2024 – Mar 2025; actual price = the Step 15 weather run; national price = demand-weighted (forecasts by forecast demand); persistence = today's price (equal to dispatching today's inputs); tightness = (available MW − demand) / demand per state and India.

**Code:** `src/forecast.py`: `jump_scores`, `available_capacity`, `tightness`; `national_features(national=...)` now weights states by demand on D (identical for demand, needed for price). 3 new tests (76 in total). Check: the "actual" run reproduces the saved actual prices within 0.84 Rs/MWh (one day; 4-decimal rounding of saved factors).

**Results (`10_price_forecast.ipynb`, national price):**

| | MAE (Rs/MWh) | Skill | Jumps caught | Precision |
|---|---|---|---|---|
| Persistence | 132 | 0 | 0/87 | — |
| **Route B realistic** | **63** | **0.53** | **58/87** | **73%** |
| Route B demand error only | 48 | 0.64 | 66/87 | 84% |
| Route B supply error only | 38 | 0.71 | 68/87 | 83% |
| Route A national, LightGBM median (best A) | 127 | 0.04 | 0/87 | — |
| Route A national, LightGBM | 149 | −0.12 | 26/87 | 46% |
| Route A states, LightGBM | 156 | −0.18 | 34/87 | 37% |

- **Route B meets the target nationally and in every state** (state skill 0.51–0.54: trade ties the prices together)
- **Route A fails:** price history can't tell where the next coal-tier step is; the median model learns "no change", the mean model calls jumps at random. For a stepped price the structural model is necessary
- **Demand error costs more than supply error** (48 vs 38 Rs/MWh alone); together 63 (partial cancellation)
- **Ranges:** average 351 Rs/MWh, contain the actual on 93% of days; downside (195) ≈ upside (156) on average, but on 20% of days the upside is > 2× the downside (just below a step). My expectation of mostly upward risk was wrong
- **Tightness:** India 22% spare on average (min 4.5%); forecast within 1.8 percentage points. Price by tightness fifth: Rs 2,653 (loosest) → 3,708 (tightest). Jumps most frequent in the middle fifths (32–34% of days), near the steps

**Output:** `data/processed/price_forecast_test.csv` (92,268 rows).

**Limitations:** the "actual" price is our dispatch model, so Route B uses the exact price mechanism and Route A must learn it (with real IEX prices Route B would also carry model error); 13 scored months; Route A not re-tuned for prices.

### Step 19 — What-if scenarios and step-edge price errors (2026-10-26)
**Why:** Part 2's O4 (when do forecasts fail) and a bridge to Part 3: which shocks create the tight days where market power would bite.

**Decisions:** Stage 6 tests chosen by me after the user expressed no preference: **what-if scenarios** (all four offered) and **step-edge price errors**. Skipped (noted as extensions): 7- and 30-day horizons, training-length tests.

**Scenarios (all of 2024, vs the Step 15 actual run):** demand +5%; drought (large and small hydro × 0.7); low-wind monsoon (each state's Jun–Sep wind scaled so every month averages its worst monsoon month, day-to-day variation kept); coal shortage (coal 0.75 → 0.65); all four together. `scale_availability` in `src/availability.py` (1 new test, 77 in total). Check: the base scenario reproduces the actual 2024 prices.

**Results (`11_scenarios.ipynb`; base 2024: Rs 3,069/MWh, 23% spare, no shortages):**

| Scenario | Price | Cost | Days up a step | Unserved days | Days < 10% spare |
|---|---|---|---|---|---|
| Demand +5% | +230 (+7.5%) | +10.8% | 170 | 0 | 92 |
| Drought | +135 | +4.6% | 74 | 0 | 41 |
| Low-wind monsoon | +51 (June +254) | +3.2% | 30 | 0 | 18 |
| Coal shortage | +720 (+23%) | +6.3% | 275 | 17 (max 3.4 GW) | 165 |
| All four | +3,286 (+107%) | +35% | 363 | 156 (max 22.6 GW) | 313 |

- Price is more sensitive than demand (5% → 7.5%): the supply curve is steep at the top
- Coal shortage is the largest single shock and the only one causing shortages; worst in January (+2,281 Rs/MWh)
- Shocks compound: ~1,140 Rs/MWh separately, 3,286 together
- The north (J&K, Punjab, Haryana, Chandigarh, Uttarakhand) is hit most
- **Step edges:** 21% of scored days sit near a step (+2% demand → ≥ 100 Rs/MWh). Route B error there is 146 vs 41 Rs/MWh elsewhere (skill 0.30 vs 0.60); correlation 0.39

**Output:** `data/processed/scenario_results.csv` (72,468 rows).

**Limitations:** uniform, year-round shocks; same coal factor everywhere; no ramping, reserves or demand response, so scarcity appears directly as unserved load priced at the value of lost load.

### Step 20 — Part 3 forecast package, IEX price hook, Part 2 report (2026-10-26)
**Why:** Part 2's O5 (hand Part 3 a view of tomorrow), the IEX compatibility promised in Step 11, and a written record of Part 2.

**Forecast package (`12_part3_package.ipynb` → `data/processed/part3_forecast_package.csv`, 13,068 rows = 396 days × 32 states + National):** for each day and area, as forecast the day before: demand (L6 with real anchored day-ahead weather) with a 10–90% range (L6 quantile models re-run with day-ahead weather; India's range = sum of state ranges, conservative), available MW by fuel group (best day-ahead), price with low/high (Stage 5), tightness, and a **near-step flag** (forecast demand +2% through dispatch raises the national price ≥ 100 Rs/MWh); plus the actual values. Loaded with `load_forecast_package()` in `src/forecast.py`. Checks: complete, no gaps; India = sum of states; low ≤ high; price equals Stage 5's realistic run (within 0.01).
- On the 44 days forecast to have < 10% spare capacity, forecast price Rs 3,754/MWh vs 3,736 actual
- The forecast near-step flag finds 50% of actual near-step days; same answer on 79% of days; near-step days concentrate at 10–20% spare
- State demand 10–90% range contains the actual 74.6% of the time

**IEX hook (`src/prices.py`):** common price format (`Date, Area, Price, Source`); `load_prices("model" | "iex")`; `to_bid_areas` (state prices → IEX bid-area prices, demand-weighted); `compare_prices` (MAE, bias, correlation, matched jumps). `data/raw/iex_bid_areas.csv`: 32 states → 13 bid areas, researched from published tables (JETIR 2018 13-area table, MPRA 103161 and 72969, an IEX DAM/GDAM training module); **four flagged uncertain:** Goa (split North W2 / South S1; W2 chosen), Puducherry (S2; Yanam S1), Meghalaya (A2 now, A1 in older tables), Ladakh (not listed; N1 with J&K). The date the 13-area layout took effect could not be confirmed (between 2016 and 2018). No IEX data downloaded: the steps are in `data/README.md`. 5 tests on made-up market data (82 in total).

**Report:** `reports/part2_forecasting.md` with six figures from `reports/make_part2_figures.py`. Writing it caught one inconsistency: the summary compared demand persistence over 15 months (4,842 MW) with the day-ahead forecast over 13 months; on the same 13 months persistence is 5,053 MW (2.32%), the forecast 2,623 MW (1.21%), skill 0.48.

**Problems met:** two checks in notebook 12 were too strict or wrong at first (a price-match tolerance of 1e-6 against 4-decimal saved values; missing fuel groups left empty instead of 0 MW), both fixed.

**End-to-end check:** notebooks 05–12 re-run in order from the committed data (results below the Part 2 summary).

---

## Part 2 summary
Day-ahead (D → D+1) forecasts, out-of-sample, Mar 2024 – Mar 2025, vs "same as today": India demand skill **0.48** (2,623 vs 5,053 MW); solar availability **0.33**, wind **0.49**; national price **0.53** (63 vs 132 Rs/MWh) through the dispatch model, while a direct price model cannot beat persistence. Key lessons: the weekly rhythm is most of the easy demand gain; real weather forecasts must be anchored (their seasonal bias otherwise makes solar worse than persistence); a stepped price needs the structural model; price-forecast risk concentrates on step-edge days; a coal shortage is the largest single shock and shocks compound. Report: `reports/part2_forecasting.md`.

**End-to-end check result (2026-10-26):** notebooks 05–12 re-run in order (08: 25 min; total ~38 min): no errors; every saved result is numerically identical (the Part 3 package byte-for-byte; notebook 07's dispatch files differed only in how some floats were written as text, largest numeric difference 0.0, so the committed copies were kept); 82 tests pass.
