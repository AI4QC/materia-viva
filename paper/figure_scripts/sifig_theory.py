#!/usr/bin/env python3
"""Supplementary figure - one property name, several levels of theory.

The label-definition problem behind the task census: a property name such as
band gap is filed under several levels of theory, each denoting a different
physical quantity, and a model trained on the name learns the mixture.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import CM, DATA, W1, save, stamp
from figkit import (ACCENT, ACCENT_SOFT, FAMILY, INK, LIGHT, MECHANISM, MID,
                    PROPERTY, SOFT)

TH = list(csv.DictReader((DATA / "gnn_theory_levels.csv").open()))

LEVEL_COL = {"gga": ACCENT, "gga-vdw": "#2E7FB8", "pbesol": ACCENT_SOFT,
             "scan": FAMILY["specialised"], "r2scan": "#4C9F70",
             "hse06": PROPERTY["total_magnetization"], "tight-binding": MECHANISM,
             "experiment": FAMILY["experimental"], "mbj": "#B07AA1",
             "gllbsc": FAMILY["framework"], "lda": "#9BC9E0",
             "forcefield": "#C8A2C8", "other": LIGHT}

by_prop = defaultdict(list)
levels = {}
for r in TH:
    by_prop[r["property"]].append((r["theory_level"], int(r["n_materials"])))
    levels[r["property"]] = int(r["n_levels"])
props = sorted(by_prop, key=lambda p: -sum(v for _, v in by_prop[p]))[:12]

fig = plt.figure(figsize=(W1 * 1.62, 7.6 * CM))
ax = fig.add_axes([0.215, 0.145, 0.735, 0.825])
y = np.arange(len(props))[::-1]
for yi, prop in zip(y, props):
    items = sorted(by_prop[prop], key=lambda kv: -kv[1])
    total = sum(v for _, v in items)
    left = 0.0
    for name, v in items:
        frac = v / total * 100
        col = LEVEL_COL.get(name, MID)
        ax.barh(yi, frac, left=left, height=0.68,
                color=(*to_rgb(col), 0.68), edgecolor="white", linewidth=0.35)
        if frac > 8:
            ax.text(left + frac / 2, yi, name, ha="center", va="center",
                    fontsize=5.2, color="white" if frac > 22 else INK)
        left += frac
    ax.text(101.5, yi, f"{levels[prop]}", ha="left", va="center", fontsize=5.8,
            color=SOFT)
ax.set_yticks(y)
ax.set_yticklabels([p.replace("_", " ") for p in props], fontsize=5.8)
ax.tick_params(axis="y", length=0, pad=1.5)
ax.set_xlim(0, 109)
ax.set_ylim(-0.7, len(props) - 0.1)
ax.set_xticks([0, 25, 50, 75, 100])
ax.set_xlabel("Labels filed under the property name (%)")
ax.text(103.0, len(props) - 0.30, "levels", fontsize=5.6, color=SOFT, ha="left")
for sp in ("right", "top"):
    ax.spines[sp].set_visible(False)

save(fig, "sifig_theory")
