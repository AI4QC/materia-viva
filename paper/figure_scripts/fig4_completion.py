#!/usr/bin/env python3
"""Figure 4 - what the corpus offers a learned completion of the property layer.

a  every trainable task ranked by the structures available to train it
b  one property name, several levels of theory: the label-definition problem
c  how many tasks are restricted to part of the pool, and by what
d  what each task could actually be asked to predict, once its domain is enforced

Panels reporting the trained models are added when their held-out numbers exist.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import (BLU, CM, CYA, DATA, GRN, GRY, LGY, ORA, PUR, RED, W2, bars,
                   save, stamp)

T = list(csv.DictReader((DATA / "gnn_tasks.csv").open()))
TH = list(csv.DictReader((DATA / "gnn_theory_levels.csv").open()))
PS = list(csv.DictReader((DATA / "gnn_prediction_sets.csv").open()))
C = json.loads((DATA / "gnn_census.json").read_text())
POOL = 13_543_277
INK, SOFT = "#1A1A1A", "#5C5C5C"

DOM_COL = {
    "pool-wide": BLU, "porous": ORA, "ion-conducting": GRN, "gapped": CYA,
    "pool-wide-biased-labels": PUR, "synthesized-only": RED, "framework": "#8C5A2B",
    "magnetic": "#B07AA1", "surface-derived": GRY, "layered": "#76B7B2",
}

fig = plt.figure(figsize=(W2, 11.6 * CM))
gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.02], width_ratios=[1.0, 1.0],
                      hspace=0.50, wspace=0.34,
                      left=0.075, right=0.975, top=0.955, bottom=0.135)

# --------------------------------------------------------------- a cascade
# Deliberately NOT another rank-decay curve: Fig. 3a already carries that shape
# for coverage. What matters here is the counting chain, and in particular the
# one stage where the number goes up, because splitting a property name by level
# of theory is what turns 151 quantities into 513 separable learning problems.
ax = fig.add_subplot(gs[0, 0])
T = C["tiers"]
stages = [
    ("properties in the registry", 166, GRY, False),
    ("carrying at least one value", C["n_properties_with_data"], GRY, False),
    ("split by level of theory", C["n_census_tasks"], ORA, True),
    ("$\\geq$300 crystals to train on",
     T["T5"]["regression_tasks"] + T["T5"]["classification_tasks"], CYA, False),
    ("$\\geq$10$^4$ crystals",
     T["T3"]["regression_tasks"] + T["T3"]["classification_tasks"], BLU, False),
    ("$\\geq$10$^6$ crystals",
     T["T1"]["regression_tasks"] + T["T1"]["classification_tasks"], "#0A3D62", False),
    ("built as training sets", C["n_training_sets"], GRN, False),
]
y = np.arange(len(stages))[::-1]
vals = np.array([v for _, v, _, _ in stages])
cols = [c for _, _, c, _ in stages]
bars(ax.barh(y, vals, height=0.66), cols, face_alpha=0.55, edge=0.7)
for yi, (label, v, col, up) in zip(y, stages):
    ax.text(v + 12, yi, f"{v}", va="center", ha="left", fontsize=6.6, color=col,
            fontweight="bold" if up else "normal")
ax.set_yticks(y)
ax.set_yticklabels([lab for lab, _, _, _ in stages], fontsize=6.0)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlim(0, 620)
ax.set_xlabel("Count")
# the one stage that multiplies rather than filters
ax.annotate("", xy=(C["n_census_tasks"] - 8, y[2] + 0.36), xytext=(176, y[1] - 0.30),
            arrowprops=dict(arrowstyle="-|>", color=ORA, lw=0.9,
                            connectionstyle="arc3,rad=-0.32", mutation_scale=7))
ax.text(322, y[1] + 0.16,
        f"$\\times${C['n_census_tasks'] / C['n_properties_with_data']:.1f}",
        fontsize=7.6, color=ORA, fontweight="bold", ha="center", va="bottom")
ax.text(0.985, 0.055, "one property name is several quantities;\n"
                      "separating them is what makes them learnable",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=5.9,
        color=SOFT, linespacing=1.5, style="italic")
stamp(fig, ax, "a")

# ------------------------------------------------------- b theory-level split
ax = fig.add_subplot(gs[0, 1])
by_prop = defaultdict(list)
levels = {}
for r in TH:
    by_prop[r["property"]].append((r["theory_level"], int(r["n_materials"])))
    levels[r["property"]] = int(r["n_levels"])
props = sorted(by_prop, key=lambda p: -sum(v for _, v in by_prop[p]))[:9]
LEVEL_COL = {"gga": BLU, "gga-vdw": "#2E7FB8", "pbesol": CYA, "scan": GRN,
             "r2scan": "#4C9F70", "hse06": PUR, "tight-binding": ORA,
             "experiment": RED, "mbj": "#B07AA1", "gllbsc": "#8C5A2B",
             "lda": "#9BC9E0", "forcefield": "#C8A2C8", "other": LGY}
y = np.arange(len(props))[::-1]
for yi, prop in zip(y, props):
    items = sorted(by_prop[prop], key=lambda kv: -kv[1])
    total = sum(v for _, v in items)
    left = 0.0
    for name, v in items:
        frac = v / total * 100
        col = LEVEL_COL.get(name, LGY)
        ax.barh(yi, frac, left=left, height=0.68,
                color=(*to_rgb(col), 0.65), edgecolor="white", linewidth=0.35)
        if frac > 7:
            ax.text(left + frac / 2, yi, name, ha="center", va="center",
                    fontsize=5.2, color="white" if frac > 20 else INK)
        left += frac
    ax.text(101.5, yi, f"{levels[prop]}", ha="left", va="center", fontsize=5.8,
            color=SOFT)
ax.set_yticks(y)
ax.set_yticklabels([p.replace("_", " ") for p in props], fontsize=5.8)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlim(0, 110)
ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xlabel("Labels under the property name (%)")
ax.text(103.0, len(props) - 0.20, "levels", fontsize=5.6, color=SOFT, ha="left")
ax.text(0.5, -0.255, "one property name covers several quantities; each name is\n"
                     "split by level of theory before a task is counted",
        transform=ax.transAxes, ha="center", va="top", fontsize=6.0, style="italic",
        color=SOFT, linespacing=1.45)
stamp(fig, ax, "b", dx=-0.058)

# --------------------------------------------------------- c domains restrict
ax = fig.add_subplot(gs[1, 0])
dom = C["declared_domains"]
names = list(dom)[::-1]
vals = [dom[k] for k in names]
y = np.arange(len(names))
bars(ax.barh(y, vals, height=0.72), [DOM_COL.get(k, GRY) for k in names],
     face_alpha=0.55, edge=0.65)
ax.set_yticks(y)
ax.set_yticklabels([k.replace("-", " ") for k in names], fontsize=6.0)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlabel("Tasks")
ax.set_xlim(0, max(vals) * 1.22)
for yi, v in zip(y, vals):
    ax.text(v + max(vals) * 0.018, yi, str(v), va="center", ha="left", fontsize=5.9,
            color=SOFT)
ax.text(0.97, 0.06, f"{C['tasks_below_half_pool']} of {C['n_training_sets']} tasks\n"
                    "are defined on less than\nhalf the pool",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=6.0,
        linespacing=1.5, color=SOFT)
stamp(fig, ax, "c")

# ------------------------------------------------- d what can actually be asked
ax = fig.add_subplot(gs[1, 1])
lab = np.array([max(int(r["n_labelled"]), 1) for r in PS])
pred = np.array([max(int(r["n_predictable"]), 1) for r in PS])
doms = [r["declared_domain"] for r in PS]
for d in sorted(set(doms), key=lambda k: -dom.get(k, 0)):
    m = np.array([x == d for x in doms])
    ax.scatter(lab[m], pred[m], s=9, facecolor=(*to_rgb(DOM_COL.get(d, GRY)), 0.55),
               edgecolor=DOM_COL.get(d, GRY), linewidth=0.4, zorder=3, label=d)
ax.plot([1, 3e7], [1, 3e7], color=LGY, lw=0.6, ls=(0, (3, 2)), zorder=1)
ax.axhline(POOL, color=GRY, lw=0.6, ls=(0, (1.5, 1.8)), zorder=2)
ax.text(2.0e7, POOL * 1.32, "whole pool", fontsize=5.8, color=GRY,
        ha="right")
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlim(0.7, 3e7)
ax.set_ylim(0.7, 6e7)
ax.set_xlabel("Structures already labelled")
ax.set_ylabel("Structures it may be asked about")
ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(-0.025, -0.02),
          handlelength=0.7, labelspacing=0.20, borderpad=0.0, fontsize=5.0,
          markerscale=0.8, ncol=2, columnspacing=0.8, handletextpad=0.35)
gated, naive = C["n_predictable_gated"], C["n_predictable_ungated"]
ax.text(0.5, -0.255, f"{gated/1e6:.0f} million predictions lie inside a declared domain,\n"
                     f"against {naive/1e9:.2f} billion without one: a factor of "
                     f"{C['gating_ratio']:.1f}",
        transform=ax.transAxes, ha="center", va="top", fontsize=6.0, linespacing=1.45,
        color=SOFT, style="italic")
stamp(fig, ax, "d", dx=-0.058)

save(fig, "fig4_completion")
