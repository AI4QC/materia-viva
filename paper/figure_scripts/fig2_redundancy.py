#!/usr/bin/env python3
"""Figure 2 - what structure-level deduplication makes visible.

a  how many databases describe one structure
b  which pairs of databases overlap, and by how much
c  the growing identity substrate, source by source in load order
d  two large databases reporting the same formation energy
e  how far apart independent databases land, per property
f  pairwise median disagreement for the most-shared property
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
from style import (BLU, CM, CYA, DATA, GRN, GRY, LGY, ORA, PUR, RED, W2, bars,
                   save, stamp)

DEG = list(csv.DictReader((DATA / "source_degree.csv").open()))
OVL = list(csv.DictReader((DATA / "source_overlap.csv").open()))
SRC = {r["key"]: r for r in csv.DictReader((DATA / "sources.csv").open())}
SUBR = list(csv.DictReader((DATA / "substrate_growth.csv").open()))
SUBJ = json.loads((DATA / "substrate_growth.json").read_text())
SUM = json.loads((DATA / "summary.json").read_text())

HAVE_AGREE = (DATA / "agreement_per_property.csv").exists()
if HAVE_AGREE:
    PAIRS = list(csv.DictReader((DATA / "agreement_pairs.csv").open()))
    PERP = list(csv.DictReader((DATA / "agreement_per_property.csv").open()))
    SPREAD = list(csv.DictReader((DATA / "agreement_spread_samples.csv").open()))

fig = plt.figure(figsize=(W2, 14.4 * CM))
gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 1.0], width_ratios=[1.0, 1.06, 1.0],
                      hspace=0.62, wspace=0.52,
                      left=0.072, right=0.978, top=0.955, bottom=0.100)

# --------------------------------------------------- a degree distribution
ax = fig.add_subplot(gs[0, 0])
d = np.array([int(r["n_sources"]) for r in DEG])
n = np.array([int(r["n_materials"]) for r in DEG])
bars(ax.bar(d, n, width=0.82), [GRY if k == 1 else BLU for k in d], face_alpha=0.55, edge=0.0)
ax.set_yscale("log")
ax.set_xlabel("Databases describing one crystal")
ax.set_ylabel("Crystals")
ax.set_xlim(0.2, d.max() + 0.8)
ax.set_ylim(0.6, n.max() * 4)
multi = int(n[d > 1].sum())
ax.annotate(f"{multi:,} crystals carry\ntwo or more databases",
            xy=(3.4, n[d == 3][0]), xytext=(7.6, 6e5), fontsize=6.2, color=BLU,
            linespacing=1.4, ha="left",
            arrowprops=dict(arrowstyle="-", color=BLU, lw=0.5,
                            connectionstyle="arc3,rad=-0.25"))
ax.annotate(f"one crystal is described\nby {int(d.max())} databases",
            xy=(d.max(), n[-1]), xytext=(9.4, 9), fontsize=6.2, color=RED,
            linespacing=1.4, ha="left",
            arrowprops=dict(arrowstyle="-", color=RED, lw=0.5,
                            connectionstyle="arc3,rad=0.30"))
ax.text(0.98, 0.99, f"{int(n[d == 1][0]):,} single-source", transform=ax.transAxes,
        ha="right", va="top", fontsize=6.2, color=GRY)
stamp(fig, ax, "a")

# ------------------------------------------------------- b overlap heatmap
ax = fig.add_subplot(gs[0, 1])
top = sorted(SRC, key=lambda k: -int(SRC[k]["n_materials"]))[:18]
idx = {k: i for i, k in enumerate(top)}
M = np.full((len(top), len(top)), np.nan)
for r in OVL:
    a, b = r["source_a"], r["source_b"]
    if a in idx and b in idx:
        M[idx[a], idx[b]] = M[idx[b], idx[a]] = int(r["n_shared"])
cmap = LinearSegmentedColormap.from_list("ovl", ["#EAF2F8", CYA, BLU, "#0A2E4A"])
cmap.set_bad("#F5F5F5")
im = ax.imshow(np.ma.masked_invalid(M), cmap=cmap, norm=LogNorm(vmin=10, vmax=5e5))
ax.set_xticks(range(len(top)))
ax.set_yticks(range(len(top)))
ax.set_xticklabels(top, rotation=90, fontsize=5.2)
ax.set_yticklabels(top, fontsize=5.2)
ax.tick_params(length=0, pad=1.2)
for spine in ax.spines.values():
    spine.set_visible(False)
cb = fig.colorbar(im, ax=ax, fraction=0.038, pad=0.018)
cb.set_label("shared structures", fontsize=6.0)
cb.ax.tick_params(labelsize=5.8, length=1.6, width=0.5)
cb.outline.set_linewidth(0.4)
top_pair = max(OVL, key=lambda r: int(r["n_shared"]))
ax.set_title(f"largest overlap: {top_pair['source_a']} $\\cap$ {top_pair['source_b']} "
             f"= {int(top_pair['n_shared']):,}", fontsize=6.2, pad=3.5)
stamp(fig, ax, "b", dx=-0.050)

# --------------------------------------------------- c substrate growth
ax = fig.add_subplot(gs[0, 2])
rows = [r for r in SUBR if int(r["matched_onto_base"]) + int(r["matched_onto_admitted"]) >= 1000
        and r["loaded_at"]]
rows.sort(key=lambda r: r["loaded_at"])
x = np.arange(len(rows))
frac = np.array([float(r["frac_matches_onto_admitted"]) for r in rows]) * 100
size = np.array([int(r["matched_onto_base"]) + int(r["matched_onto_admitted"]) for r in rows])
sc = ax.scatter(x, frac, s=8 + 26 * np.log10(size) - 26 * 3, c=frac, cmap="YlOrBr",
                vmin=-25, vmax=110, edgecolor=ORA, linewidth=0.5, zorder=3)
ax.plot(x, frac, color=LGY, lw=0.5, zorder=1)
pooled = SUBJ["frac_matches_onto_admitted"] * 100
ax.axhline(pooled, color=GRY, lw=0.6, ls=(0, (3, 2)), zorder=2)
ax.text(len(rows) + 3.4, pooled, f"{pooled:.1f}%\npooled", fontsize=6.0, color=GRY,
        ha="right", va="center", linespacing=1.35)
for key, dy, dx in (("aflow", 9, -1.6), ("jarvis-qetb", 8, -3.2), ("qmof", -13, 0.4),
                    ("core-mof", 6, -2.6), ("cmr-static", 11, -6.0), ("oqmd", 7, -0.4),
                    ("nomad", -15, 0.5)):
    for i, r in enumerate(rows):
        if r["source"] == key:
            ax.annotate(key, xy=(i, frac[i]), xytext=(i + dx, frac[i] + dy),
                        fontsize=5.9, color="#5A3A10", ha="left",
                        arrowprops=dict(arrowstyle="-", color=GRY, lw=0.4))
ax.set_xlabel("Databases in ingestion order")
ax.set_ylabel("Matches onto structures added\nduring integration (%)")
ax.set_ylim(-8, 118)
ax.set_xlim(-1.2, len(rows) + 3.8)
ax.set_xticks([0, len(rows) // 2, len(rows) - 1])
ax.set_xticklabels(["first", "", "last"], fontsize=6.2)
stamp(fig, ax, "c")

# ------------------------------------------------------------ d,e,f agreement
if HAVE_AGREE:
    import fig2_agreement  # noqa: F401  (fills the bottom row)
    fig2_agreement.draw(fig, gs, PAIRS, PERP, SPREAD)
else:
    for j, letter in zip(range(3), "def"):
        ax = fig.add_subplot(gs[1, j])
        ax.axis("off")
        ax.text(0.5, 0.5, "cross-source agreement\n(scan running)", ha="center",
                va="center", fontsize=7, color=GRY, transform=ax.transAxes)
        stamp(fig, ax, letter)

save(fig, "fig2_redundancy")
