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

- `data/` — raw and processed datasets
- `notebooks/` — exploratory analysis in Jupyter
- `src/` — core Python modules (dispatch, forecasting, bidding)
- `reports/` — write-ups and result charts

## Status

🚧 Ongoing — Day 1 of a 30-day build. Progress log below.

## Progress Log

- **Day 1:** Repo setup, folder structure, problem statement defined.
