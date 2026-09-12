#!/usr/bin/env python3
"""Figure 3 - the property layer, and the shape of what is missing.

a  every property ranked by how much of the pool it covers
b  coverage grouped by the calculation the property requires
c  how many properties a single structure carries
d  which database supplies which property
e  the spectrum store
f  what each database's own structures gained from the others
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, LogNorm, to_rgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import (BLU, CM, CYA, DATA, GRN, GRY, GROUP_COLOUR, LGY, ORA, PUR,
                   RED, W2, bars, group_of, save, stamp)

# the 15 registry entries with no value yet are not plotted: an empty column
# would sit off the logarithmic axis and inflate the emptiness of the matrix.
P = [r for r in csv.DictReader((DATA / "properties.csv").open())
     if int(r["n_materials"]) > 0]
PS = list(csv.DictReader((DATA / "property_source_matrix.csv").open()))
CV = list(csv.DictReader((DATA / "curves_by_type.csv").open()))
TIER = list(csv.DictReader((DATA / "cost_tiers.csv").open()))
XF = list(csv.DictReader((DATA / "crossfill_sources.csv").open()))
XFS = json.loads((DATA / "crossfill.json").read_text())
TJSON = json.loads((DATA / "cost_tiers.json").read_text())
SUM = json.loads((DATA / "summary.json").read_text())
NMAT = SUM["n_materials"]
NPROP = len(P)

HAVE_COUNT = (DATA / "material_property_count.csv").exists()

TIER_COL = {1: BLU, 2: CYA, 3: GRN, 4: RED}
TIER_SHORT = {1: "one self-consistent\nrun", 2: "a few extra\nruns",
              3: "linear response /\nfinite differences",
              4: "anharmonic, transport,\nbeyond-semilocal"}
tier_of = {r["property"]: int(r["tier"]) for r in TIER}

fig = plt.figure(figsize=(W2, 19.6 * CM))
gs = fig.add_gridspec(3, 3, height_ratios=[1.0, 1.12, 0.80],
                      width_ratios=[1.10, 0.92, 0.98],
                      hspace=0.84, wspace=0.40,
                      left=0.070, right=0.980, top=0.966, bottom=0.072)

# ------------------------------------------------------- a coverage ranking
ax = fig.add_subplot(gs[0, 0])
rows = sorted(P, key=lambda r: -int(r["n_materials"]))
cov = np.array([int(r["n_materials"]) for r in rows])
x = np.arange(len(rows))
cols = [TIER_COL.get(tier_of.get(r["property"]), LGY) for r in rows]
ax.scatter(x, cov, s=6, c=cols, edgecolor="none", zorder=3)
ax.plot(x, cov, color=LGY, lw=0.45, zorder=1)
ax.set_yscale("log")
ax.set_ylim(30, 3e7)
ax.set_xlim(-3, len(rows) + 44)
ax.set_xlabel(f"Properties, ranked ({NPROP} carrying values)")
ax.set_ylabel("Structures carrying the property")
for frac, style in ((0.10, (0, (4, 2))), (0.01, (0, (1.5, 1.8)))):
    ax.axhline(NMAT * frac, color=GRY, lw=0.5, ls=style, zorder=2)
    ax.text(len(rows) + 42, NMAT * frac * 1.3, f"{frac*100:g}% of pool", fontsize=5.8,
            color=GRY, ha="right")
label = {"total_energy_per_atom": (12, 1.9), "band_gap": (28, 1.15),
         "energy_above_hull": (42, 0.55), "density": (54, 1.05),
         "bulk_modulus_vrh": (34, 2.6), "dielectric_constant_electronic": (20, 3.4),
         "co2_uptake": (50, 0.40), "lattice_thermal_conductivity": (18, 2.2),
         "tc_superconducting": (18, 3.4), "shg_coefficient": (14, 1.5)}
for i, r in enumerate(rows):
    if r["property"] in label:
        dx, mul = label[r["property"]]
        ax.annotate(r["property"].replace("_", " "), xy=(i, cov[i]),
                    xytext=(i + dx, cov[i] * mul), fontsize=5.6,
                    color=TIER_COL.get(tier_of.get(r["property"]), "#555555"),
                    ha="left" if dx >= 0 else "right",
                    arrowprops=dict(arrowstyle="-", color=GRY, lw=0.35))
stamp(fig, ax, "a")

# ------------------------------------------------------------- b cost tiers
ax = fig.add_subplot(gs[0, 1])
rng = np.random.default_rng(0)
for t in (1, 2, 3, 4):
    vals = np.array([float(r["coverage"]) for r in TIER if int(r["tier"]) == t]) * 100
    jitter = rng.uniform(-0.20, 0.20, vals.size)
    ax.scatter(np.full(vals.size, t) + jitter, vals, s=11,
               facecolor=(*to_rgb(TIER_COL[t]), 0.55), edgecolor=TIER_COL[t],
               linewidth=0.45, zorder=3)
    med = np.median(vals)
    ax.plot([t - 0.34, t + 0.34], [med, med], color=TIER_COL[t], lw=1.5, zorder=4)
    ax.text(t, 190, f"{med:.2f}%", ha="center", va="bottom", fontsize=6.0,
            color=TIER_COL[t])
ax.set_yscale("log")
ax.set_ylim(2e-4, 400)
ax.set_xlim(0.45, 4.55)
ax.set_xticks([1, 2, 3, 4])
ax.set_xticklabels(["1", "2", "3", "4"], fontsize=7.0)
ax.set_xlabel("Calculation the property requires (tier)")
for t in (1, 2, 3, 4):
    ax.get_xticklabels()[t - 1].set_color(TIER_COL[t])
ax.set_ylabel("Pool covered (%)")
ax.axhline(10, color=GRY, lw=0.5, ls=(0, (4, 2)))
ax.text(4.5, 12, "10%", fontsize=5.8, color=GRY, ha="right")
stamp(fig, ax, "b", dx=-0.050)

# ------------------------------------------- c properties per material
ax = fig.add_subplot(gs[0, 2])
if HAVE_COUNT:
    C = list(csv.DictReader((DATA / "material_property_count.csv").open()))
    k = np.array([int(r["n_properties"]) for r in C])
    v = np.array([int(r["n_materials"]) for r in C])
    bars(ax.bar(k, v, width=0.92), [GRY if kk == 0 else BLU for kk in k],
         face_alpha=0.55, edge=0.0)
    ax.set_yscale("log")
    ax.set_xlabel("Properties carried by one structure")
    ax.set_ylabel("Structures")
    ax.set_xlim(-0.8, min(k.max(), 45) + 0.8)
    ax.set_ylim(0.6, v.max() * 4)
    med = int(np.repeat(k, np.minimum(v, 10**7)).mean()) if v.sum() else 0
else:
    ax.axis("off")
    ax.text(0.5, 0.5, "properties per structure\n(scan running)", ha="center", va="center",
            fontsize=7, color=GRY, transform=ax.transAxes)
stamp(fig, ax, "c", dx=-0.050)

# ------------------------------------------------- d property x source matrix
ax = fig.add_subplot(gs[1, 0:2])
prop_order = [r["property"] for r in sorted(P, key=lambda r: -int(r["n_materials"]))[:34]]
src_tot = defaultdict(int)
for r in PS:
    src_tot[r["source"]] += int(r["n_materials"])
src_order = sorted(src_tot, key=lambda k: -src_tot[k])[:26]
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
for s, lab in ((2.0 + 3.6 * 2, "$10^2$"), (2.0 + 3.6 * 4, "$10^4$"),
               (2.0 + 3.6 * 6, "$10^6$")):
    ax.scatter([], [], s=s, c=GRY, alpha=0.7, label=lab)
ax.legend(title="structures carrying the value", frameon=False, loc="lower right",
          bbox_to_anchor=(1.005, -0.02), ncol=3, columnspacing=1.1, borderpad=0.0,
          fontsize=6.0, title_fontsize=6.0, handletextpad=0.5)
stamp(fig, ax, "d")

# -------------------------------------------------------------- e curve store
ax = fig.add_subplot(gs[1, 2])
# distinct materials per curve type, not a sum over sources: a material with a
# band structure from two databases must not be counted twice.
by_type = {r["curve_type"]: [int(r["n_curves"]), int(r["n_materials"])] for r in CV}
order = sorted(by_type, key=lambda k: -by_type[k][0])
y = np.arange(len(order))[::-1]
ncur = np.array([by_type[k][0] for k in order])
nmat = np.array([by_type[k][1] for k in order])
bars(ax.barh(y + 0.19, ncur, height=0.36), PUR, face_alpha=0.50, edge=0.6)
bars(ax.barh(y - 0.19, nmat, height=0.36), GRN, face_alpha=0.50, edge=0.6)
ax.set_xscale("log")
ax.set_xlim(60, 3e6)
ax.set_yticks(y)
SHORT = {"kappa_cumulative": "$\\kappa$ cumulative", "kappa_spectral": "$\\kappa$ spectral",
         "band_structure": "band structure", "phonon_dos": "phonon DOS",
         "dos": "electronic DOS", "xas": "XAS", "xrd": "XRD", "raman": "Raman",
         "ir": "infrared", "absorption": "optical absorption"}
ax.set_yticklabels([SHORT.get(k, k.replace("_", " ")) for k in order], fontsize=5.8)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlabel("Count")
ax.legend([mpatches.Patch(facecolor=(*to_rgb(PUR), 0.5), edgecolor=PUR, lw=0.6,
                          label="spectra stored"),
           mpatches.Patch(facecolor=(*to_rgb(GRN), 0.5), edgecolor=GRN, lw=0.6,
                          label="structures reached")],
          ["spectra stored", "structures reached"], frameon=False, loc="lower right",
          bbox_to_anchor=(1.03, 0.10), handlelength=0.9, handleheight=0.8,
          labelspacing=0.3, borderpad=0.0, fontsize=6.0)
stamp(fig, ax, "e", dx=-0.055)

# ------------------------------------------------- f what the merge redistributed
# Every structure has exactly one contributing database. The lower marker is the
# property record that database supplied; the upper marker is what the structure
# carries once the others are merged onto it. The distance between them is the
# part of the record no single database could have produced.
ax = fig.add_subplot(gs[2, :])
xf = [r for r in XF if int(r["structures_contributed"]) >= 2000]
xf.sort(key=lambda r: -int(r["structures_contributed"]))
xf = xf[:24]
x = np.arange(len(xf))
own = np.array([int(r["cells_from_contributor"]) / int(r["structures_contributed"])
                for r in xf])
tot = np.array([int(r["cells_occupied"]) / int(r["structures_contributed"]) for r in xf])
fmat = np.array([float(r["frac_structures_with_external"]) for r in xf])
cols = [GROUP_COLOUR[group_of(r["source"])] for r in xf]

for i, (o, t, c) in enumerate(zip(own, tot, cols)):
    if t - o > 0.02:
        ax.annotate("", xy=(i, t), xytext=(i, o),
                    arrowprops=dict(arrowstyle="-|>", color=c, lw=0.9,
                                    shrinkA=1.6, shrinkB=0.6,
                                    mutation_scale=5.5))
ax.scatter(x, own, s=14, facecolor="white", edgecolor=GRY, linewidth=0.7, zorder=4)
ax.scatter(x, tot, s=16, c=cols, edgecolor="none", zorder=5)
for i, (t, f, c) in enumerate(zip(tot, fmat, cols)):
    ax.text(i, t + 0.52, f"{f*100:.0f}" if f >= 0.005 else "0", ha="center", va="bottom",
            fontsize=5.4, color=c if f >= 0.005 else LGY)
ax.set_xticks(x)
ax.set_xticklabels([r["source"] for r in xf], rotation=90, fontsize=5.6)
ax.tick_params(axis="x", length=0, pad=1.5)
ax.set_xlim(-0.8, len(xf) - 0.2)
ax.set_ylim(0, 18.4)
ax.set_ylabel("Property values per structure")
ax.grid(axis="y", lw=0.3, color="#EEEEEE", zorder=0)
ax.set_axisbelow(True)
ax.legend([plt.Line2D([], [], marker="o", ls="none", mfc="white", mec=GRY, mew=0.7, ms=3.4),
           plt.Line2D([], [], marker="o", ls="none", color=GRY, ms=3.6)],
          ["supplied by the contributing database",
           "carried after the other 54 are merged on"],
          frameon=False, loc="upper right", bbox_to_anchor=(1.005, 0.90),
          handletextpad=0.4, labelspacing=0.35, borderpad=0.0, fontsize=6.0)
stamp(fig, ax, "f")

save(fig, "fig3_landscape")
