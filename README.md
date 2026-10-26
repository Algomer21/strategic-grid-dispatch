# Strategic Grid Dispatch

Simulating electricity market dispatch, forecasting demand/prices with ML, and modeling strategic generator bidding using game theory to quantify market power effects.

## Problem Statement

This project simulates how a real electricity market clears prices using merit-order dispatch, then explores two questions on top of it. The demand data is daily (peak MW and daily energy), so the model produces a **daily peak clearing price for each state**, not hourly prices.

1. Can next-day demand or prices be forecasted using historical patterns and seasonal features?
2. What happens to prices and dispatch outcomes when large generators bid strategically instead of at true marginal cost — where does market power show up, and how much does it cost consumers?

Question 2 is Part 3 of the project; its plan (firms, the bidding game, how Parts 1 and 2 feed it) is in [`docs/part3_plan.md`](docs/part3_plan.md).

## Tech Stack

- **Language:** Python
- **Data handling:** pandas, numpy
- **Forecasting:** scikit-learn (ridge regression), LightGBM
- **Optimisation/bidding:** scipy
- **Weather data:** Open-Meteo historical archive (requests)
- **Visualization:** matplotlib

## Project Structure

```
data/
  raw/          original inputs, never edited by hand
  processed/    outputs of the cleaning notebook (rebuildable)
notebooks/      numbered by project stage: explore and test here
src/            finished, tested functions imported by notebooks
reports/        write-ups and result charts
archive/        old versions kept for reference
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m ipykernel install --user --name grid-dispatch --display-name "Python (grid-dispatch)"
```

Open the notebooks and pick the **Python (grid-dispatch)** kernel. Run them in number order.

Run the checks for everything in `src/`:

```bash
.venv/bin/python -m pytest
```

## Notebooks

| Notebook | What it does |
|---|---|
| `01_data_cleaning` | Cleans the raw daily state demand data |
| `02_merit_order` | Builds the dispatch models step by step: toy merit order → real stack → LP → copper-plate trading → distance-based losses |
| `03_dispatch_all_days` | Runs the loss model with coal tiers for all 1,917 days and saves the results to `data/processed/` |
| `04_seasonal_availability` | Re-runs it with monthly solar, wind and hydro availability and compares with notebook 03 |
| `05_forecast_setup` | Part 2 set-up: time split, error metrics, naive baselines (persistence, last week) for national and state demand |
| `06_weather_data` | Downloads daily weather for 151 points (demand cities, solar parks, wind zones, dams) from Open-Meteo, checks it, and combines it into one row per state and purpose |
| `07_weather_availability` | Turns weather into daily solar, wind and hydro availability per state and re-runs dispatch: the "actual" prices for Part 2 |
| `08_demand_forecast` | Day-ahead demand forecasts for every state: model ladder from persistence to LightGBM, tested month by month over 2024 – Mar 2025 |
| `09_availability_forecast` | Forecasts tomorrow's solar, wind and hydro availability from real day-ahead weather forecasts (anchored to cancel their seasonal bias) and a statistical ladder; re-runs demand with real forecasts |
| `10_price_forecast` | Forecasts tomorrow's prices through the dispatch model (Route B) and directly (Route A); splits the error into demand and supply causes; price ranges and a tightness index for Part 3 |
| `11_scenarios` | What-if shocks through dispatch (demand +5%, drought, low-wind monsoon, coal shortage, all four) and price-forecast errors near coal-tier steps |
| `12_part3_package` | Assembles the forecast package for Part 3 (demand, supply, price, ranges, tightness, step flag) and shows the IEX bid-area price hook |

Every modelling step (what, why, assumptions, checks, result) is recorded in [`docs/model_log.md`](docs/model_log.md); every data file is described in [`data/README.md`](data/README.md).

## Dispatch model (Part 1)

State-level linear program, solved with `scipy.optimize.linprog` (HiGHS):

