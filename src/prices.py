"""
Prices in one common format, so real exchange prices can replace model prices (Part 2, Stage 7).

Format: Date, Area, Price (Rs/MWh), Source. `Area` is a state, a bid area, or "National".
The model's prices are a daily *peak* price (the demand data is the daily peak), so IEX
prices should be aggregated to match before loading: e.g. the average of the evening-peak
block (18:00-22:00) of the Day-Ahead Market for each bid area. See data/README.md.
"""

import numpy as np
import pandas as pd

from dispatch import PROCESSED, RAW

IEX_FILE = RAW / "iex_dam_daily.csv"   # not in the repo: download from iexindia.com (data/README.md)


def load_bid_areas():
    """State → IEX bid area (data/raw/iex_bid_areas.csv; four entries flagged uncertain in the Note column)."""
    return pd.read_csv(RAW / "iex_bid_areas.csv")


def load_prices(source="model", path=None):
    """
    Daily prices in the common format.

    source="model": the Part 2 actual-price run (dispatch_weather_*), states and National.
    source="iex":   a daily file with columns Date, Bid_area, Price (Rs/MWh), already aggregated
                    to one value per day and bid area.
    """
    if source == "model":
        st = pd.read_csv(PROCESSED / "dispatch_weather_state_daily.csv", parse_dates=["Date"])
        nat = pd.read_csv(PROCESSED / "dispatch_weather_national_daily.csv", parse_dates=["Date"])
        out = pd.concat([st[["Date", "State", "Price"]].rename(columns={"State": "Area"}),
                         nat[["Date", "Price_avg"]].rename(columns={"Price_avg": "Price"}).assign(Area="National")])
    elif source == "iex":
        path = IEX_FILE if path is None else path
        raw = pd.read_csv(path, parse_dates=["Date"])
        missing = {"Date", "Bid_area", "Price"} - set(raw.columns)
        if missing:
            raise ValueError(f"IEX file needs columns Date, Bid_area, Price; missing {sorted(missing)}")
        if raw.duplicated(["Date", "Bid_area"]).any():
            raise ValueError("IEX file must have one row per date and bid area (aggregate first)")
        out = raw.rename(columns={"Bid_area": "Area"})[["Date", "Area", "Price"]]
    else:
        raise ValueError("source must be 'model' or 'iex'")
    return out.assign(Source=source).sort_values(["Date", "Area"], ignore_index=True)[["Date", "Area", "Price", "Source"]]


def to_bid_areas(state_prices, demand, bid_areas=None):
    """
    State prices → bid-area prices, weighted by each state's demand that day.
    state_prices: common format with states as Area; demand: date × state table (MW).
    """
    bid_areas = load_bid_areas() if bid_areas is None else bid_areas
    area_of = bid_areas.set_index("State")["Bid_area"]
    p = state_prices[state_prices.Area.isin(area_of.index)].copy()
    p["Weight"] = [demand.at[d, s] for d, s in zip(p.Date, p.Area)]
    p["Bid_area"] = p.Area.map(area_of)
    g = p.assign(PW=p.Price * p.Weight).groupby(["Date", "Bid_area"])
    out = (g.PW.sum() / g.Weight.sum()).rename("Price").reset_index().rename(columns={"Bid_area": "Area"})
    return out.assign(Source=state_prices.Source.iloc[0])[["Date", "Area", "Price", "Source"]]


def compare_prices(model, market, jump=200):
    """
    Model vs market prices per area over their common dates: MAE, bias, correlation, and how
    often both move ≥ `jump` Rs/MWh in the same direction from the day before.
    """
    m = model.merge(market, on=["Date", "Area"], suffixes=("_model", "_market"))
    if m.empty:
        raise ValueError("No common dates and areas")
    rows = {}
    for area, g in m.sort_values("Date").groupby("Area"):
        dm, dk = g.Price_model.diff(), g.Price_market.diff()
        big = dk.abs() >= jump
        rows[area] = {"days": len(g), "MAE": (g.Price_model - g.Price_market).abs().mean(),
                      "bias (model − market)": (g.Price_model - g.Price_market).mean(),
                      "correlation": g.Price_model.corr(g.Price_market),
                      "market jumps": int(big.sum()),
                      "jumps matched": int((big & (dm.abs() >= jump) & (np.sign(dm) == np.sign(dk))).sum())}
    return pd.DataFrame(rows).T
