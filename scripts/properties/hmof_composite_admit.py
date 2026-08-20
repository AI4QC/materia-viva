#!/usr/bin/env python3
"""Admit fingerprint-colliding hMOFs under a composite uniqueness key.

Same pathology as the Deem zeolites, same remedy (see deem_zeolite_admit.py).
hMOF is an *enumerated* library: one framework topology decorated with a menu
of functional groups. Sibling entries therefore share a bonding graph and a
primitive composition, which is everything the BAWL fingerprint looks at, so
46,891 of the 135,818 hashable records collided with an earlier record and the
standard pipeline dropped them (281,346 property rows lost, 88,927 of 137,652
frameworks admitted).

They are NOT duplicates. hMOF-31782 and hMOF-31783 are different hypothetical
MOFs with their own Zeo++ geometry and their own GCMC CO2 isotherm. Sending
their properties to one pool material through the normal intra-source alias
path would put several contradictory porosities and uptakes on one structure —
strictly worse than losing them. So they are separated the way Deem's
frameworks were:

    composite key = (bawl_hash, round(volume_per_site, VOL_DECIMALS))

Cell volume per site is cell-choice invariant and separates frameworks the
graph hash cannot. Records that still collide on the composite key are dropped
rather than smeared.

Critically, the colliding fingerprints are NOT registered in the match map.
The first hMOF load *did* register all 88,927 admitted fingerprints in
``hash_map``, which is why this script also reports (and, with
``--purge-ambiguous-hashes``, removes) the ones that turn out to serve more
than one material: an ambiguous fingerprint must never resolve for a later
source. 9 pool materials already carry core-mof / mofx-db references picked up
that way.

ORDER OF OPERATIONS — this replaces the tail of the normal pipeline:

    pipeline.py hmof --stage adapt
    pipeline.py hmof --stage hash
    hmof_composite_admit.py --apply          # NOT --stage match, NOT load.py

``pipeline.py hmof --stage match`` must not run: every hMOF fingerprint is in
``hash_map`` now, so it would resolve all 137,652 records onto the 88,927
existing materials and ``load.py`` would then smear them. This script does the
work both stages would have done — admit structures, attach references, insert
properties — reading ``hashes.tsv.gz``, ``staging_structs.jsonl.gz`` and
``staging_props.tsv.gz`` directly.

It is additive and re-runnable: records already admitted by the first load keep
their material (and reserve their composite slot), and a property row is only
inserted when the source has no row yet for that (native_id, property, method).

Default mode is a dry run: it opens the index read-only, classifies every
record and prints the counters without writing anything.
"""

from __future__ import annotations

import argparse
import csv as csv_module
import gzip
import json
import re
import sqlite3
import sys
import time
import zlib
from collections import Counter, defaultdict
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
from scripts.properties import load as load_module  # noqa: E402
from scripts.properties.cif_trim import trim_cif  # noqa: E402
from scripts.properties.registry import SOURCE_FAMILY  # noqa: E402

SOURCE = "hmof"
#: SOURCE_FAMILY already labels hmof; spelled out so the label is visible here
FAMILY = SOURCE_FAMILY.get(SOURCE, "mof")
#: 0.01 A^3/site on a ~50 A^3/site MOF is a 2e-4 relative tolerance, the same
#: rounding deem_zeolite_admit.py uses
VOL_DECIMALS = 2
#: a pool material counts as a true duplicate of a record only when its
#: fingerprint AND its volume per atom agree
POOL_VOLUME_TOLERANCE = 0.01

_VOLUME = re.compile(r"(?im)^\s*_cell_volume\s+([\d.]+)")
#: stage_adapt writes native_id as the first key of every staging_structs line
_NATIVE_ID = re.compile(r'^\{"native_id":\s*"([^"]*)"')


def _volume_per_site(cif: str, n_sites: int) -> float | None:
    match = _VOLUME.search(cif)
    if not match or not n_sites:
        return None
    try:
        volume = float(match.group(1))
    except ValueError:
        return None
    if not volume > 0:
        return None
    return volume / n_sites


