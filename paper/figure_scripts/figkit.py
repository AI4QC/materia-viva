"""Layout helpers for the schematic panels, plus the shared palette.

Text inside a box was previously placed by hand-computed offsets, which is why
titles sat on their subtitles in some boxes and floated in others. `boxed_text`
removes the guesswork: it measures the font in data units through the axes
transform, stacks the lines as one block, centres that block in the box, and
refuses to draw if the block would not clear the border by `pad`.
"""
from __future__ import annotations

import matplotlib.patches as mpatches
from matplotlib.colors import to_rgb

from palette import *          # noqa: F401,F403  (colour system)
import palette as P            # noqa: N812


def _unit_per_pt(ax) -> float:
    """Data units per typographic point on the y axis of `ax`."""
    inv = ax.transData.inverted()
    (_, y0), (_, y1) = inv.transform([(0.0, 0.0), (0.0, 1.0)])
    return abs(y1 - y0) * ax.figure.dpi / 72.0


def boxed_text(ax, x, y, w, h, title, sub=None, *, colour=P.ACCENT, fill=0.07,
               title_fs=6.2, sub_fs=5.2, gap_pt=2.6, pad_pt=3.2, lw=0.85,
               ls="-", z=3, title_weight="bold", draw_box=True, cx=None,
               sub_colour=None, sub_family=None):
    """A rounded box with its text centred as one block.

    `gap_pt` is the space between the title and the subtitle; `pad_pt` the
    minimum clearance from the border. Both are in points, so they look the
    same whatever the data range of the axes.
    """
    upt = _unit_per_pt(ax)
    if draw_box:
        ax.add_patch(mpatches.FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.0,rounding_size=0.55",
            linewidth=lw, edgecolor=colour, facecolor=(*to_rgb(colour), fill),
            linestyle=ls, zorder=z))

    title_h = 1.22 * title_fs * upt
    lines = 0 if sub is None else sub.count("\n") + 1
    sub_h = 0.0 if sub is None else (1.34 * sub_fs * upt) * lines
    gap = 0.0 if sub is None else gap_pt * upt
    block = title_h + gap + sub_h

    avail = h - 2 * pad_pt * upt
    if block > avail and sub is not None:                 # give the gap back first
        gap = max(0.0, gap - (block - avail))
        block = title_h + gap + sub_h

    top = y + h / 2 + block / 2
    cx = x + w / 2 if cx is None else cx
    ax.text(cx, top - title_h / 2, title, ha="center", va="center",
            fontsize=title_fs, fontweight=title_weight, color=P.INK,
            zorder=z + 3)
    if sub is not None:
        kw = {} if sub_family is None else {"family": sub_family}
        ax.text(cx, top - title_h - gap - sub_h / 2, sub, ha="center",
                va="center", fontsize=sub_fs,
                color=P.SOFT if sub_colour is None else sub_colour,
                linespacing=1.34, zorder=z + 3, **kw)
    return block <= avail


def rowstack(y_top, y_bottom, heights, gap):
    """Slot geometry for a vertical stack: returns [(y, h), ...] top-down."""
    total = sum(heights) + gap * (len(heights) - 1)
    scale = (y_top - y_bottom) / total
    out, cursor = [], y_top
    for hgt in heights:
        hh = hgt * scale
        out.append((cursor - hh, hh))
        cursor -= hh + gap * scale
    return out
