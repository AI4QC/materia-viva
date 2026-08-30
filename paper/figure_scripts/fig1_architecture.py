#!/usr/bin/env python3
"""Figure 1 - the obstacle, the resolution, and what the corpus contains.

a  schematic: unrelated identifiers, the two-path matcher, the feedback loop
b  every database by property values contributed
c  where the 13.5M structures came from
d  how each database family's references were resolved
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from matplotlib.path import Path as MPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import (BLU, CM, CYA, DATA, GRN, GRY, GROUP_COLOUR, GROUP_LABEL, LGY,
                   ORA, PUR, RED, W2, bars, group_of, icon_crystal, icon_cycle,
                   icon_database, icon_fingerprint, icon_funnel, icon_key,
                   icon_merge, icon_plus, save, stamp)

S = list(csv.DictReader((DATA / "sources.csv").open()))
SUM = json.loads((DATA / "summary.json").read_text())
EVO = json.loads((DATA / "evolution.json").read_text())
SUB = json.loads((DATA / "substrate_growth.json").read_text())

INK = "#1A1A1A"
SOFT = "#5C5C5C"

fig = plt.figure(figsize=(W2, 15.8 * CM))
gs = fig.add_gridspec(2, 3, height_ratios=[1.00, 0.96], width_ratios=[1.20, 0.90, 0.96],
                      hspace=0.30, wspace=0.42,
                      left=0.070, right=0.980, top=0.980, bottom=0.120)

# ----------------------------------------------------------------- a schematic
# Geometry note: every string below is kept under the character budget its box
# allows at the stated font size (about 0.62 x-units per character at 6 pt), so
# nothing overruns a border. Widen a box before lengthening its text.
ax = fig.add_subplot(gs[0, :])
ax.set_xlim(0, 100)
ax.set_ylim(0, 42)
ax.set_aspect("auto")
ax.axis("off")


def card(x, y, w, h, colour, alpha=0.055, lw=0.55, radius=0.55):
    ax.add_patch(mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=(*to_rgb(colour), alpha), edgecolor=colour, linewidth=lw,
        zorder=2))


def arrow(x0, y0, x1, y1, colour=GRY, lw=0.8, rad=0.0, ls="-", scale=6.5):
    ax.add_patch(mpatches.FancyArrowPatch(
        (x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=scale, color=colour,
        lw=lw, linestyle=ls, connectionstyle=f"arc3,rad={rad}",
        shrinkA=0.5, shrinkB=0.5, zorder=4))


def heading(x, y, text, colour=INK):
    ax.text(x, y, text, fontsize=7.2, fontweight="bold", ha="left", color=colour)


# ---- column 1: the obstacle -------------------------------------------------
heading(1.0, 40.4, "The obstacle")
ax.text(1.0, 38.2, "one crystal, many catalogues, no shared key",
        fontsize=6.2, ha="left", color=SOFT, style="italic")

cards = [("Materials Project", "mp-149", "general"),
         ("OQMD", "oqmd-3572", "general"),
         ("Alexandria", "agm002153674", "general"),
         ("COD", "cod-1010064", "experimental"),
         ("ICSD", "icsd-44265", "experimental"),
         ("hMOF", "hMOF-31782", "framework")]
CARD_H, CARD_GAP = 3.5, 1.15
top = 32.9
for i, (name, nid, grp) in enumerate(cards):
    col = GROUP_COLOUR[grp]
    y = top - i * (CARD_H + CARD_GAP)
    card(1.0, y, 22.4, CARD_H, col)
    icon_database(ax, 3.4, y + CARD_H / 2, 2.3, col, lw=0.55)
    ax.text(5.5, y + CARD_H / 2 + 0.72, name, ha="left", va="center",
            fontsize=6.0, color=INK, zorder=3)
    ax.text(5.5, y + CARD_H / 2 - 0.78, nid, ha="left", va="center", fontsize=5.9,
            color=col, family="monospace", zorder=3)

icon_crystal(ax, 27.4, 21.4, 4.2, SOFT, lw=0.6)
ax.text(27.4, 18.3, "one\narrangement\nof atoms", ha="center", va="top",
        fontsize=5.9, color=SOFT, linespacing=1.45)
for i in range(len(cards)):
    y = top - i * (CARD_H + CARD_GAP) + CARD_H / 2
    arrow(23.7, y, 25.6, 22.6 + (2.5 - i) * 0.30, LGY, 0.5,
          rad=0.09 * (2.5 - i) / 3, scale=4.5)

# ---- column 2: the resolution ----------------------------------------------
heading(31.6, 40.4, "The resolution")
ax.text(31.6, 38.2, "identity settled on the structure, provenance kept per value",
        fontsize=6.2, ha="left", color=SOFT, style="italic")

CARD_X, CARD_W, TEXT_X = 31.6, 32.9, 37.6
SPINE = 34.3
ax.plot([SPINE, SPINE], [6.6, 34.6], color=LGY, lw=0.7, zorder=1,
        solid_capstyle="round")

stages = [
    (30.4, icon_funnel, BLU, "Adapt",
     "one record per entry, with its unit,\nits method and its owned identifiers"),
    (22.6, icon_fingerprint, CYA, "Fingerprint",
     "the primitive cell reduced to one\ninvariant string, never the formula"),
    (14.8, icon_key, GRN, "Match",
     "an owned identifier first,\nthe fingerprint second, nothing else"),
    (7.0, icon_merge, ORA, "Resolve",
     "a hit annotates the crystal,\na miss joins the pool"),
]
for y, glyph, col, title, body in stages:
    card(CARD_X, y - 1.9, CARD_W, 6.3, col, alpha=0.055)
    glyph(ax, SPINE, y + 1.25, 3.3, col)
    ax.text(TEXT_X, y + 2.90, title, ha="left", va="center", fontsize=6.6,
            color=INK, fontweight="bold", zorder=3)
    ax.text(TEXT_X, y + 0.45, body, ha="left", va="center", fontsize=5.9,
            color=SOFT, linespacing=1.5, zorder=3)

for y0, y1 in ((30.4 - 1.9, 22.6 + 4.4), (22.6 - 1.9, 14.8 + 4.4),
               (14.8 - 1.9, 7.0 + 4.4)):
    arrow(SPINE, y0, SPINE, y1, LGY, 0.8, scale=6.0)

# the feedback loop, the one warm element in the panel
LOOP = CARD_X + CARD_W + 2.2
loop = MPath([(CARD_X + CARD_W, 8.3), (LOOP, 8.3), (LOOP, 25.1),
              (CARD_X + CARD_W, 25.1)],
             [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4])
ax.add_patch(mpatches.FancyArrowPatch(path=loop, arrowstyle="-|>", color=ORA,
                                      linewidth=0.9, linestyle=(0, (2.6, 2.0)),
                                      mutation_scale=6.5, zorder=3))
icon_cycle(ax, LOOP, 16.7, 4.2, ORA, lw=0.8)
ax.text(CARD_X, 3.9, "every admitted crystal joins the substrate the next source",
        fontsize=6.0, color=ORA, ha="left", va="center")
ax.text(CARD_X, 1.8, f"is matched against: "
                     f"{SUB['frac_matches_onto_admitted']*100:.0f}% of "
                     f"{(SUB['matched_onto_base']+SUB['matched_onto_admitted'])/1e6:.1f}M "
                     "matches land there",
        fontsize=6.0, color=ORA, ha="left", va="center", style="italic")

# ---- column 3: the corpus ---------------------------------------------------
COL3, COL3W = 71.6, 27.4
NUM_R, LAB_L = 80.2, 81.2
heading(COL3, 40.4, "The corpus")
arrow(CARD_X + CARD_W, 32.4, COL3 - 0.2, 32.4, LGY, 0.8)

card(COL3, 19.6, COL3W, 15.4, PUR, alpha=0.05)
icon_database(ax, COL3 + 3.0, 32.4, 3.4, PUR, lw=0.6)
ax.text(COL3 + 5.6, 32.4, "one deduplicated database", ha="left", va="center",
        fontsize=6.4, color=PUR, fontweight="bold", zorder=3)
figures = [(f"{SUM['n_materials']/1e6:.2f}M", "unique crystal structures"),
           (f"{SUM['n_property_rows']/1e6:.1f}M", "property values"),
           (f"{SUM['n_properties']}", f"properties, {SUM['n_sources']} sources"),
           (f"{SUM['n_curves']/1e6:.2f}M", "stored spectra")]
for i, (big, small) in enumerate(figures):
    y = 28.6 - i * 2.45
    ax.text(NUM_R, y, big, ha="right", va="center", fontsize=8.0, color=PUR,
            fontweight="bold", zorder=3)
    ax.text(LAB_L, y, small, ha="left", va="center", fontsize=6.0, color=INK,
            zorder=3)

arrow(COL3 + COL3W / 2, 19.6, COL3 + COL3W / 2, 17.2, LGY, 0.8)
card(COL3, 10.8, COL3W, 6.4, RED, alpha=0.05)
icon_merge(ax, COL3 + 3.0, 14.0, 3.2, RED)
ax.text(COL3 + COL3W / 2 + 2.4, 15.3, f"{SUM['n_multi_source_materials']:,}",
        ha="center", va="center", fontsize=8.0, color=RED, fontweight="bold",
        zorder=3)
ax.text(COL3 + COL3W / 2 + 2.4, 12.9, "crystals described by\ntwo or more sources",
        ha="center", va="center", fontsize=6.0, color=INK, linespacing=1.45,
        zorder=3)

arrow(COL3 + COL3W / 2, 10.8, COL3 + COL3W / 2, 8.4, LGY, 0.8)
card(COL3, 4.2, COL3W, 4.2, GRY, alpha=0.05)
ax.text(COL3 + COL3W / 2, 6.3, "every value keeps its source,\nrecord and method",
        ha="center", va="center", fontsize=6.1, color=INK, linespacing=1.45,
        zorder=3)

stamp(fig, ax, "a", dx=-0.058, dy=-0.024)

# -------------------------------------------------------------- b source scale
ax = fig.add_subplot(gs[1, 0])
rows = sorted(S, key=lambda r: int(r["property_rows"]), reverse=True)
vals = np.array([int(r["property_rows"]) for r in rows])
cols = [GROUP_COLOUR[group_of(r["key"])] for r in rows]
y = np.arange(len(rows))[::-1]
bars(ax.barh(y, vals, height=0.80), cols, face_alpha=0.62, edge=0.0)
ax.set_xscale("log")
ax.set_xlim(80, 2.4e8)
ax.set_ylim(-1.4, len(rows) + 0.4)
ticks = [0, 4, 8, 13, 18, 24, 30, 36, 42, 48, 53]
ax.set_yticks([y[i] for i in ticks])
ax.set_yticklabels([rows[i]["key"] for i in ticks], fontsize=5.7)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlabel("Property values contributed", labelpad=2.0)
handles = [mpatches.Patch(facecolor=(*to_rgb(GROUP_COLOUR[g]), 0.62), edgecolor="none",
                          label=GROUP_LABEL[g])
           for g in ("general", "experimental", "specialised", "framework")]
ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.46, -0.205),
          ncol=2, frameon=False, handlelength=0.9, handleheight=0.8,
          labelspacing=0.28, columnspacing=1.0, borderpad=0.0, fontsize=5.9)
ax.text(0.985, 0.03, f"{len(rows)} databases,\n"
                     f"{np.log10(vals[0] / vals[-1]):.1f} orders of magnitude",
        transform=ax.transAxes, ha="right", va="bottom", fontsize=5.9,
        linespacing=1.5, color=SOFT)
stamp(fig, ax, "b", dx=-0.064)

# --------------------------------------------------------------- c pool origin
ax = fig.add_subplot(gs[1, 1])
base, added = EVO["base_merge_total"], EVO["admitted_during_integration"]
total = base + added
left = 0.0
for label, v, col in (("Deduplicated\nstarting pool", base, GRY),
                      ("Admitted during\nassembly", added, ORA)):
    ax.barh([1], [v / 1e6], left=left / 1e6, height=0.44,
            color=(*to_rgb(col), 0.50), edgecolor=col, linewidth=0.65)
    ax.text((left + v / 2) / 1e6, 1, f"{v/1e6:.2f}M", ha="center", va="center",
            fontsize=6.4, color=INK)
    ax.text((left + v / 2) / 1e6, 1.34, label, ha="center", va="bottom", fontsize=6.0,
            linespacing=1.35, color=SOFT)
    left += v
exp, cand = SUM["pool_dataset"]["experimental"], SUM["pool_dataset"]["candidate"]
left = 0.0
for v, col in ((exp, RED), (cand, BLU)):
    ax.barh([0], [v / 1e6], left=left / 1e6, height=0.44,
            color=(*to_rgb(col), 0.50), edgecolor=col, linewidth=0.65)
    left += v
ax.text(total / 1e6 * 0.60, 0, f"{cand/1e6:.2f}M", ha="center", va="center",
        fontsize=6.4, color=INK)
ax.annotate(f"Experimental\n{exp:,}", xy=(exp / 2e6, -0.24), xytext=(2.3, -0.94),
            fontsize=6.0, color=RED, ha="center", va="center", linespacing=1.35,
            arrowprops=dict(arrowstyle="-", color=RED, lw=0.45,
                            connectionstyle="arc3,rad=0.28"))
ax.text(total / 1e6 * 0.68, -0.94, "Computational\ncandidates", ha="center",
        va="center", fontsize=6.0, color=BLU, linespacing=1.35)
ax.set_yticks([])
ax.set_ylim(-1.62, 2.10)
ax.set_xlim(0, total / 1e6 * 1.02)
ax.set_xlabel("Unique structures (millions)")
ax.spines["left"].set_visible(False)
ax.text(0.5, -0.225, f"assembly enlarged the deduplicated\npool by {added/base*100:.0f}%",
        transform=ax.transAxes, ha="center", va="top", fontsize=6.1, style="italic",
        linespacing=1.4, color=SOFT)
stamp(fig, ax, "c", dx=-0.048)

# ------------------------------------------------------------ d match routes
ax = fig.add_subplot(gs[1, 2])
order = ["general", "experimental", "specialised", "framework"]
agg = {g: np.zeros(3) for g in order}
for r in S:
    agg[group_of(r["key"])] += [int(r["refs_id"]), int(r["refs_hash"]), int(r["refs_origin"])]
x = np.arange(len(order))
bottom = np.zeros(len(order))
for i, (lab, col) in enumerate(zip(["owned identifier", "fingerprint", "own entry"],
                                   [GRN, CYA, ORA])):
    v = np.array([agg[g][i] for g in order]) / 1e6
    ax.bar(x, v, bottom=bottom, width=0.58, label=lab,
           color=(*to_rgb(col), 0.50), edgecolor=col, linewidth=0.65)
    bottom += v
ax.set_xticks(x)
ax.set_xticklabels(["General\nDFT", "Exp.\ncatalogues", "Specialised\nlibraries",
                    "Porous\nframeworks"], fontsize=6.0, linespacing=1.3)
ax.set_ylabel("References (millions)")
ax.set_ylim(0, bottom.max() * 1.22)
ax.legend(frameon=False, loc="upper right", bbox_to_anchor=(1.04, 1.03),
          handlelength=0.9, handleheight=0.8, labelspacing=0.28, borderpad=0.0,
          fontsize=6.1)
tot_id = sum(agg[g][0] for g in order)
tot_hash = sum(agg[g][1] for g in order)
ax.text(0.5, -0.225, f"{tot_id/1e6:.1f}M references resolved by identifier,\n"
                     f"{tot_hash/1e6:.1f}M by fingerprint alone",
        transform=ax.transAxes, ha="center", va="top", fontsize=6.1, style="italic",
        linespacing=1.4, color=SOFT)
stamp(fig, ax, "d", dx=-0.058)

save(fig, "fig1_architecture")
