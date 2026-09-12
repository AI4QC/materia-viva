"""How much of the property layer a structure's own contributor did not supply.

Deduplication is usually justified by what it removes. This measures what it
adds: property values that sit on a crystal because some *other* database
computed them, not the one that put the crystal in the pool.

Every material has exactly one structural contributor. For the 8,225,138 that
came from the deduplicated base merge that contributor is the merge itself,
which carried structures and no properties, so every one of their property
values is by construction externally supplied; those are reported separately
rather than mixed in, because counting them would inflate the result for free.
The informative population is the structures admitted during integration, where
the contributor is one of the source databases and did bring a property layer of
its own.

Two bitmaps over the (material, property) grid do the work in one table scan:
one marks a cell occupied at all, the other marks it supplied by the material's
own contributor. The difference is the cell the contributor left empty.

The contributor-relative figure is bounded by ingestion order. A structure's
contributor is whichever database introduced it, so only databases loaded
*after* that one can annotate it; the last source loaded is necessarily at zero,
because the structures it contributed are exactly those no earlier source held.
The same scan therefore also reports an order-independent companion -- how many
materials draw property values from two or more databases at all -- which does
not depend on who arrived first.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "index" / "materials.sqlite"
OUT = ROOT / "paper" / "data"
BASE_CANDIDATE, BASE_EXPERIMENTAL = 8_125_976, 99_162

t0 = time.time()
log = lambda m: print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.execute("PRAGMA cache_size = -1500000")
db.execute("PRAGMA mmap_size = 8000000000")
sources = {i: k for i, k in db.execute("SELECT id, key FROM source_defs")}
props = {i: n for i, n in db.execute("SELECT id, name FROM property_defs")}
NMAT, MAXPK = db.execute("SELECT COUNT(*), MAX(pk) FROM materials").fetchone()
NPROP = max(props) if props else 0
log(f"{NMAT:,} materials, {len(sources)} sources, {len(props)} properties")

# ---- structural contributor per material: 0 = base merge, else source id
contributor = np.zeros(MAXPK + 1, dtype=np.int16)
is_base = np.zeros(MAXPK + 1, dtype=bool)
for pk, dataset, idx in db.execute(
        "SELECT pk, dataset, CAST(source_index AS INTEGER) FROM materials"):
    is_base[pk] = idx < (BASE_EXPERIMENTAL if dataset == "experimental" else BASE_CANDIDATE)
log(f"base-merge materials: {int(is_base.sum()):,}")

owners: defaultdict[int, set] = defaultdict(set)
for pk, sid, via in db.execute(
        "SELECT material_pk, source_id, match_via FROM material_source_refs"):
    if via == "origin" and not is_base[pk]:
        owners[pk].add(sid)
for pk, srcs in owners.items():
    if len(srcs) == 1:
        contributor[pk] = next(iter(srcs))
del owners
admitted = int((contributor > 0).sum())
log(f"admitted materials with a single unambiguous contributor: {admitted:,}")

# ---- one scan, two bitmaps over the (material, property) grid
NBYTE = (NPROP + 8) // 8
occupied = np.zeros((MAXPK + 1, NBYTE), dtype=np.uint8)
by_owner = np.zeros((MAXPK + 1, NBYTE), dtype=np.uint8)
# order-independent companion: does this material draw values from >1 database?
first_supplier = np.zeros(MAXPK + 1, dtype=np.int16)
multi_supplier = np.zeros(MAXPK + 1, dtype=bool)

n = 0
for pk, pid, sid in db.execute(
        "SELECT material_pk, property_id, source_id FROM material_properties"):
    n += 1
    idx = pid - 1
    byte, bit = idx >> 3, np.uint8(1 << (idx & 7))
    occupied[pk, byte] |= bit
    if sid == contributor[pk]:
        by_owner[pk, byte] |= bit
    prev = first_supplier[pk]
    if prev == 0:
        first_supplier[pk] = sid
    elif prev != sid:
        multi_supplier[pk] = True
    if n % 25_000_000 == 0:
        log(f"  {n/1e6:.0f}M rows")
log(f"scan done: {n:,} rows")

# ---- reduce, restricted to admitted materials with a real contributor
own_mask = contributor > 0
# bitorder must match the packing above: bit (idx & 7) was set as 1 << (idx & 7),
# which is little-endian within the byte. numpy unpacks big-endian by default,
# which silently reverses the property columns inside every group of eight and
# produces a per-property table that looks plausible but is scrambled.
occ_bits = np.unpackbits(occupied, axis=1, bitorder="little")
own_bits = np.unpackbits(by_owner, axis=1, bitorder="little")
filled_by_other = occ_bits & ~own_bits

cells_occ_admitted = int(occ_bits[own_mask].sum())
cells_own_admitted = int(own_bits[own_mask].sum())
cells_ext_admitted = int(filled_by_other[own_mask].sum())
mats_any_ext = int((filled_by_other[own_mask].sum(axis=1) > 0).sum())
mats_any_cell = int((occ_bits[own_mask].sum(axis=1) > 0).sum())

cells_occ_base = int(occ_bits[is_base].sum())
cells_occ_all = int(occ_bits.sum())
has_any = first_supplier > 0
n_multi_supplier = int(multi_supplier.sum())
n_any_supplier = int(has_any.sum())
log(f"materials drawing property values from >=2 databases: {n_multi_supplier:,} "
    f"of {n_any_supplier:,} annotated ({n_multi_supplier/max(n_any_supplier,1):.2%})")

# per contributing source
rows = []
for sid, key in sources.items():
    m = contributor == sid
    if not m.any():
        continue
    occ = int(occ_bits[m].sum()); own = int(own_bits[m].sum())
    ext = int(filled_by_other[m].sum())
    n_mat = int(m.sum())
    n_ext_mat = int((filled_by_other[m].sum(axis=1) > 0).sum())
    rows.append((key, n_mat, n_ext_mat, occ, own, ext,
                 round(ext / occ, 6) if occ else 0.0,
                 round(n_ext_mat / n_mat, 6) if n_mat else 0.0))
rows.sort(key=lambda r: -r[1])
with (OUT / "crossfill_sources.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["source", "structures_contributed", "structures_with_external_property",
                "cells_occupied", "cells_from_contributor", "cells_from_others",
                "frac_cells_external", "frac_structures_with_external"])
    w.writerows(rows)
log("wrote crossfill_sources.csv")

# per property, over admitted materials
prows = []
for pid, name in props.items():
    col = pid - 1
    if col >= occ_bits.shape[1]:
        continue
    occ = int(occ_bits[own_mask, col].sum())
    if occ == 0:
        continue
    ext = int(filled_by_other[own_mask, col].sum())
    prows.append((name, occ, occ - ext, ext, round(ext / occ, 6)))
prows.sort(key=lambda r: -r[1])
with (OUT / "crossfill_properties.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["property", "cells_on_admitted", "from_contributor", "from_others",
                "frac_external"])
    w.writerows(prows)
log("wrote crossfill_properties.csv")

summary = {
    "materials_total": NMAT,
    "materials_base_merge": int(is_base.sum()),
    "materials_admitted_single_contributor": admitted,
    "cells_occupied_all": cells_occ_all,
    "cells_occupied_base_merge": cells_occ_base,
    "cells_occupied_admitted": cells_occ_admitted,
    "cells_from_contributor_admitted": cells_own_admitted,
    "cells_from_other_databases_admitted": cells_ext_admitted,
    "frac_cells_external_admitted":
        cells_ext_admitted / cells_occ_admitted if cells_occ_admitted else 0.0,
    "admitted_materials_with_any_property": mats_any_cell,
    "admitted_materials_with_external_property": mats_any_ext,
    "frac_admitted_materials_with_external":
        mats_any_ext / mats_any_cell if mats_any_cell else 0.0,
    # order-independent: no reference to who contributed the structure
    "materials_with_any_property": n_any_supplier,
    "materials_with_two_or_more_property_sources": n_multi_supplier,
    "frac_materials_with_two_or_more_property_sources":
        n_multi_supplier / n_any_supplier if n_any_supplier else 0.0,
}
(OUT / "crossfill.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
