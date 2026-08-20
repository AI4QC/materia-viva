#!/usr/bin/env python3
"""Load matched properties and admitted new structures into the live index.

Subcommands:

* ``migrate``            add the v3 provenance tables (idempotent)
* ``load <source>``      ingest one staged source (properties + new structures)
* ``backfill``           fill scalar filter columns, space groups and counters
* ``verify``             cross-check CSV / sqlite / blob row counts

Ordering per batch keeps crashes recoverable: blob bytes first (orphans are
harmless), then sqlite rows, then the CSV/meta append, then the match-map
update. ``verify`` reports any divergence.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sqlite3
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from materials_api.blob_store import BlobRef  # noqa: E402
from materials_api.formula import parse_formula  # noqa: E402
from materials_api.indexer import (  # noqa: E402
    _density,
    _extract_cif_fields,
    _spacegroup_symbol,
    crystal_system,
)
from scripts.properties.base import WORK_ROOT  # noqa: E402
from scripts.properties.cif_trim import trim_cif  # noqa: E402
from scripts.properties.registry import (  # noqa: E402
    CANONICAL_PROPERTIES,
    SCALAR_BACKFILL_PRIORITY,
    SCALAR_COLUMN_MAP,
    SOURCE_FAMILY,
    property_kind,
    property_unit,
    source_info,
)

DATA = PROJECT_ROOT / "data"
INDEX_DB = DATA / "index" / "materials.sqlite"
BLOB = DATA / "index" / "structures.blob"
MATCH_MAP = DATA / "props_work" / "match_map.sqlite"

#: Sources whose BAWL fingerprints provably cannot tell their own records
#: apart, so a ``hash`` row in matched.tsv.gz is not evidence of identity.
#:
#: Both are corpora of *enumerated predicted frameworks*: idealized silica and
#: aluminophosphate nets that differ in topology while reducing to primitive
#: cells the fingerprint reads as the same crystal. Measured on the Deem set,
#: the hash path collapses 126,578 distinct frameworks onto 281 pool materials,
#: one of them absorbing 27,007 of them; loading properties through those refs
#: staples one framework's elastic moduli onto a material that is a different
#: framework. This is the same finding that made scripts/properties/
#: deem_zeolite_admit.py admit these structures under a composite key
#: (bawl_hash, volume_per_site) and deliberately leave the colliding hashes out
#: of the match map -- matched.tsv.gz predates that decision and still carries
#: them, so the loader has to apply it too.
#:
#: Their ``origin`` refs (the composite-key admission, 1:1 with a pool material)
#: are unaffected and are what properties actually attach through.
FINGERPRINT_UNRELIABLE = {"deem-zeolites", "pcod"}


def set_data_root(root: Path) -> None:
    """Point every mutating path at another data root (sandbox testing)."""

    global DATA, INDEX_DB, BLOB, MATCH_MAP
    DATA = Path(root)
    INDEX_DB = DATA / "index" / "materials.sqlite"
    BLOB = DATA / "index" / "structures.blob"
    MATCH_MAP = DATA / "props_work" / "match_map.sqlite"

csv.field_size_limit(sys.maxsize)

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS source_defs (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    license TEXT,
    url TEXT
);
CREATE TABLE IF NOT EXISTS property_defs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    unit TEXT,
    kind TEXT NOT NULL DEFAULT 'num'
);
CREATE TABLE IF NOT EXISTS material_properties (
    material_pk INTEGER NOT NULL REFERENCES materials(pk) ON DELETE CASCADE,
    property_id INTEGER NOT NULL REFERENCES property_defs(id),
    source_id INTEGER NOT NULL REFERENCES source_defs(id),
    native_id TEXT,
    value_num REAL,
    value_text TEXT,
    method TEXT
);
CREATE INDEX IF NOT EXISTS idx_props_material ON material_properties(material_pk);
CREATE INDEX IF NOT EXISTS idx_props_lookup
    ON material_properties(property_id, source_id, material_pk);
CREATE TABLE IF NOT EXISTS material_source_refs (
    material_pk INTEGER NOT NULL REFERENCES materials(pk) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES source_defs(id),
    native_id TEXT NOT NULL,
    match_via TEXT NOT NULL,
    PRIMARY KEY (material_pk, source_id, native_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_srcref_source
    ON material_source_refs(source_id, native_id);
CREATE TABLE IF NOT EXISTS material_curves (
    id INTEGER PRIMARY KEY,
    material_pk INTEGER NOT NULL REFERENCES materials(pk) ON DELETE CASCADE,
    curve_type TEXT NOT NULL,
    fmt TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES source_defs(id),
    native_id TEXT,
    method TEXT,
    label TEXT,
    blob_offset INTEGER NOT NULL,
    blob_length INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_curves_material ON material_curves(material_pk);
"""


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(INDEX_DB)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA synchronous = NORMAL")
    db.execute("PRAGMA busy_timeout = 120000")
    return db


