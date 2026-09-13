#!/usr/bin/env python3
"""Draft Figure 3 - the model, and how it performs.

a  the architecture, drawn rather than described
b  JARVIS-DFT 2021 against the published leaders          [PLACEHOLDER]
c  Matbench small-data tasks against the leaderboard      [PLACEHOLDER]
d  test error on every task of the corpus                 [PLACEHOLDER]

!!!  PLACEHOLDER block below is invented. Replace with the run records and
delete this banner. The figure carries no marking of its own.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.path import Path as MPath
from matplotlib.colors import to_rgb, LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import CM, W2, bars, save, stamp
from figkit import (ACCENT, ACCENT_SOFT, BLU, CYA, GRN, GRY, INK, LGY, LIGHT,
                    MECHANISM, ORA, PALE, PUR, RED, SOFT, TIER as TIER_COLOUR,
                    ELL, boxed_text)

print("\n  *** fig_model.py: panels b-d are PLACEHOLDER ***\n")

# ======================================================================
# PLACEHOLDER
# ======================================================================
JARVIS_TASKS = ["formation\nenergy", "OPT\ngap", "total\nenergy", "MBJ\ngap", "hull\ndistance"]
JARVIS = {"iComFormer": [0.0272, 0.122, 0.0288, 0.260, 0.047],
          "eComFormer": [0.0284, 0.124, 0.0320, 0.280, 0.044],
          "PRDNet":     [0.0320, 0.140, 0.0320, 0.267, 0.041],
          "CGTNet":     [0.0268, 0.118, 0.0281, 0.252, 0.040]}
MB_TASKS = ["jdft2d", "phonons"]
MB = {"ALIGNN": ([43.42, 29.54], [0.0, 0.0]),
      "leaderboard": ([33.19, 28.80], [0.0, 0.0]),
      "CGTNet": ([32.60, 27.90], [1.10, 1.60])}
_rng = np.random.default_rng(11)
_N = 176
PH_NTRAIN = 10 ** _rng.uniform(2.4, 7.0, _N)
PH_NMAE = np.clip(0.92 * (PH_NTRAIN / 1e3) ** -0.17 * _rng.lognormal(0, 0.26, _N), 0.04, 1.6)
PH_TIER = _rng.choice([1, 2, 3, 4], _N, p=[0.34, 0.24, 0.26, 0.16])
PARAMS = 17.3
# ======================================================================

L_CMAP = ELL
TIER_COL = TIER_COLOUR

fig = plt.figure(figsize=(W2, 13.0 * CM))
_outer = fig.add_gridspec(2, 1, height_ratios=[1.16, 1.00], hspace=0.22,
                          left=0.056, right=0.988, top=0.985, bottom=0.090)
_r1 = _outer[1].subgridspec(1, 3, wspace=0.58, width_ratios=[1.05, 0.68, 1.18])

# =======================================================================
# a  architecture
# =======================================================================
ax = fig.add_subplot(_outer[0])
ax.set_xlim(0, 100); ax.set_ylim(4.4, 30.2); ax.axis("off")


def txt(x, y, t, fs=5.8, c=INK, w="normal", ha="center", va="center", rot=0):
    ax.text(x, y, t, ha=ha, va=va, fontsize=fs, color=c, fontweight=w,
            rotation=rot, linespacing=1.3, zorder=8)


def panel_title(x, y, t):
    txt(x, y, t, 6.4, INK, "bold")


def arrow(x0, y0, x1, y1, c=SOFT, lw=0.9, rad=0.0, z=6, ls="-"):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0), zorder=z,
                arrowprops=dict(arrowstyle="-|>", color=c, lw=lw, linestyle=ls,
                                mutation_scale=6.5, shrinkA=1.0, shrinkB=1.0,
                                connectionstyle=f"arc3,rad={rad}"))


# ---------------------------------------------------------------- crystal
CX, CY = 11.0, 18.0
panel_title(CX, 28.4, "periodic crystal and its graph")
cell = np.array([[-6.4, -4.2], [4.2, -5.6], [6.4, 4.2], [-4.2, 5.6]])
for dx, dy in ((-10.6, -1.4), (10.6, 1.4)):
    ax.add_patch(mpatches.Polygon(cell + (CX + dx, CY + dy), closed=True, fill=False,
                                  edgecolor=LGY, lw=0.5, zorder=1))
ax.add_patch(mpatches.Polygon(cell + (CX, CY), closed=True,
                              facecolor=(*to_rgb(CYA), 0.06), edgecolor=CYA,
                              lw=0.9, zorder=2))
sites = np.array([[0.0, 0.0], [-3.2, 1.0], [2.6, 1.6], [1.2, -2.8], [-2.0, -2.4],
                  [4.0, -0.4], [-1.0, 3.4]])
kinds = [0, 1, 1, 0, 1, 0, 1]
img = np.array([[-9.6, -1.4], [9.6, 1.4], [-2.2, 9.8], [2.2, -9.8]])
ax.add_patch(mpatches.Circle((CX, CY), 5.2, fill=False, edgecolor=GRY, lw=0.6,
                             ls=(0, (2.4, 2.0)), zorder=3))
for s, k in zip(sites[1:], kinds[1:]):                      # in-cell neighbours
    ax.plot([CX, CX + s[0]], [CY, CY + s[1]], color=GRY, lw=0.55, zorder=3)
for d in img[:2]:                                           # one periodic image edge
    p = sites[2] + d
    if abs(p[0]) < 9 and abs(p[1]) < 9:
        ax.plot([CX, CX + p[0]], [CY, CY + p[1]], color=ORA, lw=0.7,
                ls=(0, (2.0, 1.6)), zorder=3)
        ax.add_patch(mpatches.Circle((CX + p[0], CY + p[1]), 0.86,
                                     facecolor=(*to_rgb(ORA), 0.35),
                                     edgecolor=ORA, lw=0.6, zorder=4))
for s, k in zip(sites, kinds):
    col = BLU if k == 0 else PUR
    ax.add_patch(mpatches.Circle((CX + s[0], CY + s[1]), 1.02 if k == 0 else 0.82,
                                 facecolor=(*to_rgb(col), 0.85), edgecolor="white",
                                 lw=0.7, zorder=5))
txt(CX + 6.9, CY + 5.0, "$r_{\\mathrm{cut}}$", 5.2, GRY)
txt(CX, CY - 8.2, "periodic images, lattice self-edges", 5.0, SOFT)

# ------------------------------------------------------------ features
FX = 27.5
panel_title(FX + 5.0, 28.4, "equivariant features")
for i, (lab, nlobe, yy) in enumerate((("$\\ell=0$", 0, 23.0), ("$\\ell=1$", 1, 18.6),
                                      ("$\\ell=2$", 2, 14.2))):
    c = L_CMAP(0.15 + 0.4 * i)
    if nlobe == 0:
        ax.add_patch(mpatches.Circle((FX + 1.6, yy), 1.30, facecolor=(*c[:3], 0.75),
                                     edgecolor=c, lw=0.6, zorder=5))
    else:
        for j in range(2 * nlobe):
            a = np.pi * j / nlobe + (np.pi / 4 if nlobe == 2 else 0)
            e = mpatches.Ellipse((FX + 1.6 + 1.15 * np.cos(a), yy + 1.15 * np.sin(a)),
                                 2.3, 1.25, angle=np.degrees(a),
                                 facecolor=(*c[:3], 0.72 if j % 2 == 0 else 0.34),
                                 edgecolor=c, lw=0.5, zorder=5)
            ax.add_patch(e)
    txt(FX + 4.9, yy, lab, 5.4, SOFT, ha="left")
for k in range(5):                                          # channel slab
    ax.add_patch(mpatches.FancyBboxPatch(
        (FX + 7.4 + 0.42 * k, 12.0 + 0.42 * k), 3.0, 12.4,
        boxstyle="round,pad=0.10,rounding_size=0.35", linewidth=0.6,
        edgecolor=L_CMAP(0.2 + 0.18 * k), facecolor=(*L_CMAP(0.2 + 0.18 * k)[:3], 0.14),
        zorder=4 - k * 0.1))
txt(FX + 9.6, 10.4, "$C=128$ channels", 5.2, SOFT)
txt(FX + 5.0, 8.2, "$Y_{\\ell m}(\\hat{r}_{ij})$, radial basis,\nelement embedding",
    5.2, SOFT)
arrow(CX + 8.4, 18.6, FX - 1.0, 18.6, rad=0.0)

# ---------------------------------------------------------------- block
BX, BW = 45.0, 27.0
COLX, RAIL = BX + 11.0, BX + 23.4
for off in (2.2, 1.1):
    ax.add_patch(mpatches.FancyBboxPatch(
        (BX + off, 5.4 + off), BW, 21.0, boxstyle="round,pad=0.18,rounding_size=0.5",
        linewidth=0.6, edgecolor=LGY, facecolor="white", zorder=1))
ax.add_patch(mpatches.FancyBboxPatch(
    (BX, 5.4), BW, 21.0, boxstyle="round,pad=0.18,rounding_size=0.5",
    linewidth=0.9, edgecolor=BLU, facecolor=(*to_rgb(BLU), 0.035), zorder=2))
panel_title(BX + 11.0, 28.4, "equivariant block")
txt(BX + 24.4, 28.4, "$\\times\\,N$", 6.2, BLU, "bold")


def sub(y, h, title, sub_, colour, fill=0.12):
    boxed_text(ax, COLX - 8.6, y, 17.2, h, title, sub_ or None, colour=colour,
               fill=fill, title_fs=5.5, sub_fs=4.8, gap_pt=2.2, pad_pt=2.4,
               lw=0.75, z=4)


def oplus(x, y, r=0.62):
    ax.add_patch(mpatches.Circle((x, y), r, facecolor="white", edgecolor=SOFT,
                                 linewidth=0.7, zorder=7))
    ax.plot([x - r * 0.52, x + r * 0.52], [y, y], color=SOFT, lw=0.6, zorder=8)
    ax.plot([x, x], [y - r * 0.52, y + r * 0.52], color=SOFT, lw=0.6, zorder=8)


sub(22.4, 2.7, "equivariant layer norm", "", GRY, 0.06)
sub(16.8, 4.0, "SO(2) edge-frame attention", "rotate to the edge frame, 4 heads", BLU)
sub(11.2, 4.0, "self-product", "tensor square, degree-gated", BLU)
sub(6.0, 3.7, "reciprocal-space term",
    "$\\langle f_j\\cos 2\\pi\\,h\\!\\cdot\\!\\Delta x_{ij}\\rangle_j$", ORA)
for py, by in ((16.1, 22.4), (10.5, 16.1), (5.1, 10.5)):
    oplus(COLX, py)
    ax.plot([COLX, RAIL], [by, by], color=LGY, lw=0.7, zorder=3)
    ax.plot([RAIL, RAIL], [by, py], color=LGY, lw=0.7, zorder=3)
    arrow(RAIL, py, COLX + 0.70, py, c=LGY, lw=0.7, z=3)
arrow(COLX, 22.4, COLX, 20.9)
arrow(COLX, 16.8, COLX, 16.78)
arrow(COLX, 15.5, COLX, 15.25)
arrow(COLX, 11.2, COLX, 11.18)
arrow(COLX, 9.9, COLX, 9.75)
arrow(COLX, 6.0, COLX, 5.78)
txt(RAIL + 1.2, 13.4, "residual", 4.8, LGY, ha="left", rot=90)
arrow(FX + 11.4, 18.6, BX - 0.8, 18.6)

# --------------------------------------------------------------- readout
RX = 76.0
panel_title(RX + 11.0, 28.4, "readout and head")
_rs = np.random.default_rng(3)
hk = np.array([[i, j] for i in range(-3, 4) for j in range(-3, 4)])
hk = hk[(hk ** 2).sum(1) > 0]
inten = 1.0 / (1.0 + (hk ** 2).sum(1)) * _rs.uniform(0.4, 1.0, len(hk))
ax.scatter(RX + 5.4 + hk[:, 0] * 1.35, 21.6 + hk[:, 1] * 1.35,
           s=2 + 46 * inten, c=[L_CMAP(0.25 + 0.6 * v) for v in inten],
           edgecolor="none", zorder=5)
txt(RX + 5.4, 15.6, "diffraction readout", 5.5, INK, "bold")
txt(RX + 5.4, 14.0, "structure factors on a Miller set", 4.8, SOFT)
w = np.array([0.08, 0.17, 0.31, 0.22, 0.12, 0.06, 0.04])
for i, wi in enumerate(w):
    ax.add_patch(mpatches.Rectangle((RX + 13.6 + i * 1.05, 18.4), 0.80, wi * 14.0,
                                    facecolor=(*to_rgb(PUR), 0.30 + 0.6 * wi),
                                    edgecolor="none", zorder=5))
ax.plot([RX + 13.4, RX + 21.6], [18.4, 18.4], color=SOFT, lw=0.6, zorder=5)
txt(RX + 17.6, 15.6, "attention pooling", 5.5, INK, "bold")
txt(RX + 17.6, 14.0, "one vector per crystal", 4.8, SOFT)
ax.add_patch(mpatches.FancyBboxPatch(
    (RX + 2.2, 6.2), 19.0, 5.2, boxstyle="round,pad=0.18,rounding_size=0.5",
    linewidth=0.85, edgecolor=GRN, facecolor=(*to_rgb(GRN), 0.08), zorder=4))
txt(RX + 11.7, 9.6, "property head", 5.5, INK, "bold")
txt(RX + 11.7, 7.6, "a value, its uncertainty, and the\ndomain it is valid on", 4.8, SOFT)
arrow(RX + 5.4, 13.4, RX + 8.0, 11.8, rad=0.10)
arrow(RX + 17.6, 13.4, RX + 15.2, 11.8, rad=-0.10)
arrow(BX + BW + 2.6, 18.6, RX - 0.8, 20.4, rad=-0.10)
txt(RX + 11.7, 4.6, f"{PARAMS:.1f}M parameters", 5.6, ACCENT, "bold")
stamp(fig, ax, "a", dx=-0.045, dy=0.004)

# =======================================================================
# b  JARVIS-DFT
# =======================================================================
ax = fig.add_subplot(_r1[0])
models = ["PRDNet", "eComFormer", "iComFormer", "CGTNet"]
MC = {"PRDNet": "#CBD1D4", "eComFormer": "#AAB2B6", "iComFormer": "#868E92",
      "CGTNet": ACCENT}
x = np.arange(len(JARVIS_TASKS)); w_ = 0.19
ref = np.array(JARVIS["iComFormer"], float)
for j, m in enumerate(models):
    v = np.array(JARVIS[m], float) / ref
    bars(ax.bar(x + (j - 1.5) * w_, v, width=w_ * 0.90), MC[m],
         face_alpha=0.95 if m == "CGTNet" else 0.85, edge=0.0)
ax.axhline(1.0, color=GRY, lw=0.6, ls=(0, (3, 2)), zorder=1)
ax.set_xticks(x); ax.set_xticklabels(JARVIS_TASKS, fontsize=5.4)
ax.set_ylabel("Test MAE / best published", fontsize=6.4)
ax.set_ylim(0.7, 1.30)
ax.legend([mpatches.Patch(facecolor=(*to_rgb(MC[m]), 0.9)) for m in models], models,
          frameon=False, ncol=2, fontsize=5.4, handlelength=0.8, handleheight=0.75,
          labelspacing=0.22, columnspacing=0.8, loc="upper left",
          bbox_to_anchor=(-0.01, 1.04), borderpad=0.0)
stamp(fig, ax, "b", dx=-0.052)

# =======================================================================
# c  Matbench
# =======================================================================
ax = fig.add_subplot(_r1[1])
names = ["ALIGNN", "leaderboard", "CGTNet"]
MC2 = {"ALIGNN": "#CBD1D4", "leaderboard": "#868E92", "CGTNet": ACCENT}
x = np.arange(len(MB_TASKS)); w_ = 0.25
refm = np.array(MB["leaderboard"][0], float)
for j, m in enumerate(names):
    mu, sd = np.array(MB[m][0], float), np.array(MB[m][1], float)
    b = ax.bar(x + (j - 1) * w_, mu / refm, width=w_ * 0.90, yerr=sd / refm,
               error_kw=dict(lw=0.6, capsize=1.5, ecolor=GRY))
    bars(b, MC2[m], face_alpha=0.95 if m == "CGTNet" else 0.85, edge=0.0)
ax.axhline(1.0, color=GRY, lw=0.6, ls=(0, (3, 2)), zorder=1)
ax.set_xticks(x); ax.set_xticklabels(MB_TASKS, fontsize=5.8)
ax.set_ylabel("MAE / leaderboard", fontsize=6.4)
ax.set_ylim(0.8, 1.36)
ax.set_xlim(-0.56, len(MB_TASKS) - 0.44)
stamp(fig, ax, "c", dx=-0.075)

# =======================================================================
# d  every task of the corpus
# =======================================================================
ax = fig.add_subplot(_r1[2])
ax.axhspan(0.04, 1.0, color=GRN, alpha=0.05, zorder=0)
ax.scatter(PH_NTRAIN, PH_NMAE, s=13, c=[TIER_COL[t] for t in PH_TIER],
           alpha=0.80, edgecolor="none", zorder=3)
xs = np.logspace(2.4, 7.0, 40)
ax.plot(xs, 0.92 * (xs / 1e3) ** -0.17, color=INK, lw=0.9, ls=(0, (4, 2)), zorder=4)
ax.axhline(1.0, color=GRY, lw=0.7, zorder=2)
ax.text(2.0e7, 1.09, "predicting the mean", fontsize=5.2, color=GRY, ha="right")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlim(1.4e2, 2.2e7); ax.set_ylim(0.05, 1.62)
ax.set_xlabel("Crystals available to train on", fontsize=6.4)
ax.set_ylabel("Test MAE / spread of the target", fontsize=6.4)
ax.legend([plt.Line2D([], [], marker="o", ls="none", color=TIER_COL[t], ms=3.2)
           for t in (1, 2, 3, 4)],
          ["tier 1", "tier 2", "tier 3", "tier 4"], frameon=False, ncol=2,
          fontsize=5.4, loc="lower left", handletextpad=0.35, labelspacing=0.22,
          columnspacing=0.8, borderpad=0.0)
stamp(fig, ax, "d", dx=-0.055)

save(fig, "fig_model")
