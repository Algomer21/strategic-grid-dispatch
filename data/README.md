# Data

Every file the project reads or writes, where it comes from, and the assumptions inside it.

`raw/` files are inputs and are never edited by a notebook. `processed/` files are outputs and can be rebuilt by running the notebooks in order.

## raw/

### india_electricity_data.csv
Daily state-level power supply data, 1 Jan 2020 – 31 Mar 2025 (69,012 rows, 36 entities).

| Column | Unit | Meaning |
|---|---|---|
| Date | | Day |
| State | | State, UT or utility (also DVC, Essar steel, separate DD and DNH) |
| Max Demand Met | MW | Highest demand served that day |
| Shortage During Peak | MW | Demand not served at that peak |
| Energy Met | MU/day | Energy served over 24 hours |
| Drawl Schedule | MU/day | Scheduled import from the central grid |
| OD(+) / UD(-) | MU/day | Over/under-drawal against schedule |
| Max OD | MW | Largest over-drawal that day |
| Energy Shortage | MU/day | Energy not served |

**Known issues (fixed in `01_data_cleaning.ipynb`, never in this file):**
- 1,027 DNH rows (June 2022 onward) have every value shifted one column right
- 7 HP rows are corrupted (values don't fit HP), on the same dates DD and DNH are missing
- 10 rows with `Energy Met = 0`, 16 with negative `Energy Shortage`, 1 with negative `Shortage During Peak` (Kerala, 29 Jan 2020)
- From June 2022, DD stops reporting and DNH carries the merged UT total

### india_generator_stack.csv
Installed capacity by state and fuel (161 rows, 32 states, 10 fuels).

| Column | Unit | Note |
|---|---|---|
| State | | Uses `DNH and DD`; renamed to `DD & DNH` when loaded |
| Fuel_Type | | Solar, Wind, Large Hydro, Small Hydro, Coal, Lignite, Nuclear, Biopower, Gas, Diesel |
| Capacity_MW | MW | Nameplate capacity |
| Marginal_Cost_Rs_per_MWh | Rs/MWh | One cost per fuel (solar/wind 0, hydro 1,000, coal 2,000, lignite 2,300, nuclear/bio 3,500, gas 4,500, diesel 11,000). Coal is replaced by `coal_cost_tiers.csv` |

No generator data for DVC.

### coal_cost_tiers.csv
Coal marginal cost by state, replacing the flat Rs 2,000 (16 states).

| Tier | Rs/MWh | States | Reasoning |
|---|---|---|---|
| Pithead | 1,600 | Chhattisgarh, ER Odisha, MP, Telangana | Next to the mines |
| Near mines | 2,200 | West Bengal, NR UP, Bihar, Assam | Short rail haul |
| Inland far | 2,800 | Haryana, Punjab, Rajasthan, WR Maharashtra, SR Karnataka, Andhra Pradesh | Long rail haul |
| Coastal imported | 3,800 | Gujarat, Tamil Nadu | Imported or sea-shipped coal |

Assumption: rough tier averages within the Rs 1,500–5,000 range seen on the MERIT India portal, not plant-level costs.

### seasonal_availability.csv
Monthly availability factor (share of nameplate available at the daily peak) for the four weather-driven fuels.

| Column | Meaning |
|---|---|
| Month | 1–12 |
| Solar, Wind, Large Hydro, Small Hydro | Availability factor that month |

Assumptions:
- Shapes follow typical Indian patterns: wind peaks Jun–Aug (monsoon winds), hydro peaks Jul–Sep (monsoon rain) and is lowest Mar–May, solar dips Jul–Aug (cloud cover)
- Each fuel's 12-month average equals its constant factor in `src/dispatch.py` (solar 0.25, wind 0.30, large hydro 0.45, small hydro 0.40), so a seasonal run has the same yearly renewable supply as the constant run, only timed differently
- Not measured data; can be refined against CEA monthly generation reports
- All other fuels (including coal) keep a constant factor all year

### state_coordinates.csv
One point per state: its capital (32 rows). Used for distances between states.

Choices: Punjab, Haryana and Chandigarh all use Chandigarh (0 km apart); J&K & Ladakh uses Srinagar (summer capital); DD & DNH uses Daman.

### weather_points.csv
Where weather is measured for Part 2: 151 points (139 unique locations), each tied to a state and a purpose. Hand-curated, reviewed 2026-10-25 (model log Step 13).

| Column | Meaning |
|---|---|
| Point_ID | Unique id, `purpose_place_state` |
| State | State name as in the demand data |
| Purpose | `demand`, `solar`, `wind` or `hydro` |
| Place | City, solar park, wind zone or dam |
| Lat, Lon | Decimal degrees |
| Reason | Why this point was chosen |

Rules:
- **Demand (56):** the 12 states with mean peak demand ≥ 8,000 MW use their 3 largest cities (Census 2011) that are at least 100 km apart, combined by population (`city_population.csv`). Nearby big cities are skipped (Kanpur near Lucknow, Gurgaon near Faridabad, Howrah near Kolkata), so their population is not in the weights. Other states use their capital
- **Solar (46), wind (17), hydro (32):** every state with any capacity of that fuel in `india_generator_stack.csv` gets points; states with ≥ 5,000 MW of the fuel get 2–3 points (simple average, no plant-level capacity data), others 1. Small rooftop-solar states and Goa's 0.05 MW hydro use the capital
- Hydro points are at the dam, not upstream in the catchment; Himalayan hydro is snowmelt-driven in summer (temperature at those points can be used as a proxy)
- 7 rows are marked "location approximate" (small capacity: Odisha, Assam and West Bengal solar, Telangana wind, Mizoram, Bihar and Tripura hydro)

### city_population.csv
Population weights for the 36 demand cities in the 12 multi-city states (3 per state).

| Column | Meaning |
|---|---|
| Point_ID | Matches `weather_points.csv` |
| State, City | |
| Population_2011 | Census 2011 city population |
| Source | Wikipedia "List of cities in India by population" (accessed 2026-10-25) |

Some figures are for expanded city limits (e.g. Chennai 6.7 M instead of the 2011 city's 4.6 M); one source for all cities keeps the weights consistent.

### weather_daily.csv
Daily weather at every point in `weather_points.csv`, 1 Dec 2019 – 31 Mar 2025: 151 points × 1,948 days = 294,148 rows (~20 MB). Downloaded by `src/weather.py` (`fetch_all`), checked by `check_weather`, saved in `06_weather_data.ipynb`. Never edited by hand.

Source: [Open-Meteo](https://open-meteo.com/) historical weather archive (reanalysis, ERA5-based, ~10–25 km grid), licence CC BY 4.0. Days in Indian time (`Asia/Kolkata`).

| Column | Meaning |
|---|---|
| Point_ID | Matches `weather_points.csv` |
| Date | Calendar day (IST) |
| temperature_2m_max / _mean / _min | Air temperature at 2 m, °C |
| precipitation_sum | Rain (and snow as water), mm/day |
| shortwave_radiation_sum | Solar radiation, MJ/m² per day |
| cloud_cover_mean | % |
| wind_speed_100m_mean | Wind speed at 100 m (about turbine height), km/h |

Notes:
- Actual weather, so using it for day D+1 is the "perfect weather forecast" case
- Points that share a place (e.g. a capital used for demand and solar) have identical rows
- Rebuilding: re-run notebook 06. Each location is cached in `data/cache/weather/` (not in git); the free API allows ~100 five-year location downloads per hour, so a rebuild from an empty cache needs about 1.5 hours

### holidays.csv
Public holidays used as demand-forecast features, 1 Jan 2020 – 31 Mar 2025: 152 rows. Reviewed 2026-10-25 (model log Step 16).

| Column | Meaning |
|---|---|
| Date | Holiday date |
| Name | Holiday or festival |
| Scope | `national` or `regional` |
| States | `all`, or the states (`;`-separated, demand-data names) that observe it |
| Source | URL or notification the date comes from |

- **National (89):** the 17 gazetted holidays per year for Central Government offices in Delhi (DoPT office memoranda; read from gconnect.in copies, 2022 checked against a scan of the signed list because the copies had errors). Muharram 2021 uses the changed date (20 Aug). Moon-dependent dates (Id, Muharram) are as notified; short-notice changes announced on radio/TV would not appear
- **Regional (63):** Durga Puja (Saptami–Navami; West Bengal's notified dates, assumed for Odisha, Assam, Tripura), Onam (Thiruvonam only), Pongal, Chhath (evening day only), Ganesh Chaturthi (2023 split: 18 Sep in Karnataka, Telangana, AP; 19 Sep in Maharashtra, Goa), Bohag Bihu (3 days), Ugadi / Gudi Padwa, Vaisakhi (Punjab only: optional holiday in Haryana)
- Weekend holidays are kept as notified

### paddy_dates.csv
Start of paddy transplanting in Punjab and Haryana, 2020–2024 (10 rows): farm pumps switch on and demand jumps. Reviewed 2026-10-25 (model log Step 16).

| Column | Meaning |
|---|---|
| State, Year | |
| First_allowed | First date transplanting was allowed anywhere in the state |
| Main_start | First date whole districts could start (**used for the flag**; differs in 2022 and 2023, when the first date covered only the strip beyond the border fence) |
| Schedule | Zone schedule if staggered |
| Source | Dated Tribune article |

Punjab: 10 Jun 2020, 10 Jun 2021, 14 Jun 2022, 16 Jun 2023, 11 Jun 2024 (main start). Haryana: 15 June every year (fixed by the Haryana Preservation of Subsoil Water Act 2009). The paddy-season flag runs from `Main_start` to 30 September.

### forecast_weather_daily.csv
Day-ahead weather forecasts at every point in `weather_points.csv`, 1 Jan 2024 – 31 Mar 2025 (151 points × 456 days = 68,856 rows). Each value is what the forecast issued the **day before** said: Open-Meteo previous-runs archive (`*_previous_day1` hourly variables), turned into the same daily variables as `weather_daily.csv` by `hourly_to_daily` in `src/weather.py` (`09_availability_forecast.ipynb`). Licence CC BY 4.0.

- Same columns and units as `weather_daily.csv`
- **Complete from March 2024**; Jan–Feb 2024 mostly empty (a day with any missing hour is left empty)
- The forecasts are biased by season (e.g. solar radiation too high in hazy dry months, too low in the monsoon), so Part 2 uses them *anchored*: today's actual + forecast change (model log Step 17)
- Hourly data cached in `data/cache/forecast_hourly/` (not in git; ~1–2 h to re-download)

### iex_bid_areas.csv
Each of the 32 states → its IEX Day-Ahead Market **bid area** (13 areas: A1, A2, E1, E2, N1–N3, S1–S3, W1–W3) and grid region, for comparing model prices with real exchange prices (`src/prices.py`). Researched 2026-10-26 (model log Step 20).

| Column | Meaning |
|---|---|
| State | As in the demand data |
| Bid_area | IEX bid area |
| Region | Grid region (NR, WR, SR, ER, NER) |
| Note | Caveats; entries starting `UNCERTAIN` need checking |
| Source | Published tables the mapping comes from |

Sources: the 13-area table in JETIR (2018) [jetir.org/papers/JETIR1809063.pdf], MPRA papers 103161 (2020) and 72969 (12-area, 2008–14) [mpra.ub.uni-muenchen.de], an IEX DAM/GDAM training module (2021+). iexindia.com's own mapping page could not be reached. **Uncertain:** Goa (split: North W2, South S1; W2 used), Puducherry (S2; the Yanam enclave is S1), Meghalaya (A2 in the 13-area table, A1 in older ones), Ladakh (not listed; assumed N1 with J&K). The 13-area layout dates from between 2016 and 2018; before it Kerala was in S2.

### iex_dam_daily.csv (not in the repo — to add later)
Real IEX Day-Ahead Market prices, to compare with the model (`load_prices("iex")`, `compare_prices`). **How to add:**
1. Download DAM area prices from iexindia.com (Market Data → Day-Ahead Market → Area Prices), for 1 Mar 2024 – 31 Mar 2025, 15-minute or hourly blocks for every bid area
2. Aggregate to **one value per day and bid area that matches the model's daily *peak* price**: recommended, the average price of the 18:00–22:00 blocks (the evening peak). Note the choice in this README
3. Save as `data/raw/iex_dam_daily.csv` with columns `Date, Bid_area, Price` (Rs/MWh)
4. Compare: `prices.compare_prices(prices.to_bid_areas(model_state_prices, demand), prices.load_prices("iex"))` (example in `12_part3_package.ipynb`)

Check IEX's terms of use before committing their data to a public repository.

## processed/

| File | Made by | One row per | Contents |
|---|---|---|---|
| india_electricity_data_updated.csv | 01_data_cleaning | Day × state (33) | Cleaned demand data: fixes applied, Essar steel and Jharkhand dropped, DD + DNH merged, 21 one-day demand spikes set to missing (4 cyclone days kept; model log Step 16a), gaps filled within each state |
| dispatch_state_daily.csv | 03_dispatch_all_days | Day × state (32) | Constant-availability run: demand, generation, unserved, imports, exports, price |
| dispatch_flows_daily.csv | 03_dispatch_all_days | Day × trade | From, to, MW sent, loss %, MW received |
| dispatch_national_daily.csv | 03_dispatch_all_days | Day | Totals, losses, min/avg/max price, generation by fuel |
| seasonal_state_daily.csv | 04_seasonal_availability | Day × state (32) | As dispatch_state_daily, with seasonal availability |
| seasonal_flows_daily.csv | 04_seasonal_availability | Day × trade | As dispatch_flows_daily, with seasonal availability |
| seasonal_national_daily.csv | 04_seasonal_availability | Day | As dispatch_national_daily, with seasonal availability |
| weather_state_daily.csv | 06_weather_data | Day × state × purpose (101 groups) | Weather combined from the points (details below) |
| availability_daily.csv | 07_weather_availability | Day × state × weather fuel (93 pairs) | Daily availability factor from the weather (details below) |
| dispatch_weather_state_daily.csv | 07_weather_availability | Day × state (32) | **Weather-availability run: the "actual" prices for Part 2.** Same columns as dispatch_state_daily |
| dispatch_weather_flows_daily.csv | 07_weather_availability | Day × trade | As dispatch_flows_daily, weather-availability run |
| dispatch_weather_national_daily.csv | 07_weather_availability | Day | As dispatch_national_daily, weather-availability run |
| demand_forecast_test.csv | 08_demand_forecast | Day × area × model × weather case | Day-ahead demand forecasts for the test period (details below) |
| forecast_weather_state_daily.csv | 09_availability_forecast | Day × state × purpose | Day-ahead forecast weather combined into states (same weights and columns as weather_state_daily) |
| availability_forecast_test.csv | 09_availability_forecast | Day × state × weather fuel × model | Day-ahead availability forecasts, 2024 – Mar 2025 (details below) |
| demand_forecast_dayahead.csv | 09_availability_forecast | Day × state × model × weather case | Stage 3 demand models fed real day-ahead forecasts, Feb 2024 – Mar 2025 (details below) |
| price_forecast_test.csv | 10_price_forecast | Day × area × route × run | Tomorrow's price forecasts (Route B dispatch runs, Route A direct models), ranges and tightness, Mar 2024 – Mar 2025 (details below) |
| scenario_results.csv | 11_scenarios | Day × area × scenario | 2024 dispatch under what-if shocks: base, demand +5%, drought, low-wind monsoon, coal shortage, all four (details below) |
| part3_forecast_package.csv | 12_part3_package | Day × area (32 states + National) | **The hand-off to Part 3:** tomorrow's forecasts as known the day before, next to actuals (details below) |

### weather_state_daily.csv
Daily weather per state and purpose: the weighted average of that state's points in `raw/weather_daily.csv`. 101 groups (32 demand, 32 solar, 9 wind, 28 hydro) × 1,948 days = 196,748 rows (~13 MB). Made by `combine_points` in `src/weather.py`, saved in `06_weather_data.ipynb`.

| Column | Meaning |
|---|---|
| Date | Calendar day (IST), 1 Dec 2019 – 31 Mar 2025 |
| State | As in the demand data |
| Purpose | `demand`, `solar`, `wind` or `hydro` |
| (weather columns) | Same variables and units as `raw/weather_daily.csv` |

Weights: demand points by Census 2011 city population (`raw/city_population.csv`); supply points equal (no plant-level capacity); single points unchanged. Averaged day by day.

### availability_daily.csv
Share of nameplate capacity available each day for solar, wind, large hydro and small hydro, for every state with capacity of that fuel: 93 state-fuel pairs × 1,948 days (1 Dec 2019 – 31 Mar 2025) = 181,164 rows. Made by `build_availability` in `src/availability.py` (model log Step 15).

| Column | Meaning |
|---|---|
| Date | Calendar day (IST) |
| State | As in the demand data |
| Fuel_Type | Solar, Wind, Large Hydro or Small Hydro |
| Factor | 0–1, share of capacity available |

How: solar from radiation with panel heat loss; wind from a power curve on hourly 100 m wind (hourly data cached in `data/cache/wind_hourly/`, not in git; ~1 h to re-download); hydro from leaky buckets of rain (+ snowmelt in 5 Himalayan states). Each state's 2020–24 mean is scaled to the Part 1 factor (solar 0.25, wind 0.30, large hydro 0.45, small hydro 0.40) and capped at 1.0. Coal and other fuels are not in the table: they keep their constant factors.

### demand_forecast_test.csv
Every Stage 3 model's day-ahead forecast for every test day (1 Jan 2024 – 31 Mar 2025), 206,112 rows. Made in `08_demand_forecast.ipynb` (model log Step 16).

| Column | Meaning |
|---|---|
| Date | Target day T (forecast made on T − 1) |
| State | One of the 32 states, or `National` for the direct national model |
| Model | `L0 persistence`, `L0 last week`, `L1 profile`, `L2 linear`, `L3 linear + weather`, `L4 LightGBM`, `L5 linear per state`, `L5 LightGBM per state`, `L6 LightGBM median`, and `... (direct national)` |
| Weather | `none` (model uses no weather), `perfect` (tomorrow's actual weather) or `persistence` (today's weather) |
| Forecast | Forecast peak demand, MW |
| Q10, Q90 | 10% and 90% forecasts (L6, perfect weather only; empty otherwise) |
| Actual | Actual peak demand, MW |

National = sum of the 32 state rows for a model; the `(direct national)` rows are the yardstick model fitted to the national total.

### availability_forecast_test.csv
Tomorrow's availability factor for every state and weather fuel, 1 Jan 2024 – 31 Mar 2025, by model (247,196 rows). Made in `09_availability_forecast.ipynb` (model log Step 17).

| Column | Meaning |
|---|---|
| Date, State, Fuel_Type | Target day T (forecast made on T − 1) |
| Model | `L0 persistence`, `L1 month profile`, `L4 LightGBM` (solar, wind), `physics, perfect weather`, `physics, day-ahead raw`, `physics, day-ahead anchored`, `average of anchored physics + L4`, **`best day-ahead`** (solar = average, wind = anchored, hydro = rolled bucket: the input for Stage 5) |
| Weather | `none`, `perfect`, `persistence`, `day-ahead raw` or `day-ahead` (anchored) |
| Forecast, Actual | Availability factor (0–1) |

Day-ahead rows exist where forecasts do (complete from March 2024); scores use Mar 2024 – Mar 2025.

### demand_forecast_dayahead.csv
Stage 3 models L3, L4 and L6 (trained on actual weather) fed real day-ahead forecasts, monthly walk-forward from March 2024 (76,032 rows). Columns: Date, State, Model, Weather (`day-ahead` = anchored temperatures, `day-ahead raw`), Forecast, Actual (MW). Perfect and persistence-weather results for the same models are in `demand_forecast_test.csv`.

### price_forecast_test.csv
Tomorrow's price forecasts, Mar 2024 – Mar 2025 (92,268 rows). Made in `10_price_forecast.ipynb` (model log Step 18).

| Column | Meaning |
|---|---|
| Date | Target day T (forecast made on T − 1) |
| Area | A state, or `National` (demand-weighted average price) |
| Route | `B` = forecasts through the dispatch model; `A` = direct price model |
| Run | Route B: `actual`, `realistic`, `demand error only`, `supply error only`, `persistence`. Route A: `profile`, `linear + weather`, `LightGBM`, `LightGBM median` (national), `states LightGBM`, `states LightGBM median` |
| Forecast, Actual | Price, Rs/MWh (actual = the Step 15 weather-availability dispatch run) |
| Low, High | Route B realistic only: price with the 10% and 90% demand forecasts |
| Tightness_forecast, Tightness_actual | (available MW − demand) / demand for that area and day (Part 3 input) |

### scenario_results.csv
Dispatch results for every day of 2024 under six scenarios (72,468 rows). Made in `11_scenarios.ipynb` (model log Step 19).

| Column | Meaning |
|---|---|
| Date | Day |
| Area | A state, or `National` |
| Scenario | `base` (= the Step 15 actual run), `demand +5%`, `drought` (hydro × 0.7), `low-wind monsoon` (Jun–Sep wind at each state's worst monsoon month), `coal shortage` (coal 0.75 → 0.65), `all four` |
| Price | Rs/MWh (national: demand-weighted average) |
| Total_cost_Rs_per_h, Coal_MW | National rows only |
| Unserved_MW | Demand not met |

### part3_forecast_package.csv
What was known on day D about day D+1, per state and India, Mar 2024 – Mar 2025 (13,068 rows = 396 days × 33 areas). Made in `12_part3_package.ipynb`; load with `load_forecast_package()` in `src/forecast.py` (model log Step 20).

| Column | Meaning |
|---|---|
| Date, Area | Target day; a state or `National` |
| Demand_forecast, Demand_Q10, Demand_Q90 | L6 forecast and 10% / 90% forecasts (MW), real anchored day-ahead weather. National Q10/Q90 = sums of state values (wider than a true national range) |
| Demand_actual | MW |
| Solar_MW_forecast, Wind_MW_forecast, Hydro_MW_forecast, Coal_MW_forecast, Other_MW_forecast | Forecast available MW by fuel group (best day-ahead factors; coal and others at constant factors) |
| Available_MW_forecast, Available_MW_actual | Total available MW |
| Price_forecast, Price_low, Price_high, Price_actual | Route B price (Rs/MWh) and the prices with 10% / 90% demand |
| Tightness_forecast, Tightness_actual | (available − demand) / demand |
| Price_up2pct_forecast | National price if forecast demand were 2% higher (same on every row of a day) |
| Near_step_forecast, Near_step_actual | True if +2% demand raises the national price ≥ 100 Rs/MWh (forecast inputs / actual inputs) |


### market_structure_daily.csv
Part 3, Stage 1: each firm's market position on each day, Mar 2024 – Mar 2025 (11,880 rows = 396 days × 30 firms with strategic blocks). Made in `13_market_structure.ipynb` (model log Step 22).

| Column | Meaning |
|---|---|
| Date, Firm | Day; firm (= its state, one firm per state) |
| Strategic_MW | Available MW of the firm's strategic blocks (coal, lignite, gas, hydro), from `availability_daily.csv` |
| Share | Firm's share of all firms' strategic available MW (0–1) |
| RSI | Residual Supply Index: (all available MW − Strategic_MW) / (demand + losses of the competitive run) |
| Pivotal | RSI < 1: the market can't be served without this firm |
| Near_pivotal | RSI < 1.1. Weak on very tight days: when total supply < 1.1 × requirement (50 days) every firm passes |
| Region | Part 1 region (descriptive only: no regional market without line limits) |

### market_structure_national_daily.csv
Part 3, Stage 1: market-wide structure per day (396 rows). Made in `13_market_structure.ipynb`.

| Column | Meaning |
|---|---|
| Date | Day |
| Total_available_MW | Available MW of every block (all roles) |
| Requirement_MW | Demand + losses in the competitive run (`dispatch_weather_national_daily.csv`) |
| HHI | Herfindahl–Hirschman Index of strategic available capacity, 0–10,000 |
| Lowest_RSI, Lowest_RSI_firm | Smallest single-firm RSI and the firm with it |
| Pivotal_firms, Near_pivotal_firms | Number of firms with RSI < 1 / < 1.1 |
| Joint2_RSI, Joint3_RSI | RSI of the 2 / 3 largest firms that day taken together |
| Tightness, Near_step | National actual tightness and near-step flag from `part3_forecast_package.csv` |

### strategic_sample_results.csv
Part 3, sample study (model log Step 25): the 5 largest firms on 11 days chosen across tightness bands, alone and together (110 rows = 11 days × 5 firms × 2 experiments). Made in `15_market_power_sample.ipynb`. Money columns Rs per peak hour; prices Rs/MWh (demand-weighted average).

| Column | Meaning |
|---|---|
| Date, Band, Near_step, Spare % | Day; its tightness band (or `Peak day`); near a coal-tier step; spare capacity % |
| Experiment | `alone` (this firm bids strategically, everyone else at cost) or `together` (the 5 firms' equilibrium) |
| Firm, Adder | The firm; its best adder alone / its equilibrium adder (bids = cost + adder + 1, at most Rs 8,990) |
| Profit_cost, Profit | Its profit at true cost when everyone bids cost / in this experiment |
| Price_avg_cost, Price_avg | Average price everyone-at-cost / in this experiment |
| Consumer_cost_cost, Consumer_cost | Σ price × demand, at cost / in this experiment |
| Unserved_MW | Unserved demand in this experiment |
| Status, Rounds | Equilibrium only: converged / cycle / round limit; rounds used |

### Strategic-bidding results for all days (Part 3, Stages 4–7) — DEFERRED
**Not produced yet.** The full runs were held (model log Step 25); the files below are what `src/run_part3.py` will write when run. (An interrupted run on 27 Oct left a local copy of `strategic_forecast_daily.csv`; it was not reviewed and is not committed. Regenerate it with `run_part3.py stage6`.)

Made by `src/run_part3.py` (one function per stage) and read by notebooks 15–17. Days: 1 Mar 2024 – 31 Mar 2025 (396). Money columns are Rs per peak hour; prices Rs/MWh. "cost" = everyone bids true cost (the competitive benchmark, equal to `dispatch_weather_*`); strategies are **bid only** (cost + adder, no withholding; model log Step 25). Players = the 24 firms with ≥ 1 GW of strategic capacity.

**strategic_single_daily.csv** — Stage 4: each player alone, everyone else at cost (9,504 rows = 396 days × 24 firms).

| Column | Meaning |
|---|---|
| Date, Firm | Day; the firm bidding strategically |
| Adder | Its best adder (strategic blocks bid cost + adder + 1, capped at Rs 8,990) |
| Profit_cost, Profit_best | The firm's profit (true costs) bidding cost / bidding its best |
| Price_avg_*, Price_max_* | Demand-weighted average / highest state price (`_cost`, `_best`) |
| Consumer_cost_*, Generation_cost_* | Σ price × demand; true cost of the generation dispatched |
| Unserved_MW_*, Profit_total_* | Unserved demand; profit of all generators together |

**strategic_eq_national_daily.csv** — Stage 5: all 24 players together, best-response equilibrium (396 rows). Same `_cost` / `_eq` columns as above, plus `Status` (converged / cycle / round limit), `Rounds` and `Firms_marking_up`.

**strategic_eq_firms_daily.csv** — Stage 5, per firm (9,504 rows): `Date, Firm, Adder, Profit_cost, Profit_eq`.

**strategic_eq_state_daily.csv** — Stage 5, per state (13,068 rows = 396 × 33): `Date, State, Price_cost, Price_eq`.

**strategic_forecast_daily.csv** — Stage 6: UP and Maharashtra (each alone) choose a bid on day-before information, the market clears on the actual day (3,960 rows = 396 days × 2 firms × 5 strategies).

| Column | Meaning |
|---|---|
| Strategy | `perfect` (best bid for the actual day), `forecast` (best bid on Part 2's median forecast), `robust` (best average profit over the 10% / median / 90% demand forecasts), `persistence` (best bid for yesterday's actual day), `cost` (adder 0) |
| Adder | The adder that strategy chose |
| Profit, Price_avg, Consumer_cost, Unserved_MW | Outcome on the **actual** day with that adder |

Forecast scenario for day T: `part3_forecast_package.csv` state demand (`Demand_forecast`, `Demand_Q10`, `Demand_Q90`) + `availability_forecast_test.csv` rows `Model = "best day-ahead"` for solar, wind and hydro (other fuels keep their constant factor, as in Part 2).

**strategic_whatif_daily.csv** — Stage 7: the Stage 5 equilibrium on a 60-day sample (spread evenly over spare capacity) under five what-ifs (300 rows). Same columns as `strategic_eq_national_daily.csv` plus `What_if`: `Base`; `Cap Rs 5,000` (bids at most Rs 4,490); `Contracts 50%` (each firm sold half its at-cost output forward, as a contract for differences at its home state); `Coal -10%` (coal availability × 0.9); `Demand +5%`.
