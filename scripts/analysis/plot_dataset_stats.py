#!/usr/bin/env python3
"""Dataset statistics plots: experimental positives (99k) vs 6.12M unlabeled pool.

STYLE: all text English, Arial, black (user requirement 2026-07-24).
DATA/PLOT SEPARATION: reads ONLY saved extraction outputs; every figure's numbers
are also written to plot_data/*.csv so figures can be restyled without recompute.

Inputs  (data/external_structs/work/stats/):
  {exp,pool}_elements.json    element presence counts (full population)
  {exp,pool}_spg.tsv          space groups (exp full; pool 1-in-20 sample)
  {exp,pool}_dists.npz        per-structure natoms / nelems / density (full population)
Outputs (docs/figures/dataset_stats/):
  ptable_exp.png ptable_pool.png ptable_log_ratio.png
  spacegroup_exp.png spacegroup_pool.png crystal_system_compare.png
  natoms_dist.png nelements_compare.png top20_spacegroups.png density_dist.png
  plot_data/*.csv
"""
import csv, json, math, os
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymatviz as pmv

# ------------------------------------------------------------------ style
plt.rcParams.update({
    "font.family": "Arial", "text.color": "black", "axes.labelcolor": "black",
    "xtick.color": "black", "ytick.color": "black", "axes.edgecolor": "black",
    "axes.titlecolor": "black",
})
PLOTLY_FONT = dict(family="Arial", color="black")
C_EXP, C_POOL = "#4C78A8", "#F58518"          # color follows the dataset everywhere

REPO = Path(__file__).resolve().parents[2]
STATS = REPO / "data" / "raw" / "external_structs" / "work" / "stats"
OUT = REPO / "docs" / "figures" / "dataset_stats"
PD = OUT / "plot_data"
os.makedirs(PD, exist_ok=True)

CRYSTAL_SYSTEMS = [("triclinic", 1, 2), ("monoclinic", 3, 15), ("orthorhombic", 16, 74),
                   ("tetragonal", 75, 142), ("trigonal", 143, 167),
                   ("hexagonal", 168, 194), ("cubic", 195, 230)]

def crystal_system(spg):
    for name, lo, hi in CRYSTAL_SYSTEMS:
        if lo <= spg <= hi:
            return name
    return "unknown"

SPG_SYMBOL = {}
try:
    from pymatgen.symmetry.groups import SpaceGroup
    for n in range(1, 231):
        try:
            SPG_SYMBOL[n] = SpaceGroup.from_int_number(n).symbol
        except Exception:
            SPG_SYMBOL[n] = str(n)
except Exception:
    SPG_SYMBOL = {n: str(n) for n in range(1, 231)}

# ------------------------------------------------------------------ load
exp_el = json.load(open(f"{STATS}/exp_elements.json"))
pool_el = json.load(open(f"{STATS}/pool_elements.json"))
n_exp, n_pool = exp_el["n_structures"], pool_el["n_structures"]

def load_spg(fp):
    c = Counter()
    for line in open(fp):
        _i, s = line.rstrip("\n").split("\t")
        s = int(s)
        if 1 <= s <= 230:
            c[s] += 1
    return c

exp_spg, pool_spg = load_spg(f"{STATS}/exp_spg.tsv"), load_spg(f"{STATS}/pool_spg.tsv")
NE_SPG, NP_SPG = sum(exp_spg.values()), sum(pool_spg.values())
exp_d = np.load(f"{STATS}/exp_dists.npz")
pool_d = np.load(f"{STATS}/pool_dists.npz")

# ------------------------------------------------------------------ plot_data CSVs
els = sorted(set(exp_el["counts"]) | set(pool_el["counts"]))
with open(f"{PD}/elements.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["element", "exp_count", "exp_frac", "pool_count", "pool_frac",
                "log10_ratio_exp_over_pool"])
    for e in els:
        a, b = exp_el["counts"].get(e, 0), pool_el["counts"].get(e, 0)
        lr = round(math.log10((a / n_exp) / (b / n_pool)), 4) if a and b else ""
        w.writerow([e, a, round(a / n_exp, 6), b, round(b / n_pool, 6), lr])
