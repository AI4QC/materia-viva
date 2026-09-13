#!/usr/bin/env python3
"""What completing the property layer over the whole record settles.

a  registered properties -> separable tasks -> realised training sets   [real]
b  the applicability domains the tasks declare                          [real]
c  what each task already knows against what it may be asked            [real]
d  held-out error against the cross-source noise floor                  [PLACEHOLDER]
e  coverage of the pool before and after the completion                 [PLACEHOLDER]
f  what the completed layer nominates, and what survives recomputation  [PLACEHOLDER]

Panels d-f are drawn from PLACEHOLDER numbers while the models train, and the
main text asserts nothing from them. Replace the PLACEHOLDER block with the run
records when the models finish. WITH_PENDING=0 renders a-c alone.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import to_rgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matplotlib.ticker import LogLocator
from style import CM, DATA, W2, bars, save, stamp
from figkit import (ACCENT, ACCENT_SOFT, AGREE, BLU, CRITERION, CYA, ELL,
                    FAMILY, GRN, GRY, INK, LGY, LIGHT, LONG, MECHANISM,
                    MID, ORA, PALE, PROPERTY, PUR, RED, ROUTE, SHARED, SOFT,
                    TIER as TIER_COLOUR, boxed_text)
GROUP_COLOUR = FAMILY
SOFT_A = "#6B6E70"

print("\n  *** draft_fig4_completion.py panels d-f are PLACEHOLDER ***\n")

C = json.loads((DATA / "gnn_census.json").read_text())
PRED = list(csv.DictReader((DATA / "gnn_prediction_sets.csv").open()))
POOL = json.loads((DATA / "summary.json").read_text())["n_materials"]

# ======================================================================
# PLACEHOLDER  (replace with the trained-model records)
# ======================================================================
rng = np.random.default_rng(4)
_n = 26
PH_TASKS = [f"t{i}" for i in range(_n)]
PH_NOISE = rng.uniform(0.04, 0.55, _n)              # cross-source spread, normalised
PH_MAE = PH_NOISE * rng.uniform(0.45, 1.6, _n)      # held-out MAE, same units
PH_TIER = rng.choice([1, 2, 3], size=_n, p=[0.45, 0.35, 0.20])
PH_COV_PROPS = ["band gap", "formation energy", "hull distance", "bulk modulus",
                "dielectric constant", "Seebeck", "thermal conductivity",
                "work function"]
PH_COV_NOW = np.array([0.57, 0.68, 0.50, 0.015, 0.017, 0.004, 0.002, 0.001])
PH_COV_AFTER = np.array([0.93, 0.96, 0.91, 0.62, 0.58, 0.34, 0.21, 0.44])
PH_FUNNEL = [("inside a declared\ndomain", 1_105_593_143),
             ("passes the\nproperty filter", 4_100_000),
             ("ranked above\nthe known best", 190_000),
             ("survives\nrecomputation", 21_000)]
# ======================================================================

import os
WITH_PENDING = os.environ.get("WITH_PENDING", "1") not in ("0", "false")

if WITH_PENDING:
    fig = plt.figure(figsize=(W2, 13.4 * CM))
    # Rows placed by hand: the gap only has to hold one axis label and one panel
    # letter, which is 1.3 cm, not the 0.42 hspace a shared grid would spend.
    _g0 = fig.add_gridspec(1, 3, left=0.062, right=0.988, top=0.982, bottom=0.579,
                           wspace=0.46, width_ratios=[0.92, 1.02, 1.0])
    _g1 = fig.add_gridspec(1, 3, left=0.062, right=0.988, top=0.482, bottom=0.079,
                           wspace=0.46, width_ratios=[1.0, 1.0, 1.0])
else:
    fig = plt.figure(figsize=(W2, 6.1 * CM))
    _g0 = fig.add_gridspec(1, 3, left=0.062, right=0.988, top=0.960, bottom=0.175,
                           wspace=0.46, width_ratios=[0.92, 1.02, 1.0])
    _g1 = None
_r0, _r1 = _g0, _g1

# ------------------------------------------------------------------ a funnel
# A real funnel, not a bar chart: the one stage that widens is the split by
# level of theory, and the shape says so without a caption.
ax = fig.add_subplot(_r0[0])
ax.set_xlim(-1.92, 1.22); ax.set_ylim(-0.22, 5.50); ax.axis("off")
stages = [("in the registry", C["n_properties_with_data"] + 15, SOFT),
          ("carrying a value", C["n_properties_with_data"], SOFT),
          ("split by level of theory", C["n_census_tasks"], MECHANISM),
          ("at least 10,000 crystals",
           C["tiers"]["T3"]["regression_tasks"] + C["tiers"]["T3"]["classification_tasks"], BLU),
          ("built as training sets", C["n_training_sets"], GRN)]
vals = np.array([v for _, v, _ in stages], dtype=float)
half = 0.90 * vals / vals.max()
STEP = 1.16
for i in range(len(stages) - 1):
    y0, y1 = 4.70 - i * STEP, 4.70 - (i + 1) * STEP
    col = stages[i + 1][2]
    ax.add_patch(mpatches.Polygon(
        [(-half[i], y0), (half[i], y0), (half[i + 1], y1), (-half[i + 1], y1)],
        closed=True, facecolor=(*to_rgb(col), 0.20), edgecolor="none", zorder=2))
for i, (lab, v, col) in enumerate(stages):
    y = 4.70 - i * STEP
    ax.plot([-half[i], half[i]], [y, y], color=col, lw=1.6, zorder=4,
            solid_capstyle="butt")
    ax.text(0, y + 0.62, f"{v}", ha="center", va="center", fontsize=8.4,
            color=col, fontweight="bold", zorder=5)
    ax.text(0, y + 0.33, lab, ha="center", va="center", fontsize=5.7,
            color=SOFT_A, zorder=5)
ax.annotate("", xy=(-half[2] - 0.05, 4.70 - 2 * STEP + 0.03),
            xytext=(-half[1] - 0.05, 4.70 - STEP - 0.10),
            arrowprops=dict(arrowstyle="-|>", color=MECHANISM, lw=1.0, mutation_scale=7,
                            connectionstyle="arc3,rad=0.62"), zorder=6)
ax.text(-1.90, 4.70 - 1.5 * STEP, "the only\nstage that\nwidens", fontsize=5.6,
        color=MECHANISM, ha="left", va="center", linespacing=1.3, zorder=6)
stamp(fig, ax, "a", dx=-0.028)

# ----------------------------------------------------------------- b domains
ax = fig.add_subplot(_r0[1])
dom = Counter(r["declared_domain"] for r in PRED)
order = [k for k, _ in dom.most_common()]
y = np.arange(len(order))[::-1]
vals = np.array([dom[k] for k in order])
PAL = LONG
bars(ax.barh(y, vals, height=0.64), [PAL[i % len(PAL)] for i in range(len(order))],
     face_alpha=0.55, edge=0.0)
for yi, vv in zip(y, vals):
    ax.text(vv + max(vals) * 0.02, yi, str(vv), va="center", ha="left",
            fontsize=5.8, color=GRY)
ax.set_yticks(y)
ax.set_yticklabels([k.replace("-", " ") for k in order], fontsize=5.8)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlim(0, max(vals) * 1.12)
ax.set_xlabel("Training sets")
stamp(fig, ax, "b", dx=-0.078)

# ---------------------------------------------- c labelled against predictable
ax = fig.add_subplot(_r0[2])
lab = np.array([int(r["n_labelled"]) for r in PRED], dtype=float)
pre = np.array([int(r["n_predictable"]) for r in PRED], dtype=float)
ax.scatter(np.clip(lab, 0.8, None), np.clip(pre, 0.8, None), s=9,
           facecolor=(*to_rgb(BLU), 0.55), edgecolor=BLU, linewidth=0.35)
lim = np.array([0.8, 3e7])
ax.plot(lim, lim, color=LGY, lw=0.7, ls=(0, (4, 2)))
ax.axhline(POOL, color=GRY, lw=0.6, ls=(0, (1.5, 1.8)))
ax.text(1.4, POOL * 1.35, "whole pool", fontsize=5.8, color=GRY)
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlim(0.8, 3e7); ax.set_ylim(0.8, 6e7)
ax.xaxis.set_major_locator(LogLocator(numticks=5))
ax.yaxis.set_major_locator(LogLocator(numticks=5))
ax.set_xlabel("Crystals already labelled")
ax.set_ylabel("May be asked about", fontsize=6.6)
stamp(fig, ax, "c", dx=-0.078)

if WITH_PENDING:
    # ------------------------------- d held-out error against the noise floor [PH]
    ax = fig.add_subplot(_r1[0])
    TC = TIER_COLOUR
    ax.scatter(PH_NOISE, PH_MAE, s=16, c=[TC[t] for t in PH_TIER], edgecolor="none",
               alpha=0.85, zorder=3)
    lim = np.array([0.02, 0.75])
    ax.plot(lim, lim, color=GRY, lw=0.7, ls=(0, (4, 2)), zorder=2)
    ax.fill_between(lim, lim, lim * 0 + 1e-3, color=GRN, alpha=0.06, zorder=1)
    ax.text(0.46, 0.085, "below the floor\nthe sources set", fontsize=5.8, color=GRN,
            ha="center", linespacing=1.35)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(0.03, 0.8); ax.set_ylim(0.02, 1.0)
    ax.xaxis.set_major_locator(LogLocator(numticks=4))
    ax.yaxis.set_major_locator(LogLocator(numticks=4))
    ax.set_xlabel("Cross-source spread of the label")
    ax.set_ylabel("Held-out error of the model")
    ax.legend([plt.Line2D([], [], marker="o", ls="none", color=TC[t], ms=3.4)
               for t in (1, 2, 3)],
              ["tier 1", "tier 2", "tier 3"], frameon=False, loc="upper left",
              fontsize=5.8, handletextpad=0.4, labelspacing=0.28, borderpad=0.0)
    stamp(fig, ax, "d", dx=-0.078, dy=0.004)

    # -------------------------------------- e coverage before and after [PH]
    ax = fig.add_subplot(_r1[1])
    y = np.arange(len(PH_COV_PROPS))[::-1]
    for yi, a_, b_ in zip(y, PH_COV_NOW, PH_COV_AFTER):
        ax.annotate("", xy=(b_ * 100, yi), xytext=(a_ * 100, yi),
                    arrowprops=dict(arrowstyle="-|>", color=BLU, lw=1.0,
                                    mutation_scale=5.5, shrinkA=1.4, shrinkB=0.8))
    ax.scatter(PH_COV_NOW * 100, y, s=14, facecolor="white", edgecolor=GRY,
               linewidth=0.7, zorder=4)
    ax.scatter(PH_COV_AFTER * 100, y, s=16, color=BLU, edgecolor="none", zorder=5)
    ax.set_yticks(y); ax.set_yticklabels(PH_COV_PROPS, fontsize=5.8)
    ax.tick_params(axis="y", length=0, pad=1.5)
    ax.set_xscale("log"); ax.set_xlim(0.06, 260)
    ax.xaxis.set_major_locator(LogLocator(numticks=5))
    ax.set_xlabel("Pool covered (%)")
    ax.legend([plt.Line2D([], [], marker="o", ls="none", mfc="white", mec=GRY, mew=0.7, ms=3.2),
               plt.Line2D([], [], marker="o", ls="none", color=BLU, ms=3.4)],
              ["computed by a source", "after the completion"], frameon=False,
              loc="upper left", fontsize=5.8, handletextpad=0.4, labelspacing=0.3,
              borderpad=0.0)
    stamp(fig, ax, "e", dx=-0.078, dy=0.004)

    # ----------------------------------------------- f what it nominates [PH]
    ax = fig.add_subplot(_r1[2])
    labels = [s for s, _ in PH_FUNNEL]
    vals = np.array([v for _, v in PH_FUNNEL], dtype=float)
    y = np.arange(len(vals))[::-1]
    bars(ax.barh(y, vals, height=0.60), [MID, ACCENT_SOFT, ACCENT, GRN],
         face_alpha=0.65, edge=0.0)
    for yi, vv in zip(y, vals):
        txt = f"{vv/1e9:.2f}B" if vv >= 1e9 else (f"{vv/1e6:.1f}M" if vv >= 1e6 else f"{vv/1e3:.0f}k")
        ax.text(vv * 1.35, yi, txt, va="center", ha="left", fontsize=6.0, color=GRY)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=5.8, linespacing=1.3)
    ax.tick_params(axis="y", length=0, pad=1.5)
    ax.set_xscale("log"); ax.set_xlim(5e3, 2.2e10)
    ax.xaxis.set_major_locator(LogLocator(numticks=5))
    ax.set_xlabel("Structure\u2013task pairs")
    stamp(fig, ax, "f", dx=-0.078, dy=0.004)

save(fig, "fig_completion")
