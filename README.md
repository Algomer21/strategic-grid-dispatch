# Strategic Grid Dispatch

Simulating electricity market dispatch, forecasting demand/prices with ML, and modeling strategic generator bidding using game theory to quantify market power effects.

## Problem Statement

This project simulates how a real electricity market clears prices hour by hour using merit-order dispatch, then explores two questions on top of it:

1. Can next-day demand or prices be forecasted using historical patterns and seasonal features?
2. What happens to prices and dispatch outcomes when large generators bid strategically instead of at true marginal cost — where does market power show up, and how much does it cost consumers?

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

## Workflow

For each new feature: write the expected result → solve a tiny case by hand → code it in a notebook → test hand answers and edge cases → sanity-check against real-world numbers → move the working function to `src/` → commit → add a line to the progress log.

## Status

🚧 Ongoing — Day 1 of a 30-day build. Progress log below.

## Progress Log

- **Day 1:** Repo setup, folder structure, problem statement defined.
- **Day 2:** Cleaned 5 years of daily demand data (Jan 2020 – Mar 2025): dropped Essar Steel and Jharkhand, merged DD + DNH, filled nulls within each state. 33 states, ~63k rows, 0 nulls. Built a generator stack (161 state × fuel rows).
- **Day 3:** First dispatch attempt (now in `archive/`): coal set the price on 99.6% of days because coal has one flat cost. Lesson: audit what the data can produce before building the model. Restarted step by step.
- **Day 4:** Toy merit order dispatch on 3 plants, checked against hand calculations. Fixed a marginal-plant cost bug by tracing the code with real numbers. Added VOLL scarcity pricing and boundary-case tests. Reorganised the repo into data/notebooks/src with a virtual environment.