with open(f"{PD}/spacegroups.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["spg", "symbol", "crystal_system", "exp_count", "exp_frac",
                "pool_count_sampled", "pool_frac"])
    for s in range(1, 231):
        w.writerow([s, SPG_SYMBOL[s], crystal_system(s), exp_spg.get(s, 0),
                    round(exp_spg.get(s, 0) / NE_SPG, 6),
                    pool_spg.get(s, 0), round(pool_spg.get(s, 0) / NP_SPG, 6)])
cs_rows = []
for name, lo, hi in CRYSTAL_SYSTEMS:
    a = sum(v for k, v in exp_spg.items() if lo <= k <= hi)
    b = sum(v for k, v in pool_spg.items() if lo <= k <= hi)
    cs_rows.append([name, a, a / NE_SPG, b, b / NP_SPG])
with open(f"{PD}/crystal_systems.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["crystal_system", "exp_count", "exp_frac", "pool_count_sampled", "pool_frac"])
    for r in cs_rows:
        w.writerow([r[0], r[1], round(r[2], 5), r[3], round(r[4], 5)])

# ------------------------------------------------------------------ ptables (plotly, Arial black)
def styled_ptable(counts, title, **kw):
    fig = pmv.ptable_heatmap_plotly(counts, **kw)
    fig.update_layout(font=PLOTLY_FONT,
                      title=dict(text=title, x=0.35, font=dict(size=20, **PLOTLY_FONT)))
    return fig

styled_ptable(exp_el["counts"], f"Element distribution - experimental positives (n={n_exp:,})",
              log=True, colorscale="YlGnBu").write_image(
    f"{OUT}/ptable_exp.png", width=1200, height=700, scale=2)
styled_ptable(pool_el["counts"], f"Element distribution - 6.12M unlabeled pool (n={n_pool:,})",
              log=True, colorscale="YlGnBu").write_image(
    f"{OUT}/ptable_pool.png", width=1200, height=700, scale=2)
ratio = {e: round(math.log10((exp_el["counts"][e] / n_exp) / (pool_el["counts"][e] / n_pool)), 3)
         for e in els if exp_el["counts"].get(e) and pool_el["counts"].get(e)}
fig = pmv.ptable_heatmap_plotly(ratio, colorscale="RdBu_r", cscale_range=(-1.5, 1.5))
fig.update_layout(font=PLOTLY_FONT, title=dict(
    text="Element coverage bias: log10(exp / pool share)<br>"
         "<sup>red = enriched in experimental positives, blue = enriched in 6.12M pool</sup>",
    x=0.5, xanchor="center", y=0.97, font=dict(size=18, **PLOTLY_FONT)))
fig.write_image(f"{OUT}/ptable_log_ratio.png", width=1200, height=720, scale=2)
print("ptables done")

# ------------------------------------------------------------------ spacegroup bars (pymatviz)
for tag, c, title in (("exp", exp_spg, f"Space-group distribution - experimental positives (n={NE_SPG:,})"),
                      ("pool", pool_spg, f"Space-group distribution - 6.12M pool (1/20 sample, n={NP_SPG:,})")):
    series = pd.Series({k: v for k, v in sorted(c.items())})
    fig = pmv.spacegroup_bar(series.index.repeat(series.values).tolist(), log=True)
    fig.update_layout(font=PLOTLY_FONT,
                      title=dict(text=title, x=0.5, font=dict(size=20, **PLOTLY_FONT)))
    fig.write_image(f"{OUT}/spacegroup_{tag}.png", width=1600, height=600, scale=2)
print("spacegroup bars done")

# ------------------------------------------------------------------ crystal systems (grouped bars)
names = [r[0] for r in cs_rows]
fe = [r[2] * 100 for r in cs_rows]; fp_ = [r[4] * 100 for r in cs_rows]
x = np.arange(len(names)); wdt = 0.38
fig, ax = plt.subplots(figsize=(10, 5.8), dpi=200)
b1 = ax.bar(x - wdt/2, fe, wdt, label=f"experimental positives (n={NE_SPG:,})",
            color=C_EXP, edgecolor="white", linewidth=1)
b2 = ax.bar(x + wdt/2, fp_, wdt, label=f"6.12M pool (sampled n={NP_SPG:,})",
            color=C_POOL, edgecolor="white", linewidth=1)
for bars in (b1, b2):
    for b in bars:
        ax.annotate(f"{b.get_height():.1f}", (b.get_x() + b.get_width()/2, b.get_height()),
                    ha="center", va="bottom", fontsize=9, color="black")
ax.set_xticks(x); ax.set_xticklabels(names, fontsize=11)
ax.set_ylabel("share of structures (%)")
ax.set_title("Crystal-system distribution: experimental positives vs 6.12M pool", pad=14)
ax.set_ylim(0, max(max(fe), max(fp_)) * 1.28)
ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0.01, 1.0), fontsize=10,
          labelcolor="black")
