#!/usr/bin/env python3
"""Figure 1 - the obstacle, the resolution, and what the corpus contains.

a  schematic: unrelated identifiers, the two-path matcher, the feedback loop
b  every database by property values contributed
c  how much of each database no other database holds
d  how each database family resolved its references
e  matches landing on structures admitted during assembly
f  how many databases describe one crystal
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
from style import OUT as _OUT  # noqa: F401
from style import CM, DATA, W2, bars, group_of, save, stamp, GROUP_LABEL, icon_database, icon_crystal, icon_funnel, icon_fingerprint, icon_key, icon_merge, icon_plus, icon_cycle
from figkit import (ACCENT, boxed_text as _bt, ACCENT_SOFT, AGREE, BLU, CRITERION, CYA, ELL,
                    FAMILY, GRN, GRY, INK, LGY, LIGHT, LONG, MECHANISM,
                    MID, ORA, PALE, PROPERTY, PUR, RED, ROUTE, SHARED, SOFT,
                    TIER as TIER_COLOUR, boxed_text)
GROUP_COLOUR = FAMILY

S = list(csv.DictReader((DATA / "sources.csv").open()))
SUM = json.loads((DATA / "summary.json").read_text())
EVO = json.loads((DATA / "evolution.json").read_text())
SUB = json.loads((DATA / "substrate_growth.json").read_text())
CURVE = list(csv.DictReader((DATA / "substrate_curve.csv").open()))

INK = "#1A1A1A"
SOFT = "#5C5C5C"

fig = plt.figure(figsize=(W2, 17.9 * CM))
# Panel a is a drawing, not a plot: it gets its own near-full-width gridspec so
# it is not indented by the tick labels of the panels underneath it.
_ga = fig.add_gridspec(1, 1, left=0.013, right=0.997, top=0.992, bottom=0.618)
_gb = fig.add_gridspec(2, 1, left=0.060, right=0.992, top=0.566, bottom=0.052,
                       hspace=0.36)
_r1 = _gb[0].subgridspec(1, 2, wspace=0.24, width_ratios=[1.52, 1.0])
_r2 = _gb[1].subgridspec(1, 3, wspace=0.38)


# ----------------------------------------------------------------- a schematic
# Geometry note: every string below is kept under the character budget its box
# allows at the stated font size (about 0.62 x-units per character at 6 pt), so
# nothing overruns a border. Widen a box before lengthening its text.
ax = fig.add_subplot(_ga[0])
ax.set_xlim(0, 100)
ax.set_ylim(4.6, 41.2)
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

# A real crystal, not an illustration: CaMg2Sb2 carries 21 references from 17
# databases in the assembled record. Six of them are shown; the identifiers are
# the ones those databases actually publish for it.
cards = [("Materials Project", "mp-aaaaaodx", "general"),
         ("OQMD", "oqmd-16944", "general"),
         ("Alexandria", "agm003194148", "general"),
         ("ICSD", "icsd-100045", "experimental"),
         ("COD", "cod-7221200", "experimental"),
         ("SNUMAT", "SM-7783", "specialised")]
COL1, COL1W = 1.0, 22.4
slots1 = stack(len(cards))
for (name, nid, grp), (y, h) in zip(cards, slots1):
    col = GROUP_COLOUR[grp]
    card(COL1, y, COL1W, h, col)
    icon_database(ax, COL1 + 2.4, y + h / 2, 2.3, col, lw=0.55)
    _bt(ax, COL1, y, COL1W, h, name, nid, colour=col, title_fs=6.0, sub_fs=5.7,
        gap_pt=1.8, pad_pt=2.2, draw_box=False, cx=(COL1 + 4.6 + COL1W) / 2, z=3,
        title_weight="normal", sub_colour=col, sub_family="monospace")

icon_crystal(ax, 27.6, 21.4, 4.2, SOFT, lw=0.6)
ax.text(27.6, 18.3, "one crystal:\nCaMg$_2$Sb$_2$", ha="center", va="top",
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
TEXT_CX = (TEXT_X + CARD_X + CARD_W) / 2
for (glyph, col, title, text), (y, h) in zip(stages, slots2):
    card(CARD_X, y, CARD_W, h, col, alpha=0.055)
    glyph(ax, SPINE, y + h / 2, 3.3, col)
    _bt(ax, CARD_X, y, CARD_W, h, title, text, colour=col, title_fs=6.6,
        sub_fs=5.9, gap_pt=3.0, pad_pt=3.4, draw_box=False, cx=TEXT_CX, z=3)
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

slots3 = stack(3, heights=[14.6, 8.0, 4.2])
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
ax.text(COL3 + COL3W / 2 + 2.4, ry + rh - 2.4,
        f"{SUM['n_multi_source_materials']:,}", ha="center", va="center",
        fontsize=8.2, color=RED, fontweight="bold", zorder=3)
ax.text(COL3 + COL3W / 2 + 2.4, ry + 2.2,
        "crystals described by\ntwo or more sources", ha="center", va="center",
        fontsize=6.0, color=INK, linespacing=1.5, zorder=3)

arrow(COL3 + COL3W / 2, ry, COL3 + COL3W / 2, gy + gh, LGY, 0.8)
card(COL3, gy, COL3W, gh, GRY, alpha=0.05)
ax.text(COL3 + COL3W / 2, gy + gh / 2, "every value keeps its source,\nrecord and method",
        ha="center", va="center", fontsize=6.1, color=INK, linespacing=1.45,
        zorder=3)

stamp(fig, ax, "a", dx=-0.010, dy=-0.018)

# -------------------------------------------------------------- b source scale
ax = fig.add_subplot(_r1[0])
rows = sorted(S, key=lambda r: int(r["property_rows"]), reverse=True)
vals = np.array([int(r["property_rows"]) for r in rows])
cols = [GROUP_COLOUR[group_of(r["key"])] for r in rows]
y = np.arange(len(rows))[::-1]
bars(ax.barh(y, vals, height=0.80), cols, face_alpha=0.62, edge=0.0)
ax.set_xscale("log")
ax.set_xlim(80, 2.4e8)
ax.set_ylim(-1.4, len(rows) + 0.4)
ticks = [0, 4, 8, 13, 18, 24, 30, 36, 42, 48, 53]
def _short(k, n=17):
    return k if len(k) <= n else k[:n - 1] + "\u2026"
ax.set_yticks([y[i] for i in ticks])
ax.set_yticklabels([_short(rows[i]["key"]) for i in ticks], fontsize=5.7)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlabel("Property values contributed", labelpad=1.6)
handles = [mpatches.Patch(facecolor=(*to_rgb(GROUP_COLOUR[g]), 0.62), edgecolor="none",
                          label=GROUP_LABEL[g])
           for g in ("general", "experimental", "specialised", "framework")]
ax.legend(handles=handles, loc="lower right", bbox_to_anchor=(1.01, -0.015),
          ncol=1, frameon=False, handlelength=0.85, handleheight=0.8,
          labelspacing=0.36, borderpad=0.0, fontsize=5.8)
stamp(fig, ax, "b", dx=-0.058)

# ------------------------------------------ c how much of a database is its own
# The question no database can answer from the inside: of the crystals I hold,
# how many does nobody else hold? Order-independent, unlike the admission
# figures, because it asks about the finished record rather than about when a
# source arrived.
EXC = list(csv.DictReader((DATA / "source_exclusivity.csv").open()))
ax = fig.add_subplot(_r1[1])
xv = np.array([int(r["n_materials"]) for r in EXC], dtype=float)
yv = np.array([float(r["frac_sole"]) for r in EXC]) * 100
cv = [GROUP_COLOUR[group_of(r["source"])] for r in EXC]
ax.scatter(xv, yv, s=16, c=cv, alpha=0.80, edgecolor="white", linewidth=0.35,
           zorder=3)
ax.set_xscale("log")
ax.set_xlim(1.2e3, 1.4e7)
ax.set_ylim(-7, 110)
ax.set_yticks([0, 25, 50, 75, 100])
ax.set_xlabel("Crystals the database annotates")
ax.set_ylabel("Held by no other database (%)")
ax.grid(axis="y", lw=0.3, color="#EFEFEF"); ax.set_axisbelow(True)
LAB = {"alexandria": (0.06, -13, "left"), "elementa": (-0.02, 9, "center"),
       "gnome": (-0.20, -13, "right"), "deem-zeolites": (-0.34, 8, "right"),
       "hmof": (0.16, 8, "left"), "nomad": (0.10, -12, "left"),
       "materials-project": (0.20, 0, "left"), "materiae": (-0.58, -5, "right"),
       "cod": (0.02, 11, "center"), "icsd": (-0.92, 3, "right")}
_at = {r["source"]: (int(r["n_materials"]), float(r["frac_sole"]) * 100) for r in EXC}
for key, (dx, dy, ha) in LAB.items():
    x0, y0 = _at[key]
    ax.annotate(key, xy=(x0, y0), xytext=(x0 * 10 ** dx, y0 + dy), fontsize=5.4,
                color=GROUP_COLOUR[group_of(key)], ha=ha, va="center", zorder=5,
                arrowprops=dict(arrowstyle="-", color=LGY, lw=0.4, shrinkA=0.5,
                                shrinkB=2.0))
stamp(fig, ax, "c", dx=-0.062)

# ------------------------------------- e matches onto structures admitted later
SUBR = [r for r in csv.DictReader((DATA / "substrate_growth.csv").open())
        if int(r["matched_onto_base"]) + int(r["matched_onto_admitted"]) >= 1000
        and r["loaded_at"]]
SUBR.sort(key=lambda r: r["loaded_at"])
ax = fig.add_subplot(_r2[1])
x = np.arange(len(SUBR))
frac = np.array([float(r["frac_matches_onto_admitted"]) for r in SUBR]) * 100
size = np.array([int(r["matched_onto_base"]) + int(r["matched_onto_admitted"])
                 for r in SUBR])
ax.scatter(x, frac, s=6 + 22 * np.log10(size) - 22 * 3, c=frac, cmap="YlOrBr",
           vmin=-25, vmax=110, edgecolor=ORA, linewidth=0.45, zorder=3)
ax.plot(x, frac, color=LGY, lw=0.5, zorder=1)
pooled = SUB["frac_matches_onto_admitted"] * 100
ax.axhline(pooled, color=GRY, lw=0.6, ls=(0, (3, 2)), zorder=2)
ax.text(len(SUBR) - 0.5, pooled + 4, f"{pooled:.0f}% pooled", fontsize=6.0,
        color=GRY, ha="right")
for key, dx, dy in (("aflow", -1.0, 12), ("core-mof", -3.0, 6), ("nomad", -1.0, -16)):
    for i, r in enumerate(SUBR):
        if r["source"] == key:
            ax.annotate(key, xy=(i, frac[i]), xytext=(i + dx, frac[i] + dy),
                        fontsize=5.8, color="#5A3A10", ha="right" if dx < 0 else "left",
                        arrowprops=dict(arrowstyle="-", color=GRY, lw=0.4))
ax.set_xlabel("Databases in ingestion order")
ax.set_ylabel("Matches onto admitted\nstructures (%)")
ax.set_ylim(-10, 118)
ax.set_xlim(-1.0, len(SUBR) + 0.5)
ax.set_xticks([0, len(SUBR) - 1])
ax.set_xticklabels(["first", "last"], fontsize=6.2)
stamp(fig, ax, "e", dx=-0.068, dy=0.004)

# ----------------------------------------------------- f databases per crystal
DEG = list(csv.DictReader((DATA / "source_degree.csv").open()))
ax = fig.add_subplot(_r2[2])
d = np.array([int(r["n_sources"]) for r in DEG])
n = np.array([int(r["n_materials"]) for r in DEG])
o = np.argsort(d); d, n = d[o], n[o]
bars(ax.bar(d, n, width=0.86), [GRY if k == 1 else BLU for k in d],
     face_alpha=0.55, edge=0.0)
ax.set_yscale("log")
ax.set_xlabel("Databases describing one crystal")
ax.set_ylabel("Crystals")
ax.set_xlim(0, d.max() + 1)
ax.set_ylim(0.6, n.max() * 14)
multi = int(n[d >= 2].sum())
ax.annotate(f"{multi/1e6:.2f}M carry\ntwo or more", xy=(3.3, n[d == 3][0]),
            xytext=(6.2, n.max() * 0.9), fontsize=6.0, color=BLU, linespacing=1.35,
            va="center", arrowprops=dict(arrowstyle="-", color=BLU, lw=0.5,
                                         connectionstyle="arc3,rad=-0.22"))
stamp(fig, ax, "f", dx=-0.068, dy=0.004)

# ------------------------------------------------------------ d match routes
ax = fig.add_subplot(_r2[0])
order = ["general", "experimental", "specialised", "framework"]
agg = {g: np.zeros(3) for g in order}
for r in S:
    agg[group_of(r["key"])] += [int(r["refs_id"]), int(r["refs_hash"]), int(r["refs_origin"])]
x = np.arange(len(order))
bottom = np.zeros(len(order))
for i, (lab, col) in enumerate(zip(["owned identifier", "fingerprint", "own entry"],
                                   [GRN, CYA, ORA])):
    v = np.array([agg[g][i] for g in order]) / 1e6
    ax.bar(x, v, bottom=bottom, width=0.60, label=lab,
           color=(*to_rgb(col), 0.50), edgecolor=col, linewidth=0.65)
    bottom += v
ax.set_xticks(x)
ax.set_xticklabels(["General\nDFT", "Exp.\ncatalogues", "Specialised\nlibraries",
                    "Porous\nframeworks"], fontsize=6.0, linespacing=1.3)
ax.set_ylabel("References (millions)")
ax.set_ylim(0, bottom.max() * 1.30)
ax.legend(frameon=False, loc="upper right", bbox_to_anchor=(1.05, 1.06),
          handlelength=0.9, handleheight=0.8, labelspacing=0.26, borderpad=0.0,
          fontsize=6.0)
stamp(fig, ax, "d", dx=-0.068, dy=0.004)

save(fig, "fig_record")
