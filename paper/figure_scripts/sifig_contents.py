#!/usr/bin/env python3
"""Supplementary figure - what the property layer holds, panel by panel.

a  how many properties a single structure carries
b  which database supplies which property
c  the spectrum store, by curve type

These three were carried by the main text in an earlier draft. They document the
corpus rather than drive an argument, so they sit here.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import CM, DATA, W2, bars, group_of, save, stamp
from figkit import ACCENT, FAMILY, GRY, INK, MID, PROPERTY, SOFT

GROUP_COLOUR = FAMILY
PUR, GRN = PROPERTY["total_magnetization"], FAMILY["specialised"]

P = [r for r in csv.DictReader((DATA / "properties.csv").open())
     if int(r["n_materials"]) > 0]
PS = list(csv.DictReader((DATA / "property_source_matrix.csv").open()))
CV = list(csv.DictReader((DATA / "curves_by_type.csv").open()))

fig = plt.figure(figsize=(W2, 15.2 * CM))
_g0 = fig.add_gridspec(1, 2, left=0.072, right=0.988, top=0.975, bottom=0.700,
                       wspace=0.34, width_ratios=[1.0, 1.02])
_g1 = fig.add_gridspec(1, 1, left=0.072, right=0.988, top=0.610, bottom=0.085)

# ------------------------------------------- a properties per structure
ax = fig.add_subplot(_g0[0])
C = list(csv.DictReader((DATA / "material_property_count.csv").open()))
k = np.array([int(r["n_properties"]) for r in C])
v = np.array([int(r["n_materials"]) for r in C])
bars(ax.bar(k, v, width=0.92), [MID if kk == 0 else ACCENT for kk in k],
     face_alpha=0.55, edge=0.0)
ax.set_yscale("log")
ax.set_xlabel("Properties carried by one structure")
ax.set_ylabel("Structures")
ax.set_xlim(-0.8, min(k.max(), 45) + 0.8)
ax.set_ylim(0.6, v.max() * 4)
stamp(fig, ax, "a", dx=-0.058, dy=0.006)

# -------------------------------------------------------------- b curve store
ax = fig.add_subplot(_g0[1])
by_type = {r["curve_type"]: [int(r["n_curves"]), int(r["n_materials"])] for r in CV}
order = sorted(by_type, key=lambda kk: -by_type[kk][0])
y = np.arange(len(order))[::-1]
ncur = np.array([by_type[kk][0] for kk in order])
nmat = np.array([by_type[kk][1] for kk in order])
bars(ax.barh(y + 0.19, ncur, height=0.36), PUR, face_alpha=0.50, edge=0.6)
bars(ax.barh(y - 0.19, nmat, height=0.36), GRN, face_alpha=0.50, edge=0.6)
ax.set_xscale("log")
ax.set_xlim(60, 3e6)
ax.set_yticks(y)
SHORT = {"kappa_cumulative": "$\\kappa$ cumulative", "kappa_spectral": "$\\kappa$ spectral",
         "band_structure": "band structure", "phonon_dos": "phonon DOS",
         "dos": "electronic DOS", "xas": "XAS", "xrd": "XRD", "raman": "Raman",
         "ir": "infrared", "absorption": "optical absorption"}
ax.set_yticklabels([SHORT.get(kk, kk.replace("_", " ")) for kk in order], fontsize=5.8)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlabel("Count")
ax.legend([mpatches.Patch(facecolor=(*to_rgb(PUR), 0.5), edgecolor=PUR, lw=0.6),
           mpatches.Patch(facecolor=(*to_rgb(GRN), 0.5), edgecolor=GRN, lw=0.6)],
          ["spectra stored", "structures reached"], frameon=False, loc="lower right",
          bbox_to_anchor=(1.03, 0.06), handlelength=0.9, handleheight=0.8,
          labelspacing=0.3, borderpad=0.0, fontsize=6.0)
stamp(fig, ax, "b", dx=-0.070, dy=0.006)

# ------------------------------------------------- c property x source matrix
ax = fig.add_subplot(_g1[0])
prop_order = [r["property"] for r in sorted(P, key=lambda r: -int(r["n_materials"]))[:34]]
src_tot = defaultdict(int)
for r in PS:
    src_tot[r["source"]] += int(r["n_materials"])
src_order = sorted(src_tot, key=lambda kk: -src_tot[kk])[:26]
pi = {p: i for i, p in enumerate(prop_order)}
si = {s: i for i, s in enumerate(src_order)}
xs, ys, ss, cs = [], [], [], []
for r in PS:
    if r["property"] in pi and r["source"] in si:
        n = int(r["n_materials"])
        if n == 0:
            continue
        xs.append(pi[r["property"]])
        ys.append(si[r["source"]])
        ss.append(2.0 + 3.6 * np.log10(n))
        cs.append(GROUP_COLOUR[group_of(r["source"])])
ax.scatter(xs, ys, s=ss, c=cs, alpha=0.78, edgecolor="none")
ax.set_xticks(range(len(prop_order)))
ax.set_xticklabels([p.replace("_", " ") for p in prop_order], rotation=90, fontsize=5.2)
ax.set_yticks(range(len(src_order)))
ax.set_yticklabels(src_order, fontsize=5.2)
ax.tick_params(length=0, pad=1.2)
ax.set_xlim(-0.8, len(prop_order) - 0.2)
ax.set_ylim(-0.8, len(src_order) - 0.2)
ax.invert_yaxis()
ax.grid(True, lw=0.25, color="#EDEDED", zorder=0)
ax.set_axisbelow(True)
for spine in ax.spines.values():
    spine.set_visible(False)
for s_, lab in ((2.0 + 3.6 * 2, "$10^2$"), (2.0 + 3.6 * 4, "$10^4$"),
                (2.0 + 3.6 * 6, "$10^6$")):
    ax.scatter([], [], s=s_, c=GRY, alpha=0.7, label=lab)
ax.legend(title="structures carrying the value", frameon=False, loc="lower right",
          bbox_to_anchor=(1.005, -0.02), ncol=3, columnspacing=1.1, borderpad=0.0,
          fontsize=6.0, title_fontsize=6.0, handletextpad=0.5)
stamp(fig, ax, "c", dx=-0.058, dy=0.006)

save(fig, "sifig_contents")
