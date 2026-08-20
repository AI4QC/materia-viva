#!/usr/bin/env python3
"""Attach the recomputed PhononDB phonon scalars to the live index.

The NIMS PhononDB acquisition ships phonon results only as rendered PNGs, but
every record carries the complete phonopy displacement/force dataset.
``scripts/properties/phonondb_phonons.py`` recomputes the real numbers into
``data/props_work/phonondb/phonons.jsonl.gz``; this one-off joins those rows to
the pool through the source's own matched.tsv.gz (native_id
``phonondb-<uuid>`` -> material_id) and INSERTs canonical property rows under
the existing 'phonondb' source def.

Canonical mapping (units follow scripts/properties/registry.py):

    max_freq_thz  -> phonon_max_frequency  [THz]
    min_freq_thz  -> phonon_min_frequency  [THz]
    has_imaginary -> has_imaginary_phonon  [bool]
    cv_300k       -> heat_capacity         [J/mol·K]

Cv is recomputed per primitive cell; NIMS publishes it per formula unit, so it
is divided by the record's ``z_formula`` and the normalization is stated in the
method string, following the convention aflow_ael_attach.py uses.

Idempotence: refuses to run when rows for these properties already exist under
the phonondb source unless --replace is given (which deletes exactly those rows
first). --dry-run resolves and counts against a read-only connection.

Usage:
    python -m scripts.properties.phonondb_attach --dry-run
    python -m scripts.properties.phonondb_attach
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.properties.load import (  # noqa: E402
    INDEX_DB,
    PropertyDefs,
    _source_def,
    connect,
    migrate,
)

WORK = PROJECT_ROOT / "data" / "props_work" / "phonondb"
PHONONS = WORK / "phonons.jsonl.gz"
MATCHED = WORK / "matched.tsv.gz"

METHOD = "phonopy PBEsol (PhononDB)"
METHOD_CV = "phonopy PBEsol (PhononDB) 300K, Cv per mole of formula units"

#: sanity bounds; values outside are dropped and counted
MAX_FREQ_THZ = 300.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    if not PHONONS.is_file():
        raise SystemExit(f"missing recomputed phonons: {PHONONS}")
    if not MATCHED.is_file():
        raise SystemExit(f"missing matched map, load phonondb first: {MATCHED}")

    # native_id -> [material_id, ...]
    targets: dict[str, list[str]] = {}
    with gzip.open(MATCHED, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, material_id, _via = line.rstrip("\n").split("\t")
            targets.setdefault(native_id, []).append(material_id)

    db = connect()
    migrate(db)
    source_id = _source_def(db, "phonondb")
    db.commit()
    defs = PropertyDefs(db)
    names = ("phonon_max_frequency", "phonon_min_frequency",
             "has_imaginary_phonon", "heat_capacity")
    property_ids = {name: defs.get(name, None) for name in names}

    existing = db.execute(
        "SELECT COUNT(*) FROM material_properties WHERE source_id = ? "
        f"AND property_id IN ({','.join('?' for _ in property_ids)})",
        (source_id, *property_ids.values()),
    ).fetchone()[0]
    if existing and not args.replace:
        raise SystemExit(
            f"{existing:,} phonon rows already attached; pass --replace to redo"
        )
    if existing and args.replace and not args.dry_run:
        db.execute(
            "DELETE FROM material_properties WHERE source_id = ? "
            f"AND property_id IN ({','.join('?' for _ in property_ids)})",
            (source_id, *property_ids.values()),
        )
        db.commit()
        print(f"replaced: deleted {existing:,} previous rows", flush=True)

    pk_of: dict[str, int] = {}
    counters: Counter[str] = Counter()
    batch: list[tuple] = []

    def resolve(material_id: str) -> int | None:
        if material_id not in pk_of:
            row = db.execute(
                "SELECT pk FROM materials WHERE material_id = ?", (material_id,)
            ).fetchone()
            if row is None:
                return None
            pk_of[material_id] = row[0]
        return pk_of[material_id]

    with gzip.open(PHONONS, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            counters["records"] += 1
            if record.get("error"):
                counters["record_error"] += 1
                continue
            material_ids = targets.get(record["native_id"])
            if not material_ids:
                counters["unmatched"] += 1
                continue
            values: list[tuple[str, float | None, str]] = []
            hi = record.get("max_freq_thz")
            lo = record.get("min_freq_thz")
            if hi is not None and abs(hi) <= MAX_FREQ_THZ:
                values.append(("phonon_max_frequency", float(hi), METHOD))
            elif hi is not None:
                counters["dropped_max_freq_out_of_range"] += 1
            if lo is not None and abs(lo) <= MAX_FREQ_THZ:
                values.append(("phonon_min_frequency", float(lo), METHOD))
            if record.get("has_imaginary") is not None:
                values.append((
                    "has_imaginary_phonon",
                    1.0 if record["has_imaginary"] else 0.0,
                    METHOD,
                ))
            cv = record.get("cv_300k")
            z = record.get("z_formula") or 1
            if cv is not None and z:
                per_fu = float(cv) / float(z)
                if 0 < per_fu < 5000:
                    values.append(("heat_capacity", per_fu, METHOD_CV))
                else:
                    counters["dropped_cv_out_of_range"] += 1
            for material_id in dict.fromkeys(material_ids):
                pk = resolve(material_id)
                if pk is None:
                    counters["material_missing"] += 1
                    continue
                for name, value, method in values:
                    batch.append((
                        pk, property_ids[name], source_id,
                        record["native_id"], value, None, method,
                    ))
                    counters["rows"] += 1
            if len(batch) >= 20_000 and not args.dry_run:
                db.executemany(
                    "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                db.commit()
                batch.clear()
    if batch and not args.dry_run:
        db.executemany(
            "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)", batch
        )
    if not args.dry_run:
        db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES "
            "('phonondb_phonons_attached', ?)",
            (json.dumps(dict(counters), sort_keys=True),),
        )
        db.commit()
    db.close()
    print(json.dumps(dict(counters), indent=2, sort_keys=True))
    print("dry run, nothing written" if args.dry_run else "attached")
    return 0


if __name__ == "__main__":
    sys.exit(main())