- **Supply:** 161 state × fuel generator rows; available capacity = nameplate × availability factor (constant; monthly for solar, wind and hydro in the seasonal run; daily from each state's weather in the weather run, which Part 2 uses as the actual prices)
- **Costs:** coal cost by state tier (pithead 1,600 · near mines 2,200 · inland 2,800 · coastal/imported 3,800 Rs/MWh), other fuels at fixed costs
- **Trading:** any state can trade with any other; no line limits
- **Losses:** min(0.5% + 4% per 1,000 km × 1.2 routing factor, 10%), distance between state capitals
- **Prices:** the shadow price of each state's supply = demand constraint (locational price)

Main limitations: daily peak only; renewable availability from assumed shapes (seasonal run) or physical rules not fitted to measured generation (weather run), with no time of day and coal constant all year; coal costs by state tier rather than by plant; no transmission limits; DVC excluded (no generator data).

## Forecasting (Part 2)

Day-ahead forecasts: on day D, forecast D+1 for every state. Full write-up: [`reports/part2_forecasting.md`](reports/part2_forecasting.md).

- **Weather:** 151 points chosen by purpose (population-weighted cities, solar parks, wind zones, dams), Open-Meteo archive; real day-ahead forecasts from Open-Meteo's previous-runs archive, **anchored** (today's actual + forecast change) to cancel their seasonal bias
- **Availability truth:** solar from radiation with panel heat loss, wind from a power curve on hourly 100 m wind, hydro from rain (+ snowmelt) "leaky buckets"; each state scaled to its Part 1 factor. Dispatch with it gives the "actual" prices
- **Models:** predict the change from today; ladder persistence → profile → ridge → LightGBM (mean, median, quantiles); monthly walk-forward; trained on actual weather, fed forecasts in the test
- **Prices:** Route B = forecast demand and supply through the dispatch model; Route A = direct price model (fails)
- **Results (Mar 2024 – Mar 2025, vs "same as today"):** demand skill 0.48, solar 0.33, wind 0.49, national price 0.53
- **Hand-off:** `data/processed/part3_forecast_package.csv`; IEX bid-area hook in `src/prices.py`

Main limitations: the "actual" price is the model's own (not IEX); availability truth is modelled, not measured; 13 scored months with real forecasts; daily peak only.

## Workflow

For each new feature: write the expected result → solve a tiny case by hand → code it in a notebook → test hand answers and edge cases → sanity-check against real-world numbers → move the working function to `src/` → commit → add a line to the progress log.

## Status

🚧 Ongoing. Part 1 (dispatch) and Part 2 (forecasting) complete; Part 3 (strategic bidding) next.

## Progress Log

