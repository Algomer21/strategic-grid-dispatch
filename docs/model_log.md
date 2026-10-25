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

**Outputs:** `data/processed/availability_daily.csv`; `data/processed/dispatch_weather_{state,flows,national}_daily.csv` — the "actual" prices for Part 2. Constant (`dispatch_*`) and seasonal (`seasonal_*`) runs are kept for comparison.

**Limitations:** the shapes are physical rules, not fitted to measured generation (CEA data could calibrate them); snowmelt share and threshold are single values for five states; hydro buckets ignore reservoir operating rules and pumped storage; daily averages, not the peak hour (Step 11, decision 3).