ax.spines[["top", "right"]].set_visible(False)
ax.grid(axis="y", alpha=0.25)
fig.tight_layout(); fig.savefig(f"{OUT}/crystal_system_compare.png"); plt.close(fig)
print("crystal_system_compare done")

# ------------------------------------------------------------------ NEW: atoms per cell
bins = np.arange(0.5, 61.5, 1)
he, _ = np.histogram(np.clip(exp_d["natoms"], 0, 60), bins=bins)
hp, _ = np.histogram(np.clip(pool_d["natoms"], 0, 60), bins=bins)
centers = np.arange(1, 61)
with open(f"{PD}/natoms_hist.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["natoms(60=60+)", "exp_count", "exp_frac", "pool_count", "pool_frac"])
    for i, cval in enumerate(centers):
        w.writerow([cval, he[i], round(he[i]/len(exp_d["natoms"]), 6),
                    hp[i], round(hp[i]/len(pool_d["natoms"]), 6)])
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=200)
ax.step(centers, he / he.sum() * 100, where="mid", color=C_EXP, lw=2,
        label=f"experimental positives (n={len(exp_d['natoms']):,})")
ax.step(centers, hp / hp.sum() * 100, where="mid", color=C_POOL, lw=2,
        label=f"6.12M pool (n={len(pool_d['natoms']):,})")
ax.set_xlabel("atoms per (primitive) cell   [60 = 60+]")
ax.set_ylabel("share of structures (%)")
ax.set_title("Cell-size distribution: experimental positives vs 6.12M pool", pad=12)
ax.legend(frameon=False, labelcolor="black")
ax.spines[["top", "right"]].set_visible(False); ax.grid(alpha=0.25)
fig.tight_layout(); fig.savefig(f"{OUT}/natoms_dist.png"); plt.close(fig)
print("natoms_dist done")

# ------------------------------------------------------------------ NEW: number of elements (arity)
cats = ["1", "2", "3", "4", "5+"]
def arity_frac(arr):
    a = np.clip(arr, 1, 5)
    return [np.mean(a == k) * 100 for k in (1, 2, 3, 4)] + [np.mean(a == 5) * 100]
ae, ap_ = arity_frac(exp_d["nelems"]), arity_frac(pool_d["nelems"])
with open(f"{PD}/arity.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["n_elements", "exp_pct", "pool_pct"])
    for c_, a, b in zip(cats, ae, ap_):
        w.writerow([c_, round(a, 3), round(b, 3)])
x = np.arange(len(cats))
fig, ax = plt.subplots(figsize=(8.6, 5.2), dpi=200)
b1 = ax.bar(x - 0.19, ae, 0.38, color=C_EXP, edgecolor="white",
            label=f"experimental positives (n={len(exp_d['nelems']):,})")
b2 = ax.bar(x + 0.19, ap_, 0.38, color=C_POOL, edgecolor="white",
            label=f"6.12M pool (n={len(pool_d['nelems']):,})")
for bars in (b1, b2):
    for b in bars:
        ax.annotate(f"{b.get_height():.1f}", (b.get_x() + b.get_width()/2, b.get_height()),
                    ha="center", va="bottom", fontsize=9, color="black")
ax.set_xticks(x); ax.set_xticklabels(cats)
ax.set_xlabel("number of distinct elements")
ax.set_ylabel("share of structures (%)")
ax.set_title("Chemical complexity: experimental positives vs 6.12M pool", pad=12)
ax.set_ylim(0, max(max(ae), max(ap_)) * 1.25)
ax.legend(frameon=False, labelcolor="black")
ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="y", alpha=0.25)
fig.tight_layout(); fig.savefig(f"{OUT}/nelements_compare.png"); plt.close(fig)
print("nelements_compare done")

