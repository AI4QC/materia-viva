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
CURVE = list(csv.DictReader((DATA / "substrate_curve.csv").open()))

INK = "#1A1A1A"
SOFT = "#5C5C5C"

fig = plt.figure(figsize=(W2, 15.0 * CM))
gs = fig.add_gridspec(2, 3, height_ratios=[1.00, 0.96], width_ratios=[1.20, 0.90, 0.96],
                      hspace=0.24, wspace=0.42,
                      left=0.070, right=0.980, top=0.980, bottom=0.120)

# ----------------------------------------------------------------- a schematic
# Geometry note: every string below is kept under the character budget its box
# allows at the stated font size (about 0.62 x-units per character at 6 pt), so
# nothing overruns a border. Widen a box before lengthening its text.
ax = fig.add_subplot(gs[0, :])
ax.set_xlim(0, 100)
ax.set_ylim(4.7, 42)
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


# ---- shared vertical band -------------------------------------------------
# All three columns start and end on the same two lines. Card heights and gaps
# are derived from the band rather than chosen by eye, so the columns cannot
# drift out of alignment when text is edited.
BAND_TOP, BAND_BOT = 35.0, 5.0
BAND_H = BAND_TOP - BAND_BOT
HEAD_Y, SUB_Y = 39.6, 37.4


def stack(n, heights=None, top=BAND_TOP, bottom=BAND_BOT):
    """Return (y_bottom, height) per card, filling the band with equal gaps."""
    span = top - bottom
    if heights is None:
        h = None
    else:
        h = list(heights)
    if h is None:
        gap = 1.8 if n > 4 else 1.6
        card_h = (span - gap * (n - 1)) / n
        h = [card_h] * n
    gap = (span - sum(h)) / (n - 1) if n > 1 else 0.0
    out, y = [], top
    for card_h in h:
        out.append((y - card_h, card_h))
        y -= card_h + gap
    return out


# ---- column 1: the obstacle -------------------------------------------------
heading(1.0, HEAD_Y, "The obstacle")
ax.text(1.0, SUB_Y, "one crystal, many catalogues, no shared key",
        fontsize=6.2, ha="left", color=SOFT, style="italic")

cards = [("Materials Project", "mp-149", "general"),
         ("OQMD", "oqmd-3572", "general"),
         ("Alexandria", "agm002153674", "general"),
         ("COD", "cod-1010064", "experimental"),
         ("ICSD", "icsd-44265", "experimental"),
         ("hMOF", "hMOF-31782", "framework")]
COL1, COL1W = 1.0, 22.4
slots1 = stack(len(cards))
for (name, nid, grp), (y, h) in zip(cards, slots1):
    col = GROUP_COLOUR[grp]
    card(COL1, y, COL1W, h, col)
    icon_database(ax, COL1 + 2.4, y + h / 2, 2.3, col, lw=0.55)
    ax.text(COL1 + 4.5, y + h / 2 + 0.70, name, ha="left", va="center",
            fontsize=6.0, color=INK, zorder=3)
    ax.text(COL1 + 4.5, y + h / 2 - 0.76, nid, ha="left", va="center", fontsize=5.9,
            color=col, family="monospace", zorder=3)

icon_crystal(ax, 27.6, 21.4, 4.2, SOFT, lw=0.6)
ax.text(27.6, 18.3, "the same\ncrystal", ha="center", va="top",
        fontsize=6.0, color=SOFT, linespacing=1.45)
for i, (y, h) in enumerate(slots1):
    arrow(COL1 + COL1W + 0.3, y + h / 2, 25.6, 22.6 + (2.5 - i) * 0.30, LGY, 0.5,
          rad=0.09 * (2.5 - i) / 3, scale=4.5)

# ---- column 2: the resolution ----------------------------------------------
heading(31.6, HEAD_Y, "The resolution")
ax.text(31.6, SUB_Y, "identity settled on the structure, provenance kept per value",
        fontsize=6.2, ha="left", color=SOFT, style="italic")

