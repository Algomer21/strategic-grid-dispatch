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

## processed/

| File | Made by | One row per | Contents |
|---|---|---|---|
| india_electricity_data_updated.csv | 01_data_cleaning | Day × state (33) | Cleaned demand data: fixes applied, Essar steel and Jharkhand dropped, DD + DNH merged, gaps filled within each state |
| dispatch_state_daily.csv | 03_dispatch_all_days | Day × state (32) | Constant-availability run: demand, generation, unserved, imports, exports, price |
| dispatch_flows_daily.csv | 03_dispatch_all_days | Day × trade | From, to, MW sent, loss %, MW received |
| dispatch_national_daily.csv | 03_dispatch_all_days | Day | Totals, losses, min/avg/max price, generation by fuel |
| seasonal_state_daily.csv | 04_seasonal_availability | Day × state (32) | As dispatch_state_daily, with seasonal availability |
| seasonal_flows_daily.csv | 04_seasonal_availability | Day × trade | As dispatch_flows_daily, with seasonal availability |
| seasonal_national_daily.csv | 04_seasonal_availability | Day | As dispatch_national_daily, with seasonal availability |
