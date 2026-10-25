"""
Daily weather for Part 2: download from the Open-Meteo historical archive.

Developed in notebooks/06_weather_data.ipynb. Points (where to measure, and why)
are in data/raw/weather_points.csv. Each location is downloaded once and kept in
data/cache/weather/, so re-running never downloads again.

Weather data by Open-Meteo.com, licence CC BY 4.0.
"""

import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
CACHE = ROOT / "data" / "cache" / "weather"

# ---------------------------------------------------------------------------
# Assumptions
# ---------------------------------------------------------------------------

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "Asia/Kolkata"   # a "day" is an Indian day, matching the demand data

# one extra month before the demand data (1 Jan 2020) so lags and rainfall totals start on day 1
START = "2019-12-01"
END = "2025-03-31"

DAILY_VARIABLES = [
    "temperature_2m_max",       # °C
    "temperature_2m_mean",      # °C
    "temperature_2m_min",       # °C
    "precipitation_sum",        # mm
    "shortwave_radiation_sum",  # MJ/m²
    "cloud_cover_mean",         # %
    "wind_speed_100m_mean",     # km/h, roughly wind-turbine hub height
]

# physically possible ranges, used to catch broken downloads
VALID_RANGE = {
    "temperature_2m_max": (-40, 55), "temperature_2m_mean": (-45, 50), "temperature_2m_min": (-50, 45),
    "precipitation_sum": (0, 1000), "shortwave_radiation_sum": (0, 40),
    "cloud_cover_mean": (0, 100), "wind_speed_100m_mean": (0, 150),
}

PAUSE_S = 1.0          # pause between downloads: the API is free, don't hammer it
RETRY_WAIT_S = 65      # wait after "too many requests" (HTTP 429), then try again
MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# One location
# ---------------------------------------------------------------------------

def parse_daily(payload, start, end, variables=DAILY_VARIABLES):
    """
    Turn an Open-Meteo JSON answer into a DataFrame: Date + one column per variable.

    Raises if any day is missing, duplicated or empty, so a broken download never
    gets saved silently.
    """
    if "daily" not in payload:
        raise ValueError(f"No daily data in answer: {payload.get('reason', payload)}")

    df = pd.DataFrame(payload["daily"])
    df["Date"] = pd.to_datetime(df.pop("time"))

    expected = pd.date_range(start, end, freq="D")
    if len(df) != len(expected) or not (df["Date"].to_numpy() == expected.to_numpy()).all():
        raise ValueError(f"Expected {len(expected)} days {start}..{end}, got {len(df)}")

    missing = [v for v in variables if v not in df.columns]
    if missing:
        raise ValueError(f"Variables missing from answer: {missing}")
    if df[variables].isna().any().any():
        raise ValueError(f"Empty values: {df[variables].isna().sum()[lambda s: s > 0].to_dict()}")

    return df[["Date"] + list(variables)]


def fetch_point(lat, lon, start=START, end=END, variables=DAILY_VARIABLES):
    """
    Download daily weather for one location.

    Temporary problems are retried: 'too many requests' (429), server errors (5xx),
    dropped connections and empty/garbled answers. Anything else (e.g. a bad
    request, 400) stops loudly.
    """
    params = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
              "daily": ",".join(variables), "timezone": TIMEZONE}
    problem = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(ARCHIVE_URL, params=params, timeout=60)
            if response.status_code == 429 or response.status_code >= 500:
                # e.g. "Hourly API request limit exceeded": a 5-year download counts as
                # many requests, so the free tier allows ~100 locations per hour
                problem = f"HTTP {response.status_code} {response.text[:120]}"
            else:
                response.raise_for_status()
                return parse_daily(response.json(), start, end, variables)
        except (requests.ConnectionError, requests.Timeout, requests.JSONDecodeError) as e:
            problem = type(e).__name__
        print(f"  {lat}, {lon}: {problem}, waiting {RETRY_WAIT_S} s (try {attempt + 1}/{MAX_RETRIES})")
        time.sleep(RETRY_WAIT_S)
    raise RuntimeError(f"Download failed {MAX_RETRIES} times ({lat}, {lon}): {problem}")


# ---------------------------------------------------------------------------
# All points
# ---------------------------------------------------------------------------

def load_points():
    """Weather points: one row per point (state, purpose, location)."""
    return pd.read_csv(RAW / "weather_points.csv")


