#!/usr/bin/env python3
"""Recover properties lost to intra-source fingerprint duplicates.

Until 2026-08-19 ``pipeline.stage_match`` dropped a record outright when
another record of the SAME source had already claimed its fingerprint
(``duplicate_within_source``). That is wrong whenever the duplicate carries its
own measurements: Alexandria's ``agm-X`` / ``agm-X:pbesol`` / ``agm-X:scan`` are
one crystal computed with three functionals, and only the first one's numbers
reached the index. Across all loaded sources 1.63M records were dropped this
way.

The fix in the pipeline (an alias map) only helps future loads. This repairs
what is already in the index, without re-loading anything:

1. read the source's staged property rows and its per-record fingerprints;
2. find native_ids that carry properties but have no row in
   ``material_source_refs`` (i.e. were dropped);
3. resolve each through the match map by FINGERPRINT — the canonical record's
   structure is in the pool, so its hash resolves to the right material;
4. insert the missing refs (``match_via='hash'``) and the missing property rows.

Idempotent: a native_id that already has property rows under this source is
skipped, so re-running adds nothing.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.properties.base import WORK_ROOT  # noqa: E402
from scripts.properties.load import (  # noqa: E402
    MATCH_MAP,
    PropertyDefs,
    _source_def,
    connect,
    migrate,
)


def repair(source: str, dry_run: bool) -> dict:
    work = WORK_ROOT / source
    props_path = work / "staging_props.tsv.gz"
    hashes_path = work / "hashes.tsv.gz"
    if not props_path.is_file() or not hashes_path.is_file():
        raise SystemExit(f"{source}: staging artifacts missing under {work}")

    started = time.time()
    counters: Counter[str] = Counter()
    db = connect()
    migrate(db)
    source_id = _source_def(db, source)
    db.commit()

    # native_ids that already reach a material through any route
    attached = {
        row[0]
        for row in db.execute(
            "SELECT DISTINCT native_id FROM material_source_refs WHERE source_id = ?",
            (source_id,),
        )
    }
    counters["already_attached"] = len(attached)

    # fingerprints of every hashed record
    hash_of: dict[str, str] = {}
    with gzip.open(hashes_path, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4 or parts[3].startswith("FAIL:"):
                continue
            hash_of[parts[0]] = parts[3]

    # candidates: carry properties, are hashed, but never landed
    wanted: set[str] = set()
    with gzip.open(props_path, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id = line.split("\t", 1)[0]
            if native_id not in attached and native_id in hash_of:
                wanted.add(native_id)
    counters["orphan_records"] = len(wanted)
    if not wanted:
        db.close()
        return dict(counters)

    match_db = sqlite3.connect(f"file:{MATCH_MAP}?mode=ro", uri=True)
    pk_of: dict[str, int] = {}
    resolved: dict[str, list[int]] = {}
    for native_id in wanted:
        material_ids = [
            row[0]
            for row in match_db.execute(
                "SELECT material_id FROM hash_map WHERE hash = ?",
                (hash_of[native_id],),
            )
        ]
        pks = []
        for material_id in dict.fromkeys(material_ids):
            pk = pk_of.get(material_id)
            if pk is None:
                row = db.execute(
                    "SELECT pk FROM materials WHERE material_id = ?", (material_id,)
                ).fetchone()
                if row is None:
                    continue
                pk = pk_of[material_id] = row[0]
            pks.append(pk)
        if pks:
            resolved[native_id] = pks
            counters["resolved_records"] += 1
        else:
            counters["unresolvable"] += 1
    match_db.close()

    if dry_run:
        with gzip.open(props_path, "rt", encoding="utf-8") as handle:
            next(handle)
            for line in handle:
                native_id = line.split("\t", 1)[0]
                if native_id in resolved:
                    counters["property_rows_would_add"] += len(resolved[native_id])
        db.close()
        counters["minutes"] = round((time.time() - started) / 60, 1)
        return dict(counters)

    ref_batch = [
        (pk, source_id, native_id, "hash")
        for native_id, pks in resolved.items()
        for pk in pks
    ]
    for start in range(0, len(ref_batch), 50_000):
        db.executemany(
            "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, ?)",
            ref_batch[start : start + 50_000],
        )
    counters["refs_added"] = len(ref_batch)
    db.commit()

    defs = PropertyDefs(db)
    batch: list[tuple] = []
    with gzip.open(props_path, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, name, value_num, value_text, unit, method = (
                line.rstrip("\n").split("\t")
            )
            pks = resolved.get(native_id)
            if not pks:
                continue
            property_id = defs.get(name, unit or None)
            for pk in pks:
                batch.append((
                    pk, property_id, source_id, native_id,
                    float(value_num) if value_num else None,
                    value_text or None, method or None,
                ))
                counters["property_rows_added"] += 1
            if len(batch) >= 50_000:
                db.executemany(
                    "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                batch.clear()
                db.commit()
    if batch:
        db.executemany(
            "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)", batch
        )
    db.commit()
    db.close()
    counters["minutes"] = round((time.time() - started) / 60, 1)
    return dict(counters)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = {}
    for source in args.sources:
        print(f"=== {source} ===", flush=True)
        report[source] = repair(source, args.dry_run)
        print(json.dumps(report[source], indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
