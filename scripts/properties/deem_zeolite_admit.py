#!/usr/bin/env python3
"""Admit Deem zeolites with a composite uniqueness key.

BAWL fingerprints collapse enumerated idealized SiO2 frameworks (every Si is
4-coordinated, every O 2-coordinated, so the bonding-graph hash cannot separate
distinct nets). The standard pipeline therefore admitted only 3,304 of 331k
frameworks. This one-off admits the rest under a composite key:

    (bawl_hash, round(volume_per_site, 2))

volume-per-site is cell-choice invariant and separates frameworks the graph
hash cannot. Hash-colliding zeolites are deliberately NOT registered in the
match map's hash_map — their fingerprint is ambiguous for matching, so future
fingerprint lookups must not resolve to them. Pool collisions found by the
original run are re-checked: a pool material only counts as a true duplicate
when its volume-per-atom agrees within 1%.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from materials_api.formula import parse_formula  # noqa: E402
from materials_api.indexer import (  # noqa: E402
    _density,
    _extract_cif_fields,
    _spacegroup_symbol,
    crystal_system,
)
from materials_api.repository import MaterialRepository  # noqa: E402
from scripts.properties.load import INDEX_DB, BLOB, MATCH_MAP, connect, migrate, _source_def  # noqa: E402

WORK = PROJECT_ROOT / "data" / "props_work" / "deem-zeolites"
DATA = PROJECT_ROOT / "data"

_VOLUME = re.compile(r"(?im)^\s*_cell_volume\s+([\d.]+)")


def main() -> int:
    started = time.time()
    db = connect()
    migrate(db)
    source_def_id = _source_def(db, "deem-zeolites")
    db.commit()
    match_db = sqlite3.connect(f"file:{MATCH_MAP}?mode=ro", uri=True)
    counters: Counter[str] = Counter()

    # hashes for every record (native_id -> hash, n_sites)
    hashes: dict[str, tuple[str, int]] = {}
    with gzip.open(WORK / "hashes.tsv.gz", "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, n_sites, _formula, hashed = line.rstrip("\n").split("\t")
            if not hashed.startswith("FAIL:"):
                hashes[native_id] = (hashed, int(n_sites))

    # already-admitted deem zeolites (origin refs) keep their composite slots
    existing_natives = {
        row[0]
        for row in db.execute(
            "SELECT native_id FROM material_source_refs "
            "WHERE source_id = ? AND match_via = 'origin'",
            (source_def_id,),
        )
    }

    # volume-per-atom of the pool materials the colliding hashes pointed at
    pool_by_hash: dict[str, list[tuple[str, float]]] = {}
    wanted_hashes = {h for h, _ in hashes.values()}
    for start_hash, material_id in match_db.execute(
        "SELECT hash, material_id FROM hash_map"
    ):
        if start_hash in wanted_hashes:
            pool_by_hash.setdefault(start_hash, []).append((material_id, 0.0))
    flat_ids = {mid for entries in pool_by_hash.values() for mid, _ in entries}
    vol_of: dict[str, float] = {}
    ids = list(flat_ids)
    for start in range(0, len(ids), 900):
        chunk = ids[start : start + 900]
        marks = ",".join("?" for _ in chunk)
        for material_id, volume, n_atoms in db.execute(
            f"SELECT material_id, volume, n_atoms FROM materials "
            f"WHERE material_id IN ({marks})",
            chunk,
        ):
            if volume and n_atoms:
                vol_of[material_id] = volume / n_atoms

    repository = MaterialRepository(INDEX_DB, BLOB)
    repository.connection.close()
    repository.connection = db

    next_index = int(db.execute(
        "SELECT MAX(CAST(source_index AS INTEGER)) FROM materials "
        "WHERE dataset = 'candidate'"
    ).fetchone()[0]) + 1

    seen_keys: set[tuple[str, float]] = set()
    csv_handle = (DATA / "sources" / "candidate" / "train.csv").open(
        "a", newline="", encoding="utf-8"
    )
    import csv as csv_module

    writer = csv_module.writer(csv_handle)
    meta_handle = (DATA / "sources" / "candidate" / "added_meta.tsv").open(
        "a", encoding="utf-8"
    )
    ref_rows: list[tuple] = []

    with BLOB.open("ab") as blob, \
            gzip.open(WORK / "staging_structs.jsonl.gz", "rt", encoding="utf-8") as rows:
        for line in rows:
            payload = json.loads(line)
            native_id = payload["native_id"]
            if native_id in existing_natives:
                counters["already_admitted"] += 1
                continue
            entry = hashes.get(native_id)
            if entry is None:
                counters["hash_failed"] += 1
                continue
            hashed, n_sites = entry
            cif = payload["cif"]
            volume_match = _VOLUME.search(cif)
            if not volume_match or not n_sites:
                counters["no_volume"] += 1
                continue
            vol_per_site = float(volume_match.group(1)) / n_sites
            key = (hashed, round(vol_per_site, 2))
            if key in seen_keys:
                counters["composite_duplicate"] += 1
                continue
            # true pool duplicate: same fingerprint AND volume/atom within 1%
            true_match = None
            for material_id, _ in pool_by_hash.get(hashed, ()):
                pool_vol = vol_of.get(material_id)
                if pool_vol and abs(pool_vol - vol_per_site) / pool_vol < 0.01:
                    true_match = material_id
                    break
            if true_match:
                seen_keys.add(key)
                ref_rows.append((true_match, native_id))
                counters["true_pool_match"] += 1
                continue
            seen_keys.add(key)
            try:
                info = parse_formula(hashed.split("_", 2)[2])
            except (IndexError, ValueError):
                counters["bad_formula"] += 1
                continue
            fields = _extract_cif_fields(cif)
            try:
                spacegroup = int(hashed.split("_")[1])
            except (IndexError, ValueError):
                spacegroup = None
            compressed = zlib.compress(cif.encode("utf-8"), 3)
            offset = blob.tell()
            blob.write(compressed)
            index = next_index
            next_index += 1
            material_id = f"pool-train-{index}"
            record = {
                "material_id": material_id,
                "formula": info.formula,
                "chemical_system": info.chemical_system,
                "elements": info.elements,
                "dataset": "candidate",
                "is_experimental": False,
                "source_split": "train",
                "source_index": str(index),
                "n_elements": info.n_elements,
                "n_atoms": info.n_atoms,
                "pbes_gap": None,
                "density": _density(info.formula, fields.get("volume")),
                "spacegroup_number": spacegroup,
                "spacegroup_symbol": _spacegroup_symbol(spacegroup),
                "crystal_system": crystal_system(spacegroup),
                "material_family": "zeolite",
                "blob_offset": offset,
                "blob_length": len(compressed),
            }
            material_pk = repository.add_material(record, commit=False)
            db.execute(
                "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, 'origin')",
                (material_pk, source_def_id, native_id),
            )
            writer.writerow([index, info.formula, cif, ""])
            meta_handle.write(
                f"{index}\tdeem-zeolites\t{native_id}\t{hashed}\t{n_sites}\n"
            )
            counters["admitted"] += 1
            if counters["admitted"] % 5_000 == 0:
                db.commit()
                csv_handle.flush()
                meta_handle.flush()
                print(
                    f"{counters['admitted']:,} admitted "
                    f"({time.time() - started:.0f}s)",
                    flush=True,
                )
    # re-attach refs for verified true pool duplicates
    pk_cache: dict[str, int] = {}
    for material_id, native_id in ref_rows:
        pk = pk_cache.get(material_id)
        if pk is None:
            row = db.execute(
                "SELECT pk FROM materials WHERE material_id = ?", (material_id,)
            ).fetchone()
            if row is None:
                continue
            pk = pk_cache[material_id] = row[0]
        db.execute(
            "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, 'hash')",
            (pk, source_def_id, native_id),
        )
    count = db.execute(
        "SELECT COUNT(*) FROM materials WHERE dataset = 'candidate'"
    ).fetchone()[0]
    db.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES "
        "('candidate_count', ?)",
        (str(count),),
    )
    db.commit()
    csv_handle.close()
    meta_handle.close()
    db.close()
    # NOTE: colliding hashes intentionally NOT added to match_map hash_map.
    print(json.dumps(dict(counters), indent=2, sort_keys=True))
    print(f"done in {(time.time() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