def migrate(db: sqlite3.Connection) -> None:
    db.executescript(MIGRATION_SQL)
    columns = {row[1] for row in db.execute("PRAGMA table_info(materials)")}
    if "material_family" not in columns:
        db.execute("ALTER TABLE materials ADD COLUMN material_family TEXT")
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_materials_family "
            "ON materials(material_family, pk) WHERE material_family IS NOT NULL"
        )
    db.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', '3')"
    )
    for name, (unit, kind) in CANONICAL_PROPERTIES.items():
        db.execute(
            "INSERT OR IGNORE INTO property_defs (name, unit, kind) VALUES (?, ?, ?)",
            (name, unit, kind),
        )
    db.commit()


def _loaded_sources(db: sqlite3.Connection) -> dict:
    row = db.execute(
        "SELECT value FROM metadata WHERE key = 'loaded_property_sources'"
    ).fetchone()
    return json.loads(row[0]) if row else {}


def _set_loaded(db: sqlite3.Connection, loaded: dict) -> None:
    db.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES "
        "('loaded_property_sources', ?)",
        (json.dumps(loaded, sort_keys=True),),
    )


def _source_def(db: sqlite3.Connection, source: str) -> int:
    info = source_info(source)
    db.execute(
        "INSERT INTO source_defs (key, name, license, url) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET name = excluded.name, "
        "license = excluded.license, url = excluded.url",
        (source, info.get("name", source), info.get("license"),
         info.get("official_url")),
    )
    return db.execute(
        "SELECT id FROM source_defs WHERE key = ?", (source,)
    ).fetchone()[0]


class PropertyDefs:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        self.cache: dict[str, int] = dict(
            db.execute("SELECT name, id FROM property_defs")
        )

    def get(self, name: str, unit: str | None) -> int:
        if name not in self.cache:
            self.db.execute(
                "INSERT OR IGNORE INTO property_defs (name, unit, kind) "
                "VALUES (?, ?, ?)",
                (name, unit or property_unit(name), property_kind(name)),
            )
            self.cache[name] = self.db.execute(
                "SELECT id FROM property_defs WHERE name = ?", (name,)
            ).fetchone()[0]
        return self.cache[name]


def _resolve_material_pks(
    db: sqlite3.Connection, material_ids: set[str]
) -> dict[str, int]:
    result: dict[str, int] = {}
    ids = list(material_ids)
    for start in range(0, len(ids), 900):
        chunk = ids[start : start + 900]
        placeholders = ",".join("?" for _ in chunk)
        result.update(
            db.execute(
                f"SELECT material_id, pk FROM materials "
                f"WHERE material_id IN ({placeholders})",
                chunk,
            )
        )
    return result


def _next_index(db: sqlite3.Connection, dataset: str) -> int:
    row = db.execute(
        "SELECT MAX(CAST(source_index AS INTEGER)) FROM materials WHERE dataset = ?",
        (dataset,),
    ).fetchone()
    return int(row[0]) + 1 if row and row[0] is not None else 0


