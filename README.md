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
- **Forecasting:** scikit-learn, statsmodels (ARIMA), XGBoost/LightGBM
- **Optimisation/bidding:** scipy
- **Visualization:** matplotlib, plotly

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

Run the checks for `src/dispatch.py`:

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

Every modelling step (what, why, assumptions, checks, result) is recorded in [`docs/model_log.md`](docs/model_log.md); every data file is described in [`data/README.md`](data/README.md).

## Dispatch model (Part 1)

State-level linear program, solved with `scipy.optimize.linprog` (HiGHS):

- **Supply:** 161 state × fuel generator rows; available capacity = nameplate × availability factor (constant, or monthly for solar, wind and hydro in the seasonal run)
- **Costs:** coal cost by state tier (pithead 1,600 · near mines 2,200 · inland 2,800 · coastal/imported 3,800 Rs/MWh), other fuels at fixed costs
- **Trading:** any state can trade with any other; no line limits
- **Losses:** min(0.5% + 4% per 1,000 km × 1.2 routing factor, 10%), distance between state capitals
- **Prices:** the shadow price of each state's supply = demand constraint (locational price)

Main limitations: daily peak only; seasonal factors are assumed shapes, monthly (no time of day), with coal constant all year; coal costs by state tier rather than by plant; no transmission limits; DVC excluded (no generator data).

## Workflow

For each new feature: write the expected result → solve a tiny case by hand → code it in a notebook → test hand answers and edge cases → sanity-check against real-world numbers → move the working function to `src/` → commit → add a line to the progress log.

## Status

🚧 Ongoing. Part 1 (dispatch) complete; Part 2 (forecasting) and Part 3 (strategic bidding) next.

## Progress Log

- **Day 1:** Repo setup, folder structure, problem statement defined.
- **Day 2:** Cleaned 5 years of daily demand data (Jan 2020 – Mar 2025): dropped Essar Steel and Jharkhand, merged DD + DNH, filled nulls within each state. 33 states, ~63k rows, 0 nulls. Built a generator stack (161 state × fuel rows).
- **Day 3:** First dispatch attempt (now in `archive/`): coal set the price on 99.6% of days because coal has one flat cost. Lesson: audit what the data can produce before building the model. Restarted step by step.
- **Day 4:** Toy merit order dispatch on 3 plants, checked against hand calculations. Fixed a marginal-plant cost bug by tracing the code with real numbers. Added VOLL scarcity pricing and boundary-case tests. Reorganised the repo into data/notebooks/src with a virtual environment.
- **Day 5:** Real generator stack with availability factors (nameplate solar made the price 0). National dispatch over 1,917 days; state surplus/deficit and regional analysis showed the North importing ~17 GW from the West at peak.
- **Day 6:** Rewrote dispatch as a linear program and validated it against merit order (0 disagreements over 1,917 days). Built a copper-plate trading model (one price everywhere) and a distance-based loss model that gives locational prices; realised losses of 3.4% match India's ~3–4%.
- **Day 7:** Added coal cost tiers by state, moved the models into `src/dispatch.py` with pytest checks, and ran the loss model for all 1,917 days (8.8 s). Average price now ranges Rs 1,650–3,770 instead of sitting at Rs 2,000. Part 1 complete.
- **Day 8:** Fixed 1,027 column-shifted DNH rows and 7 corrupted HP rows in cleaning: DD & DNH demand had been frozen and its demand counted as shortage (real national peak shortage 412 MW, not ~1 GW). Added seasonal availability: monsoon prices fall 120–170 Rs/MWh and winter prices rise 110–245, with summer roughly unchanged. Started `docs/model_log.md` and `data/README.md` as running references.
