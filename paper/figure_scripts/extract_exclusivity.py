#!/usr/bin/env python3
"""How much of each database no other database holds.

For every source: the crystals it annotates, and how many of those carry a
reference from no other source. Order-independent, unlike the admission counts,
because it asks about the finished record rather than about when a source
arrived.

Writes paper/data/source_exclusivity.csv.
"""
from __future__ import annotations

import collections
import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = f"file:{ROOT}/data/index/materials.sqlite?mode=ro"
OUT = ROOT / "paper" / "data" / "source_exclusivity.csv"

db = sqlite3.connect(DB, uri=True)
db.execute("pragma mmap_size=8000000000")
SRC = {i: k for i, k in db.execute("select id,key from source_defs")}

degree: collections.Counter[int] = collections.Counter()
holds: dict[int, set[int]] = collections.defaultdict(set)
seen: set[tuple[int, int]] = set()
for pk, sid in db.execute("select material_pk, source_id from material_source_refs"):
    # a source may file several native ids against one crystal; count it once
    if (pk, sid) in seen:
        continue
    seen.add((pk, sid))
    degree[pk] += 1
    holds[sid].add(pk)

rows = []
for sid, mats in holds.items():
    n = len(mats)
    sole = sum(1 for m in mats if degree[m] == 1)
    rows.append((SRC[sid], n, sole, sole / n))
rows.sort(key=lambda r: -r[1])

with OUT.open("w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["source", "n_materials", "n_sole", "frac_sole"])
    for key, n, sole, frac in rows:
        w.writerow([key, n, sole, f"{frac:.6f}"])
print(f"{len(rows)} sources, {len(degree):,} crystals carrying a reference -> {OUT}")
