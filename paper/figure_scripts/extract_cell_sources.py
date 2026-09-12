"""How many databases stand behind one filled cell of the property matrix.

The agreement scan reports how far apart two databases land when both describe
one crystal. This reports the prior question: how much of the property layer is
even open to that check. A cell of the (crystal x property) matrix is *checkable*
only if two or more databases put a value in it; the rest of the layer rests on a
single provider, and no amount of cross-source machinery can test it.

The count has to be over distinct (crystal, property, database) triples rather
than over rows, because one database routinely supplies several rows for one cell
-- different methods, different spin channels, several calculations of the same
crystal. Counting rows would report method multiplicity as independent support,
which is the opposite of what the number is for.

Done in numpy rather than SQL: packing the triple into one int64 and sorting is
about two minutes, where a GROUP BY over 1.3e8 rows spills to disk.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "index" / "materials.sqlite"
OUT = ROOT / "paper" / "data"

t0 = time.time()
log = lambda m: print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.execute("PRAGMA cache_size = -1500000")
db.execute("PRAGMA mmap_size = 8000000000")
props = {i: n for i, n in db.execute("SELECT id, name FROM property_defs")}
NPROP = max(props)
NROW = db.execute("SELECT COUNT(*) FROM material_properties").fetchone()[0]
NSRC = db.execute("SELECT MAX(id) FROM source_defs").fetchone()[0]
SRC_BITS = 64                      # 55 sources today; 64 leaves room and keeps the shift cheap
assert NSRC < SRC_BITS, f"{NSRC} sources no longer fit in {SRC_BITS}"
log(f"{NROW:,} rows, {len(props)} properties, {NSRC} sources")

key = np.empty(NROW, dtype=np.int64)
i = 0
CH = 4_000_000
cur = db.execute("SELECT material_pk, property_id, source_id FROM material_properties")
while True:
    block = cur.fetchmany(CH)
    if not block:
        break
    a = np.asarray(block, dtype=np.int64)
    # (crystal, property) occupies the high bits so that >> 6 yields the cell id
    key[i:i + len(a)] = ((a[:, 0] * NPROP + (a[:, 1] - 1)) * SRC_BITS) + a[:, 2]
    i += len(a)
    if i % 20_000_000 < CH:
        log(f"  {i/1e6:.0f}M rows")
assert i == NROW, (i, NROW)
log("read done")

triples = np.unique(key)            # distinct (crystal, property, database)
del key
log(f"distinct (crystal, property, database) triples: {triples.size:,}")

cells, counts = np.unique(triples // SRC_BITS, return_counts=True)
del triples
n_cells = cells.size
log(f"filled cells: {n_cells:,}")

hist = np.bincount(counts)
multi = int((counts >= 2).sum())
prop_of_cell = (cells % NPROP).astype(np.int32) + 1
per_prop: dict[int, list[int]] = {}
for pid in np.unique(prop_of_cell):
    m = prop_of_cell == pid
    per_prop[int(pid)] = [int(m.sum()), int((counts[m] >= 2).sum())]

with (OUT / "cell_sources.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["property", "cells_filled", "cells_with_two_or_more_sources",
                "frac_checkable"])
    rows = [(props[p], a, b, round(b / a, 6) if a else 0.0)
            for p, (a, b) in per_prop.items()]
    rows.sort(key=lambda r: -r[1])
    w.writerows(rows)
log("wrote cell_sources.csv")

summary = {
    "cells_filled": n_cells,
    "cells_with_two_or_more_sources": multi,
    "frac_cells_with_two_or_more_sources": multi / n_cells if n_cells else 0.0,
    "max_sources_on_one_cell": int(counts.max()),
    "cells_by_n_sources": {str(k): int(v) for k, v in enumerate(hist) if v and k},
}
(OUT / "cell_sources.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
