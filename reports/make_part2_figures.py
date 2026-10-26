"""
Figures for reports/part2_forecasting.md, made from the saved Part 2 results.
Run from the project root:  .venv/bin/python reports/make_part2_figures.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from dispatch import PROCESSED, load_generators  # noqa: E402

OUT = ROOT / "reports" / "figures"
OUT.mkdir(exist_ok=True)
SCORE = slice("2024-03-01", "2025-03-31")
plt.rcParams.update({"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False, "font.size": 9})


def national(p):
    return p.groupby("Date")[["Actual", "Forecast"]].sum()


# 1. Demand ladder (Stage 3: Jan 2024 – Mar 2025; Stage 4 day-ahead: Mar 2024 – Mar 2025)
d3 = pd.read_csv(PROCESSED / "demand_forecast_test.csv", parse_dates=["Date"])
d3 = d3[d3.State != "National"]
order = ["L0 persistence", "L0 last week", "L1 profile", "L2 linear", "L3 linear + weather",
         "L4 LightGBM", "L5 linear per state", "L5 LightGBM per state", "L6 LightGBM median"]
mae = {}
for m in order:
    sub = d3[(d3.Model == m) & (d3.Weather.isin(["none", "perfect"]))]
    g = national(sub)
    mae[m] = (g.Actual - g.Forecast).abs().mean() / 1000
mae = pd.Series(mae)
fig, ax = plt.subplots(figsize=(7, 3.6))
colors = ["#9e9e9e" if m.startswith("L0") else "#3b75af" for m in mae.index]
ax.barh(mae.index, mae.values, color=colors)
ax.axvline(mae["L0 persistence"] * 0.8, color="red", ls="--", lw=1, label="target: 20% better than persistence")
ax.invert_yaxis(); ax.set_xlabel("national MAE (GW), Jan 2024 – Mar 2025, perfect weather")
ax.set_title("Day-ahead demand: each step of the model ladder"); ax.legend(loc="lower right", fontsize=8)
for i, v in enumerate(mae.values):
    ax.text(v + 0.05, i, f"{v:.2f}", va="center", fontsize=8)
fig.tight_layout(); fig.savefig(OUT / "fig1_demand_ladder.png"); plt.close(fig)

# 2. Heatwave: L6 with real day-ahead weather
dd = pd.read_csv(PROCESSED / "demand_forecast_dayahead.csv", parse_dates=["Date"])
l6 = national(dd[(dd.Model == "L6 LightGBM median") & (dd.Weather == "day-ahead")])
pers = national(d3[d3.Model == "L0 persistence"])
w = slice("2024-05-01", "2024-07-15")
fig, ax = plt.subplots(figsize=(8, 3.3))
ax.plot(l6.loc[w].Actual / 1000, color="black", lw=1.6, label="actual")
ax.plot(pers.loc[w].Forecast / 1000, lw=1, alpha=0.7, label="persistence (same as yesterday)")
ax.plot(l6.loc[w].Forecast / 1000, lw=1.3, label="L6 LightGBM, real day-ahead weather")
ax.axvspan(pd.Timestamp("2024-05-17"), pd.Timestamp("2024-06-19"), color="red", alpha=0.07, label="heatwave")
ax.set_ylabel("India peak demand (GW)"); ax.legend(fontsize=8, ncol=2)
ax.set_title("The 2024 heatwave: tomorrow's demand, forecast vs actual")
fig.tight_layout(); fig.savefig(OUT / "fig2_heatwave.png"); plt.close(fig)

# 3. Raw day-ahead availability bias by month
af = pd.read_csv(PROCESSED / "availability_forecast_test.csv", parse_dates=["Date"])
cap = load_generators().groupby(["State", "Fuel_Type"]).Capacity_MW.sum().rename("C")
raw = af[(af.Model == "physics, day-ahead raw") & af.Fuel_Type.isin(["Solar", "Wind"])].join(cap, on=["State", "Fuel_Type"])
raw = raw[raw.Date.between(SCORE.start, SCORE.stop)]
bias = (raw.assign(B=(raw.Forecast - raw.Actual) * raw.C).groupby(["Fuel_Type", "Date"]).B.sum()
        .unstack(0).groupby(lambda d: d.to_period("M")).mean() / 1000)
fig, ax = plt.subplots(figsize=(8, 3.2))
bias.plot.bar(ax=ax, width=0.8, color=["#e8a33d", "#3b75af"])
ax.axhline(0, color="black", lw=0.8); ax.set_ylabel("raw forecast − actual (GW)"); ax.set_xlabel("")
ax.set_title("Raw weather forecasts are biased by season (India available MW)")
ax.set_xticks(range(len(bias))); ax.set_xticklabels([p.strftime("%b %y") for p in bias.index], rotation=0, fontsize=7)
fig.tight_layout(); fig.savefig(OUT / "fig3_forecast_bias.png"); plt.close(fig)

# 4. Price: Route B vs persistence
pf = pd.read_csv(PROCESSED / "price_forecast_test.csv", parse_dates=["Date"])
n = pf[pf.Area == "National"].pivot_table(index="Date", columns=["Route", "Run"], values="Forecast")
actual = pf[(pf.Area == "National") & (pf.Route == "B") & (pf.Run == "realistic")].set_index("Date").Actual
fig, axes = plt.subplots(2, 1, figsize=(8, 5), sharey=True)
for ax, w, t in [(axes[0], slice("2024-05-01", "2024-07-15"), "May – July 2024"),
                 (axes[1], slice("2024-10-15", "2025-01-15"), "October 2024 – January 2025")]:
    ax.plot(actual.loc[w], color="black", lw=1.5, label="actual")
    ax.plot(n[("B", "persistence")].loc[w], lw=1, alpha=0.7, label="persistence")
    ax.plot(n[("B", "realistic")].loc[w], lw=1.2, label="Route B: forecasts through dispatch")
    ax.plot(n[("A", "LightGBM")].loc[w], lw=0.9, alpha=0.8, ls=":", label="Route A: direct model")
    ax.set_title(t, fontsize=9); ax.set_ylabel("Rs/MWh")
axes[0].legend(fontsize=7, ncol=4); fig.suptitle("Tomorrow's national price")
fig.tight_layout(); fig.savefig(OUT / "fig4_price_routes.png"); plt.close(fig)

# 5. Tightness vs price
pkg = pd.read_csv(PROCESSED / "part3_forecast_package.csv", parse_dates=["Date"])
nat = pkg[pkg.Area == "National"].set_index("Date")
bins = pd.qcut(nat.Tightness_forecast, 5, labels=False)          # 0 = tightest fifth
q = pd.DataFrame({"price": nat.Price_actual.groupby(bins, observed=True).mean(),
                  "spare": nat.Tightness_forecast.groupby(bins, observed=True).mean(),
                  "near": nat.Near_step_actual.groupby(bins, observed=True).mean()})
fig, ax = plt.subplots(figsize=(6.5, 3.2))
ax.bar(range(5), q.price, color="#3b75af")
ax.set_xticks(range(5)); ax.set_xticklabels([f"{s:.0%} spare" for s in q.spare])
ax.set_ylabel("actual price (Rs/MWh)"); ax.set_ylim(2000, 4000)
ax2 = ax.twinx(); ax2.plot(range(5), q.near * 100, color="#e8a33d", marker="o"); ax2.set_ylabel("days near a step (%)", color="#e8a33d")
ax2.spines["right"].set_visible(True)
ax.set_title("Tighter days cost more; steps sit in the middle")
fig.tight_layout(); fig.savefig(OUT / "fig5_tightness.png"); plt.close(fig)

# 6. What-ifs
sc = pd.read_csv(PROCESSED / "scenario_results.csv", parse_dates=["Date"])
s = sc[sc.Area == "National"].groupby("Scenario").Price.mean()
chg = (s - s["base"]).drop("base").reindex(["low-wind monsoon", "drought", "demand +5%", "coal shortage", "all four"])
fig, ax = plt.subplots(figsize=(6.5, 3))
ax.barh(chg.index, chg.values, color=["#9ecae1", "#6baed6", "#3182bd", "#e6550d", "#a50f15"])
for i, v in enumerate(chg.values):
    ax.text(v + 30, i, f"+{v:,.0f}", va="center", fontsize=8)
ax.set_xlabel("change in 2024 average price (Rs/MWh)"); ax.set_xlim(0, chg.max() * 1.15)
ax.set_title("What-if shocks: coal matters most, and shocks compound")
fig.tight_layout(); fig.savefig(OUT / "fig6_whatifs.png"); plt.close(fig)

print("saved", sorted(p.name for p in OUT.glob("*.png")))
