#!/usr/bin/env python3
"""Recover the Alexandria PBEsol / SCAN runs the match stage silently dropped.

``agm-X``, ``agm-X:pbesol`` and ``agm-X:scan`` are ONE crystal computed with
three functionals. During the original alexandria load, stage_match admitted
whichever record it saw first and rejected the other two as
``duplicate_within_source`` - correct as a *structure* decision, wrong as a
*property* decision, because it threw away two complete DFT runs. 429,727
records were lost that way: their band gaps, formation energies, hull
distances, magnetizations, total energies, dos_ef and phase-separation
energies were never stored, and the index kept only the PBE numbers. The root
cause is fixed for future loads (stage_match now writes an alias map and the
loader attaches aliases to the canonical material); this script repairs the
data already in the index.

The staged property files for alexandria were deleted in a disk cleanup, so
recovery reads the raw shards again, streaming the pbesol-3d and scan-3d
subsets exactly as ``adapters/alexandria.py`` and ``alexandria_topup.py`` do.

THE JOIN, so nobody mistakes it for fuzzy matching: a dropped record's
suffixed native_id (``<mat_id>:pbesol`` / ``<mat_id>:scan``) is resolved by
looking up the BARE ``mat_id`` in material_source_refs. That is an identity
join on Alexandria's own primary key - the re-run carries the same mat_id
precisely because it is the same crystal - and the structural equality was
already proven by the match stage itself, which is the very reason it called
the record a within-source duplicate. No formula, composition or hash
comparison is involved or needed here.

Recovered rows reproduce the adapter's mapping and units exactly, so they are
indistinguishable from what a clean load would have written:

    e_form              -> formation_energy_per_atom  [eV/atom]
    e_above_hull        -> energy_above_hull          [eV/atom]
    band_gap_ind        -> band_gap                   [eV]
    band_gap_dir        -> band_gap_direct            [eV]
    total_mag           -> total_magnetization        [μB] (method "<f> per cell")
    energy_total/nsites -> total_energy_per_atom      [eV/atom]
    spg                 -> spacegroup_number          [-]
    dos_ef              -> dos_at_fermi               [states/eV]
    e_phase_separation  -> phase_separation_energy    [eV/atom]

with method 'PBEsol' or 'SCAN' per subset, and the dos_ef / e_phase_separation
guards imported from alexandria_topup so one rule governs the whole source.
The fields the top-up deliberately excludes (energy_corrected, stress,
decomposition, prototype_id, location, run_timestamp, per-site tensors) stay
excluded here too; see that module's docstring.

Each recovered record also gets its missing material_source_refs row for the
suffixed native_id, with match_via='hash'.

Idempotence: a record whose suffixed native_id already has a ref is skipped, so
re-running is a no-op. --replace deletes exactly what a previous run added,
using the manifest it writes to
data/props_work/alexandria/recovered_functional_runs.tsv.gz.

Usage:
    python -m scripts.properties.alexandria_recover_functional_runs --dry-run
    python -m scripts.properties.alexandria_recover_functional_runs
    python -m scripts.properties.alexandria_recover_functional_runs --spot-check 5
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.properties.adapters._util import safe_float  # noqa: E402
from scripts.properties.alexandria_topup import (  # noqa: E402
    FIELD_MAP,
    GAPPED_EV,
    MAX_ABS_PHASE_SEPARATION,
    SOURCE,
    _pks,
    _read_only_db,
    _source_id,
    build_ref_map,
    clean,
    iter_entries,
    iter_shards,
)
from scripts.properties.load import (  # noqa: E402
    PropertyDefs,
    _source_def,
    connect,
    migrate,
)

#: the two re-run subsets; the PBE sets were admitted and need nothing
SUBSETS = ("pbesol-3d", "scan-3d")

MANIFEST = (
    PROJECT_ROOT / "data" / "props_work" / "alexandria"
    / "recovered_functional_runs.tsv.gz"
)

#: canonical name <- native key, unit; mirrors AlexandriaAdapter._build_record
PLAIN_SCALARS = (
    ("formation_energy_per_atom", "e_form", "eV/atom"),
    ("energy_above_hull", "e_above_hull", "eV/atom"),
    ("band_gap", "band_gap_ind", "eV"),
    ("band_gap_direct", "band_gap_dir", "eV"),
)

UNITS = {
    "formation_energy_per_atom": "eV/atom",
    "energy_above_hull": "eV/atom",
    "band_gap": "eV",
    "band_gap_direct": "eV",
    "total_magnetization": "μB/cell",
    "total_energy_per_atom": "eV/atom",
    "spacegroup_number": None,
    "dos_at_fermi": "states/eV",
    "phase_separation_energy": "eV/atom",
}

INSERT_PROP = "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)"
INSERT_REF = "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, 'hash')"


def build_values(
    data: dict, method: str, counters: Counter
) -> list[tuple[str, float, str]]:
    """(canonical name, value, method) exactly as the adapter would emit."""

    values: list[tuple[str, float, str]] = []
    for name, key, _unit in PLAIN_SCALARS:
        value = safe_float(data.get(key))
        if value is not None:
            values.append((name, value, method))

    total_mag = safe_float(data.get("total_mag"))
    if total_mag is not None:
        values.append(("total_magnetization", total_mag, f"{method} per cell"))

    energy_total = safe_float(data.get("energy_total"))
    nsites = safe_float(data.get("nsites"))
    if energy_total is not None and nsites:
        values.append(("total_energy_per_atom", energy_total / nsites, method))

    spacegroup = safe_float(data.get("spg"))
    if spacegroup:
        values.append(("spacegroup_number", float(int(spacegroup)), method))

    for key, name, _unit in FIELD_MAP:
        value = clean(key, data, counters)
        if value is not None:
            values.append((name, value, method))
    return values


def run_replace(db, source_id: int) -> int:
    """Delete exactly the rows a previous run added, per the manifest."""

    if not MANIFEST.is_file():
        raise SystemExit(
            f"--replace needs the manifest of the previous run: {MANIFEST}"
        )
    pairs: list[tuple[str, int]] = []
    with gzip.open(MANIFEST, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, pk = line.rstrip("\n").split("\t")
            pairs.append((native_id, int(pk)))
    props = refs = 0
    for start in range(0, len(pairs), 20_000):
        for native_id, pk in pairs[start : start + 20_000]:
            props += db.execute(
                "DELETE FROM material_properties WHERE material_pk = ? "
                "AND source_id = ? AND native_id = ?",
                (pk, source_id, native_id),
            ).rowcount
            refs += db.execute(
                "DELETE FROM material_source_refs WHERE material_pk = ? "
                "AND source_id = ? AND native_id = ?",
                (pk, source_id, native_id),
            ).rowcount
        db.commit()
    print(f"--replace: deleted {props:,} property rows and {refs:,} refs",
          flush=True)
    return props


def run_recover(args) -> int:
    counters: Counter[str] = Counter()
    started = time.time()

    if args.dry_run:
        db = _read_only_db()
        source_id = _source_id(db)
        property_id_of = dict(db.execute("SELECT name, id FROM property_defs"))
    else:
        db = connect()
        db.execute("PRAGMA cache_size = -2097152")  # 2 GB page cache
        migrate(db)
        source_id = _source_def(db, SOURCE)
        db.commit()
        if args.replace:
            counters["replaced_property_rows"] = run_replace(db, source_id)
        defs = PropertyDefs(db)
        property_id_of = {
            name: defs.get(name, unit) for name, unit in UNITS.items()
        }
        db.commit()

    ref_map = build_ref_map(db, source_id)

    prop_batch: list[tuple] = []
    ref_batch: list[tuple] = []
    manifest: list[str] = []
    manifest_handle = None
    if not args.dry_run:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        manifest_handle = gzip.open(MANIFEST, "wt", encoding="utf-8")
        manifest_handle.write("native_id\tmaterial_pk\n")
    last_report = started

    def flush(force: bool = False) -> None:
        if args.dry_run:
            prop_batch.clear()
            ref_batch.clear()
            manifest.clear()
            return
        if not force and len(prop_batch) < args.batch_size:
            return
        if ref_batch:
            db.executemany(INSERT_REF, ref_batch)
            ref_batch.clear()
        if prop_batch:
            db.executemany(INSERT_PROP, prop_batch)
            prop_batch.clear()
        if manifest:
            manifest_handle.writelines(manifest)
            manifest.clear()
        db.commit()

    for subdir, method, native_id, data in iter_entries(
        limit=args.limit, subsets=SUBSETS
    ):
        counters["records"] += 1
        counters[f"records_{method}"] += 1
        if native_id in ref_map:
            counters["already_present"] += 1
            continue
        bare = native_id.rsplit(":", 1)[0]
        pks = _pks(ref_map.get(bare))
        if not pks:
            counters["bare_id_not_in_index"] += 1
            continue
        counters["recovered_records"] += 1
        counters[f"recovered_records_{method}"] += 1
        values = build_values(data, method, counters)
        for pk in pks:
            ref_batch.append((pk, source_id, native_id))
            counters["refs_added"] += 1
            manifest.append(f"{native_id}\t{pk}\n")
            for name, value, value_method in values:
                prop_batch.append((
                    pk, property_id_of[name], source_id, native_id,
                    value, None, value_method,
                ))
                counters["rows"] += 1
                counters[f"rows_{name}"] += 1
                counters[f"rows_{name}_{method}"] += 1
        flush()
        now = time.time()
        if now - last_report >= args.progress_seconds:
            elapsed = now - started
            print(
                f"[alexandria-recover] {counters['records']:,} records, "
                f"{counters['recovered_records']:,} recovered, "
                f"{counters['rows']:,} rows, "
                f"{counters['records'] / elapsed:,.0f} rec/s, "
                f"{elapsed / 60:.1f} min",
                flush=True,
            )
            last_report = now
    flush(force=True)

    counters["minutes"] = round((time.time() - started) / 60, 2)
    if not args.dry_run:
        manifest_handle.close()
        db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES "
            "('alexandria_functional_runs_recovered', ?)",
            (json.dumps(
                {
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "why": "stage_match dropped the PBEsol/SCAN re-runs of "
                           "already-admitted agm ids as duplicate_within_source; "
                           "their properties were never stored",
                    "join": "bare mat_id -> material_source_refs (identity join "
                            "on the source's own id)",
                    "subsets": list(SUBSETS),
                    "manifest": str(MANIFEST),
                    "guards": {
                        "dos_ef": "finite; negative clamped to 0.0 when "
                                  f"band_gap_ind > {GAPPED_EV} eV, else dropped",
                        "e_phase_separation":
                            f"finite and |v| <= {MAX_ABS_PHASE_SEPARATION}",
                    },
                    "counters": dict(counters),
                },
                sort_keys=True,
            ),),
        )
        db.commit()
    db.close()
    print(json.dumps(dict(counters), indent=2, sort_keys=True))
    print("dry run, nothing written" if args.dry_run else "recovered")
    return 0


def run_spot_check(args) -> int:
    """Compare N recovered records against the raw shards they came from."""

    if not MANIFEST.is_file():
        raise SystemExit(f"no manifest to spot check: {MANIFEST}")
    recovered: set[str] = set()
    with gzip.open(MANIFEST, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            recovered.add(line.split("\t", 1)[0])

    from scripts.properties.adapters.alexandria import _iter_shard_entries

    rng = random.Random(args.seed)
    shards = list(iter_shards(SUBSETS))
    db = _read_only_db()
    source_id = _source_id(db)
    property_id_of = dict(db.execute("SELECT name, id FROM property_defs"))
    name_of = {pid: name for name, pid in property_id_of.items()}

    results = []
    attempts = 0
    while len(results) < args.spot_check and attempts < args.spot_check * 20:
        attempts += 1
        subdir, method, suffix, shard = rng.choice(shards)
        target = rng.randrange(args.spot_check_depth)
        entry = None
        for index, candidate in enumerate(_iter_shard_entries(shard)):
            if index == target:
                entry = candidate
                break
        if entry is None:
            continue
        data = entry.get("data") or {}
        mat_id = str(data.get("mat_id") or "").strip()
        native_id = f"{mat_id}:{suffix}"
        if native_id not in recovered:
            continue
        expected = {
            name: (round(value, 12), value_method)
            for name, value, value_method in build_values(
                data, method, Counter()
            )
        }
        stored: dict[str, tuple] = {}
        for pid, value, value_method in db.execute(
            "SELECT property_id, value_num, method FROM material_properties "
            "WHERE source_id = ? AND native_id = ?",
            (source_id, native_id),
        ):
            stored[name_of[pid]] = (round(value, 12), value_method)
        refs = db.execute(
            "SELECT material_pk, match_via FROM material_source_refs "
            "WHERE source_id = ? AND native_id = ?",
            (source_id, native_id),
        ).fetchall()
        bare_refs = db.execute(
            "SELECT material_pk FROM material_source_refs "
            "WHERE source_id = ? AND native_id = ?",
            (source_id, mat_id),
        ).fetchall()
        results.append({
            "shard": f"{subdir}/{shard.name}",
            "entry_index": target,
            "native_id": native_id,
            "refs_added": refs,
            "bare_id_refs": [pk for pk, in bare_refs],
            "same_material_pk": sorted(pk for pk, _ in refs)
            == sorted(pk for pk, in bare_refs),
            "raw_fields": {
                key: data.get(key)
                for key in ("e_form", "e_above_hull", "band_gap_ind",
                            "band_gap_dir", "total_mag", "energy_total",
                            "nsites", "spg", "dos_ef", "e_phase_separation")
            },
            "expected_vs_stored": {
                name: {"expected": expected.get(name),
                       "stored": stored.get(name),
                       "match": expected.get(name) == stored.get(name)}
                for name in sorted(set(expected) | set(stored))
            },
            "all_match": expected == stored,
        })
    db.close()
    print(json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False))
    print(f"{sum(1 for r in results if r['all_match'])}/{len(results)} "
          "records match the raw shard exactly")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="stream, resolve and count; write nothing")
    parser.add_argument("--replace", action="store_true",
                        help="delete what a previous run added (per manifest) "
                             "before recovering again")
    parser.add_argument("--spot-check", type=int, default=0,
                        help="compare N recovered records with the raw shards")
    parser.add_argument("--spot-check-depth", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=20_000)
    parser.add_argument("--progress-seconds", type=float, default=60.0)
    args = parser.parse_args()

    if args.spot_check:
        return run_spot_check(args)
    return run_recover(args)


if __name__ == "__main__":
    sys.exit(main())
