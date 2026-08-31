"""Separate substrate growth from a source's own admissions.

`refs_to_admitted` in evolution_sources.csv counts every reference that lands
on a structure absent from the base merge -- including the structures the
source itself contributed. The quantity that actually demonstrates a growing
identity substrate is narrower: references resolved by *matching* (an
authoritative id or a fingerprint, never an origin claim) onto a structure some
earlier source admitted. Those are matches that would have missed had the same
source been loaded first.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "index" / "materials.sqlite"
OUT = ROOT / "paper" / "data"
BASE_CANDIDATE, BASE_EXPERIMENTAL = 8_125_976, 99_162

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.execute("PRAGMA mmap_size = 8000000000")
sources = {i: k for i, k in db.execute("SELECT id, key FROM source_defs")}
MAXPK = db.execute("SELECT MAX(pk) FROM materials").fetchone()[0]

is_base = np.zeros(MAXPK + 1, dtype=bool)
for pk, dataset, idx in db.execute(
        "SELECT pk, dataset, CAST(source_index AS INTEGER) FROM materials"):
    is_base[pk] = idx < (BASE_EXPERIMENTAL if dataset == "experimental" else BASE_CANDIDATE)

matched_base: Counter = Counter()
matched_grown: Counter = Counter()
origin: Counter = Counter()
for pk, sid, via in db.execute(
        "SELECT material_pk, source_id, match_via FROM material_source_refs"):
    if via == "origin":
        origin[sid] += 1
    elif is_base[pk]:
        matched_base[sid] += 1
    else:
        matched_grown[sid] += 1

loaded = json.loads(db.execute(
    "SELECT value FROM metadata WHERE key='loaded_property_sources'").fetchone()[0])
rows = []
for sid, key in sources.items():
    mb, mg, og = matched_base[sid], matched_grown[sid], origin[sid]
    rows.append((key, loaded.get(key, {}).get("at", ""), mb, mg, og,
                 round(mg / (mb + mg), 6) if mb + mg else 0.0))
rows.sort(key=lambda r: (r[1] or "9999", r[0]))
with (OUT / "substrate_growth.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["source", "loaded_at", "matched_onto_base", "matched_onto_admitted",
                "origin_refs", "frac_matches_onto_admitted"])
    w.writerows(rows)

total_mb, total_mg = sum(matched_base.values()), sum(matched_grown.values())
summary = {
    "matched_onto_base": total_mb,
    "matched_onto_admitted": total_mg,
    "frac_matches_onto_admitted": total_mg / (total_mb + total_mg),
    "origin_refs": sum(origin.values()),
}
(OUT / "substrate_growth.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
