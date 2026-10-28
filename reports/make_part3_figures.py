"""
Figures for reports/part3_strategic_bidding.md, made from the saved Part 3 results.
Figure 2 re-runs four best-response searches (Stage 3, ~6 s); the rest only read CSVs.
Run from the project root:  .venv/bin/python reports/make_part3_figures.py
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
from bidding import best_response, firm_blocks  # noqa: E402
from dispatch import (PROCESSED, LossDispatchModel, daily_availability_lookup,  # noqa: E402
                      load_coordinates, load_demand, load_generators, loss_matrix)

OUT = ROOT / "reports" / "figures"
OUT.mkdir(exist_ok=True)
plt.rcParams.update({"figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False, "font.size": 9})

national = pd.read_csv(PROCESSED / "market_structure_national_daily.csv", parse_dates=["Date"]).set_index("Date")
structure = pd.read_csv(PROCESSED / "market_structure_daily.csv", parse_dates=["Date"])
sample = pd.read_csv(PROCESSED / "strategic_sample_results.csv", parse_dates=["Date"])
forecast = pd.read_csv(PROCESSED / "strategic_forecast_daily.csv", parse_dates=["Date"])


# 1. Concentration vs pivotal firms (Stage 1)
fig, ax = plt.subplots(1, 2, figsize=(10, 3.4), gridspec_kw={"width_ratios": [1.6, 1]})
ax[0].plot(national.index, national["Lowest_RSI"], color="tab:blue", label="Lowest single-firm RSI")
ax[0].axhline(1.0, color="tab:red", linestyle="--", linewidth=1, label="RSI = 1: a firm is pivotal")
ax[0].fill_between(national.index, 0.9, 1.0, where=national["Lowest_RSI"] < 1, color="tab:red", alpha=0.15)
ax[0].set_ylim(0.9, 1.42)
ax[0].set_ylabel("RSI")
ax[0].set_title(f"HHI {national['HHI'].mean():,.0f} ('unconcentrated'), yet {int((national['Pivotal_firms'] > 0).sum())} pivotal days")
ax[0].legend(loc="upper left", fontsize=8)
per_firm = structure[structure["Pivotal"]].groupby("Firm").size().sort_values()
ax[1].barh(per_firm.index, per_firm.values, color="tab:red")
ax[1].set_xlabel("Days pivotal (of 396)")
ax[1].set_title("Pivotal firms")
plt.tight_layout()
fig.savefig(OUT / "p3_fig1_pivotal.png", bbox_inches="tight")
plt.close(fig)


# 2. One firm, four days: UP's profit against its bid (Stage 3)
gen = load_generators()
blocks = firm_blocks(gen)
demand = load_demand()
states = list(demand.columns)
model = LossDispatchModel(gen, loss_matrix(load_coordinates(), states), states)
DAYS = {"Pivotal, 5% spare": "2025-01-30", "Near-step, 12%": "2025-02-06",
        "Ordinary, 23%": "2024-03-17", "Slack, 53%": "2024-08-25"}
daily = pd.read_csv(PROCESSED / "availability_daily.csv", parse_dates=["Date"])
lookup = daily_availability_lookup(daily[daily["Date"].isin(pd.to_datetime(list(DAYS.values())))])

fig, axes = plt.subplots(1, 4, figsize=(12, 2.9))
for ax, (label, d) in zip(axes, DAYS.items()):
    d = pd.Timestamp(d)
    br = best_response(model, blocks, "NR UP", demand.loc[d], lookup[d])
    t = br["table"][np.isclose(br["table"]["Withholding"], 0)].sort_values("Adder")
    ax.plot(t["Adder"], t["Profit"] / 1e5, color="tab:blue", linewidth=1.2)
    ax.axhline(br["profit_at_cost"] / 1e5, color="tab:gray", linestyle=":", linewidth=1)
    ax.scatter([br["adder"]], [br["profit"] / 1e5], color="black", zorder=5, s=20)
    gain = br["profit"] / br["profit_at_cost"]
    ax.set_title(f"{label}\nbest +{br['adder']:,}: profit ×{gain:.1f}", fontsize=8.5)
    ax.set_xlabel("Adder (Rs/MWh)")
axes[0].set_ylabel("UP profit (Rs lakh / peak hour)")
plt.tight_layout()
fig.savefig(OUT / "p3_fig2_one_firm.png", bbox_inches="tight")
plt.close(fig)


# 3. Alone vs together across the sample (sample study)
alone = sample[sample["Experiment"] == "alone"]
together = sample[sample["Experiment"] == "together"].drop_duplicates("Date").set_index("Date")
worst = (100 * (alone["Consumer_cost"] / alone["Consumer_cost_cost"] - 1)).groupby(alone["Date"]).max()
eq = 100 * (together["Consumer_cost"] / together["Consumer_cost_cost"] - 1)
order = together.sort_values("Spare %").index
labels = [f"{d:%d %b %y}\n{together.loc[d, 'Spare %']:.0f}%{' step' if together.loc[d, 'Near_step'] else ''}" for d in order]
x = np.arange(len(order))
fig, ax = plt.subplots(figsize=(10, 3.2))
ax.bar(x - 0.2, worst[order], 0.4, color="tab:orange", label="Worst single firm alone")
ax.bar(x + 0.2, eq[order], 0.4, color="tab:red", label="5 largest firms together (equilibrium)")
ax.set_xticks(x, labels, fontsize=7.5)
ax.set_ylabel("Consumer cost increase (%)")
ax.set_title("Market power on 11 sample days, tightest first")
ax.legend(fontsize=8)
plt.tight_layout()
fig.savefig(OUT / "p3_fig3_alone_together.png", bbox_inches="tight")
plt.close(fig)


# 4. Price umbrella: profits at cost, alone and together (sample study)
firms = ["NR UP", "WR Maharashtra", "Chhattisgarh", "MP", "Gujarat"]
tog = sample[sample["Experiment"] == "together"].groupby("Firm")[["Profit_cost", "Profit"]].sum().reindex(firms) / 1e7
alo = alone.groupby("Firm")["Profit"].sum().reindex(firms) / 1e7
x = np.arange(len(firms))
fig, ax = plt.subplots(figsize=(7, 3.2))
ax.bar(x - 0.27, tog["Profit_cost"], 0.27, color="tab:gray", label="Everyone bids cost")
ax.bar(x, alo, 0.27, color="tab:orange", label="Firm marks up alone")
ax.bar(x + 0.27, tog["Profit"], 0.27, color="tab:red", label="All 5 strategic (equilibrium)")
ax.set_xticks(x, ["UP", "Maharashtra", "Chhattisgarh", "MP", "Gujarat"])
ax.set_ylabel("Profit over 11 days (Rs crore / peak hour, summed)")
ax.set_title("Every firm earns more when another firm leads")
ax.legend(fontsize=8)
plt.tight_layout()
fig.savefig(OUT / "p3_fig4_umbrella.png", bbox_inches="tight")
plt.close(fig)

# 5. Bidding on forecasts (Stage 6): strategies, and market power by forecast spare capacity
from forecast import load_forecast_package  # noqa: E402
w = forecast.pivot_table(index=["Date", "Firm"], columns="Strategy", values="Profit")
gain = w.sub(w["cost"], axis=0)
strategies = ["forecast", "robust", "persistence"]
share = pd.DataFrame({f: [100 * g[s].sum() / g["perfect"].sum() for s in strategies]
                      for f, g in gain.groupby(level="Firm")}, index=strategies)
p = forecast.pivot_table(index="Date", columns=["Firm", "Strategy"], values="Price_avg")
power = pd.DataFrame({f: p[(f, "perfect")] / p[(f, "cost")] - 1 for f in forecast["Firm"].unique()}).max(axis=1) > 0.05
pkg = load_forecast_package()
spare = pkg[pkg["Area"] == "National"].set_index("Date")["Tightness_forecast"].reindex(power.index)
bands = pd.cut(spare, [0, 0.10, 0.15, 0.20, 0.30, 1.0], labels=["≤10%", "10–15%", "15–20%", "20–30%", ">30%"])
by_band = 100 * power.groupby(bands, observed=True).mean()

fig, ax = plt.subplots(1, 2, figsize=(10, 3.2))
x = np.arange(len(strategies))
ax[0].bar(x - 0.2, share["NR UP"], 0.4, color="tab:blue", label="UP")
ax[0].bar(x + 0.2, share["WR Maharashtra"], 0.4, color="tab:orange", label="Maharashtra")
ax[0].axhline(100, color="tab:gray", linestyle=":", linewidth=1)
ax[0].set_xticks(x, ["Part 2 forecast", "Scenario average\n(robust)", "Yesterday\n(persistence)"])
ax[0].set_ylabel("% of perfect-foresight gain")
ax[0].set_title("Bidding on what is known the day before")
ax[0].legend(fontsize=8)
ax[1].bar(by_band.index.astype(str), by_band.values, color="tab:red")
ax[1].set_xlabel("Forecast spare capacity")
ax[1].set_ylabel("Days with market power (%)")
ax[1].set_title(f"Market power on {int(power.sum())} of {len(power)} days: not only tight ones")
plt.tight_layout()
fig.savefig(OUT / "p3_fig5_forecasts.png", bbox_inches="tight")
plt.close(fig)

print("Saved:", ", ".join(sorted(p.name for p in OUT.glob("p3_*.png"))))
