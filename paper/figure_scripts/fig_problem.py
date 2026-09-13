#!/usr/bin/env python3
"""Draft Figure 2 - what the public record looks like once it is resolved.

Merges the redundancy/agreement figure and the coverage figure into one, since
Section 2.2 is now a single section. Panels that only illustrate rather than
argue (properties per structure, the property x source matrix, the spectrum
store) move to the Supplementary Information.

a  which databases overlap, and by how much
b  how often independent databases agree, per property
c  how far apart they land
d  pairwise disagreement for the most-shared property
e  every property ranked by how much of the pool it covers
f  coverage grouped by the calculation the property requires
g  what each database's own structures gained from the others
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm, to_rgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import CM, DATA, W2, bars, group_of, save, stamp
from figkit import (ACCENT, ACCENT_SOFT, AGREE, BLU, CRITERION, CYA, ELL,
                    FAMILY, GRN, GRY, INK, LGY, LIGHT, LONG, MECHANISM,
                    MID, ORA, PALE, PROPERTY, PUR, RED, ROUTE, SHARED, SOFT,
                    TIER as TIER_COLOUR, boxed_text)
GROUP_COLOUR = FAMILY

OVL = list(csv.DictReader((DATA / "source_overlap.csv").open()))
SRC = {r["key"]: r for r in csv.DictReader((DATA / "sources.csv").open())}
SUM = json.loads((DATA / "summary.json").read_text())
NMAT = SUM["n_materials"]
P = [r for r in csv.DictReader((DATA / "properties.csv").open())
     if int(r["n_materials"]) > 0]
NPROP = len(P)
TIER = list(csv.DictReader((DATA / "cost_tiers.csv").open()))
tier_of = {r["property"]: int(r["tier"]) for r in TIER}
TIER_COL = TIER_COLOUR
XF = list(csv.DictReader((DATA / "crossfill_sources.csv").open()))
PAIRS = list(csv.DictReader((DATA / "agreement_pairs.csv").open()))
PERP = list(csv.DictReader((DATA / "agreement_per_property.csv").open()))
SPREAD = list(csv.DictReader((DATA / "agreement_spread_samples.csv").open()))

NICE = {"band_gap": "band gap", "formation_energy_per_atom": "formation energy",
        "energy_above_hull": "hull distance", "total_magnetization": "magnetisation",
        "bulk_modulus_vrh": "bulk modulus", "shear_modulus_vrh": "shear modulus",
        "density": "density", "volume_per_atom": "volume per atom"}
PROP_COL = PROPERTY

fig = plt.figure(figsize=(W2, 17.0 * CM))
# Each row is placed by hand rather than by height_ratios + hspace: the three
# rows need different amounts of room beneath them (a colour bar, an axis label,
# a column of rotated source names), and one shared hspace has to be as large as
# the worst of them, which is where the white space came from. Row 0 is exactly
# as tall as the heat map is wide, so the square has no slack to leave empty.
_g0 = fig.add_gridspec(1, 3, left=0.066, right=0.988, top=0.988, bottom=0.641,
                       wspace=0.40, width_ratios=[1.22, 0.90, 0.94])
_g1 = fig.add_gridspec(1, 3, left=0.066, right=0.988, top=0.562, bottom=0.356,
                       wspace=0.50, width_ratios=[1.20, 1.0, 0.86])
_g2 = fig.add_gridspec(1, 1, left=0.066, right=0.988, top=0.279, bottom=0.078)
_r0, _r1 = _g0, _g1

# ------------------------------------------------------- a overlap heatmap
ax = fig.add_subplot(_r0[0])
# selected by how many structures each database annotates, not by how much it
# overlaps: the framework libraries have to stay in, because their empty rows
# are the point of the panel.
order = sorted(SRC, key=lambda k: -int(SRC[k]["n_materials"]))[:18]
idx = {k: i for i, k in enumerate(order)}
M = np.full((len(order), len(order)), np.nan)
for r in OVL:
    a, b = r["source_a"], r["source_b"]
    if a in idx and b in idx:
        M[idx[a], idx[b]] = M[idx[b], idx[a]] = int(r["n_shared"])
cmap = SHARED
cmap.set_bad("#F4F6F7")
im = ax.imshow(np.ma.masked_invalid(M), cmap=cmap,
               norm=LogNorm(vmin=10, vmax=5e5))
# symmetric matrix: rows and columns are in the same order, so it is named once
ax.set_yticks(range(len(order)))
ax.set_yticklabels(order, fontsize=5.0)
ax.set_xticks([])
ax.tick_params(length=0, pad=1.2)
for sp in ax.spines.values():
    sp.set_visible(False)
cb = fig.colorbar(im, ax=ax, orientation="horizontal", fraction=0.032, pad=0.055)
cb.set_label("shared crystals", fontsize=5.8, labelpad=1.2)
cb.ax.tick_params(labelsize=5.2, length=1.4, width=0.4)
cb.outline.set_linewidth(0.4)
ax.set_anchor("N")
stamp(fig, ax, "a", dx=-0.070)

# -------------------------------------------------- b agreement per property
ax = fig.add_subplot(_r0[1])
perp = [r for r in PERP if int(r["n_multi_source_materials"]) >= 500]
perp.sort(key=lambda r: float(r["frac_within_tol"]))
y = np.arange(len(perp))
frac = np.array([float(r["frac_within_tol"]) for r in perp]) * 100
bars(ax.barh(y, frac, height=0.66),
     [PROP_COL.get(r["property"], GRY) for r in perp], face_alpha=0.50, edge=0.7)
ax.set_yticks(y)
ax.set_yticklabels([NICE.get(r["property"], r["property"]) for r in perp], fontsize=6.0)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlim(0, 105)
ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xlabel("Independent databases agreeing (%)")
stamp(fig, ax, "b", dx=-0.070)

# --------------------------------------------------------- c spread curves
ax = fig.add_subplot(_r0[2])
by_prop = defaultdict(list)
for r in SPREAD:
    by_prop[r["property"]].append(float(r["spread"]))
for name in sorted(by_prop, key=lambda k: -len(by_prop[k])):
    v = np.sort(np.array(by_prop[name]))
    if v.size < 50:
        continue
    ax.plot(np.clip(v, 1e-4, None), np.linspace(0, 100, v.size), lw=1.0,
            color=PROP_COL.get(name, GRY), label=NICE.get(name, name))
ax.set_xscale("log"); ax.set_xlim(1e-4, 30); ax.set_ylim(0, 100)
ax.set_xlabel("Spread between databases")
ax.set_ylabel("Crystals below (%)")
ax.legend(frameon=True, facecolor="white", framealpha=0.9, edgecolor="none",
          loc="lower right", fontsize=5.4, handlelength=1.0,
          labelspacing=0.24, borderpad=0.25)
ax.grid(True, axis="y", lw=0.3, color="#EFEFEF"); ax.set_axisbelow(True)
stamp(fig, ax, "c", dx=-0.070)

# ------------------------------------------------ d pairwise disagreement
ax = fig.add_subplot(_r1[0])
rows = [r for r in PAIRS if r["property"] == "formation_energy_per_atom"]
best = {}
for r in rows:
    k = (r["source_a"], r["source_b"])
    if k not in best or int(r["n_shared"]) > int(best[k]["n_shared"]):
        best[k] = r
rows = sorted(best.values(), key=lambda r: -int(r["n_shared"]))[:10][::-1]
y = np.arange(len(rows))
med = np.array([float(r["median_abs_diff"]) for r in rows])
within = np.array([float(r["frac_within_tol"]) for r in rows]) * 100
ax.hlines(y, 0, med, color=LGY, lw=0.8, zorder=1)
sc = ax.scatter(med, y, s=15, c=within, cmap=AGREE, vmin=0, vmax=100,
                edgecolor=GRY, linewidth=0.4, zorder=3)
ax.set_yticks(y)
ax.set_yticklabels([f"{r['source_a']} $\\cdot$ {r['source_b']}" for r in rows], fontsize=5.2)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xscale("log")
ax.set_xlabel("Median |$\\Delta$| in formation energy (eV/atom)")
ax.axvline(0.05, color=GRY, lw=0.6, ls=(0, (3, 2)), zorder=2)
ax.set_xlim(0.0092, 0.112)
cb = fig.colorbar(sc, ax=ax, orientation="vertical", fraction=0.030, pad=0.035)
cb.set_label("within tolerance (%)", fontsize=5.6, labelpad=1.6)
cb.ax.tick_params(labelsize=5.2, length=1.4, width=0.4)
cb.outline.set_linewidth(0.4)
stamp(fig, ax, "d", dx=-0.070, dy=0.004)

# --------------------------------------------------------- e coverage ranking
ax = fig.add_subplot(_r1[1])
rows = sorted(P, key=lambda r: -int(r["n_materials"]))
cov = np.array([int(r["n_materials"]) for r in rows])
x = np.arange(len(rows))
ax.scatter(x, cov, s=5, c=[TIER_COL.get(tier_of.get(r["property"]), LGY) for r in rows],
           edgecolor="none", zorder=3)
ax.plot(x, cov, color=LGY, lw=0.45, zorder=1)
ax.set_yscale("log"); ax.set_ylim(30, 3e7); ax.set_xlim(-3, len(rows) + 30)
ax.set_xlabel(f"Properties, ranked ({NPROP} carrying values)")
ax.set_ylabel("Crystals carrying the property")
for frac_, style in ((0.10, (0, (4, 2))), (0.01, (0, (1.5, 1.8)))):
    ax.axhline(NMAT * frac_, color=GRY, lw=0.5, ls=style, zorder=2)
    ax.text(len(rows) + 28, NMAT * frac_ * 1.35, f"{frac_*100:g}% of pool",
            fontsize=5.6, color=GRY, ha="right")
stamp(fig, ax, "e", dx=-0.070, dy=0.004)

# ------------------------------------------------------------- f cost tiers
ax = fig.add_subplot(_r1[2])
rng = np.random.default_rng(0)
for t in (1, 2, 3, 4):
    v = np.array([float(r["coverage"]) for r in TIER if int(r["tier"]) == t]) * 100
    ax.scatter(np.full(v.size, t) + rng.uniform(-0.20, 0.20, v.size), v, s=10,
               facecolor=(*to_rgb(TIER_COL[t]), 0.55), edgecolor=TIER_COL[t],
               linewidth=0.45, zorder=3)
    ax.plot([t - 0.34, t + 0.34], [np.median(v)] * 2, color=TIER_COL[t], lw=1.5, zorder=4)
ax.set_yscale("log"); ax.set_ylim(2e-4, 400); ax.set_xlim(0.45, 4.55)
ax.set_xticks([1, 2, 3, 4]); ax.set_xticklabels(["1", "2", "3", "4"], fontsize=7.0)
for t in (1, 2, 3, 4):
    ax.get_xticklabels()[t - 1].set_color(TIER_COL[t])
ax.set_xlabel("Calculation required (tier)")
ax.set_ylabel("Pool covered (%)")
ax.axhline(10, color=GRY, lw=0.5, ls=(0, (4, 2)))
stamp(fig, ax, "f", dx=-0.070, dy=0.004)

# --------------------------------------------- g what the merge added, by source
ax = fig.add_subplot(_g2[0])
xf = sorted([r for r in XF if int(r["structures_contributed"]) >= 2000],
            key=lambda r: -int(r["structures_contributed"]))[:24]
x = np.arange(len(xf))
own = np.array([int(r["cells_from_contributor"]) / int(r["structures_contributed"]) for r in xf])
tot_ = np.array([int(r["cells_occupied"]) / int(r["structures_contributed"]) for r in xf])
fmat = np.array([float(r["frac_structures_with_external"]) for r in xf])
cols = [GROUP_COLOUR[group_of(r["source"])] for r in xf]
for i, (o, t, c) in enumerate(zip(own, tot_, cols)):
    if t - o > 0.02:
        ax.annotate("", xy=(i, t), xytext=(i, o),
                    arrowprops=dict(arrowstyle="-|>", color=c, lw=0.9,
                                    shrinkA=1.6, shrinkB=0.6, mutation_scale=5.5))
ax.scatter(x, own, s=13, facecolor="white", edgecolor=GRY, linewidth=0.7, zorder=4)
ax.scatter(x, tot_, s=15, c=cols, edgecolor="none", zorder=5)
for i, (t, f, c) in enumerate(zip(tot_, fmat, cols)):
    ax.text(i, t + 0.55, f"{f*100:.0f}", ha="center", va="bottom", fontsize=5.4,
            color=c if f >= 0.005 else LGY)
ax.set_xticks(x)
ax.set_xticklabels([r["source"] for r in xf], rotation=90, fontsize=5.6)
ax.tick_params(axis="x", length=0, pad=1.5)
ax.set_xlim(-0.8, len(xf) - 0.2); ax.set_ylim(0, 17.4)
ax.set_yticks([0, 5, 10, 15])
ax.set_ylabel("Property values per structure")
ax.grid(axis="y", lw=0.3, color="#EEEEEE"); ax.set_axisbelow(True)
ax.legend([plt.Line2D([], [], marker="o", ls="none", mfc="white", mec=GRY, mew=0.7, ms=3.2),
           plt.Line2D([], [], marker="o", ls="none", color=GRY, ms=3.4)],
          ["supplied by the contributing database",
           "carried after the other 54 are merged on"],
          frameon=False, loc="upper right", bbox_to_anchor=(1.005, 0.99),
          handletextpad=0.4, labelspacing=0.3, borderpad=0.0, fontsize=6.0)
stamp(fig, ax, "g", dy=0.004)

save(fig, "fig_problem")
