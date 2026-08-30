"""One table scan that answers two questions the index alone cannot.

1. How complete is the 13.5M x 166 property matrix, per material?
2. When two independent databases report the same property for the same
   crystal, do they agree?

Question 2 is only askable because deduplication put the two records on one
material and provenance kept them apart afterwards. Both answers come from a
single sequential pass over material_properties; the table is ~1.2e8 rows and
re-reading it once per property would take hours.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from array import array
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "index" / "materials.sqlite"
OUT = ROOT / "paper" / "data"
OUT.mkdir(parents=True, exist_ok=True)

#: Properties whose values are directly comparable between databases once the
#: method string is held fixed. Extensive or convention-dependent quantities
#: (total energies, prototype labels) are deliberately excluded: two databases
#: disagreeing on a total energy reflects a different reference, not a
#: different answer.
COMPARABLE = {
    "band_gap": 0.05,                    # eV, tolerance for "agrees"
    "formation_energy_per_atom": 0.05,   # eV/atom
    "energy_above_hull": 0.05,           # eV/atom
    "total_magnetization": 0.05,         # muB
    "density": 0.02,                     # g/cm3 (relative below)
    "bulk_modulus_vrh": 5.0,             # GPa
    "volume_per_atom": 0.2,              # A^3/atom
    "shear_modulus_vrh": 5.0,            # GPa
}
#: compared as a relative rather than absolute difference
RELATIVE = {"density", "volume_per_atom"}

t0 = time.time()


def log(m: str) -> None:
    print(f"[{time.time() - t0:7.1f}s] {m}", flush=True)


def write_csv(name: str, header, rows) -> None:
    with (OUT / name).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    log(f"wrote {name}")


db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.execute("PRAGMA cache_size = -1500000")
db.execute("PRAGMA mmap_size = 8000000000")

sources = {i: k for i, k in db.execute("SELECT id, key FROM source_defs")}
props = {i: n for i, n in db.execute("SELECT id, name FROM property_defs")}
prop_id = {n: i for i, n in props.items()}
NMAT, MAXPK = db.execute("SELECT COUNT(*), MAX(pk) FROM materials").fetchone()
watch = {prop_id[n]: n for n in COMPARABLE if n in prop_id}
log(f"watching {len(watch)} comparable properties over {MAXPK} materials")

# property-presence bitmap: 166 properties -> 21 bytes per material
NBYTE = (len(props) + 8) // 8
bitmap = np.zeros((MAXPK + 1, NBYTE), dtype=np.uint8)

# collected values for the comparable properties
buf_pk = {p: array("i") for p in watch}
buf_src = {p: array("h") for p in watch}
buf_val = {p: array("d") for p in watch}
buf_meth = {p: array("i") for p in watch}
methods: dict[int, dict[str, int]] = {p: {} for p in watch}
method_names: dict[int, list[str]] = {p: [] for p in watch}

n = 0
cur = db.execute(
    "SELECT material_pk, property_id, source_id, value_num, method "
    "FROM material_properties")
for pk, pid, sid, val, meth in cur:
    n += 1
    idx = pid - 1
    bitmap[pk, idx >> 3] |= np.uint8(1 << (idx & 7))
    if pid in watch and val is not None:
        key = meth or ""
        table = methods[pid]
        code = table.get(key)
        if code is None:
            code = len(method_names[pid])
            table[key] = code
            method_names[pid].append(key)
        buf_pk[pid].append(pk)
        buf_src[pid].append(sid)
        buf_val[pid].append(val)
        buf_meth[pid].append(code)
    if n % 20_000_000 == 0:
        log(f"  {n/1e6:.0f}M rows")
log(f"scan done: {n} rows")

# ------------------------------------------------- per-material completeness
popcount = np.unpackbits(bitmap, axis=1).sum(axis=1).astype(np.int32)
popcount[0] = 0
hist = Counter(popcount[1:].tolist())
write_csv("material_property_count.csv", ["n_properties", "n_materials"],
          sorted(hist.items()))
filled = int(popcount[1:].sum())
summary = {
    "matrix_cells": NMAT * len(props),
    "matrix_filled": filled,
    "matrix_fill_fraction": filled / (NMAT * len(props)),
    "median_properties_per_material": int(np.median(popcount[1:])),
    "materials_with_zero_properties": int((popcount[1:] == 0).sum()),
}
log(f"completeness: {summary}")
del bitmap, popcount

# ------------------------------------------------------- cross-source agreement
pair_rows = []
spread_rows = []
per_prop = []
for pid, name in watch.items():
    pk = np.frombuffer(buf_pk[pid], dtype=np.int32)
    sid = np.frombuffer(buf_src[pid], dtype=np.int16)
    val = np.frombuffer(buf_val[pid], dtype=np.float64)
    mth = np.frombuffer(buf_meth[pid], dtype=np.int32)
    if pk.size == 0:
        continue
    order = np.argsort(pk, kind="stable")
    pk, sid, val, mth = pk[order], sid[order], val[order], mth[order]
    # group boundaries
    starts = np.flatnonzero(np.r_[True, pk[1:] != pk[:-1]])
    ends = np.r_[starts[1:], pk.size]
    rel = name in RELATIVE
    tol = COMPARABLE[name]

    pair_stat: dict[tuple[int, int], list] = defaultdict(list)
    spreads = []
    n_multi = 0
    for s, e in zip(starts, ends):
        if e - s < 2:
            continue
        gs, gv = sid[s:e], val[s:e]
        uniq = np.unique(gs)
        if uniq.size < 2:
            continue
        n_multi += 1
        # one value per source: median within source, so a source reporting the
        # same quantity under several methods is not counted twice
        vals = np.array([np.median(gv[gs == u]) for u in uniq])
        lo, hi = vals.min(), vals.max()
        spreads.append((hi - lo) / max(abs(hi), abs(lo), 1e-9) if rel else hi - lo)
        for i in range(uniq.size):
            for j in range(i + 1, uniq.size):
                a, b = int(uniq[i]), int(uniq[j])
                d = vals[j] - vals[i]
                if rel:
                    d = d / max(abs(vals[i]), 1e-9)
                pair_stat[(a, b)].append((vals[i], vals[j], d))
    spreads = np.array(spreads) if spreads else np.zeros(0)
    for (a, b), triples in pair_stat.items():
        if len(triples) < 200:
            continue
        arr = np.array(triples)
        d = arr[:, 2]
        pair_rows.append((
            name, sources[a], sources[b], len(triples),
            float(np.median(d)), float(np.median(np.abs(d))),
            float(np.mean(np.abs(d) <= tol)),
            float(np.corrcoef(arr[:, 0], arr[:, 1])[0, 1])
            if arr[:, 0].std() > 0 and arr[:, 1].std() > 0 else float("nan"),
        ))
    if spreads.size:
        qs = np.percentile(spreads, [50, 75, 90, 95, 99])
        per_prop.append((
            name, int(pk.size), int(n_multi), len(method_names[pid]),
            float(np.mean(spreads <= tol)), *[float(q) for q in qs],
            float(spreads.max())))
        # store the full spread distribution, thinned for plotting
        step = max(1, spreads.size // 20000)
        for v in np.sort(spreads)[::step]:
            spread_rows.append((name, float(v)))
    log(f"  {name}: {pk.size} values, {n_multi} multi-source materials")

write_csv("agreement_pairs.csv",
          ["property", "source_a", "source_b", "n_shared", "median_signed_diff",
           "median_abs_diff", "frac_within_tol", "pearson_r"],
          sorted(pair_rows, key=lambda r: (r[0], -r[3])))
write_csv("agreement_per_property.csv",
          ["property", "n_values", "n_multi_source_materials", "n_methods",
           "frac_within_tol", "p50_spread", "p75_spread", "p90_spread",
           "p95_spread", "p99_spread", "max_spread"], per_prop)
write_csv("agreement_spread_samples.csv", ["property", "spread"], spread_rows)
write_csv("agreement_methods.csv", ["property", "method", "code"],
          [(props[p], m, c) for p, names in method_names.items()
           for c, m in enumerate(names)])

(OUT / "completeness.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
log("DONE")
