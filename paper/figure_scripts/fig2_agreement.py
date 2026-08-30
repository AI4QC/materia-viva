"""Bottom row of Figure 2: how far apart independent databases land.

Kept in its own module so the top row can be regenerated without the
cross-source value scan, which reads the whole property table.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import BLU, CYA, GRN, GRY, LGY, ORA, PUR, RED, bars, stamp

#: display name and tolerance, matching extract_agreement.COMPARABLE
NICE = {
    "band_gap": ("band gap", "0.05 eV"),
    "formation_energy_per_atom": ("formation energy", "0.05 eV/atom"),
    "energy_above_hull": ("hull distance", "0.05 eV/atom"),
    "total_magnetization": ("magnetisation", r"0.05 $\mu_\mathrm{B}$"),
    "bulk_modulus_vrh": ("bulk modulus", "5 GPa"),
    "shear_modulus_vrh": ("shear modulus", "5 GPa"),
    "density": ("density", "2% rel."),
    "volume_per_atom": ("volume per atom", "20% rel."),
}
PROP_COL = {"band_gap": BLU, "formation_energy_per_atom": GRN,
            "energy_above_hull": CYA, "total_magnetization": PUR,
            "bulk_modulus_vrh": ORA, "shear_modulus_vrh": RED,
            "density": "#8C5A2B", "volume_per_atom": GRY}


def draw(fig, gs, pairs, perp, spread):
    perp = [r for r in perp if int(r["n_multi_source_materials"]) >= 500]
    perp.sort(key=lambda r: float(r["frac_within_tol"]))

    # ------------------------------------------------ d agreement fractions
    ax = fig.add_subplot(gs[1, 0])
    y = np.arange(len(perp))
    frac = np.array([float(r["frac_within_tol"]) for r in perp]) * 100
    cols = [PROP_COL.get(r["property"], GRY) for r in perp]
    bars(ax.barh(y, frac, height=0.68), cols, face_alpha=0.50, edge=0.7)
    ax.set_yticks(y)
    ax.set_yticklabels([NICE.get(r["property"], (r["property"], ""))[0] for r in perp],
                       fontsize=6.0)
    ax.tick_params(axis="y", length=0, pad=1.5)
    ax.set_xlim(0, 124)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Independent databases agreeing (%)")
    for i, r in enumerate(perp):
        ax.text(frac[i] + 2.0, i, f"{int(r['n_multi_source_materials']):,}",
                va="center", ha="left", fontsize=5.6, color=GRY)
    ax.text(0.5, -0.245, "figures at the right of each bar give the number of\n"
                         "crystals carrying that property from two or more databases",
            transform=ax.transAxes, ha="center", va="top", fontsize=5.9,
            color=GRY, linespacing=1.45)
    stamp(fig, ax, "d")

    # ------------------------------------------------------- e spread curves
    ax = fig.add_subplot(gs[1, 1])
    by_prop = defaultdict(list)
    for r in spread:
        by_prop[r["property"]].append(float(r["spread"]))
    order = sorted(by_prop, key=lambda k: -len(by_prop[k]))
    for name in order:
        v = np.sort(np.array(by_prop[name]))
        if v.size < 50:
            continue
        v = np.clip(v, 1e-4, None)
        ax.plot(v, np.linspace(0, 100, v.size), lw=1.0,
                color=PROP_COL.get(name, GRY),
                label=NICE.get(name, (name, ""))[0])
    ax.set_xscale("log")
    ax.set_xlim(1e-4, 30)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Spread between databases (property unit)")
    ax.set_ylabel("Structures below (%)")
    ax.legend(frameon=False, loc="upper left", fontsize=5.8, handlelength=1.1,
              labelspacing=0.28, borderpad=0.0)
    ax.grid(True, axis="y", lw=0.3, color="#EFEFEF")
    ax.set_axisbelow(True)
    stamp(fig, ax, "e", dx=-0.050)

    # --------------------------------------------- f pairwise disagreement
    ax = fig.add_subplot(gs[1, 2])
    target = "formation_energy_per_atom"
    rows = [r for r in pairs if r["property"] == target]
    if not rows:
        target = max({r["property"] for r in pairs},
                     key=lambda p: sum(int(r["n_shared"]) for r in pairs
                                       if r["property"] == p))
        rows = [r for r in pairs if r["property"] == target]
    rows.sort(key=lambda r: -int(r["n_shared"]))
    rows = rows[:12][::-1]
    y = np.arange(len(rows))
    med = np.array([float(r["median_abs_diff"]) for r in rows])
    within = np.array([float(r["frac_within_tol"]) for r in rows]) * 100
    ax.hlines(y, 0, med, color=LGY, lw=0.8, zorder=1)
    sc = ax.scatter(med, y, s=16, c=within, cmap="RdYlGn", vmin=0, vmax=100,
                    edgecolor=GRY, linewidth=0.4, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r['source_a']} $\\cdot$ {r['source_b']}" for r in rows],
                       fontsize=5.4)
    ax.tick_params(axis="y", length=0, pad=1.5)
    ax.set_xscale("log")
    ax.set_xlabel(f"Median |$\\Delta$| in {NICE.get(target, (target, ''))[0]} "
                  "(eV/atom)")
    ax.axvline(0.05, color=GRY, lw=0.6, ls=(0, (3, 2)), zorder=2)
    ax.text(0.052, len(rows) - 0.4, "0.05 eV/atom", fontsize=5.6, color=GRY, ha="left")
    cb = fig.colorbar(sc, ax=ax, fraction=0.040, pad=0.03)
    cb.set_label("within tolerance (%)", fontsize=5.8)
    cb.ax.tick_params(labelsize=5.4, length=1.4, width=0.4)
    cb.outline.set_linewidth(0.4)
    ax.text(0.5, -0.245, "the 12 database pairs sharing the most structures",
            transform=ax.transAxes, ha="center", va="top", fontsize=6.0, style="italic")
    stamp(fig, ax, "f", dx=-0.050)
