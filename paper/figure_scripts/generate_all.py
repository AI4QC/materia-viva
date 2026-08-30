#!/usr/bin/env python3
"""Regenerate every figure from the published index, in dependency order.

    python paper/figure_scripts/generate_all.py            # figures only
    python paper/figure_scripts/generate_all.py --extract  # rebuild the CSVs too

The extraction stage reads the whole index and takes roughly half an hour on a
warm page cache; the figure stage reads only paper/data/*.csv and takes seconds.
They are separate so that a caption or a colour can be changed without touching
the database.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

EXTRACT = [
    "extract_stats.py",       # pool shape, sources, properties, curves, overlaps
    "extract_evolution.py",   # base merge vs admitted, per source
    "extract_substrate.py",   # matches onto admitted structures
    "extract_agreement.py",   # per-material completeness + cross-source agreement
    "cost_tiers.py",          # coverage grouped by required calculation
    "extract_gnn_census.py",  # task census + gated prediction sets (reads data/ml)
]
FIGURES = [
    "fig1_architecture.py",
    "fig2_redundancy.py",
    "fig3_landscape.py",
    "fig4_completion.py",
    "make_si_tables.py",      # Supplementary Tables S1-S4
]


def run(script: str) -> None:
    print(f"==> {script}", flush=True)
    subprocess.run([sys.executable, str(HERE / script)], cwd=ROOT, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true",
                    help="rebuild paper/data/*.csv from data/index/materials.sqlite")
    args = ap.parse_args()
    if args.extract:
        for script in EXTRACT:
            run(script)
    for script in FIGURES:
        run(script)
    print("done: paper/figs/*.pdf")


if __name__ == "__main__":
    main()