def ingest_new_structures(
    db: sqlite3.Connection,
    source: str,
    source_def_id: int,
    limit: int | None = None,
) -> tuple[dict[str, list[int]], Counter]:
    """Append admitted structures to blob/sqlite/CSV/meta; return native->pk."""

    work = WORK_ROOT / source
    new_path = work / "new_structs.jsonl.gz"
    counters: Counter[str] = Counter()
    native_pks: dict[str, list[int]] = {}
    if not new_path.exists():
        return native_pks, counters

    from materials_api.repository import MaterialRepository

    match_db = sqlite3.connect(MATCH_MAP)
    repository = MaterialRepository(INDEX_DB, BLOB)
    repository.connection.close()
    repository.connection = db  # share the already-open connection

    next_idx = {
        "candidate": _next_index(db, "candidate"),
        "experimental": _next_index(db, "experimental"),
    }
    csv_handles = {}
    csv_writers = {}
    meta_handles = {}
    for dataset, csv_dir, meta_name in (
        ("candidate", DATA / "sources" / "candidate", "added_meta.tsv"),
        ("experimental", DATA / "sources" / "experimental", "synth_meta.tsv"),
    ):
        handle = (csv_dir / "train.csv").open("a", newline="", encoding="utf-8")
        csv_handles[dataset] = handle
        csv_writers[dataset] = csv.writer(handle)
        meta_path = csv_dir / meta_name
        fresh = not meta_path.exists()
        meta = meta_path.open("a", encoding="utf-8")
        if fresh:
            meta.write("index\tsource\tsource_id\tbawl_hash\tn_sites\n")
        meta_handles[dataset] = meta

    pending_csv: list[tuple[str, list]] = []
    pending_meta: list[tuple[str, str]] = []
    pending_map: list[tuple] = []
    started = time.time()

    def flush_files() -> None:
        db.commit()
        for dataset, row in pending_csv:
            csv_writers[dataset].writerow(row)
        for dataset, line in pending_meta:
            meta_handles[dataset].write(line)
        for handle in (*csv_handles.values(), *meta_handles.values()):
            handle.flush()
        pending_csv.clear()
        pending_meta.clear()
        match_db.executemany(
            "INSERT INTO hash_map VALUES (?, ?)",
            [(row[0], row[1]) for row in pending_map],
        )
        match_db.executemany(
            "INSERT INTO id_map VALUES (?, ?, ?)",
            [(source, row[2], row[1]) for row in pending_map],
        )
        match_db.commit()
        pending_map.clear()

    with BLOB.open("ab") as blob, gzip.open(new_path, "rt", encoding="utf-8") as rows:
        for line in rows:
            if limit is not None and counters["added"] >= limit:
                break
            payload = json.loads(line)
            # Defensive second pass: pipeline.stage_match already trims, and
            # trimming is idempotent (a trimmed CIF is a fixed point), so this
            # only catches new_structs.jsonl.gz written before the trim step
            # existed.  It cannot move the fingerprint: `hashed` below is the
            # hash the hash stage computed on the full text, and trimming is
            # fingerprint-preserving (see cif_trim_verify.py).
            cif = trim_cif(payload["cif"])
            hashed = payload["bawl_hash"]
            already = match_db.execute(
                "SELECT material_id FROM hash_map WHERE hash = ? LIMIT 1", (hashed,)
            ).fetchone()
            if already:
                # The fingerprint entered the pool between match and load (an
                # earlier record of this same run, or another source). Do not
                # add a second copy, but DO record the reference so this
                # record's properties still reach the material.
                counters["skipped_already_present"] += 1
                row = db.execute(
                    "SELECT pk FROM materials WHERE material_id = ?", (already[0],)
                ).fetchone()
                if row is not None:
                    db.execute(
                        "INSERT OR IGNORE INTO material_source_refs "
                        "VALUES (?, ?, ?, 'hash')",
                        (row[0], source_def_id, payload["native_id"]),
                    )
                    native_pks.setdefault(payload["native_id"], []).append(row[0])
                continue
            try:
                info = parse_formula(payload["formula"])
            except ValueError:
                counters["skipped_bad_formula"] += 1
                continue
            dataset = "experimental" if payload.get("experimental") else "candidate"
            index = next_idx[dataset]
            next_idx[dataset] += 1
            material_id = (
                f"{'exp' if dataset == 'experimental' else 'pool'}-train-{index}"
            )
            fields = _extract_cif_fields(cif)
            spacegroup = None
            try:
                spacegroup = int(hashed.split("_")[1])
            except (IndexError, ValueError):
                pass
            compressed = zlib.compress(cif.encode("utf-8"), 3)
            offset = blob.tell()
            blob.write(compressed)
            reference = BlobRef(offset=offset, length=len(compressed))
            record = {
                "material_id": material_id,
                "formula": info.formula,
                "chemical_system": info.chemical_system,
                "elements": info.elements,
                "dataset": dataset,
                "is_experimental": dataset == "experimental",
                "source_split": "train",
                "source_index": str(index),
                "n_elements": info.n_elements,
                "n_atoms": info.n_atoms,
                "pbes_gap": None,
                "density": _density(info.formula, fields.get("volume")),
                "spacegroup_number": spacegroup,
                "spacegroup_symbol": _spacegroup_symbol(spacegroup),
                "crystal_system": crystal_system(spacegroup),
                "material_family": SOURCE_FAMILY.get(source),
                "blob_offset": reference.offset,
                "blob_length": reference.length,
                **fields,
            }
            material_pk = repository.add_material(record, commit=False)
            db.execute(
                "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, 'origin')",
                (material_pk, source_def_id, payload["native_id"]),
            )
            native_pks.setdefault(payload["native_id"], []).append(material_pk)
            pending_csv.append(
                (dataset, [index, info.formula, cif, ""])
            )
            pending_meta.append(
                (
                    dataset,
                    f"{index}\t{source}\t{payload['native_id']}\t{hashed}"
                    f"\t{payload.get('n_sites', '')}\n",
                )
            )
            pending_map.append((hashed, material_id, payload["native_id"]))
            counters["added"] += 1
            counters[f"added_{dataset}"] += 1
            if len(pending_csv) >= 2_000:
                flush_files()
                if counters["added"] % 50_000 < 2_000:
                    print(
                        f"[{source}] {counters['added']:,} new structures "
                        f"({time.time() - started:.0f}s)",
                        flush=True,
                    )
        flush_files()
    for handle in (*csv_handles.values(), *meta_handles.values()):
        handle.close()

    match_db.close()
    return native_pks, counters


