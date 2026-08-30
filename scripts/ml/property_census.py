#!/usr/bin/env python3
"""Census of trainable property data in the MateriaViva index.

One sequential pass over ``material_properties`` (121M rows) grouped by
(property, source, method), plus a per-property distinct-material count.
Both are written as JSON so the ranking/threshold logic can be re-run
without touching the 21 GB database again.

Usage
-----
    python scripts/ml/property_census.py --db data/index/materials.sqlite \
        --out data/ml/census

Outputs
-------
``census_groups.json``   per (property, source, method) rows + value stats
``census_property.json`` per property: distinct materials, method split, verdict
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

# A GNN needs enough independent structures to fit; these thresholds mirror
# what the community treats as viable (matbench's smallest task is 312 rows,
# but 312 only works for very smooth targets with heavy regularisation).
TIERS = (
    (100_000, "tier1-large"),
    (10_000, "tier2-solid"),
    (2_000, "tier3-small"),
    (300, "tier4-fewshot"),
    (0, "tier5-insufficient"),
)


def tier(n: int) -> str:
    for floor, name in TIERS:
        if n >= floor:
            return name
    return "tier5-insufficient"


def scan_groups(con: sqlite3.Connection) -> list[dict]:
    """Full sequential scan: rows and value stats per property/source/method."""
    sql = """
        SELECT p.property_id, p.source_id, COALESCE(p.method, ''),
               COUNT(*),
               SUM(p.value_num IS NOT NULL),
               SUM(p.value_text IS NOT NULL),
               MIN(p.value_num), MAX(p.value_num), AVG(p.value_num)
        FROM material_properties p
        GROUP BY p.property_id, p.source_id, COALESCE(p.method, '')
    """
    out = []
    for row in con.execute(sql):
        out.append(
            {
                "property_id": row[0],
                "source_id": row[1],
                "method": row[2],
                "n_rows": row[3],
                "n_num": row[4],
                "n_text": row[5],
                "min": row[6],
                "max": row[7],
                "mean": row[8],
            }
        )
    return out


def scan_distinct(con: sqlite3.Connection) -> dict[int, int]:
    """Distinct materials per property -- the real training-set size."""
    sql = """
        SELECT property_id, COUNT(DISTINCT material_pk)
        FROM material_properties GROUP BY property_id
    """
    return {int(pid): int(n) for pid, n in con.execute(sql)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/index/materials.sqlite", type=Path)
    ap.add_argument("--out", default="data/ml/census", type=Path)
    ap.add_argument(
        "--skip-distinct",
        action="store_true",
        help="reuse an existing census_property.json distinct count",
    )
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.execute("PRAGMA temp_store=FILE")
    con.execute("PRAGMA cache_size=-2000000")  # 2 GB page cache

    props = {
        int(i): {"name": n, "unit": u or "", "kind": k}
        for i, n, u, k in con.execute("SELECT id,name,unit,kind FROM property_defs")
    }
    sources = {int(i): k for i, k in con.execute("SELECT id,key FROM source_defs")}

    t0 = time.time()
    print("scanning groups (full table pass)...", file=sys.stderr, flush=True)
    groups = scan_groups(con)
    print(f"  {len(groups)} groups in {time.time() - t0:.0f}s", file=sys.stderr)

    for g in groups:
        g["property"] = props.get(g["property_id"], {}).get("name", "?")
        g["source"] = sources.get(g["source_id"], "?")
    (args.out / "census_groups.json").write_text(json.dumps(groups, indent=1))

    distinct_path = args.out / "census_property.json"
    if args.skip_distinct and distinct_path.exists():
        distinct = {
            int(p["property_id"]): p["n_materials"]
            for p in json.loads(distinct_path.read_text())
        }
    else:
        t0 = time.time()
        print("scanning distinct materials per property...", file=sys.stderr, flush=True)
        distinct = scan_distinct(con)
        print(f"  done in {time.time() - t0:.0f}s", file=sys.stderr)

    per_prop: dict[int, dict] = {}
    for g in groups:
        pid = g["property_id"]
        rec = per_prop.setdefault(
            pid,
            {
                "property_id": pid,
                "property": g["property"],
                "unit": props.get(pid, {}).get("unit", ""),
                "kind": props.get(pid, {}).get("kind", "num"),
                "n_rows": 0,
                "n_materials": distinct.get(pid, 0),
                "sources": {},
                "methods": {},
            },
        )
        rec["n_rows"] += g["n_rows"]
        rec["sources"][g["source"]] = rec["sources"].get(g["source"], 0) + g["n_rows"]
        key = g["method"] or "(unspecified)"
        rec["methods"][key] = rec["methods"].get(key, 0) + g["n_rows"]

    out = sorted(per_prop.values(), key=lambda r: -r["n_materials"])
    for rec in out:
        rec["n_sources"] = len(rec["sources"])
        rec["n_methods"] = len(rec["methods"])
        rec["dup_ratio"] = round(rec["n_rows"] / max(rec["n_materials"], 1), 3)
        rec["tier"] = tier(rec["n_materials"])
        rec["sources"] = dict(sorted(rec["sources"].items(), key=lambda kv: -kv[1]))
        rec["methods"] = dict(sorted(rec["methods"].items(), key=lambda kv: -kv[1]))
    distinct_path.write_text(json.dumps(out, indent=1))
    print(f"wrote {args.out}/census_groups.json and census_property.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
