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