- **Day 1:** Repo setup, folder structure, problem statement defined.
- **Day 2:** Cleaned 5 years of daily demand data (Jan 2020 – Mar 2025): dropped Essar Steel and Jharkhand, merged DD + DNH, filled nulls within each state. 33 states, ~63k rows, 0 nulls. Built a generator stack (161 state × fuel rows).
- **Day 3:** First dispatch attempt (now in `archive/`): coal set the price on 99.6% of days because coal has one flat cost. Lesson: audit what the data can produce before building the model. Restarted step by step.
- **Day 4:** Toy merit order dispatch on 3 plants, checked against hand calculations. Fixed a marginal-plant cost bug by tracing the code with real numbers. Added VOLL scarcity pricing and boundary-case tests. Reorganised the repo into data/notebooks/src with a virtual environment.
- **Day 5:** Real generator stack with availability factors (nameplate solar made the price 0). National dispatch over 1,917 days; state surplus/deficit and regional analysis showed the North importing ~17 GW from the West at peak.
- **Day 6:** Rewrote dispatch as a linear program and validated it against merit order (0 disagreements over 1,917 days). Built a copper-plate trading model (one price everywhere) and a distance-based loss model that gives locational prices; realised losses of 3.4% match India's ~3–4%.
- **Day 7:** Added coal cost tiers by state, moved the models into `src/dispatch.py` with pytest checks, and ran the loss model for all 1,917 days (8.8 s). Average price now ranges Rs 1,650–3,770 instead of sitting at Rs 2,000. Part 1 complete.
- **Day 8:** Fixed 1,027 column-shifted DNH rows and 7 corrupted HP rows in cleaning: DD & DNH demand had been frozen and its demand counted as shortage (real national peak shortage 412 MW, not ~1 GW). Added seasonal availability: monsoon prices fall 120–170 Rs/MWh and winter prices rise 110–245, with summer roughly unchanged. Started `docs/model_log.md` and `data/README.md` as running references.
- **Day 9:** Planned Part 2 (day-ahead forecasting of state demand and weather-based availability, priced through the dispatch model, linked to Part 3's bidders). Set up the time split, metrics and naive baselines: "same as yesterday" is already 2.2% off nationally (4.8 GW), and 2.4–10% for states. Models must beat it by 20%.
- **Day 10:** Chose 151 weather points by purpose (population-weighted cities for demand; solar parks, wind zones and dams for supply) and downloaded 5 years of daily weather from Open-Meteo. Wind's assumed seasonal shape matches the weather well; solar's overstates winter and understates the monsoon; rain peaks a month before hydro output, so reservoirs need a running total. Delhi's demand is U-shaped in temperature. Combined the points into states (population-weighted for demand).
- **Day 11:** Turned weather into daily availability (solar with panel heat loss, wind through a power curve on hourly wind, hydro as leaky buckets with Himalayan snowmelt), each state matched to its Part 1 average. The new dispatch run is Part 2's "actual" price: pre-monsoon is dearer and Aug–Oct cheaper than the seasonal run, and day-to-day price swings are ~40% larger. Price persistence is 4.5% off, twice demand's error.
- **Day 12:** Found and fixed 21 one-day typos in the demand data (Telangana 236 MW among ~12,400 MW days), keeping 4 real cyclone days. Built day-ahead demand forecasts for all 32 states with hand-checked holiday and paddy-season tables and a leakage-tested feature set. Tested month by month over 2024 – Mar 2025, the best model (LightGBM, median) is 1.1% off nationally, half the error of "same as yesterday", and cuts the heatwave error from 4.8 to 2.2 GW. Holidays remain the weak spot.
- **Day 13:** Downloaded real day-ahead weather forecasts for all 139 locations. Raw forecasts made solar *worse* than "same as today": the forecast model is too sunny in the hazy dry season and too cloudy in the monsoon. Anchoring (today's actual + forecast change) cancels that bias: tomorrow's wind availability error halves (skill 0.49), solar improves by a third (0.33), and demand with real forecasts reaches skill 0.48. Without a weather forecast, renewable output is barely more predictable than "same as today".
- **Day 14:** Forecast tomorrow's prices. Pushing the demand and availability forecasts through the dispatch model halves the price error of "same as today" (skill 0.53) and flags two in three price jumps; a direct price model can't beat persistence, because price history doesn't know where the coal-tier steps are. Demand forecast error costs more than supply error. Prices climb from Rs 2,650 to 3,710/MWh as spare capacity shrinks.
- **Day 15:** Stress-tested the market. One year of demand growth (+5%) raises prices 7.5%; a coal shortage is the biggest single shock (+23%, shortages on 17 days); all four shocks together double the price, because pressures compound near the top of the supply curve. A fifth of days sit near a coal-tier step, where price-forecast errors are 3.6× larger.
- **Day 16:** Packaged everything Part 2 knows about tomorrow for Part 3 (demand, supply, price, ranges, tightness, a near-step flag), built the hook for comparing with real IEX prices by bid area, wrote the Part 2 report and re-ran notebooks 05–12 end to end. Part 2 complete.
- **Day 17:** Planned Part 3 (strategic bidding, [`docs/part3_plan.md`](docs/part3_plan.md)): one firm per state bidding cost + an adder and able to withhold coal, lignite, gas and hydro, with solar and wind must-run; a one-day bidding game solved by trying every bid through the dispatch model, then best responses between firms. A first check on Part 2's weather-based run: some firm is pivotal (the market can't be served without it) on 53 of 396 days in Mar 2024 – Mar 2025, and nine firms are pivotal at least once.