def _attach_aliases(
    db: sqlite3.Connection,
    source: str,
    source_def_id: int,
    native_pks: dict[str, list[int]],
    counters: Counter,
) -> None:
    """Attach intra-source fingerprint duplicates to their canonical material.

    One structure, several records that each carry their own properties (e.g.
    Alexandria's PBE / PBEsol / SCAN runs of one crystal). stage_match aliased
    them to the canonical record; without this they land in props_unmatched.

    Called from load_source, NOT from ingest_new_structures: that function
    returns early when ``new_structs.jsonl.gz`` is absent, which is exactly the
    re-load path (the staging file gets cleaned up after the first load), so an
    alias step living inside it would silently never run on a re-load.  It also
    has to run *after* matched.tsv.gz is folded in, because the canonical
    record is usually a matched one rather than a newly admitted one.
    """

    alias_path = WORK_ROOT / source / "alias.tsv.gz"
    if not alias_path.is_file():
        return
    alias_refs: list[tuple] = []
    with gzip.open(alias_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            duplicate, canonical = line.rstrip("\n").split("\t")
            for pk in native_pks.get(canonical, ()):
                native_pks.setdefault(duplicate, []).append(pk)
                alias_refs.append((pk, source_def_id, duplicate, "hash"))
                counters["alias_refs"] += 1
    for start in range(0, len(alias_refs), 50_000):
        db.executemany(
            "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, ?)",
            alias_refs[start : start + 50_000],
        )
    db.commit()


def load_source(source: str, *, limit: int | None = None) -> None:
    work = WORK_ROOT / source
    matched_path = work / "matched.tsv.gz"
    props_path = work / "staging_props.tsv.gz"
    if not matched_path.exists() or not props_path.exists():
        raise SystemExit(f"{source}: pipeline artifacts missing under {work}")

    db = connect()
    migrate(db)
    loaded = _loaded_sources(db)
    if source in loaded:
        raise SystemExit(
            f"{source} is already loaded ({loaded[source]}); refusing to double-load"
        )
    source_def_id = _source_def(db, source)
    leftover = db.execute(
        "SELECT COUNT(*) FROM material_properties WHERE source_id = ?",
        (source_def_id,),
    ).fetchone()[0]
    if leftover:
        # A crashed earlier attempt left partial rows; start that source clean.
        print(f"[{source}] clearing {leftover:,} rows from an interrupted load",
              flush=True)
        db.execute(
            "DELETE FROM material_properties WHERE source_id = ?",
            (source_def_id,),
        )
        db.execute(
            "DELETE FROM material_source_refs WHERE source_id = ? "
            "AND match_via != 'origin'",
            (source_def_id,),
        )
        db.commit()
    defs = PropertyDefs(db)
    counters: Counter[str] = Counter()
    started = time.time()

    native_pks, new_counters = ingest_new_structures(
        db, source, source_def_id, limit=limit
    )
    counters.update(new_counters)

    # Seed from the links this source already has. A re-load that only adds
    # newly mapped property fields must reach every record the first load
    # linked — including structures admitted back then, whose
    # new_structs.jsonl.gz may since have been cleaned up. Without this, those
    # records' properties would silently become props_unmatched on re-load.
    for native_id, material_pk in db.execute(
        "SELECT native_id, material_pk FROM material_source_refs WHERE source_id = ?",
        (source_def_id,),
    ):
        pks = native_pks.setdefault(native_id, [])
        if material_pk not in pks:
            pks.append(material_pk)
            counters["preexisting_links"] += 1

    material_ids: set[str] = set()
    matched_rows: list[tuple[str, str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    drop_hash = source in FINGERPRINT_UNRELIABLE
    with gzip.open(matched_path, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, material_id, via = line.rstrip("\n").split("\t")
            if drop_hash and via == "hash":
                counters["hash_match_rejected"] += 1
                continue
            matched_rows.append((native_id, material_id, via))
            seen_pairs.add((native_id, material_id))
            material_ids.add(material_id)

    # Authoritative-id links found by the *latest* adapt. stage_adapt rewrites
    # id_matches.tsv.gz against the live id map every run, but only stage_match
    # folds it into matched.tsv.gz — and a re-load deliberately skips the
    # expensive hash/match stages. Reading it here is what makes a re-load pick
    # up ids that became resolvable since the last full match (e.g. every COD
    # id that entered the pool after this source was first matched); otherwise
    # those links are written to disk and then ignored, and their properties
    # are counted as props_unmatched.
    id_matches_path = work / "id_matches.tsv.gz"
    if id_matches_path.is_file():
        with gzip.open(id_matches_path, "rt", encoding="utf-8") as handle:
            next(handle)
            for line in handle:
                native_id, material_id, via = line.rstrip("\n").split("\t")
                if (native_id, material_id) in seen_pairs:
                    continue
                seen_pairs.add((native_id, material_id))
                matched_rows.append((native_id, material_id, via))
                material_ids.add(material_id)
                counters["id_links_refreshed"] += 1
    del seen_pairs
    pk_of = _resolve_material_pks(db, material_ids)

    ref_batch = []
    for native_id, material_id, via in matched_rows:
        material_pk = pk_of.get(material_id)
        if material_pk is None:
            counters["matched_missing_material"] += 1
            continue
        native_pks.setdefault(native_id, []).append(material_pk)
        ref_batch.append((material_pk, source_def_id, native_id, via))
        counters["matched_refs"] += 1
    del matched_rows
    for start in range(0, len(ref_batch), 50_000):
        db.executemany(
            "INSERT OR IGNORE INTO material_source_refs VALUES (?, ?, ?, ?)",
            ref_batch[start : start + 50_000],
        )
        if start % 2_000_000 == 0:
            db.commit()
    db.commit()
    del ref_batch

    _attach_aliases(db, source, source_def_id, native_pks, counters)

    prop_batch: list[tuple] = []
    with gzip.open(props_path, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, name, value_num, value_text, unit, method = (
                line.rstrip("\n").split("\t")
            )
            pks = native_pks.get(native_id)
            if not pks:
                counters["props_unmatched"] += 1
                continue
            property_id = defs.get(name, unit or None)
            for material_pk in dict.fromkeys(pks):
                prop_batch.append((
                    material_pk,
                    property_id,
                    source_def_id,
                    native_id,
                    float(value_num) if value_num else None,
                    value_text or None,
                    method or None,
                ))
                counters["property_rows"] += 1
            if len(prop_batch) >= 50_000:
                db.executemany(
                    "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)",
                    prop_batch,
                )
                prop_batch.clear()
                if counters["property_rows"] % 2_000_000 < 50_000:
                    db.commit()
                    print(
                        f"[{source}] {counters['property_rows']:,} property rows",
                        flush=True,
                    )
    if prop_batch:
        db.executemany(
            "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)",
            prop_batch,
        )

    loaded[source] = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "property_rows": counters["property_rows"],
        "matched_refs": counters["matched_refs"],
        "new_structures": counters["added"],
    }
    _set_loaded(db, loaded)
    for dataset, key in (
        ("candidate", "candidate_count"),
        ("experimental", "experimental_count"),
    ):
        count = db.execute(
            "SELECT COUNT(*) FROM materials WHERE dataset = ?", (dataset,)
        ).fetchone()[0]
        db.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, str(count)),
        )
    db.commit()
    db.close()
    counters["load_minutes"] = round((time.time() - started) / 60, 1)
    report_path = work / "load_report.json"
    report_path.write_text(
        json.dumps(dict(counters), indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(dict(counters), indent=2, sort_keys=True), flush=True)


def backfill() -> None:
    db = connect()
    migrate(db)
    started = time.time()

    print("backfilling space groups from merge-metadata fingerprints", flush=True)
    _backfill_spacegroups(db)

    source_ids = dict(db.execute("SELECT key, id FROM source_defs"))
    property_ids = dict(db.execute("SELECT name, id FROM property_defs"))
    for prop_name, column in SCALAR_COLUMN_MAP.items():
        property_id = property_ids.get(prop_name)
        if property_id is None:
            continue
        value_column = (
            "value_text" if property_kind(prop_name) == "text" else "value_num"
        )
        for source in SCALAR_BACKFILL_PRIORITY:
            source_id = source_ids.get(source)
            if source_id is None:
                continue
            cursor = db.execute(
                f"UPDATE materials SET {column} = ("
                f"  SELECT mp.{value_column} FROM material_properties mp"
                f"  WHERE mp.material_pk = materials.pk"
                f"    AND mp.property_id = ? AND mp.source_id = ?"
                f"    AND mp.{value_column} IS NOT NULL LIMIT 1"
                f") WHERE {column} IS NULL AND pk IN ("
                f"  SELECT material_pk FROM material_properties"
                f"  WHERE property_id = ? AND source_id = ?"
                f"    AND {value_column} IS NOT NULL)",
                (property_id, source_id, property_id, source_id),
            )
            if cursor.rowcount:
                print(
                    f"  {column} <- {prop_name} [{source}]: "
                    f"{cursor.rowcount:,} rows",
                    flush=True,
                )
            db.commit()

    print("labelling material families", flush=True)
    source_ids_by_key = dict(db.execute("SELECT key, id FROM source_defs"))
    for source, family in SOURCE_FAMILY.items():
        source_id = source_ids_by_key.get(source)
        if source_id is None:
            continue
        cursor = db.execute(
            "UPDATE materials SET material_family = ? WHERE material_family IS NULL "
            "AND pk IN (SELECT material_pk FROM material_source_refs "
            "WHERE source_id = ?)",
            (family, source_id),
        )
        if cursor.rowcount:
            print(f"  {family} <- {source}: {cursor.rowcount:,} rows", flush=True)
    dim_property = db.execute(
        "SELECT id FROM property_defs WHERE name = 'dimensionality'"
    ).fetchone()
    if dim_property:
        for text, family in (("2D", "2d-material"), ("1D", "1d-material")):
            cursor = db.execute(
                "UPDATE materials SET material_family = ? "
                "WHERE material_family IS NULL AND pk IN ("
                "  SELECT material_pk FROM material_properties "
                "  WHERE property_id = ? AND value_text = ?)",
                (family, dim_property[0], text),
            )
            if cursor.rowcount:
                print(
                    f"  {family} <- dimensionality={text}: {cursor.rowcount:,} rows",
                    flush=True,
                )
    db.commit()

    property_counts = {
        "spacegroup": db.execute(
            "SELECT COUNT(*) FROM materials WHERE spacegroup_number IS NOT NULL"
        ).fetchone()[0],
        "pbes_gap": db.execute(
            "SELECT COUNT(*) FROM materials WHERE pbes_gap IS NOT NULL"
        ).fetchone()[0],
        "density": db.execute(
            "SELECT COUNT(*) FROM materials WHERE density IS NOT NULL"
        ).fetchone()[0],
        "formation_energy": db.execute(
            "SELECT COUNT(*) FROM materials WHERE formation_energy_per_atom "
            "IS NOT NULL"
        ).fetchone()[0],
        "energy_above_hull": db.execute(
            "SELECT COUNT(*) FROM materials WHERE energy_above_hull IS NOT NULL"
        ).fetchone()[0],
        "magnetism": db.execute(
            "SELECT COUNT(*) FROM materials WHERE magnetic_ordering IS NOT NULL "
            "OR total_magnetization IS NOT NULL"
        ).fetchone()[0],
        "elasticity": db.execute(
            "SELECT COUNT(*) FROM materials WHERE bulk_modulus IS NOT NULL "
            "OR shear_modulus IS NOT NULL"
        ).fetchone()[0],
    }
    db.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES "
        "('property_counts', ?)",
        (json.dumps(property_counts, sort_keys=True),),
    )
    db.commit()
    db.close()
    print(
        f"backfill done in {(time.time() - started) / 60:.1f} min: "
        + json.dumps(property_counts, sort_keys=True),
        flush=True,
    )


def _backfill_spacegroups(db: sqlite3.Connection) -> None:
    """Space groups for the whole pool, parsed from the BAWL middle token."""

    have = db.execute(
        "SELECT COUNT(*) FROM materials WHERE spacegroup_number IS NOT NULL"
    ).fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    if have >= total * 0.95:
        print(f"  space groups already cover {have:,}/{total:,}; skipping")
        return

    match_db = sqlite3.connect(f"file:{MATCH_MAP}?mode=ro", uri=True)
    updated = 0
    batch: list[tuple[int, str, str, str]] = []

    def flush() -> None:
        nonlocal updated, batch
        db.executemany(
            "UPDATE materials SET spacegroup_number = ?, spacegroup_symbol = ?, "
            "crystal_system = ? WHERE material_id = ? "
            "AND spacegroup_number IS NULL",
            [(n, s, c, m) for n, s, c, m in batch],
        )
        updated += len(batch)
        batch = []
        db.commit()

    for hashed, material_id in match_db.execute(
        "SELECT hash, material_id FROM hash_map"
    ):
        try:
            number = int(hashed.split("_")[1])
        except (IndexError, ValueError):
            continue
        if not 1 <= number <= 230:
            continue
        batch.append((
            number,
            _spacegroup_symbol(number),
            crystal_system(number),
            material_id,
        ))
        if len(batch) >= 20_000:
            flush()
    flush()
    match_db.close()
    have = db.execute(
        "SELECT COUNT(*) FROM materials WHERE spacegroup_number IS NOT NULL"
    ).fetchone()[0]
    print(f"  space groups now cover {have:,}/{total:,} materials", flush=True)


def verify() -> None:
    db = connect()
    report = {}
    for dataset in ("candidate", "experimental"):
        sqlite_count = db.execute(
            "SELECT COUNT(*) FROM materials WHERE dataset = ?", (dataset,)
        ).fetchone()[0]
        report[dataset] = {"sqlite": sqlite_count}
    for table in ("material_properties", "material_source_refs", "property_defs",
                  "source_defs"):
        try:
            report[table] = db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            report[table] = None
    report["loaded_sources"] = _loaded_sources(db)
    db.close()
    print(json.dumps(report, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root", type=Path, default=None,
        help="alternate data root (sandbox testing)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    load_parser = sub.add_parser("load")
    load_parser.add_argument("source")
    load_parser.add_argument("--limit", type=int, default=None)
    sub.add_parser("backfill")
    sub.add_parser("verify")
    args = parser.parse_args()

    if args.data_root is not None:
        set_data_root(args.data_root)

    if args.command == "migrate":
        db = connect()
        migrate(db)
        db.close()
        print("migrated to schema v3")
    elif args.command == "load":
        load_source(args.source, limit=args.limit)
    elif args.command == "backfill":
        backfill()
    elif args.command == "verify":
        verify()
    return 0


if __name__ == "__main__":
    sys.exit(main())
