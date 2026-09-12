"""Shared plotting style. Nature column widths, Arial, Okabe-Ito-derived hues."""
from __future__ import annotations

import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "paper" / "data"
OUT = ROOT / "paper" / "figs"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.family": "Arial", "font.sans-serif": ["Arial", "Liberation Sans", "DejaVu Sans"],
    "font.size": 7.2, "axes.labelsize": 7.6, "axes.titlesize": 7.8,
    "xtick.labelsize": 6.8, "ytick.labelsize": 6.8, "legend.fontsize": 6.8,
    "axes.linewidth": 0.55, "xtick.major.width": 0.55, "ytick.major.width": 0.55,
    "xtick.major.size": 2.2, "ytick.major.size": 2.2,
    "xtick.minor.width": 0.4, "ytick.minor.width": 0.4,
    "xtick.minor.size": 1.2, "ytick.minor.size": 1.2,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 400, "savefig.dpi": 400, "savefig.bbox": "tight",
    "savefig.pad_inches": 0.02, "pdf.fonttype": 42, "ps.fonttype": 42,
    "svg.fonttype": "none",
    "mathtext.fontset": "custom", "mathtext.rm": "Arial",
    "mathtext.it": "Arial:italic", "mathtext.bf": "Arial:bold",
})

CM = 1 / 2.54
W1, W2 = 8.9 * CM, 18.3 * CM          # Nature single / double column

BLU = "#005B93"
CYA = "#35A7D8"
GRN = "#156646"
ORA = "#E08A1E"
RED = "#D6564C"
PUR = "#9861B0"
GRY = "#8A8C8E"
LGY = "#C9CBCD"
BRN = "#8C5A2B"

#: the four source families the manuscript groups databases into
GROUP_COLOUR = {
    "general": BLU,
    "experimental": RED,
    "specialised": GRN,
    "framework": ORA,
}
GROUP_LABEL = {
    "general": "General-purpose DFT",
    "experimental": "Experimental catalogues",
    "specialised": "Specialised property libraries",
    "framework": "Porous and framework materials",
}
SOURCE_GROUP = {
    "alexandria": "general", "aflow": "general", "elementa": "general",
    "oqmd": "general", "gnome": "general", "materials-project": "general",
    "jarvis-qetb": "general", "matbench-discovery": "general",
    "jarvis-dft": "general", "carolina": "general", "odbx": "general",
    "mc3d": "general", "nomad": "general",
    "cod": "experimental", "icsd": "experimental",
    "hmof": "framework", "mof-carbon-capture": "framework",
    "deem-zeolites": "framework", "qmof": "framework", "mofx-db": "framework",
    "core-mof": "framework", "fair-mofs": "framework", "ec-mof": "framework",
    "curated-cof": "framework", "iza-zeolite": "framework", "pcod": "framework",
    "open-framework-aluminophosphate": "framework",
}


def group_of(key: str) -> str:
    return SOURCE_GROUP.get(key, "specialised")


def stamp(fig, ax, letter: str, dx: float = -0.055, dy: float = 0.028) -> None:
    """Panel letter in figure coordinates, aligned to the axes' top-left."""
    box = ax.get_position()
    fig.text(box.x0 + dx, box.y1 + dy, letter, fontsize=9, fontweight="bold",
             va="bottom", ha="left")


def bars(container, colour, face_alpha: float = 0.42, edge: float = 0.7):
    """Same-hue outline, translucent interior."""
    colours = [colour] * len(container) if isinstance(colour, str) else colour
    for patch, col in zip(container, colours):
        patch.set_alpha(None)
        patch.set_facecolor(to_rgba(col, face_alpha))
        patch.set_edgecolor(to_rgba(col, 1.0))
        patch.set_linewidth(edge)
    return container


def save(fig, stem: str) -> None:
    for suffix in (".pdf", ".png", ".svg"):
        fig.savefig(OUT / f"{stem}{suffix}")
    print(f"wrote {stem}.pdf/.png/.svg")


# --------------------------------------------------------------------------
# Small vector glyphs for the schematic. Everything is drawn in the host axes'
# data coordinates and sized by `s`, so a glyph can sit inside a box without a
# separate inset axes and without rasterising anything.
# --------------------------------------------------------------------------
import numpy as _np
import matplotlib.patches as _mp
from matplotlib.path import Path as _Path


def _stroke(ax, xs, ys, colour, lw=0.7, **kw):
    ax.plot(xs, ys, color=colour, lw=lw, solid_capstyle="round",
            solid_joinstyle="round", zorder=kw.pop("zorder", 5), **kw)


def icon_database(ax, x, y, s, colour, lw=0.7):
    """A stack of three discs: the conventional data-store glyph."""
    w, h = s, s * 0.30
    for k, dy in enumerate((-s * 0.34, 0.0, s * 0.34)):
        ax.add_patch(_mp.Ellipse((x, y + dy), w, h, facecolor="white",
                                 edgecolor=colour, linewidth=lw, zorder=5 + k))
    ax.add_patch(_mp.Rectangle((x - w / 2, y - s * 0.34), w, s * 0.34,
                               facecolor="white", edgecolor="none", zorder=5.5))
    _stroke(ax, [x - w / 2, x - w / 2], [y - s * 0.34, y + s * 0.34], colour, lw)
    _stroke(ax, [x + w / 2, x + w / 2], [y - s * 0.34, y + s * 0.34], colour, lw)


