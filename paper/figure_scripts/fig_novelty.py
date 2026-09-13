#!/usr/bin/env python3
"""Figure 5 - what a claim of novelty is measured against.

a  one generated structure under four identity criteria            [schematic]
b  how much of each generated set is still new as the reference grows
c  which databases actually hold the structures that were called new
d  the strictest criterion at which each set is already in the record

Panels b-d are the real audit: paper/figure_scripts/extract_novelty_audit.py
over scripts/novelty/audit_generated.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import to_rgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import CM, W2, bars, save, stamp
from figkit import (ACCENT, ACCENT_SOFT, AGREE, BLU, CRITERION, CYA, ELL,
                    FAMILY, GRN, GRY, INK, LGY, LIGHT, LONG, MECHANISM,
                    MID, ORA, PALE, PROPERTY, PUR, RED, ROUTE, SHARED, SOFT,
                    TIER as TIER_COLOUR, boxed_text)
GROUP_COLOUR = FAMILY

import json
from style import DATA as _DATA, SOURCE_GROUP

AUDIT = json.loads((_DATA / "novelty_audit.json").read_text())
SETS = AUDIT["sets"]
REFERENCES = AUDIT["reference_tiers"]

#: the sets drawn, in the order they are argued about, with the label used
#: the sets the ladder is drawn for. The property-conditioned MatterGen run
#: (ml_bulk_modulus = 400 GPa) lands within a point of the unconditional one on
#: every rung, so it is kept in novelty_audit.json for the SI and not repeated here.
SHOWN = [("GNoME", "GNoME"),
         ("MatterGen-local-base", "MatterGen"),
         ("CrystaLLM", "CrystaLLM"),
         ("CDVAE", "CDVAE"),
         ("FTCP", "FTCP"),
         ("Ion-Exchange", "ion exchange"),
         ("Random", "random enumeration")]
SHOWN_B = [l for _, l in SHOWN]
#: the two template baselines are dashed, so that the pairs which land on the
#: same value (CrystaLLM with ion exchange, FTCP with random enumeration) stay
#: separable where the curves cross
LINE_COLOUR = {"GNoME": ACCENT, "MatterGen": MECHANISM,
               "CrystaLLM": FAMILY["specialised"], "CDVAE": ACCENT_SOFT,
               "FTCP": PUR, "ion exchange": FAMILY["experimental"],
               "random enumeration": MID}
DASHED = {"ion exchange", "random enumeration"}

#: the ladder, loosest criterion last; a set is filed under the strictest one
#: that already finds it
RUNGS = [("exact structure", "exact"),
         ("composition and\nspace group", "comp_sg"),
         ("composition", "comp"),
         ("stoichiometry pattern\nand space group", "proto_sg"),
         ("found under none", "none")]
RUNG_COLOUR = [FAMILY["experimental"], MECHANISM, FAMILY["framework"],
               ACCENT_SOFT, FAMILY["specialised"]]

fig = plt.figure(figsize=(W2, 11.3 * CM))
# Rows placed by hand; the gap under the schematic only has to hold one panel
# letter, and the row beneath it only its own tick labels.
_g0 = fig.add_gridspec(1, 1, left=0.020, right=0.990, top=0.982, bottom=0.540)
_g1 = fig.add_gridspec(1, 3, left=0.072, right=0.986, top=0.494, bottom=0.128,
                       wspace=0.50, width_ratios=[1.24, 0.90, 1.04])
_outer, _r1 = [None, None], _g1

# --------------------------------------------- a the criteria, drawn
ax = fig.add_subplot(_g0[0])
ax.set_xlim(0, 100); ax.set_ylim(3.9, 33.6); ax.axis("off")
INK, SOFT = "#1A1A1A", "#6B6E70"

CELL = np.array([[-4.6, -3.1], [3.1, -4.1], [4.6, 3.1], [-3.1, 4.1]])
BASIS = np.array([[0.0, 0.0], [-2.2, 0.8], [1.9, 1.2], [0.9, -2.1], [-1.4, -1.7]])


def mini(cx, cy, cols, scale=1.0, shear=0.0, disorder=None, faded=False):
    """A small crystal: cell outline plus a basis, both in data coordinates."""
    M = np.array([[1.0, shear], [0.0, 1.0]])
    cell = (CELL * scale) @ M.T
    a = 0.30 if faded else 1.0
    ax.add_patch(mpatches.Polygon(cell + (cx, cy), closed=True,
                                  facecolor=(*to_rgb(CYA), 0.05 * a),
                                  edgecolor=(*to_rgb(CYA), 0.9 * a), lw=0.8, zorder=3))
    for k, b in enumerate((BASIS * scale) @ M.T):
        col = cols[k % len(cols)]
        if disorder is not None and k == disorder:
            w1 = mpatches.Wedge((cx + b[0], cy + b[1]), 1.02, 90, 270,
                                facecolor=(*to_rgb(cols[0]), 0.85), edgecolor="white",
                                lw=0.6, zorder=5)
            w2 = mpatches.Wedge((cx + b[0], cy + b[1]), 1.02, 270, 450,
                                facecolor=(*to_rgb(cols[1]), 0.85), edgecolor="white",
                                lw=0.6, zorder=5)
            ax.add_patch(w1); ax.add_patch(w2)
        else:
            ax.add_patch(mpatches.Circle((cx + b[0], cy + b[1]), 1.02,
                                         facecolor=(*to_rgb(col), 0.85 * a),
                                         edgecolor="white", lw=0.6, zorder=5))


def verdict(x, y, text, colour):
    ax.add_patch(mpatches.FancyBboxPatch(
        (x - 5.0, y - 1.35), 10.0, 2.7, boxstyle="round,pad=0.10,rounding_size=1.2",
        linewidth=0.0, facecolor=(*to_rgb(colour), 0.16), zorder=4))
    ax.text(x, y, text, ha="center", va="center", fontsize=5.6, color=colour,
            fontweight="bold", zorder=6)


A, B = BLU, PUR
# the query, on the left
ax.text(9.0, 31.4, "a generated structure", ha="center", fontsize=6.2,
        color=INK, fontweight="bold")
mini(9.0, 20.0, [A, B, A, B, A], scale=1.30)
ax.text(9.0, 10.6, "is it already in the record?", ha="center", fontsize=5.4, color=SOFT)

COLS = [
    ("exact structure", "no record matches atom\nfor atom", [A, B, A, B, A],
     dict(scale=1.30, shear=0.0), GRN, "new", False),
    ("primitive cell and\ncomposition", "the same crystal in a\ndifferent setting",
     [A, B, A, B, A], dict(scale=1.30, shear=0.34), BLU, "not new", True),
    ("prototype and\ndecoration", "the same framework,\ndifferent occupants",
     [B, A, B, A, B], dict(scale=1.30, shear=0.0), ORA, "not new", True),
    ("ordered approximant", "an ordered model of a\ndisordered phase",
     [A, B, A, B, A], dict(scale=1.30, shear=0.0, disorder=1), RED, "not new", True),
]
X0, DX = 30.0, 17.6
for i, (title, sub_, cols, kw, colour, v, matched) in enumerate(COLS):
    x = X0 + i * DX
    # the criteria are numbered so the text can name them without repeating them
    ax.add_patch(mpatches.Circle((x - 7.9, 31.4), 1.20, facecolor=INK,
                                 edgecolor="none", zorder=6))
    ax.text(x - 7.9, 31.4, str(i + 1), ha="center", va="center", fontsize=5.4,
            color="white", fontweight="bold", zorder=7)
    ax.text(x, 31.4, title, ha="center", va="center", fontsize=5.9, color=INK,
            fontweight="bold", linespacing=1.3)
    if matched:
        mini(x, 20.0, cols, **kw)
    else:
        mini(x, 20.0, cols, scale=kw["scale"], faded=True)
        ax.plot([x - 5.4, x + 5.4], [14.6, 25.4], color=RED, lw=1.0, zorder=7)
        ax.plot([x - 5.4, x + 5.4], [25.4, 14.6], color=RED, lw=1.0, zorder=7)
    ax.text(x, 12.0, sub_, ha="center", va="center", fontsize=5.1, color=SOFT,
            linespacing=1.35)
    verdict(x, 6.2, v, colour)
    ax.annotate("", xy=(x - 6.4, 20.0), xytext=(x - DX + 6.6 if i else 15.2, 20.0),
                zorder=2,
                arrowprops=dict(arrowstyle="-|>", color=LGY if i else SOFT,
                                lw=0.8, mutation_scale=6, shrinkA=1.0, shrinkB=1.0))
ax.plot([22.0, 22.0], [4.4, 29.2], color=LGY, lw=0.6, ls=(0, (2.4, 2.0)), zorder=1)
stamp(fig, ax, "a", dx=-0.014, dy=0.002)

# ---------------------------------------- b what widening the search does
# Left of the rule the criterion is fixed (the exact structure) and the
# reference widens; right of it the reference is fixed (all 55 sources) and the
# criterion loosens to any of the four. Each step only adds a test, so a set can
# only lose crystals along the axis. Widening the reference costs a few points.
# Loosening the criterion is what empties the claim.
ax = fig.add_subplot(_r1[0])
NREF = len(REFERENCES)
x = np.arange(NREF + 1)
for key, lab in [(k, l) for k, l in SHOWN if l in SHOWN_B]:
    S_ = SETS[key]
    v = np.concatenate([np.array(S_["tier_novelty"]),
                        [S_["ladder"]["none"] / S_["n"] * 100]])
    dashed = lab in DASHED
    z = 4 if lab in ("GNoME", "MatterGen") else 3
    ax.plot(x[:NREF], v[:NREF], marker="o", ms=3.0, lw=1.0, color=LINE_COLOUR[lab],
            ls=(0, (2.6, 1.6)) if dashed else "-", zorder=z, label=lab)
    ax.plot(x[NREF - 1:], v[NREF - 1:], marker="o", ms=3.0, lw=1.0,
            color=LINE_COLOUR[lab], ls=(0, (2.6, 1.6)) if dashed else "-", zorder=z)
ax.axvline(NREF - 1, color=LGY, lw=0.6, ls=(0, (2.4, 2.0)), zorder=1)
# four of the five curves land on the floor within a point of each other, so the
# names go in a legend in the empty lower left rather than on the curve ends
ax.legend(frameon=False, fontsize=5.1, loc="lower left", bbox_to_anchor=(-0.02, 0.0),
          handlelength=1.2, labelspacing=0.26, borderpad=0.0, handletextpad=0.45)
ax.set_xticks(x)
ax.set_xticklabels(list(REFERENCES) + ["any of the\nfour criteria"],
                   fontsize=5.1, linespacing=1.25)
ax.get_xticklabels()[-1].set_color(MECHANISM)
ax.set_ylabel("Still reported as new (%)")
ax.set_ylim(-4, 114)
ax.set_xlim(-0.24, len(x) - 0.16)
ax.set_yticks([0, 20, 40, 60, 80, 100])
ax.text(-0.15, 108.5, "the reference widens", fontsize=5.2, color=SOFT,
        style="italic", ha="left", va="center")
ax.text(len(x) - 0.85, 108.5, "the criterion loosens", fontsize=5.2,
        color=MECHANISM, style="italic", ha="right", va="center")
ax.grid(axis="y", lw=0.3, color="#EFEFEF"); ax.set_axisbelow(True)
stamp(fig, ax, "b", dx=-0.072, dy=0.004)

# --------------------------------------------- d novelty under each criterion
# Same sets, same reference, four criteria. Each bar is filed under the
# strictest criterion that already finds the crystal somewhere in the record.
ax = fig.add_subplot(_r1[2])
y = np.arange(len(SHOWN))[::-1]
for i, (key, lab) in enumerate(SHOWN):
    L = SETS[key]["ladder"]
    n = SETS[key]["n"]
    left = 0.0
    for (rung, field), col in zip(RUNGS, RUNG_COLOUR):
        v = L[field] / n * 100
        ax.barh([y[i]], [v], left=[left], height=0.68,
                color=(*to_rgb(col), 0.70), edgecolor="white", linewidth=0.6,
                zorder=3)
        left += v
    ax.text(-1.6, y[i], lab, ha="right", va="center", fontsize=5.8, color=INK,
            linespacing=1.25)
ax.set_yticks([]); ax.set_xlim(0, 100); ax.set_ylim(-1.05, len(SHOWN) - 0.35)
ax.set_xlabel("Generated crystals (%)")
for sp in ("left", "right", "top"):
    ax.spines[sp].set_visible(False)
# the rungs are numbered as in panel a, so the key can be a strip of digits and
# the caption can carry the wording
ax.legend([mpatches.Patch(facecolor=(*to_rgb(c), 0.70)) for c in RUNG_COLOUR],
          ["1", "2", "3", "4", "new"],
          frameon=False, fontsize=5.6, loc="lower center",
          bbox_to_anchor=(0.5, -0.028), ncol=5, handlelength=0.8,
          handleheight=0.8, labelspacing=0.2, columnspacing=0.9,
          handletextpad=0.35, borderpad=0.0)
stamp(fig, ax, "d", dx=-0.072, dy=0.004)

# -------------------------------------------------- c where the matches are
# Pooled over the six sample sets: the databases that hold the crystals a
# strict test still calls a match. Materials Project, the reference these
# claims are usually made against, is near the bottom.
ax = fig.add_subplot(_r1[1])
POOLED = ("MatterGen-local-base", "MatterGen-local-bulk400", "CrystaLLM",
          "CDVAE", "Ion-Exchange", "Random", "FTCP")
pool = {}
for key in POOLED:
    for src, cnt in SETS[key]["sources_of_exact_matches"].items():
        pool[src] = pool.get(src, 0) + cnt
order = sorted(pool, key=lambda k: -pool[k])[:11]
yy = np.arange(len(order))[::-1]
vals = np.array([pool[k] for k in order], dtype=float)
cols = [FAMILY[SOURCE_GROUP.get(k, "specialised")] for k in order]
bars(ax.barh(yy, vals, height=0.66), cols, face_alpha=0.62, edge=0.0)
for yi, v in zip(yy, vals):
    ax.text(v + max(vals) * 0.025, yi, f"{v:.0f}", va="center", ha="left",
            fontsize=5.6, color=GRY)
ax.set_yticks(yy)
ax.set_yticklabels([k if len(k) <= 18 else k[:17] + "\u2026" for k in order],
                   fontsize=5.6)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlim(0, max(vals) * 1.20)
ax.set_xlabel("Generated crystals held")
ax.text(max(vals) * 1.18, yy[-1] - 0.95,
        f"pooled over {sum(SETS[k]['n'] for k in POOLED):,} generated crystals",
        ha="right", va="center", fontsize=5.4, color=SOFT, style="italic")
ax.set_ylim(-1.55, len(order) - 0.35)
stamp(fig, ax, "c", dx=-0.072, dy=0.004)

save(fig, "fig_novelty")
