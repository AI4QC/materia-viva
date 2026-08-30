"""Measure the one thing that makes the index self-extending.

Every structure a source admits has its fingerprint and native ids written back
into the match map, so the *next* source matches against a larger identity
substrate than the previous one did. That is testable: split each source's
references by whether the material they point at came from the original base
merge or was admitted later during integration, and order the result by the
time each source was loaded.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "index" / "materials.sqlite"
OUT = ROOT / "paper" / "data"

#: sizes of the two halves of the deduplicated base merge, from metadata.build_report
BASE_CANDIDATE = 8_125_976
BASE_EXPERIMENTAL = 99_162
BASE_TOTAL = BASE_CANDIDATE + BASE_EXPERIMENTAL

t0 = time.time()
log = lambda m: print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.execute("PRAGMA cache_size = -1000000")
db.execute("PRAGMA mmap_size = 8000000000")

sources = {i: k for i, k in db.execute("SELECT id, key FROM source_defs")}
NMAT, MAXPK = db.execute("SELECT COUNT(*), MAX(pk) FROM materials").fetchone()

# is_base[pk] == 1 when this material came from the deduplicated base merge
is_base = np.zeros(MAXPK + 1, dtype=bool)
for pk, dataset, idx in db.execute(
        "SELECT pk, dataset, CAST(source_index AS INTEGER) FROM materials"):
    limit = BASE_EXPERIMENTAL if dataset == "experimental" else BASE_CANDIDATE
    is_base[pk] = idx < limit
log(f"base merge {int(is_base.sum())} of {NMAT} materials")

ref_base: Counter = Counter()
ref_grown: Counter = Counter()
for pk, sid in db.execute("SELECT material_pk, source_id FROM material_source_refs"):
    (ref_base if is_base[pk] else ref_grown)[sid] += 1
log("ref split done")

loaded = json.loads(db.execute(
    "SELECT value FROM metadata WHERE key='loaded_property_sources'").fetchone()[0])

rows = []
for sid, key in sources.items():
    meta = loaded.get(key, {})
    b, g = ref_base[sid], ref_grown[sid]
    rows.append((key, meta.get("at", ""), b, g, b + g,
                 round(g / (b + g), 6) if b + g else 0.0,
                 meta.get("new_structures", 0)))
rows.sort(key=lambda r: (r[1] or "9999", r[0]))
with (OUT / "evolution_sources.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["source", "loaded_at", "refs_to_base_merge", "refs_to_admitted",
                "refs_total", "frac_refs_to_admitted", "new_structures_reported"])
    w.writerows(rows)
log("wrote evolution_sources.csv")

summary = {
    "base_merge_total": BASE_TOTAL,
    "base_merge_candidate": BASE_CANDIDATE,
    "base_merge_experimental": BASE_EXPERIMENTAL,
    "admitted_during_integration": NMAT - BASE_TOTAL,
    "growth_fraction": (NMAT - BASE_TOTAL) / BASE_TOTAL,
    "refs_to_base_merge": sum(ref_base.values()),
    "refs_to_admitted": sum(ref_grown.values()),
}
(OUT / "evolution.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
log(json.dumps(summary))
