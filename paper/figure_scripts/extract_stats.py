"""Extract every number the manuscript quotes, straight from the published index.

One streaming pass per table. Never a correlated subquery per source: the
property table holds 1.2e8 rows and rescanning it 54 times costs an hour and
counts each source against a different snapshot.
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "index" / "materials.sqlite"
OUT = ROOT / "paper" / "data"
OUT.mkdir(parents=True, exist_ok=True)

t0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)


def write_csv(name: str, header: list[str], rows) -> None:
    path = OUT / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    log(f"wrote {name}")


db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
db.execute("PRAGMA cache_size = -2000000")   # 2 GB page cache
db.execute("PRAGMA temp_store = MEMORY")
db.execute("PRAGMA mmap_size = 8000000000")

sources = {i: (k, n, lic) for i, k, n, lic in
           db.execute("SELECT id, key, name, license FROM source_defs")}
props = {i: (n, u, k) for i, n, u, k in
         db.execute("SELECT id, name, unit, kind FROM property_defs")}
NMAT, MAXPK = db.execute("SELECT COUNT(*), MAX(pk) FROM materials").fetchone()
log(f"{len(sources)} sources, {len(props)} properties, {NMAT} materials, max pk {MAXPK}")

summary: dict[str, object] = {"n_materials": NMAT, "max_pk": MAXPK,
                              "n_sources": len(sources), "n_properties": len(props)}

# ---------------------------------------------------------------- pool shape
rows = db.execute(
    "SELECT dataset, COUNT(*), SUM(n_atoms), AVG(n_atoms), "
    "       SUM(spacegroup_number IS NOT NULL) "
    "FROM materials GROUP BY dataset").fetchall()
write_csv("pool_dataset.csv",
          ["dataset", "n_materials", "total_sites", "mean_sites", "with_spacegroup"], rows)
summary["pool_dataset"] = {r[0]: r[1] for r in rows}

rows = db.execute(
    "SELECT COALESCE(material_family, 'bulk'), COUNT(*) "
    "FROM materials GROUP BY 1 ORDER BY 2 DESC").fetchall()
write_csv("pool_family.csv", ["family", "n_materials"], rows)

rows = db.execute(
    "SELECT crystal_system, COUNT(*) FROM materials GROUP BY 1 ORDER BY 2 DESC").fetchall()
write_csv("pool_crystal_system.csv", ["crystal_system", "n_materials"], rows)

rows = db.execute(
    "SELECT n_elements, COUNT(*) FROM materials GROUP BY 1 ORDER BY 1").fetchall()
write_csv("pool_n_elements.csv", ["n_elements", "n_materials"], rows)

rows = db.execute(
    "SELECT element, COUNT(*) FROM material_elements GROUP BY 1 ORDER BY 2 DESC").fetchall()
write_csv("pool_elements.csv", ["element", "n_materials"], rows)
log("pool shape done")

# ------------------------------------------------- material_source_refs pass
# PK is (material_pk, source_id, native_id) WITHOUT ROWID, so this scan already
# arrives grouped by material: the per-material source set never needs a sort.
via_counts: Counter = Counter()          # (source_id, via_kind) -> refs
src_materials: Counter = Counter()       # source_id -> distinct materials
degree_hist: Counter = Counter()         # n distinct sources -> n materials
pair_counts: Counter = Counter()         # (src_a, src_b) -> shared materials
multi_source_pks = bytearray((MAXPK >> 3) + 1)

cur = db.execute(
    "SELECT material_pk, source_id, match_via FROM material_source_refs")
current_pk = None
current: set[int] = set()
n_refs = 0


def flush(pk: int, srcs: set[int]) -> None:
    degree_hist[len(srcs)] += 1
    for s in srcs:
        src_materials[s] += 1
    if len(srcs) > 1:
        multi_source_pks[pk >> 3] |= 1 << (pk & 7)
        ordered = sorted(srcs)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                pair_counts[(a, b)] += 1


for pk, sid, via in cur:
    n_refs += 1
    kind = via.split(":", 1)[0] if via.startswith("id:") else via
    via_counts[(sid, kind)] += 1
    if pk != current_pk:
        if current_pk is not None:
            flush(current_pk, current)
        current_pk, current = pk, set()
    current.add(sid)
if current_pk is not None:
    flush(current_pk, current)
log(f"source-ref pass done: {n_refs} refs")

summary["n_source_refs"] = n_refs
summary["n_annotated_materials"] = sum(degree_hist.values())
summary["n_multi_source_materials"] = sum(n for d, n in degree_hist.items() if d > 1)

write_csv("source_degree.csv", ["n_sources", "n_materials"],
          sorted(degree_hist.items()))
write_csv("source_overlap.csv", ["source_a", "source_b", "n_shared"],
          [(sources[a][0], sources[b][0], n)
           for (a, b), n in sorted(pair_counts.items(), key=lambda kv: -kv[1])])

# --------------------------------------------------- material_properties pass
# Scanned through idx_props_lookup(property_id, source_id, material_pk), so the
# stream is already ordered and distinct-material counting is a running compare.
ps_rows: Counter = Counter()             # (property_id, source_id) -> rows
ps_materials: Counter = Counter()        # (property_id, source_id) -> distinct materials
prop_bitmap = bytearray((MAXPK >> 3) + 1)
prop_materials: dict[int, int] = {}
prop_multi: dict[int, int] = {}          # property -> materials with >=2 sources
src_prop_rows: Counter = Counter()       # source_id -> rows
src_props: defaultdict[int, set] = defaultdict(set)
any_prop_bitmap = bytearray((MAXPK >> 3) + 1)

cur = db.execute(
    "SELECT property_id, source_id, material_pk FROM material_properties "
    "ORDER BY property_id, source_id, material_pk")

cur_prop = None
cur_src = None
last_pk = -1
n_rows = 0
prop_count = 0
prop_multi_count = 0
# per-property second bitmap: material already seen under a *different* source
prop_seen_once = bytearray((MAXPK >> 3) + 1)
prop_seen_multi = bytearray((MAXPK >> 3) + 1)


def close_property(pid: int) -> None:
    global prop_count, prop_multi_count
    prop_materials[pid] = prop_count
    prop_multi[pid] = prop_multi_count
    prop_count = 0
    prop_multi_count = 0


for pid, sid, pk in cur:
    n_rows += 1
    if pid != cur_prop:
        if cur_prop is not None:
            close_property(cur_prop)
            # clear only the bytes we touched is not worth it; reallocate
            prop_seen_once = bytearray((MAXPK >> 3) + 1)
            prop_seen_multi = bytearray((MAXPK >> 3) + 1)
        cur_prop, cur_src, last_pk = pid, None, -1
    if sid != cur_src:
        cur_src, last_pk = sid, -1
    src_prop_rows[sid] += 1
    src_props[sid].add(pid)
    ps_rows[(pid, sid)] += 1
    if pk != last_pk:
        last_pk = pk
        ps_materials[(pid, sid)] += 1
        byte, bit = pk >> 3, 1 << (pk & 7)
        if not (prop_seen_once[byte] & bit):
            prop_seen_once[byte] |= bit
            prop_count += 1
        elif not (prop_seen_multi[byte] & bit):
            prop_seen_multi[byte] |= bit
            prop_multi_count += 1
        if not (any_prop_bitmap[byte] & bit):
            any_prop_bitmap[byte] |= bit
    if n_rows % 20_000_000 == 0:
        log(f"  property pass {n_rows/1e6:.0f}M rows")
if cur_prop is not None:
    close_property(cur_prop)
log(f"property pass done: {n_rows} rows")

summary["n_property_rows"] = n_rows
summary["n_materials_with_any_property"] = sum(bin(b).count("1") for b in any_prop_bitmap)

write_csv("properties.csv",
          ["property", "unit", "kind", "rows", "n_sources", "n_materials",
           "n_materials_multi_source", "coverage_fraction"],
          [(props[pid][0], props[pid][1], props[pid][2],
            sum(v for (p, _), v in ps_rows.items() if p == pid),
            len({s for (p, s) in ps_rows if p == pid}),
            prop_materials.get(pid, 0), prop_multi.get(pid, 0),
            round(prop_materials.get(pid, 0) / NMAT, 8))
           for pid in sorted(props, key=lambda p: -prop_materials.get(p, 0))])

write_csv("property_source_matrix.csv",
          ["property", "source", "rows", "n_materials"],
          [(props[p][0], sources[s][0], ps_rows[(p, s)], ps_materials[(p, s)])
           for (p, s) in sorted(ps_rows, key=lambda k: -ps_rows[k])])

# ------------------------------------------------------------------- curves
rows = db.execute(
    "SELECT curve_type, source_id, fmt, COUNT(*), COUNT(DISTINCT material_pk) "
    "FROM material_curves GROUP BY 1, 2, 3").fetchall()
write_csv("curves.csv", ["curve_type", "source", "fmt", "n_curves", "n_materials"],
          [(t, sources[s][0], f, n, m) for t, s, f, n, m in rows])
n_curve, n_curve_mat = db.execute(
    "SELECT COUNT(*), COUNT(DISTINCT material_pk) FROM material_curves").fetchone()
summary["n_curves"] = n_curve
summary["n_materials_with_curves"] = n_curve_mat
log("curves done")

# ------------------------------------------------------------------ sources
loaded = json.loads(db.execute(
    "SELECT value FROM metadata WHERE key='loaded_property_sources'").fetchone()[0])
rows = []
for sid, (key, name, lic) in sorted(sources.items(), key=lambda kv: -src_prop_rows[kv[0]]):
    meta = loaded.get(key, {})
    rows.append((
        key, name, lic,
        src_prop_rows[sid], len(src_props[sid]), src_materials[sid],
        via_counts[(sid, "id")], via_counts[(sid, "hash")], via_counts[(sid, "origin")],
        meta.get("new_structures", 0), meta.get("matched_refs", 0), meta.get("at", "")))
write_csv("sources.csv",
          ["key", "name", "license", "property_rows", "n_properties", "n_materials",
           "refs_id", "refs_hash", "refs_origin", "new_structures", "matched_refs",
           "loaded_at"], rows)

(OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
log("summary.json written")
log("DONE")
