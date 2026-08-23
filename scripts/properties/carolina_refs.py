#!/usr/bin/env python3
"""Backfill Carolina Materials Database provenance refs.

The 214,435 Carolina structures were folded into the original local candidate
pool without per-source attribution. This hashes the legacy LMDB (pickled
Structure.as_dict payloads) with the standard pool protocol and records a
('carolina', carolina-<key>) source ref for every fingerprint match. No new
structures and no properties are added — provenance only.
"""

from __future__ import annotations

import json
import os
import pickle
import sqlite3
import sys
import time
import warnings
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

# Defaults to the legacy-data symlink documented in docs/storage-layout.md.
LMDB_PATH = os.environ.get("MV_CAROLINA_LMDB") or str(
    PROJECT_ROOT / "data" / "raw" / "legacy-material-data"
    / "carolina_matdb_structs.lmdb"
)
MATCH_MAP = PROJECT_ROOT / "data" / "props_work" / "match_map.sqlite"
INDEX_DB = PROJECT_ROOT / "data" / "index" / "materials.sqlite"

_hasher = None


def _init() -> None:
    global _hasher
    import os
    import warnings as w

    w.filterwarnings("ignore")
    from material_hasher.hasher.bawl import BAWLHasher

    _hasher = BAWLHasher()
    sys.stderr = open(os.devnull, "w")


def _work(item: tuple[str, bytes]) -> tuple[str, str]:
    key, payload = item
    try:
        from pymatgen.core import Structure

        structure = Structure.from_dict(pickle.loads(payload))
        if len(structure) > 500 or not structure.is_ordered:
            return key, "FAIL:CAPS"
        structure = structure.get_primitive_structure()
        if len(structure) > 300:
            return key, "FAIL:CAPS"
        return key, _hasher.get_material_hash(structure)
    except Exception as exc:  # noqa: BLE001
        return key, "FAIL:" + repr(exc)[:80]


def _iter_lmdb():
    import lmdb

    env = lmdb.open(LMDB_PATH, readonly=True, lock=False, subdir=False)
    with env.begin() as txn:
        for key, value in txn.cursor():
            yield key.decode(), value


def main() -> int:
    started = time.time()
    from scripts.properties.load import connect, migrate, _source_def

    db = connect()
    migrate(db)
    source_def_id = _source_def(db, "carolina")
    db.commit()
    match_db = sqlite3.connect(f"file:{MATCH_MAP}?mode=ro", uri=True)
    counters: Counter[str] = Counter()

    pk_of: dict[str, int] = {}
    ref_batch: list[tuple[int, int, str, str]] = []

    def flush() -> None:
        db.executemany(
            "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, ?)",
            ref_batch,
        )
        db.commit()
        ref_batch.clear()

    with Pool(26, initializer=_init) as pool:
        for key, hashed in pool.imap_unordered(_work, _iter_lmdb(), chunksize=64):
            counters["done"] += 1
            if hashed.startswith("FAIL:"):
                counters["hash_failed"] += 1
            else:
                hits = [
                    row[0]
                    for row in match_db.execute(
                        "SELECT material_id FROM hash_map WHERE hash = ?",
                        (hashed,),
                    )
                ]
                if not hits:
                    counters["unmatched"] += 1
                for material_id in dict.fromkeys(hits):
                    pk = pk_of.get(material_id)
                    if pk is None:
                        row = db.execute(
                            "SELECT pk FROM materials WHERE material_id = ?",
                            (material_id,),
                        ).fetchone()
                        if row is None:
                            continue
                        pk = pk_of[material_id] = row[0]
                    ref_batch.append(
                        (pk, source_def_id, f"carolina-{key}", "hash")
                    )
                    counters["refs"] += 1
            if len(ref_batch) >= 20_000:
                flush()
            if counters["done"] % 20_000 == 0:
                print(
                    f"{counters['done']:,} hashed, {counters['refs']:,} refs, "
                    f"{counters['unmatched']:,} unmatched "
                    f"({(time.time() - started) / 60:.1f} min)",
                    flush=True,
                )
    flush()
    db.close()
    match_db.close()
    print(json.dumps(dict(counters), indent=2, sort_keys=True))
    print(f"done in {(time.time() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