def cache_file(lat, lon, cache_dir=CACHE):
    return Path(cache_dir) / f"{lat:.3f}_{lon:.3f}.csv"


def fetch_all(points, cache_dir=CACHE, fetch=fetch_point, verbose=True):
    """
    Weather for every point, as one long table: Point_ID, Date, variables.

    Each unique location is downloaded once (several points can share a place,
    e.g. a capital used for demand and solar) and cached; cached locations are
    read from disk. `fetch` is replaceable so tests can run without internet.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    locations = points[["Lat", "Lon"]].drop_duplicates()
    weather = {}
    for i, (lat, lon) in enumerate(locations.itertuples(index=False), 1):
        path = cache_file(lat, lon, cache_dir)
        if path.exists():
            weather[(lat, lon)] = pd.read_csv(path, parse_dates=["Date"])
            continue
        if verbose:
            print(f"[{i}/{len(locations)}] downloading {lat}, {lon}")
        df = fetch(lat, lon)
        df.to_csv(path, index=False)
        weather[(lat, lon)] = df
        time.sleep(PAUSE_S if fetch is fetch_point else 0)

    out = [weather[(p.Lat, p.Lon)].assign(Point_ID=p.Point_ID) for p in points.itertuples()]
    out = pd.concat(out, ignore_index=True)
    return out[["Point_ID", "Date"] + [c for c in out.columns if c not in ("Point_ID", "Date")]]


# ---------------------------------------------------------------------------
# Points -> states
# ---------------------------------------------------------------------------

def load_population():
    """Census 2011 population of the demand cities in multi-city states."""
    return pd.read_csv(RAW / "city_population.csv")


def point_weights(points, population):
    """
    Weight of each point within its (State, Purpose) group; weights sum to 1 per group.

    Demand points are weighted by city population (more people, more load); a state
    with one demand point gets weight 1. Supply points get equal weights: there is
    no plant-level capacity data to weight them by.
    """
    w = points[["Point_ID", "State", "Purpose"]].merge(
        population[["Point_ID", "Population_2011"]], on="Point_ID", how="left")
    group_size = w.groupby(["State", "Purpose"])["Point_ID"].transform("size")

    is_demand = w["Purpose"] == "demand"
    needs_pop = is_demand & (group_size > 1)
    if w.loc[needs_pop, "Population_2011"].isna().any():
        missing = w.loc[needs_pop & w["Population_2011"].isna(), "Point_ID"].tolist()
        raise ValueError(f"No population for demand points: {missing}")

    w["Raw"] = 1.0
    w.loc[needs_pop, "Raw"] = w.loc[needs_pop, "Population_2011"]
    w["Weight"] = w["Raw"] / w.groupby(["State", "Purpose"])["Raw"].transform("sum")
    return w[["Point_ID", "State", "Purpose", "Weight"]]


def combine_points(weather, points, population, variables=DAILY_VARIABLES):
    """
    One weather row per Date, State and Purpose: the weighted average of its points.

    Averages are taken per day, so a heatwave in one city still shows up (diluted
    by its weight) in that day's state value.
    """
    weights = point_weights(points, population)
    df = weather.merge(weights, on="Point_ID", how="inner")
    if len(df) != len(weather):
        raise ValueError("Some weather rows have no point in the weights table")
    df[variables] = df[variables].mul(df["Weight"], axis=0)
    out = df.groupby(["Date", "State", "Purpose"], as_index=False)[variables].sum()
    return out.sort_values(["State", "Purpose", "Date"], ignore_index=True)


def check_weather(weather, points, start=START, end=END):
    """Raise if any point or day is missing, or any value is outside its physical range."""
    n_days = len(pd.date_range(start, end, freq="D"))
    counts = weather.groupby("Point_ID")["Date"].nunique()
    if set(counts.index) != set(points["Point_ID"]):
        raise ValueError("Points missing from weather table")
    if (counts != n_days).any() or len(weather) != n_days * len(points):
        raise ValueError("Days missing or duplicated")
    if weather.isna().any().any():
        raise ValueError("NaN in weather table")
    for var, (lo, hi) in VALID_RANGE.items():
        bad = ~weather[var].between(lo, hi)
        if bad.any():
            raise ValueError(f"{var}: {bad.sum()} values outside {lo}..{hi}")
    return True
