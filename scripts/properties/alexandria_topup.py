#!/usr/bin/env python3
"""Top up the loaded Alexandria source with the two fields its adapter skipped.

``scripts/properties/adapters/alexandria.py`` maps only e_form, e_above_hull,
band_gap_ind, band_gap_dir, total_mag, energy_total (as total_energy_per_atom),
spg and the 2D/1D dimensionality tag. The local bulk shards carry two further
scalars that belong in the canonical vocabulary:

    dos_ef             -> dos_at_fermi            [states/eV]
    e_phase_separation -> phase_separation_energy [eV/atom]

This is a targeted attach, not a re-load: it streams the same shards in the
same ``_SUBSETS`` order with the adapter's own ``_iter_shard_entries`` and
rebuilds the adapter's native_id scheme (bare mat_id for pbe-3d/2d/1d,
``<mat_id>:pbesol`` / ``<mat_id>:scan`` for the re-run sets), then joins those
ids to the live index through ``material_source_refs`` for the 'alexandria'
source and INSERTs only the two new properties. Nothing already stored is
touched, so the 44.6M rows the first ingestion wrote stay exactly as they are.
convex_hull*.json.bz2 files are skipped, same as the adapter.

Deliberately NOT ingested (do not re-litigate):

* ``energy_corrected`` - a hull-fitting correction of the same total energy we
  already store as total_energy_per_atom; keeping both would double-count one
  quantity under two names with no way to tell them apart downstream.
* ``stress`` - a 3x3 tensor; the schema stores scalars and curves.
* ``decomposition`` - a variable-length map of competing-phase ids/amounts,
  i.e. a relation, not a property value; e_above_hull and the new
  phase_separation_energy already carry its scalar content.
* ``prototype_id``, ``location``, ``run_timestamp`` - provenance/bookkeeping,
  not material properties.
* per-site ``charge`` / ``forces`` / ``magmom`` arrays - per-site tensors; the
  schema stores scalars and curves, and the adapter already drops them before
  building structures.

Guards: non-finite values are dropped, and |e_phase_separation| > 20 eV/atom is
dropped as a runaway. Negative dos_ef is not a sentinel - the values form a
continuum from -4.5 to -1e-06 and land almost entirely on gapped records, i.e.
they are smearing / interpolation undershoot of a quantity whose true value is
zero. So a negative dos_ef is clamped to 0.0 when the record is gapped
(band_gap_ind > 0.01 eV) and dropped otherwise, because a negative density of
states on a metal is not interpretable. Every clamp and drop is counted.

Idempotence: refuses to run when rows for these two properties already exist
under the alexandria source unless --replace is given (which deletes exactly
those rows first, and nothing else).

Usage:
    python -m scripts.properties.alexandria_topup --coverage --per-shard 3000
    python -m scripts.properties.alexandria_topup --dry-run --per-shard 3000
    python -m scripts.properties.alexandria_topup
    python -m scripts.properties.alexandria_topup --spot-check 5
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import sqlite3  # noqa: E402

from scripts.properties.adapters.alexandria import (  # noqa: E402
    _SUBSETS,
    _iter_shard_entries,
)
from scripts.properties.adapters._util import safe_float  # noqa: E402
from scripts.properties.base import ACQUIRED_ROOT  # noqa: E402
from scripts.properties.load import (  # noqa: E402
    INDEX_DB,
    PropertyDefs,
    _source_def,
    connect,
    migrate,
)

SOURCE = "alexandria"
RAW_ROOT = ACQUIRED_ROOT / SOURCE

#: native data key -> (canonical property name, unit)
FIELD_MAP: tuple[tuple[str, str, str], ...] = (
    ("dos_ef", "dos_at_fermi", "states/eV"),
    ("e_phase_separation", "phase_separation_energy", "eV/atom"),
)

#: sanity bound for e_phase_separation; anything wilder is a failed run
MAX_ABS_PHASE_SEPARATION = 20.0  # eV/atom

#: band_gap_ind above this counts as gapped, so dos_ef must physically be 0
GAPPED_EV = 0.01

#: how the stored native_ids map back onto the raw subsets, for projections
_SUBSET_REF_SQL = """
SELECT CASE
         WHEN native_id LIKE '%:pbesol' THEN 'pbesol-3d'
         WHEN native_id LIKE '%:scan' THEN 'scan-3d'
         WHEN native_id LIKE 'agm2%' THEN 'pbe-2d'
         WHEN native_id LIKE 'agm1%' THEN 'pbe-1d'
         ELSE 'pbe-3d-2025.07.02'
       END AS subset, COUNT(*)