CARD_X, CARD_W, TEXT_X = 31.6, 29.4, 37.6
SPINE = 34.3
stages = [
    (icon_funnel, BLU, "Adapt",
     "one record per entry, with its unit,\nits method and its owned identifiers"),
    (icon_fingerprint, CYA, "Fingerprint",
     "the primitive cell reduced to one\ninvariant string, never the formula"),
    (icon_key, GRN, "Match",
     "an owned identifier first,\nthe fingerprint second, nothing else"),
    (icon_merge, ORA, "Resolve",
     "a hit annotates the crystal,\na miss joins the pool"),
]
slots2 = stack(len(stages))
ax.plot([SPINE, SPINE], [slots2[-1][0], BAND_TOP], color=LGY, lw=0.7, zorder=1,
        solid_capstyle="round")
for (glyph, col, title, text), (y, h) in zip(stages, slots2):
    card(CARD_X, y, CARD_W, h, col, alpha=0.055)
    glyph(ax, SPINE, y + h / 2 - 0.55, 3.3, col)
    ax.text(TEXT_X, y + h - 1.55, title, ha="left", va="center", fontsize=6.6,
            color=INK, fontweight="bold", zorder=3)
    ax.text(TEXT_X, y + h / 2 - 1.05, text, ha="left", va="center", fontsize=5.9,
            color=SOFT, linespacing=1.5, zorder=3)
for (ytop, _), (ybot, hbot) in zip(slots2[:-1], slots2[1:]):
    arrow(SPINE, ytop, SPINE, ybot + hbot, LGY, 0.8, scale=6.0)

# the feedback loop, the one warm element in the panel
LOOP = 70.0
BADGE_X = 67.6
loop = MPath([(CARD_X + CARD_W, slots2[3][0] + slots2[3][1] / 2), (LOOP, 8.3),
              (LOOP, 25.1), (CARD_X + CARD_W, slots2[1][0] + slots2[1][1] / 2)],
             [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4])
ax.add_patch(mpatches.FancyArrowPatch(path=loop, arrowstyle="-|>", color=ORA,
                                      linewidth=1.6, linestyle=(0, (3.4, 1.9)),
                                      mutation_scale=10, zorder=3))
# the number the loop is worth, set on the loop itself rather than in a caption
badge_y = 18.4
ax.add_patch(mpatches.FancyBboxPatch(
    (BADGE_X - 3.2, badge_y - 1.8), 6.4, 3.6,
    boxstyle="round,pad=0,rounding_size=1.5", facecolor="white",
    edgecolor=ORA, linewidth=1.1, zorder=5))
ax.text(BADGE_X, badge_y + 0.05,
        f"{SUB['frac_matches_onto_admitted']*100:.0f}%", ha="center", va="center",
        fontsize=8.6, color=ORA, fontweight="bold", zorder=6)


# ---- column 3: the corpus ---------------------------------------------------
COL3, COL3W = 71.6, 27.4
heading(COL3, HEAD_Y, "The corpus")
ax.text(COL3, SUB_Y, "one row per crystal, every value traceable",
        fontsize=6.2, ha="left", color=SOFT, style="italic")

slots3 = stack(3, heights=[15.4, 6.4, 4.2])
(py, ph), (ry, rh), (gy, gh) = slots3
arrow(CARD_X + CARD_W, py + ph - 1.2, COL3 - 0.2, py + ph - 1.2, LGY, 0.8)

card(COL3, py, COL3W, ph, PUR, alpha=0.05)
icon_database(ax, COL3 + 3.0, py + ph - 2.6, 3.4, PUR, lw=0.6)
ax.text(COL3 + 5.6, py + ph - 2.6, "one deduplicated database", ha="left",
        va="center", fontsize=6.4, color=PUR, fontweight="bold", zorder=3)
figures = [(f"{SUM['n_materials']/1e6:.2f}M", "unique crystal structures"),
           (f"{SUM['n_property_rows']/1e6:.1f}M", "property values"),
           (f"{SUM['n_properties']}", f"properties, {SUM['n_sources']} sources"),
           (f"{SUM['n_curves']/1e6:.2f}M", "stored spectra")]