def icon_crystal(ax, x, y, s, colour, lw=0.6):
    """A projected unit cell: four corners, two edges and a body diagonal."""
    a, d = s * 0.42, s * 0.20
    pts = [(-a, -a), (a, -a), (a, a), (-a, a)]
    back = [(px + d, py + d) for px, py in pts]
    for poly in (pts, back):
        xs = [x + px for px, _ in poly] + [x + poly[0][0]]
        ys = [y + py for _, py in poly] + [y + poly[0][1]]
        _stroke(ax, xs, ys, colour, lw)
    for (px, py), (bx, by) in zip(pts, back):
        _stroke(ax, [x + px, x + bx], [y + py, y + by], colour, lw * 0.8)
    for px, py in pts + back:
        ax.add_patch(_mp.Circle((x + px, y + py), s * 0.055, facecolor=colour,
                                edgecolor="none", zorder=6))


def icon_funnel(ax, x, y, s, colour, lw=0.7):
    """Many inputs, one normalised output."""
    w, t = s * 0.46, s * 0.34
    _stroke(ax, [x - w, x + w, x + s * 0.10, x + s * 0.10,
                 x - s * 0.10, x - s * 0.10, x - w],
            [y + t, y + t, y - s * 0.06, y - t, y - t, y - s * 0.06, y + t],
            colour, lw)
    for dx in (-w * 0.55, 0.0, w * 0.55):
        _stroke(ax, [x + dx, x + dx], [y + t + s * 0.30, y + t + s * 0.08],
                colour, lw * 0.8)


def icon_fingerprint(ax, x, y, s, colour, lw=0.7):
    """Nested ridges: one invariant string per structure."""
    for k, r in enumerate((0.16, 0.27, 0.38, 0.49)):
        span = 150 - k * 8
        th = _np.radians(_np.linspace(90 - span / 2, 90 + span / 2, 60))
        ax.plot(x + s * r * _np.cos(th), y - s * 0.16 + s * r * _np.sin(th) * 1.05,
                color=colour, lw=lw * (1.0 - 0.08 * k), solid_capstyle="round",
                zorder=5)
    _stroke(ax, [x, x], [y - s * 0.16, y - s * 0.02], colour, lw)


def icon_key(ax, x, y, s, colour, lw=0.7):
    """An authoritative identifier: it either fits or it does not."""
    r = s * 0.17
    ax.add_patch(_mp.Circle((x - s * 0.28, y), r, facecolor="none",
                            edgecolor=colour, linewidth=lw, zorder=5))
    _stroke(ax, [x - s * 0.28 + r, x + s * 0.42], [y, y], colour, lw)
    for dx in (s * 0.20, s * 0.34):
        _stroke(ax, [x + dx, x + dx], [y, y - s * 0.16], colour, lw)


def icon_merge(ax, x, y, s, colour, lw=0.7):
    """Two records resolving onto one material."""
    for sign in (1, -1):
        ax.add_patch(_mp.FancyArrowPatch(
            (x - s * 0.42, y + sign * s * 0.26), (x + s * 0.30, y),
            arrowstyle="-|>", mutation_scale=5, color=colour, lw=lw,
            connectionstyle=f"arc3,rad={-sign * 0.28}", zorder=5))
    ax.add_patch(_mp.Circle((x + s * 0.40, y), s * 0.10, facecolor=colour,
                            edgecolor="none", zorder=6))


def icon_plus(ax, x, y, s, colour, lw=0.8):
    """Admission: the pool gains a member."""
    ax.add_patch(_mp.Circle((x, y), s * 0.36, facecolor="none", edgecolor=colour,
                            linewidth=lw, zorder=5))
    _stroke(ax, [x - s * 0.18, x + s * 0.18], [y, y], colour, lw)
    _stroke(ax, [x, x], [y - s * 0.18, y + s * 0.18], colour, lw)


def icon_cycle(ax, x, y, s, colour, lw=0.8):
    """The substrate feeding back into the matcher."""
    th = _np.radians(_np.linspace(35, 305, 80))
    ax.plot(x + s * 0.34 * _np.cos(th), y + s * 0.34 * _np.sin(th), color=colour,
            lw=lw, solid_capstyle="round", zorder=5)
    ax.add_patch(_mp.FancyArrowPatch(
        (x + s * 0.34 * _np.cos(_np.radians(320)),
         y + s * 0.34 * _np.sin(_np.radians(320))),
        (x + s * 0.34 * _np.cos(_np.radians(36)),
         y + s * 0.34 * _np.sin(_np.radians(36))),
        arrowstyle="-|>", mutation_scale=5, color=colour, lw=lw,
        connectionstyle="arc3,rad=0.30", zorder=5))