FROM material_source_refs WHERE source_id = ? GROUP BY 1
"""

INSERT_SQL = "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)"


# --------------------------------------------------------------------------
# raw shard streaming (identical ordering / ids to the adapter)
# --------------------------------------------------------------------------


def iter_shards(subsets: tuple[str, ...] | None = None):
    """(subset dir, method, native_id suffix, shard path) in adapter order."""

    for subdir, prefix, method, suffix, _dimensionality in _SUBSETS:
        if subsets is not None and subdir not in subsets:
            continue
        directory = RAW_ROOT / subdir
        if not directory.is_dir():
            continue
        shards = sorted(
            path
            for path in directory.iterdir()
            if path.name.startswith(prefix)
            and path.name.endswith(".json.bz2")
            and not path.name.startswith("convex_hull")
        )
        for shard in shards:
            yield subdir, method, suffix, shard


def iter_entries(
    limit: int | None = None,
    per_shard: int | None = None,
    subsets: tuple[str, ...] | None = None,
):
    """Yield (subset, method, native_id, data) for every raw record.

    ``limit`` matches the adapter's semantics (a global cap on yielded
    records); ``per_shard`` caps each shard instead, which spreads a sample
    evenly over every subset and every shard; ``subsets`` restricts the walk
    to named subset directories.
    """

    count = 0
    for subdir, method, suffix, shard in iter_shards(subsets):
        taken = 0
        for entry in _iter_shard_entries(shard):
            if limit is not None and count >= limit:
                return
            if per_shard is not None and taken >= per_shard:
                break
            data = entry.get("data") or {}
            mat_id = str(data.get("mat_id") or "").strip()
            if not mat_id:
                continue
            count += 1
            taken += 1
            native_id = f"{mat_id}:{suffix}" if suffix else mat_id
            yield subdir, method, native_id, data


def clean(key: str, data: dict, counters: Counter) -> float | None:
    """Parse + sanity-guard one native value; count every clamp and drop.

    Takes the whole ``data`` dict rather than the bare value because the
    dos_ef rule needs the record's band gap to tell undershoot from nonsense.
    """

    raw = data.get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        counters[f"dropped_{key}_unparsable"] += 1
        return None
    if not math.isfinite(value):
        counters[f"dropped_{key}_non_finite"] += 1
        return None
    if key == "dos_ef" and value < 0.0:
        gap = safe_float(data.get("band_gap_ind"))
        if gap is not None and gap > GAPPED_EV:
            # No states at E_F in a gap: the negative number is smearing /
            # interpolation undershoot of a true zero.
            counters["clamped_dos_ef_gapped"] += 1
            return 0.0
        counters["dropped_dos_ef_negative_metal"] += 1
        return None
    if key == "e_phase_separation" and abs(value) > MAX_ABS_PHASE_SEPARATION:
        counters["dropped_e_phase_separation_out_of_range"] += 1
        return None
    return value


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return float("nan")


def _read_only_db() -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
    db.execute("PRAGMA query_only = ON")
    db.execute("PRAGMA busy_timeout = 120000")
    return db


def _source_id(db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT id FROM source_defs WHERE key = ?", (SOURCE,)
    ).fetchone()
    if row is None:
        raise SystemExit(f"source {SOURCE!r} is not loaded in {INDEX_DB}")
    return row[0]


def refs_by_subset(db: sqlite3.Connection, source_id: int) -> dict[str, int]:
    return dict(db.execute(_SUBSET_REF_SQL, (source_id,)))


def build_ref_map(db: sqlite3.Connection, source_id: int) -> dict[str, object]:
    """native_id -> pk (or [pk, ...] for the few ids matching several pool rows).

    Single-pk ids keep a bare int rather than a one-element list: the map has
    ~6.35M entries, and one list object per entry would cost several hundred
    extra MB for nothing.
    """

    started = time.time()
    before = _rss_mb()
    ref_map: dict[str, object] = {}
    rows = 0
    multi = 0
    for native_id, pk in db.execute(
        "SELECT native_id, material_pk FROM material_source_refs "
        "WHERE source_id = ?",
        (source_id,),
    ):
        rows += 1
        seen = ref_map.get(native_id)
        if seen is None:
            ref_map[native_id] = pk
        elif type(seen) is list:
            seen.append(pk)
        else:
            ref_map[native_id] = [seen, pk]
            multi += 1
    after = _rss_mb()
    print(
        f"ref map: {rows:,} refs -> {len(ref_map):,} native_ids "
        f"({multi:,} with several pks) in {time.time() - started:.0f}s; "
        f"RSS {before:.0f} -> {after:.0f} MB (+{after - before:.0f} MB)",
        flush=True,
    )
    return ref_map


def _pks(seen) -> tuple[int, ...]:
    if seen is None:
        return ()
    if type(seen) is list:
        return tuple(dict.fromkeys(seen))
    return (seen,)


# --------------------------------------------------------------------------
# modes
# --------------------------------------------------------------------------


def run_coverage(args) -> int:
    """Sample the shards and report non-null coverage + projected row cost."""

    counters: Counter[str] = Counter()
    per_subset: dict[str, Counter] = defaultdict(Counter)
    started = time.time()
    for subdir, _method, _native_id, data in iter_entries(
        args.limit, args.per_shard
    ):
        bucket = per_subset[subdir]
        bucket["sampled"] += 1
        counters["sampled"] += 1
        for key, _name, _unit in FIELD_MAP:
            raw = data.get(key)
            if raw is not None:
                bucket[f"present_{key}"] += 1
            if clean(key, data, counters) is not None:
                bucket[f"usable_{key}"] += 1

    db = _read_only_db()
    source_id = _source_id(db)
    refs = refs_by_subset(db, source_id)
    db.close()

    report: dict[str, object] = {
        "sampled_records": counters["sampled"],
        "seconds": round(time.time() - started, 1),
        "per_subset": {},
        "projected_rows": {},
    }
    projected = Counter()
    for subdir, bucket in per_subset.items():
        sampled = bucket["sampled"] or 1
        entry = {"sampled": bucket["sampled"], "stored_refs": refs.get(subdir, 0)}
        for key, name, _unit in FIELD_MAP:
            usable = bucket[f"usable_{key}"]
            fraction = usable / sampled
            entry[key] = {
                "present": bucket[f"present_{key}"],
                "usable": usable,
                "usable_fraction": round(fraction, 6),
            }
            projected[name] += round(refs.get(subdir, 0) * fraction)
        report["per_subset"][subdir] = entry
    report["projected_rows"] = dict(projected)
    report["projected_rows_total"] = sum(projected.values())
    report["drops_in_sample"] = {
        k: v for k, v in sorted(counters.items()) if k.startswith("dropped_")
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def run_attach(args) -> int:
    counters: Counter[str] = Counter()
    started = time.time()
    names = [name for _key, name, _unit in FIELD_MAP]

    if args.dry_run:
        db = _read_only_db()
    else:
        db = connect()
        # idx_props_material takes random inserts across 13.4M material_pks;
        # a roomy page cache keeps that B-tree from thrashing.
        db.execute("PRAGMA cache_size = -2097152")  # 2 GB page cache
        migrate(db)

    source_id = (
        _source_id(db) if args.dry_run else _source_def(db, SOURCE)
    )
    if not args.dry_run:
        db.commit()

    marks = ",".join("?" for _ in names)
    existing_defs = dict(
        db.execute(f"SELECT name, id FROM property_defs WHERE name IN ({marks})",
                   names)
    )
    if existing_defs:
        ids = list(existing_defs.values())
        leftover = db.execute(
            "SELECT COUNT(*) FROM material_properties WHERE source_id = ? "
            f"AND property_id IN ({','.join('?' for _ in ids)})",
            (source_id, *ids),
        ).fetchone()[0]
        if leftover and not args.replace:
            raise SystemExit(
                f"{leftover:,} alexandria rows already exist for {names}; "
                "pass --replace to delete exactly those and re-attach"
            )
        if leftover and args.replace and not args.dry_run:
            db.execute(
                "DELETE FROM material_properties WHERE source_id = ? "
                f"AND property_id IN ({','.join('?' for _ in ids)})",
                (source_id, *ids),
            )
            db.commit()
            counters["replaced_rows"] = leftover
            print(f"--replace: deleted {leftover:,} previous rows", flush=True)
        elif leftover:
            counters["existing_rows"] = leftover

    if args.dry_run:
        property_id_of = {name: -1 for name in names}
    else:
        defs = PropertyDefs(db)
        property_id_of = {
            name: defs.get(name, unit) for _key, name, unit in FIELD_MAP
        }
        db.commit()

    ref_map = build_ref_map(db, source_id)

    batch: list[tuple] = []
    last_report = started
    committed = 0

    def flush(force: bool = False) -> None:
        nonlocal committed
        if args.dry_run:
            batch.clear()
            return
        if not batch:
            return
        if force or len(batch) >= args.batch_size:
            db.executemany(INSERT_SQL, batch)
            committed += len(batch)
            batch.clear()
            if force or committed % args.commit_every < args.batch_size:
                db.commit()

    for _subdir, method, native_id, data in iter_entries(
        args.limit, args.per_shard
    ):
        counters["records"] += 1
        pks = _pks(ref_map.get(native_id))
        if not pks:
            counters["native_id_not_in_index"] += 1
            continue
        counters["records_resolved"] += 1
        for key, name, _unit in FIELD_MAP:
            value = clean(key, data, counters)
            if value is None:
                if data.get(key) is None:
                    counters[f"null_{key}"] += 1
                continue
            property_id = property_id_of[name]
            for pk in pks:
                batch.append(
                    (pk, property_id, source_id, native_id, value, None, method)
                )
                counters["rows"] += 1
                counters[f"rows_{name}"] += 1
        flush()
        now = time.time()
        if now - last_report >= args.progress_seconds:
            elapsed = now - started
            print(
                f"[alexandria-topup] {counters['records']:,} records, "
                f"{counters['rows']:,} rows, "
                f"{counters['records'] / elapsed:,.0f} rec/s, "
                f"{elapsed / 60:.1f} min",
                flush=True,
            )
            last_report = now
    flush(force=True)

    counters["minutes"] = round((time.time() - started) / 60, 2)
    if not args.dry_run:
        db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES "
            "('alexandria_topup_attached', ?)",
            (json.dumps(
                {
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "properties": {
                        name: unit for _key, name, unit in FIELD_MAP
                    },
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
    print("dry run, nothing written" if args.dry_run else "attached")
    return 0


def run_spot_check(args) -> int:
    """Re-read random raw records and compare them with the stored rows."""

    rng = random.Random(args.seed)
    shards = list(iter_shards())
    picks = [rng.choice(shards) for _ in range(args.spot_check)]
    offsets = [rng.randrange(args.spot_check_depth) for _ in picks]

    db = _read_only_db()
    source_id = _source_id(db)
    prop_ids = dict(
        db.execute(
            "SELECT name, id FROM property_defs WHERE name IN (?, ?)",
            [name for _key, name, _unit in FIELD_MAP],
        )
    )
    results = []
    for (subdir, method, suffix, shard), offset in zip(picks, offsets):
        entry = None
        for index, candidate in enumerate(_iter_shard_entries(shard)):
            if index == offset:
                entry = candidate
                break
        if entry is None:
            continue
        data = entry.get("data") or {}
        mat_id = str(data.get("mat_id") or "").strip()
        native_id = f"{mat_id}:{suffix}" if suffix else mat_id
        row = {
            "shard": f"{subdir}/{shard.name}",
            "entry_index": offset,
            "native_id": native_id,
            "method_expected": method,
            "fields": {},
        }
        for key, name, _unit in FIELD_MAP:
            raw = data.get(key)
            stored = db.execute(
                "SELECT value_num, method FROM material_properties "
                "WHERE source_id = ? AND property_id = ? AND native_id = ?",
                (source_id, prop_ids[name], native_id),
            ).fetchall()
            row["fields"][name] = {
                "raw": raw,
                "stored": [
                    {"value": value, "method": stored_method}
                    for value, stored_method in stored
                ],
                "match": bool(stored)
                and all(
                    value is not None
                    and raw is not None
                    and abs(value - float(raw)) <= 1e-9 * max(1.0, abs(float(raw)))
                    and stored_method == method
                    for value, stored_method in stored
                ),
            }
        results.append(row)
    db.close()
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", action="store_true",
                        help="sample the shards and report field coverage "
                             "plus the projected row cost; touches no writes")
    parser.add_argument("--dry-run", action="store_true",
                        help="stream, resolve and count; write nothing")
    parser.add_argument("--replace", action="store_true",
                        help="delete existing alexandria rows for these two "
                             "properties before inserting")
    parser.add_argument("--spot-check", type=int, default=0,
                        help="re-read N random raw records and compare them "
                             "with the stored rows")
    parser.add_argument("--spot-check-depth", type=int, default=20_000,
                        help="how deep into a shard a spot check may sample")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None,
                        help="global cap on records, adapter semantics")
    parser.add_argument("--per-shard", type=int, default=None,
                        help="cap records per shard (spreads a sample over "
                             "every subset)")
    parser.add_argument("--batch-size", type=int, default=20_000)
    parser.add_argument("--commit-every", type=int, default=500_000)
    parser.add_argument("--progress-seconds", type=float, default=60.0)
    args = parser.parse_args()

    if args.spot_check:
        return run_spot_check(args)
    if args.coverage:
        return run_coverage(args)
    return run_attach(args)


if __name__ == "__main__":
    sys.exit(main())
