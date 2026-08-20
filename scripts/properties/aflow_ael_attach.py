#!/usr/bin/env python3
"""Attach AFLOW AEL elastic / AGL thermal properties to the live index.

The main aflow load (2,981,853 AFLUX records) was fetched without ael_*/agl_*
columns. This one-off reads the targeted AEL/AGL page dump
(data/raw/acquired/aflow/aflux-ael-agl-2026-08-18/page-*.json, 5,664 entries),
resolves each auid through the match map (id_map: ('aflow', auid) ->
material_id -- populated for every matched/added aflow record, so this is a
pure join, no hashing) and INSERTs canonical property rows directly into
data/index/materials.sqlite under the existing 'aflow' source def.

Canonical mapping (units follow scripts/properties/registry.py):

    ael_bulk_modulus_vrh          -> bulk_modulus_vrh   [GPa]
    ael_shear_modulus_vrh         -> shear_modulus_vrh  [GPa]
    ael_poisson_ratio             -> poisson_ratio      [-]
    agl_debye                     -> debye_temperature  [K]
    agl_thermal_conductivity_300K -> thermal_conductivity [W/m·K]
    agl_heat_capacity_Cp_300K     -> heat_capacity      [J/mol·K] (x R from
                                     AFLOW's kB/cell; per mole of unit cells,
                                     noted in the method string)
    agl_thermal_expansion_300K    -> thermal_expansion  [1/K]

Exact zeros for Cp / thermal expansion (one known failed AGL record) are
skipped as unphysical. Idempotence: refuses to run if rows for these
properties already exist under the aflow source unless --replace is given
(which deletes exactly those rows first). --dry-run parses, resolves and
counts against a read-only connection and writes nothing.

Usage:
    python -m scripts.properties.aflow_ael_attach --dry-run
    python -m scripts.properties.aflow_ael_attach
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.properties.load import (  # noqa: E402
    INDEX_DB,
    MATCH_MAP,
    PropertyDefs,
    _resolve_material_pks,
    _source_def,
    connect,
    migrate,
)

DEFAULT_PAGES_DIR = (
    PROJECT_ROOT / "data" / "raw" / "acquired" / "aflow" / "aflux-ael-agl-2026-08-18"
)

GAS_CONSTANT = 8.314462618  # J/(mol*K); converts kB/cell -> J/(mol-of-cells*K)

METHOD_AEL = "PBE AEL (AFLOW)"
METHOD_AGL = "PBE AGL (AFLOW)"
METHOD_AGL_300K = "PBE AGL (AFLOW) 300K"

#: native field -> (canonical name, unit, method, value scale, skip exact 0)
FIELD_MAP = (
    ("ael_bulk_modulus_vrh", "bulk_modulus_vrh", "GPa", METHOD_AEL, 1.0, False),
    ("ael_shear_modulus_vrh", "shear_modulus_vrh", "GPa", METHOD_AEL, 1.0, False),
    ("ael_poisson_ratio", "poisson_ratio", None, METHOD_AEL, 1.0, False),
    ("agl_debye", "debye_temperature", "K", METHOD_AGL, 1.0, False),
    ("agl_thermal_conductivity_300K", "thermal_conductivity", "W/m·K",
     METHOD_AGL_300K, 1.0, False),
    ("agl_heat_capacity_Cp_300K", "heat_capacity", "J/mol·K",
     METHOD_AGL_300K + ", Cp per mole of unit cells", GAS_CONSTANT, True),
    ("agl_thermal_expansion_300K", "thermal_expansion", "1/K",
     METHOD_AGL_300K, 1.0, True),
)


def read_records(pages_dir: Path) -> dict[str, dict]:
    """auid -> record from every page-*.json (list or legacy dict payloads)."""
    pages = sorted(pages_dir.glob("page-*.json"))
    if not pages:
        raise SystemExit(f"no page-*.json files under {pages_dir}")
    records: dict[str, dict] = {}
    for page in pages:
        payload = json.loads(page.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = list(payload.values())
        for rec in payload:
            auid = rec.get("auid")
            if auid:
                records[auid] = rec
    return records


def resolve_material_ids(auids: list[str]) -> dict[str, list[str]]:
    """auid -> [material_id, ...] via the match map's ('aflow', auid) rows."""
    match_db = sqlite3.connect(f"file:{MATCH_MAP}?mode=ro", uri=True)
    resolved: dict[str, list[str]] = {}
    for start in range(0, len(auids), 900):
        chunk = auids[start : start + 900]
        marks = ",".join("?" for _ in chunk)
        for native_id, material_id in match_db.execute(
            f"SELECT native_id, material_id FROM id_map "
            f"WHERE source = 'aflow' AND native_id IN ({marks})",
            chunk,
        ):
            bucket = resolved.setdefault(native_id, [])
            if material_id not in bucket:
                bucket.append(material_id)
    match_db.close()
    return resolved


