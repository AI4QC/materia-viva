#!/usr/bin/env python3
"""Trainable tasks: one property at one level of theory, with its material count.

``property_census.py`` reports per property and per (property, source, method);
neither answers the question a training plan actually asks, which is how many
distinct crystals carry a given property *at a given level of theory*.  A single
property name covers several physical quantities -- a semilocal band gap and a
hybrid one are not interchangeable labels -- so the task, not the property, is
the unit that can be trained.

This regenerates ``task_census.json``, which Figure 4 of the manuscript reads.
It used to be an ad-hoc artifact with no producer in the repository, which meant
it silently survived a re-ingest and described a corpus that no longer existed.

One sequential pass over material_properties, packing (property, level, material)
into an int64 so the distinct count is a single np.unique rather than 151
separate scans or a bitmap per level.

    python scripts/ml/task_census.py --out data/ml/census
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from array import array
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.ml.method_groups import (  # noqa: E402
    CONDITION_SPLIT_PROPERTIES,
    condition_key,
    theory_level,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/index/materials.sqlite", type=Path)
    ap.add_argument("--out", default="data/ml/census", type=Path)
    args = ap.parse_args()

    t0 = time.time()
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    db.execute("PRAGMA cache_size = -1500000")
    db.execute("PRAGMA mmap_size = 8000000000")
    props = {i: (n, u, k) for i, n, u, k in
             db.execute("SELECT id, name, unit, kind FROM property_defs")}
    sources = {i: k for i, k in db.execute("SELECT id, key FROM source_defs")}

    # What separates two tasks depends on the property.  For most, it is the
    # level of theory: a semilocal band gap and a hybrid one are different
    # quantities.  For the condition-dependent properties it is the condition
    # itself -- co2_uptake holds four GCMC conditions per framework, and
    # collapsing them to a level of theory would merge four physical targets
    # into one.  Grouping the wrong way here is what silently turns a task
    # count of 497 into 281.
    cond_props = {pid for pid, (name, _u, _k) in props.items()
                  if name in CONDITION_SPLIT_PROPERTIES}
    key_cache: dict[tuple[bool, str | None], int] = {}
    level_names: list[str] = []
    level_index: dict[str, int] = {}

    def level_code(pid: int, method: str | None) -> int:
        by_condition = pid in cond_props
        cache_key = (by_condition, method)
        code = key_cache.get(cache_key)
        if code is None:
            name = condition_key(method) if by_condition else theory_level(method)
            code = level_index.get(name)
            if code is None:
                code = len(level_names)
                level_names.append(name)
                level_index[name] = code
            key_cache[cache_key] = code
        return code

    packed = array("q")
    n = 0
    for pid, pk, method in db.execute(
            "SELECT property_id, material_pk, method FROM material_properties"):
        # property (14 bits) | task key (18 bits) | material (32 bits)
        packed.append((pid << 50) | (level_code(pid, method) << 32) | pk)
        n += 1
        if n % 25_000_000 == 0:
            print(f"  {n/1e6:.0f}M rows  {time.time()-t0:.0f}s", flush=True)
    print(f"scan done: {n:,} rows, {len(level_names)} distinct task keys "
          f"({time.time()-t0:.0f}s)", flush=True)

    keys = np.frombuffer(packed, dtype=np.int64)
    del packed
    keys = np.unique(keys)                      # distinct (property, level, material)
    print(f"distinct (property, level, material): {len(keys):,} "
          f"({time.time()-t0:.0f}s)", flush=True)

    group = keys >> 32                          # property | task key
    edges = np.flatnonzero(np.r_[True, group[1:] != group[:-1]])
    counts = np.diff(np.r_[edges, len(group)])
    gids = group[edges]

    per_prop: dict[int, list[tuple[str, int]]] = {}
    for gid, count in zip(gids.tolist(), counts.tolist()):
        pid, lvl = gid >> 18, gid & 0x3FFFF
        per_prop.setdefault(pid, []).append((level_names[lvl], int(count)))

    # per-property totals and top sources come from the same index cheaply
    rows_of = dict(db.execute(
        "SELECT property_id, COUNT(*) FROM material_properties GROUP BY property_id"))
    src_rows: dict[int, dict[str, int]] = {}
    for pid, sid, count in db.execute(
            "SELECT property_id, source_id, COUNT(*) FROM material_properties "
            "GROUP BY property_id, source_id"):
        src_rows.setdefault(pid, {})[sources.get(sid, str(sid))] = count

    out = []
    for pid, groups in per_prop.items():
        name, unit, kind = props.get(pid, (str(pid), None, "num"))
        groups.sort(key=lambda kv: -kv[1])
        srcs = sorted(src_rows.get(pid, {}).items(), key=lambda kv: -kv[1])
        out.append({
            "p": name, "k": kind, "u": unit,
            "mat": int(sum(c for _, c in groups)),   # materials summed over levels
            "rows": int(rows_of.get(pid, 0)),
            "cond": name in CONDITION_SPLIT_PROPERTIES,
            "ns": len(srcs),
            "top_src": [[s, int(c)] for s, c in srcs[:3]],
            "groups": [{"g": g, "n": int(c)} for g, c in groups],
        })
    out.sort(key=lambda r: -r["mat"])

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "task_census.json").write_text(json.dumps(out), encoding="utf-8")
    tasks = sum(len(r["groups"]) for r in out)
    print(f"\nwrote {args.out/'task_census.json'}")
    print(f"  properties {len(out)}   tasks (property x level) {tasks}")
    for thr in (1_000_000, 100_000, 10_000, 2_000, 300):
        reg = sum(1 for r in out for g in r["groups"]
                  if g["n"] >= thr and r["k"] == "num")
        cls = sum(1 for r in out for g in r["groups"]
                  if g["n"] >= thr and r["k"] != "num")
        print(f"  >= {thr:>9,}: {reg:3d} regression, {cls:2d} classification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