for i, (big, small) in enumerate(figures):
    y = py + ph - 6.4 - i * 2.45
    ax.text(80.2, y, big, ha="right", va="center", fontsize=8.0, color=PUR,
            fontweight="bold", zorder=3)
    ax.text(81.2, y, small, ha="left", va="center", fontsize=6.0, color=INK,
            zorder=3)

arrow(COL3 + COL3W / 2, py, COL3 + COL3W / 2, ry + rh, LGY, 0.8)
card(COL3, ry, COL3W, rh, RED, alpha=0.05)
icon_merge(ax, COL3 + 3.0, ry + rh / 2, 3.2, RED)
ax.text(COL3 + COL3W / 2 + 2.4, ry + rh / 2 + 1.2,
        f"{SUM['n_multi_source_materials']:,}", ha="center", va="center",
        fontsize=8.0, color=RED, fontweight="bold", zorder=3)
ax.text(COL3 + COL3W / 2 + 2.4, ry + rh / 2 - 1.2,
        "crystals described by\ntwo or more sources", ha="center", va="center",
        fontsize=6.0, color=INK, linespacing=1.45, zorder=3)

arrow(COL3 + COL3W / 2, ry, COL3 + COL3W / 2, gy + gh, LGY, 0.8)
card(COL3, gy, COL3W, gh, GRY, alpha=0.05)
ax.text(COL3 + COL3W / 2, gy + gh / 2, "every value keeps its source,\nrecord and method",
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
stamp(fig, ax, "b", dx=-0.064)

# --------------------------------------------------- c the growing substrate
# The mechanism drawn in panel a, measured: every step is one source's
# admissions re-entering the match map, so the pool that the next source is
# matched against is the one this step just enlarged.
ax = fig.add_subplot(gs[1, 1])
base = EVO["base_merge_total"]
x = np.arange(len(CURVE) + 1)
y = np.array([base] + [int(r["substrate_after"]) for r in CURVE]) / 1e6
ax.fill_between(x, base / 1e6, y, step="post", color=(*to_rgb(ORA), 0.30),
                linewidth=0, zorder=2)
ax.step(x, y, where="post", color=ORA, lw=1.0, zorder=3)
ax.axhline(base / 1e6, color=GRY, lw=0.6, ls=(0, (3, 2)), zorder=1)
ax.set_xlim(-1.2, len(CURVE) + 1.2)
ax.set_ylim(base / 1e6 - 0.7, y[-1] / 1 * 1.0 + 0.5)
ax.set_xticks([0, len(CURVE)])
ax.set_xticklabels(["first", "last"], fontsize=6.2)
ax.set_xlabel("Sources in ingestion order")
ax.set_ylabel("Structures the next source\ncan be matched against (millions)")

ax.text(0.6, base / 1e6 - 0.30, f"{base/1e6:.2f}M at the start", fontsize=6.0,
        color=GRY, ha="left", va="top")
ax.annotate(f"{y[-1]:.2f}M", xy=(len(CURVE), y[-1]), xytext=(len(CURVE) + 0.6,
            y[-1] + 0.30), fontsize=6.8, color=ORA, fontweight="bold", ha="right")
for key, dx, dy in (("alexandria", 1.4, -0.55), ("aflow", 1.4, 0.58),
                    ("gnome", 1.6, -0.30), ("cod", -2.6, -0.95),
                    ("nomad", -1.4, -0.62)):
    for i, r in enumerate(CURVE):
        if r["source"] == key and int(r["admitted"]) > 0:
            ax.annotate(f"{key}\n$+${int(r['admitted'])/1e3:.0f}k",
                        xy=(i + 1, int(r["substrate_after"]) / 1e6),
                        xytext=(i + 1 + dx, int(r["substrate_after"]) / 1e6 + dy),
                        fontsize=5.7, color="#5A3A10", linespacing=1.35,
                        ha="left" if dx > 0 else "right", va="center",
                        arrowprops=dict(arrowstyle="-", color=GRY, lw=0.4))
stamp(fig, ax, "c", dx=-0.062)

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
stamp(fig, ax, "d", dx=-0.058)

save(fig, "fig1_architecture")