# ------------------------------------------------------------------ NEW: top-20 space groups
top = sorted(range(1, 231), key=lambda s: exp_spg.get(s, 0), reverse=True)[:20]
lab = [f"{SPG_SYMBOL[s]} (#{s})" for s in top]
fe_ = [exp_spg.get(s, 0) / NE_SPG * 100 for s in top]
fp2 = [pool_spg.get(s, 0) / NP_SPG * 100 for s in top]
with open(f"{PD}/top20_spacegroups.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["spg", "symbol", "exp_pct", "pool_pct"])
    for s, a, b in zip(top, fe_, fp2):
        w.writerow([s, SPG_SYMBOL[s], round(a, 4), round(b, 4)])
y = np.arange(len(top))[::-1]
fig, ax = plt.subplots(figsize=(9, 9), dpi=200)
ax.barh(y + 0.19, fe_, 0.38, color=C_EXP, edgecolor="white",
        label="experimental positives")
ax.barh(y - 0.19, fp2, 0.38, color=C_POOL, edgecolor="white",
        label="6.12M pool (sampled)")
ax.set_yticks(y); ax.set_yticklabels(lab, fontsize=10)
ax.set_xlabel("share of structures (%)")
ax.set_title("Top-20 space groups (ranked by experimental share)", pad=12)
ax.legend(frameon=False, labelcolor="black")
ax.spines[["top", "right"]].set_visible(False); ax.grid(axis="x", alpha=0.25)
fig.tight_layout(); fig.savefig(f"{OUT}/top20_spacegroups.png"); plt.close(fig)
print("top20_spacegroups done")

# ------------------------------------------------------------------ NEW: mass density
de = exp_d["density"][exp_d["density"] > 0]
dp = pool_d["density"][pool_d["density"] > 0]
bins = np.linspace(0, 15, 121)
he, _ = np.histogram(np.clip(de, 0, 15), bins=bins)
hp, _ = np.histogram(np.clip(dp, 0, 15), bins=bins)
cent = (bins[:-1] + bins[1:]) / 2
with open(f"{PD}/density_hist.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["density_bin_center_g_cm3", "exp_frac", "pool_frac"])
    for c_, a, b in zip(cent, he / he.sum(), hp / hp.sum()):
        w.writerow([round(c_, 4), round(a, 6), round(b, 6)])
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=200)
ax.fill_between(cent, he / he.sum() * 100, step="mid", color=C_EXP, alpha=0.45,
                label=f"experimental positives (n={len(de):,}, median {np.median(de):.2f})")
ax.fill_between(cent, hp / hp.sum() * 100, step="mid", color=C_POOL, alpha=0.45,
                label=f"6.12M pool (n={len(dp):,}, median {np.median(dp):.2f})")
ax.step(cent, he / he.sum() * 100, where="mid", color=C_EXP, lw=1.5)
ax.step(cent, hp / hp.sum() * 100, where="mid", color=C_POOL, lw=1.5)
ax.set_xlabel("mass density (g/cm$^3$)   [clipped at 15]")
ax.set_ylabel("share of structures (%)")
ax.set_title("Density distribution - the geometry-source bias axis "
             "(PU models can exploit this shortcut)", pad=12)
ax.legend(frameon=False, labelcolor="black")
ax.spines[["top", "right"]].set_visible(False); ax.grid(alpha=0.25)
fig.tight_layout(); fig.savefig(f"{OUT}/density_dist.png"); plt.close(fig)
print("density_dist done")
print("ALL_PLOTS_DONE ->", OUT)
