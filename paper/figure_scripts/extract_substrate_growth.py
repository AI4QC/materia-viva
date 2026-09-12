"""Reconstruct the matching substrate as it grew, source by source.

The point the schematic makes in words -- each source is matched against a
larger pool than the one before it -- is a curve, and this recovers it. A
material outside the base merge was admitted by whichever source holds an
`origin` reference to it; ordering those sources by the time they were loaded
gives the size of the substrate that every later source was matched against.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "index" / "materials.sqlite"
OUT = ROOT / "paper" / "data"
BASE_CANDIDATE, BASE_EXPERIMENTAL = 8_125_976, 99_162
BASE_TOTAL = BASE_CANDIDATE + BASE_EXPERIMENTAL

db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.execute("PRAGMA mmap_size = 8000000000")
sources = {i: k for i, k in db.execute("SELECT id, key FROM source_defs")}
MAXPK = db.execute("SELECT MAX(pk) FROM materials").fetchone()[0]

is_base = np.zeros(MAXPK + 1, dtype=bool)
for pk, dataset, idx in db.execute(
        "SELECT pk, dataset, CAST(source_index AS INTEGER) FROM materials"):
    is_base[pk] = idx < (BASE_EXPERIMENTAL if dataset == "experimental" else BASE_CANDIDATE)

# which source claims each admitted material as its own entry
owners: defaultdict[int, set] = defaultdict(set)
for pk, sid, via in db.execute(
        "SELECT material_pk, source_id, match_via FROM material_source_refs"):
    if via == "origin" and not is_base[pk]:
        owners[pk].add(sid)

admitted = Counter()
ambiguous = 0
for pk, srcs in owners.items():
    if len(srcs) == 1:
        admitted[next(iter(srcs))] += 1
    else:
        ambiguous += 1
unattributed = int((~is_base[1:]).sum()) - sum(admitted.values()) - ambiguous

loaded = json.loads(db.execute(
    "SELECT value FROM metadata WHERE key='loaded_property_sources'").fetchone()[0])
sub = {r["source"]: r for r in csv.DictReader((OUT / "substrate_growth.csv").open())}

rows = []
for sid, key in sources.items():
    at = loaded.get(key, {}).get("at", "")
    r = sub.get(key, {})
    rows.append({
        "source": key,
        "loaded_at": at,
        "admitted": admitted[sid],
        "matched_onto_base": int(r.get("matched_onto_base", 0) or 0),
        "matched_onto_admitted": int(r.get("matched_onto_admitted", 0) or 0),
    })
rows.sort(key=lambda r: (r["loaded_at"] or "9999", r["source"]))

# substrate before each source is loaded, and after
size = BASE_TOTAL
for r in rows:
    r["substrate_before"] = size
    size += r["admitted"]
    r["substrate_after"] = size
    tot = r["matched_onto_base"] + r["matched_onto_admitted"]
    r["frac_onto_admitted"] = round(r["matched_onto_admitted"] / tot, 6) if tot else 0.0

with (OUT / "substrate_curve.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

summary = {
    "base_total": BASE_TOTAL,
    "final_total": size,
    "attributed_admissions": sum(admitted.values()),
    "ambiguous_admissions": ambiguous,
    "unattributed_admissions": unattributed,
    "largest_admitters": [(sources[s], n) for s, n in admitted.most_common(6)],
}
(OUT / "substrate_curve.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
