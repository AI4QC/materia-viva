#!/usr/bin/env python3
"""Replace NOMAD's first-seen scalar with the median of its group.

NOMAD holds several calculations per (material, property, level of theory):
band gap averages 2.99 entries per group and reaches 1,004.  The first pass kept
whichever entry the catalog happened to list first, which is arbitrary, and
measured against a sample it moves 47% of multi-entry groups by a mean of
0.081 eV, with a 95th percentile of 0.43 eV.  That is larger than the 50 meV
tolerance the cross-database agreement analysis uses, so an arbitrary choice here
would show up as disagreement in a paper whose subject is disagreement.

The median is what the agreement analysis already applies to every other source,
so using it here makes NOMAD consistent with the rest rather than special.

Only ``value_num`` changes.  Row identity is (native_id, property, method), which
the median does not affect, so structures, provenance references and the
admission record are all untouched -- this deliberately does not re-run match or
re-admit structures.

    python scripts/properties/nomad_fix_medians.py --stage collect
    python scripts/properties/nomad_fix_medians.py --stage apply
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.properties.nomad_catalog_scalars import (  # noqa: E402
    NOMAD_ROOT, _dig, method_string, scalars_of,
)

WORK = PROJECT_ROOT / "data" / "props_work" / "nomad"
RAW = WORK / "all_values.tsv.gz"
SORTED = WORK / "all_values.sorted.tsv.gz"
INDEX_DB = PROJECT_ROOT / "data" / "index" / "materials.sqlite"

t0 = time.time()
log = lambda m: print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


def stage_collect(root: Path) -> None:
    pages = sorted(root.glob("catalog/page-*.json.gz"))
    log(f"collecting every value from {len(pages)} catalog pages")
    n = rows = 0
    with gzip.open(RAW, "wt", encoding="utf-8") as out:
        for i, page in enumerate(pages, 1):
            with gzip.open(page, "rt", encoding="utf-8") as fh:
                for record in json.load(fh)["data"]:
                    n += 1
                    res = record.get("results") or {}
                    mid = _dig(res, "material.material_id")
                    if not mid:
                        continue
                    for name, value, quals in scalars_of(res):
                        # \x01 keeps the key fields separable from method text
                        out.write(f"{mid}\x01{name}\x01"
                                  f"{method_string(res, *quals)}\t{value!r}\n")
                        rows += 1
            if i % 500 == 0:
                log(f"  page {i}/{len(pages)}  {rows:,} values")
    log(f"wrote {rows:,} values from {n:,} entries")

    log("sorting by (material, property, method)")
    env = dict(os.environ, LC_ALL="C")
    subprocess.run(
        f"zcat {RAW} | sort -t'\t' -k1,1 -S 4G --parallel=8 | gzip -1 > {SORTED}",
        shell=True, check=True, env=env)
    log("sorted")


def stage_apply() -> None:
    db = sqlite3.connect(INDEX_DB)
    db.execute("PRAGMA journal_mode = WAL")
    source_id = db.execute(
        "SELECT id FROM source_defs WHERE key = 'nomad'").fetchone()[0]
    prop_id = {n: i for i, n in db.execute("SELECT id, name FROM property_defs")}

    # No existing index covers (source, native_id, property, method), so every
    # UPDATE would otherwise scan 1.3e8 rows. A partial index over this source's
    # 10.2M rows is small, builds in a couple of minutes, and is dropped after.
    log("building a temporary partial index on the source's rows")
    db.execute(
        f"CREATE INDEX IF NOT EXISTS tmp_nomad_fix ON material_properties"
        f"(native_id, property_id, method) WHERE source_id = {int(source_id)}")
    db.commit()
    log("index built")

    updates: list[tuple] = []
    changed = same = groups = 0

    def flush() -> None:
        nonlocal updates
        if updates:
            db.executemany(
                "UPDATE material_properties SET value_num = ? "
                "WHERE source_id = ? AND native_id = ? AND property_id = ? "
                "AND method = ? AND value_num IS NOT ?", updates)
            db.commit()
            updates = []

    log("applying medians")
    with gzip.open(SORTED, "rt", encoding="utf-8") as fh:
        current_key = None
        values: list[float] = []
        for line in fh:
            key, _, value = line.rstrip("\n").rpartition("\t")
            if key != current_key:
                if current_key is not None:
                    groups += 1
                    values.sort()
                    median = values[(len(values) - 1) // 2]
                    mid, name, method = current_key.split("\x01", 2)
                    pid = prop_id.get(name)
                    if pid is not None:
                        if len(values) > 1 and median != values[0]:
                            changed += 1
                            updates.append((median, source_id, mid, pid, method,
                                            median))
                        else:
                            same += 1
                    if len(updates) >= 20_000:
                        flush()
                        if groups % 1_000_000 < 20_000:
                            log(f"  {groups:,} groups, {changed:,} corrected")
                current_key, values = key, []
            values.append(float(value))
        if current_key is not None:
            groups += 1
            values.sort()
            median = values[(len(values) - 1) // 2]
            mid, name, method = current_key.split("\x01", 2)
            pid = prop_id.get(name)
            if pid is not None and len(values) > 1 and median != values[0]:
                changed += 1
                updates.append((median, source_id, mid, pid, method, median))
    flush()
    log(f"groups {groups:,}   corrected {changed:,}   unchanged {same:,}")
    log("dropping the temporary index")
    db.execute("DROP INDEX IF EXISTS tmp_nomad_fix")
    db.commit()
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    db.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("collect", "apply", "both"), default="both")
    ap.add_argument("--root", type=Path, default=NOMAD_ROOT)
    args = ap.parse_args()
    if args.stage in ("collect", "both"):
        stage_collect(args.root)
    if args.stage in ("apply", "both"):
        stage_apply()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