def build_rows(
    records: dict[str, dict],
    id_map: dict[str, list[str]],
    pk_of: dict[str, int],
    property_id_of,
    source_def_id: int | None,
    counters: Counter,
) -> list[tuple]:
    rows: list[tuple] = []
    for auid, rec in records.items():
        material_ids = id_map.get(auid)
        if not material_ids:
            counters["auids_missing_from_id_map"] += 1
            continue
        pks = [pk_of[m] for m in material_ids if m in pk_of]
        if not pks:
            counters["auids_missing_material_row"] += 1
            continue
        counters["auids_resolved"] += 1
        for field, name, unit, method, scale, skip_zero in FIELD_MAP:
            value = rec.get(field)
            if value is None:
                continue
            value = float(value)
            if skip_zero and value == 0.0:
                counters["skipped_zero_unphysical"] += 1
                continue
            property_id = property_id_of(name, unit)
            for pk in dict.fromkeys(pks):
                rows.append((
                    pk, property_id, source_def_id, auid,
                    value * scale, None, method,
                ))
                counters["property_rows"] += 1
                counters[f"rows_{name}"] += 1
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages-dir", type=Path, default=DEFAULT_PAGES_DIR)
    parser.add_argument("--dry-run", action="store_true",
                        help="parse + resolve + count only; no writes")
    parser.add_argument("--replace", action="store_true",
                        help="delete existing aflow rows for these properties "
                             "before inserting")
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    started = time.time()
    counters: Counter[str] = Counter()

    records = read_records(args.pages_dir)
    counters["records"] = len(records)

    id_map = resolve_material_ids(list(records))
    material_ids = {m for ids in id_map.values() for m in ids}

    if args.dry_run:
        db = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
        db.execute("PRAGMA query_only = ON")
        existing_names = {
            row[0] for row in db.execute("SELECT name FROM property_defs")
        }
        missing = sorted(
            {name for _, name, *_ in FIELD_MAP} - existing_names
        )
        counters["property_defs_to_create"] = len(missing)

        def property_id_of(name, unit):  # noqa: ARG001 - dry-run stand-in
            return -1
        row = db.execute(
            "SELECT id FROM source_defs WHERE key = 'aflow'"
        ).fetchone()
        source_def_id = row[0] if row else None
        pk_of = _resolve_material_pks(db, material_ids)
        build_rows(records, id_map, pk_of, property_id_of, source_def_id,
                   counters)
        counters["would_insert_rows"] = counters.pop("property_rows", 0)
        db.close()
    else:
        db = connect()
        migrate(db)
        source_def_id = _source_def(db, "aflow")
        defs = PropertyDefs(db)
        names = sorted({name for _, name, *_ in FIELD_MAP})
        existing_ids = [
            row[0] for row in db.execute(
                "SELECT id FROM property_defs WHERE name IN "
                f"({','.join('?' for _ in names)})", names,
            )
        ]
        if existing_ids:
            marks = ",".join("?" for _ in existing_ids)
            leftover = db.execute(
                f"SELECT COUNT(*) FROM material_properties "
                f"WHERE source_id = ? AND property_id IN ({marks})",
                (source_def_id, *existing_ids),
            ).fetchone()[0]
            if leftover and not args.replace:
                raise SystemExit(
                    f"{leftover:,} aflow AEL/AGL rows already present; "
                    "pass --replace to delete and re-attach"
                )
            if leftover:
                db.execute(
                    f"DELETE FROM material_properties "
                    f"WHERE source_id = ? AND property_id IN ({marks})",
                    (source_def_id, *existing_ids),
                )
                counters["replaced_rows"] = leftover
                db.commit()
        pk_of = _resolve_material_pks(db, material_ids)
        rows = build_rows(records, id_map, pk_of, defs.get, source_def_id,
                          counters)
        for start in range(0, len(rows), args.batch_size):
            db.executemany(
                "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows[start : start + args.batch_size],
            )
            db.commit()
        db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES "
            "('aflow_ael_agl_attached', ?)",
            (json.dumps({
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "pages_dir": str(args.pages_dir),
                "property_rows": counters["property_rows"],
                "auids_resolved": counters["auids_resolved"],
            }, sort_keys=True),),
        )
        db.commit()
        db.close()

    counters["minutes"] = round((time.time() - started) / 60, 2)
    print(json.dumps(dict(counters), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