def _read_hashes(work: Path) -> dict[str, tuple[str, int]]:
    hashes: dict[str, tuple[str, int]] = {}
    with gzip.open(work / "hashes.tsv.gz", "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, n_sites, _formula, hashed = line.rstrip("\n").split("\t")
            if not hashed.startswith("FAIL:"):
                hashes[native_id] = (hashed, int(n_sites))
    return hashes


def _warn_about_match_stage(work: Path) -> None:
    matched = work / "matched.tsv.gz"
    if not matched.is_file():
        return
    rows = 0
    with gzip.open(matched, "rt", encoding="utf-8") as handle:
        next(handle, None)
        for _ in handle:
            rows += 1
            if rows > 1:
                break
    if rows:
        print(
            "WARNING: matched.tsv.gz is not empty. `pipeline.py hmof --stage match`\n"
            "         resolves the colliding fingerprints onto the existing pool\n"
            "         materials; do NOT run load.py hmof against it.",
            file=sys.stderr,
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write to the index (default: dry run, index opened read-only)",
    )
    parser.add_argument(
        "--purge-ambiguous-hashes",
        action="store_true",
        help="with --apply, delete fingerprints serving >1 material from the "
             "match map's hash_map so no later source can resolve them",
    )
    parser.add_argument("--vol-decimals", type=int, default=VOL_DECIMALS)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after N staged records (verification aid). The reservation "
             "pass over already-admitted records always reads the whole file, "
             "so a limited run can never admit a duplicate.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="sandbox data root (index/blob/match map live under it)",
    )
    parser.add_argument(
        "--work-root",
        type=Path,
        default=None,
        help="sandbox props_work root holding the hmof staging artifacts",
    )
    args = parser.parse_args()
    if args.data_root:
        load_module.set_data_root(args.data_root)

    started = time.time()
    work_root = args.work_root or load_module.WORK_ROOT
    work = Path(work_root) / SOURCE
    for name in ("hashes.tsv.gz", "staging_structs.jsonl.gz", "staging_props.tsv.gz"):
        if not (work / name).is_file():
            raise SystemExit(f"{SOURCE}: missing {work / name}; run adapt + hash first")
    _warn_about_match_stage(work)

    counters: Counter[str] = Counter()
    if args.apply:
        db = load_module.connect()
        load_module.migrate(db)
        source_def_id = load_module._source_def(db, SOURCE)
        db.commit()
    else:
        db = sqlite3.connect(f"file:{load_module.INDEX_DB}?mode=ro", uri=True)
        row = db.execute(
            "SELECT id FROM source_defs WHERE key = ?", (SOURCE,)
        ).fetchone()
        source_def_id = row[0] if row else None

    hashes = _read_hashes(work)
    counters["hashes_available"] = len(hashes)

    # records the first load already admitted: they keep their material and
    # reserve their composite slot
    existing_pk: dict[str, int] = {}
    if source_def_id is not None:
        for native_id, material_pk in db.execute(
            "SELECT native_id, material_pk FROM material_source_refs "
            "WHERE source_id = ? AND match_via = 'origin'",
            (source_def_id,),
        ):
            existing_pk[native_id] = material_pk
    counters["already_admitted_records"] = len(existing_pk)
    our_pks = set(existing_pk.values())

    # pool materials the colliding fingerprints currently point at, minus the
    # hMOF materials themselves (those are handled through existing_pk)
    match_db = sqlite3.connect(f"file:{load_module.MATCH_MAP}?mode=ro", uri=True)
    wanted = {hashed for hashed, _ in hashes.values()}
    pool_by_hash: dict[str, list[str]] = defaultdict(list)
    hash_map_rows = 0
    for hashed, material_id in match_db.execute("SELECT hash, material_id FROM hash_map"):
        if hashed in wanted:
            hash_map_rows += 1
            pool_by_hash[hashed].append(material_id)
    counters["hash_map_entries_for_hmof"] = hash_map_rows
    flat = {mid for entries in pool_by_hash.values() for mid in entries}
    pk_of: dict[str, int] = {}
    vol_of: dict[str, float] = {}
    ids = sorted(flat)
    for start in range(0, len(ids), 900):
        chunk = ids[start : start + 900]
        marks = ",".join("?" for _ in chunk)
        for material_id, pk, volume, n_atoms in db.execute(
            f"SELECT material_id, pk, volume, n_atoms FROM materials "
            f"WHERE material_id IN ({marks})",
            chunk,
        ):
            pk_of[material_id] = pk
            if volume and n_atoms:
                vol_of[material_id] = volume / n_atoms

    # ---------------------------------------------------------------- pass 0
    # Materials the first load already created own their composite slot no
    # matter where their record sits in the file, so reserve those keys before
    # anything can be admitted against them.
    seen_keys: dict[tuple[str, float], str] = {}
    #: native_id -> material pk, or PENDING for a framework still to be admitted
    PENDING = 0
    native_pk: dict[str, int] = {}
    to_admit: list[tuple[str, str, str, int, float]] = []
    pool_refs: list[tuple[str, int]] = []
    keys_by_hash: dict[str, set[float]] = defaultdict(set)
    dropped_natives: dict[str, str] = {}

    def _key_of(payload: dict) -> tuple[str, float] | None:
        entry = hashes.get(payload["native_id"])
        if entry is None:
            return None
        hashed, n_sites = entry
        vol_per_site = _volume_per_site(payload["cif"], n_sites)
        if vol_per_site is None:
            return None
        return hashed, round(vol_per_site, args.vol_decimals)

    if existing_pk:
        with gzip.open(
            work / "staging_structs.jsonl.gz", "rt", encoding="utf-8"
        ) as rows:
            for line in rows:
                # cheap pre-filter: the native_id is the first key of the
                # object stage_adapt writes, so the head of the line is enough
                head = _NATIVE_ID.match(line)
                if head is not None and head.group(1) not in existing_pk:
                    continue
                payload = json.loads(line)
                native_id = payload["native_id"]
                if native_id not in existing_pk:
                    continue
                key = _key_of(payload)
                if key is None:
                    continue
                owner = seen_keys.setdefault(key, native_id)
                if owner != native_id:
                    counters["already_admitted_key_clash"] += 1
                keys_by_hash[key[0]].add(key[1])
                native_pk[native_id] = existing_pk[native_id]

    # ---------------------------------------------------------------- pass 1
    # classify every staged record; nothing is written yet
    with gzip.open(work / "staging_structs.jsonl.gz", "rt", encoding="utf-8") as rows:
        for line in rows:
            if args.limit is not None and counters["records"] >= args.limit:
                break
            counters["records"] += 1
            payload = json.loads(line)
            native_id = payload["native_id"]
            entry = hashes.get(native_id)
            if entry is None:
                counters["hash_failed"] += 1
                dropped_natives[native_id] = "hash_failed"
                continue
            hashed, n_sites = entry
            cif = payload["cif"]
            vol_per_site = _volume_per_site(cif, n_sites)
            if vol_per_site is None:
                counters["no_volume"] += 1
                dropped_natives[native_id] = "no_volume"
                continue
            key = (hashed, round(vol_per_site, args.vol_decimals))
            if native_id in existing_pk:
                # already a pool material; its key was reserved in pass 0
                counters["already_admitted"] += 1
                continue
            if key in seen_keys:
                counters["composite_duplicate"] += 1
                dropped_natives[native_id] = "composite_duplicate"
                continue
            true_match = None
            for material_id in pool_by_hash.get(hashed, ()):
                pk = pk_of.get(material_id)
                if pk is None or pk in our_pks:
                    continue
                pool_vol = vol_of.get(material_id)
                if (
                    pool_vol
                    and abs(pool_vol - vol_per_site) / pool_vol < POOL_VOLUME_TOLERANCE
                ):
                    true_match = (material_id, pk)
                    break
            seen_keys[key] = native_id
            keys_by_hash[hashed].add(key[1])
            if true_match is not None:
                counters["true_pool_match"] += 1
                native_pk[native_id] = true_match[1]
                pool_refs.append((native_id, true_match[1]))
                continue
            to_admit.append((native_id, hashed, cif, n_sites, vol_per_site))
            native_pk[native_id] = PENDING
            counters["to_admit"] += 1

    counters["distinct_composite_keys"] = len(seen_keys)
    counters["distinct_fingerprints"] = len(keys_by_hash)
    ambiguous = {h for h, vols in keys_by_hash.items() if len(vols) > 1}
    counters["ambiguous_fingerprints"] = len(ambiguous)
    counters["ambiguous_fingerprints_in_hash_map"] = sum(
        1 for h in ambiguous if h in pool_by_hash
    )
    counters["frameworks_separated_vs_hash_only"] = (
        len(seen_keys) - len(keys_by_hash)
    )

    # ---------------------------------------------------------------- pass 2
    # admit the new frameworks
    if args.apply and to_admit:
        from materials_api.repository import MaterialRepository

        repository = MaterialRepository(load_module.INDEX_DB, load_module.BLOB)
        repository.connection.close()
        repository.connection = db
        next_index = load_module._next_index(db, "candidate")
        csv_dir = load_module.DATA / "sources" / "candidate"
        csv_handle = (csv_dir / "train.csv").open("a", newline="", encoding="utf-8")
        writer = csv_module.writer(csv_handle)
        meta_path = csv_dir / "added_meta.tsv"
        fresh = not meta_path.exists()
        meta_handle = meta_path.open("a", encoding="utf-8")
        if fresh:
            meta_handle.write("index\tsource\tsource_id\tbawl_hash\tn_sites\n")
        with load_module.BLOB.open("ab") as blob:
            for native_id, hashed, cif, n_sites, _vol in to_admit:
                cif = trim_cif(cif)
                try:
                    info = parse_formula(hashed.split("_", 2)[2])
                except (IndexError, ValueError):
                    counters["bad_formula"] += 1
                    dropped_natives[native_id] = "bad_formula"
                    native_pk.pop(native_id, None)
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
                    "material_family": FAMILY,
                    "blob_offset": offset,
                    "blob_length": len(compressed),
                    **fields,
                }
                material_pk = repository.add_material(record, commit=False)
                db.execute(
                    "INSERT OR IGNORE INTO material_source_refs "
                    "VALUES (?, ?, ?, 'origin')",
                    (material_pk, source_def_id, native_id),
                )
                native_pk[native_id] = material_pk
                writer.writerow([index, info.formula, cif, ""])
                meta_handle.write(
                    f"{index}\t{SOURCE}\t{native_id}\t{hashed}\t{n_sites}\n"
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
        db.commit()
        csv_handle.close()
        meta_handle.close()
        for native_id, pk in pool_refs:
            db.execute(
                "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, 'hash')",
                (pk, source_def_id, native_id),
            )
        db.commit()

    # ---------------------------------------------------------------- pass 3
    # attach every linked record's own properties, skipping rows the first
    # load already inserted
    have: set[tuple[str, int, str]] = set()
    if source_def_id is not None:
        for native_id, property_id, method in db.execute(
            "SELECT native_id, property_id, method FROM material_properties "
            "WHERE source_id = ?",
            (source_def_id,),
        ):
            have.add((native_id, property_id, method))
    counters["existing_property_rows"] = len(have)

    defs = load_module.PropertyDefs(db) if args.apply else None
    def_ids: dict[str, int] = dict(db.execute("SELECT name, id FROM property_defs"))
    batch: list[tuple] = []
    with gzip.open(work / "staging_props.tsv.gz", "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, name, value_num, value_text, unit, method = (
                line.rstrip("\n").split("\t")
            )
            pk = native_pk.get(native_id)
            if pk is None:
                counters["property_rows_dropped"] += 1
                reason = dropped_natives.get(native_id, "unlinked")
                counters[f"property_rows_dropped_{reason}"] += 1
                continue
            if pk == PENDING and args.apply:
                # only reachable if pass 2 failed to admit the framework
                counters["property_rows_dropped"] += 1
                counters["property_rows_dropped_not_admitted"] += 1
                continue
            if defs is not None:
                property_id = defs.get(name, unit or None)
            else:
                property_id = def_ids.get(name)
                if property_id is None:
                    counters["property_rows_new_definition"] += 1
            if (native_id, property_id, method or None) in have:
                counters["property_rows_already_present"] += 1
                continue
            counters["property_rows_new"] += 1
            if args.apply:
                batch.append((
                    pk,
                    property_id,
                    source_def_id,
                    native_id,
                    float(value_num) if value_num else None,
                    value_text or None,
                    method or None,
                ))
                if len(batch) >= 50_000:
                    db.executemany(
                        "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                    batch.clear()
    if args.apply:
        if batch:
            db.executemany(
                "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)", batch
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

    # ------------------------------------------------- ambiguous fingerprints
    # Never registered here: an ambiguous fingerprint must not resolve for a
    # later source. The first load already put all of them in hash_map, so the
    # only write this script can make to the match map is a deletion.
    stale = sorted(ambiguous & set(pool_by_hash))
    # collateral: rows under an ambiguous fingerprint that point somewhere
    # other than an hMOF material. An ambiguous fingerprint is unusable for
    # everyone, so purging removes those too — reported so the cost is visible.
    counters["ambiguous_hash_map_rows"] = sum(
        len(pool_by_hash[h]) for h in stale
    )
    counters["ambiguous_hash_map_rows_other_sources"] = sum(
        1
        for h in stale
        for material_id in pool_by_hash[h]
        if pk_of.get(material_id) not in our_pks
    )
    if args.purge_ambiguous_hashes:
        if not args.apply:
            raise SystemExit("--purge-ambiguous-hashes requires --apply")
        match_db.close()
        writable = sqlite3.connect(load_module.MATCH_MAP)
        writable.execute("PRAGMA busy_timeout = 120000")
        purged = 0
        for start in range(0, len(stale), 500):
            chunk = stale[start : start + 500]
            marks = ",".join("?" for _ in chunk)
            cursor = writable.execute(
                f"DELETE FROM hash_map WHERE hash IN ({marks})", chunk
            )
            purged += cursor.rowcount
        writable.commit()
        writable.close()
        counters["hash_map_rows_purged"] = purged
    else:
        match_db.close()

    db.close()
    counters["minutes"] = round((time.time() - started) / 60, 2)
    report = dict(counters)
    report["mode"] = "apply" if args.apply else "dry-run"
    report["vol_decimals"] = args.vol_decimals
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.apply:
        (work / "composite_admit_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
