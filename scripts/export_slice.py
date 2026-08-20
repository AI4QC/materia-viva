#!/usr/bin/env python3
"""Build a small, self-contained MateriaViva index for frontend development.

The full index is ~47 GB across three files, which is not something you want to
pull down to tweak a chart. This carves out a slice that is small enough to
commit-and-forget but still exercises every code path the UI has: every source,
every property name, every curve type, every material family, both datasets.

Selection is a greedy set cover, not a random sample. A random 1,000 materials
out of 13.5 million would miss almost every rare property -- there are 165
property names and 54 sources, and the long tail (obelix's 83 rows, tcod's 357)
would never appear, so the very panels most likely to be broken are the ones a
random slice cannot show you. So:

1. cover every (property, source) pair that exists at all;
2. cover every (curve_type, source) pair;
3. cover every material_family, crystal system and dataset;
4. top up to --limit with a spread across the pool so listings, facets and
   pagination look like the real thing rather than a museum of edge cases.

Output is a directory holding materials.sqlite + structures.blob + curves.blob,
byte-compatible with what scripts/serve.py --runtime expects. Primary keys are
preserved so material_ids in bug reports still line up with the full index;
only blob offsets are rewritten, since the payloads move.

    python scripts/export_slice.py --out data/slice --limit 1000
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = PROJECT_ROOT / "backend" / "materials_api" / "schema.sql"
SOURCE_INDEX = PROJECT_ROOT / "data" / "index"


def _connect_ro(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=600)
    db.execute("PRAGMA busy_timeout = 600000")
    return db


def choose_materials(db: sqlite3.Connection, limit: int) -> list[int]:
    """Greedy cover of every (property, source) and (curve_type, source) pair."""

    started = time.time()
    # material -> set of coverage targets it satisfies. Built from the two
    # provenance tables; a full scan of material_properties is unavoidable but
    # runs once and only keeps the DISTINCT triples.
    wanted: dict[int, set[tuple]] = defaultdict(set)
    target_owners: dict[tuple, set[int]] = defaultdict(set)

    for pk, prop, src in db.execute(
        "SELECT DISTINCT material_pk, property_id, source_id FROM material_properties"
    ):
        key = ("p", prop, src)
        wanted[pk].add(key)
        target_owners[key].add(pk)
    print(f"  property targets: {len(target_owners):,} ({time.time()-started:.0f}s)", flush=True)

    for pk, ctype, src in db.execute(
        "SELECT DISTINCT material_pk, curve_type, source_id FROM material_curves"
    ):
        key = ("c", ctype, src)
        wanted[pk].add(key)
        target_owners[key].add(pk)

    for pk, family in db.execute(
        "SELECT pk, material_family FROM materials WHERE material_family IS NOT NULL"
    ):
        key = ("f", family, None)
        wanted[pk].add(key)
        target_owners[key].add(pk)
    print(f"  all targets: {len(target_owners):,} ({time.time()-started:.0f}s)", flush=True)

    # Greedy: repeatedly take the material covering the most still-uncovered
    # targets. Rarest-first ordering keeps this cheap -- a target owned by one
    # material forces that material in, and most of the tail is like that.
    uncovered = set(target_owners)
    chosen: list[int] = []
    seen: set[int] = set()
    by_rarity = sorted(target_owners, key=lambda k: len(target_owners[k]))
    for key in by_rarity:
        if key not in uncovered:
            continue
        # Of the materials that own this rare target, take the one that also
        # covers the most other uncovered targets.
        best = max(target_owners[key], key=lambda pk: len(wanted[pk] & uncovered))
        if best in seen:
            uncovered -= wanted[best]
            continue
        seen.add(best)
        chosen.append(best)
        uncovered -= wanted[best]
    # Coverage is never truncated by --limit. A slice that silently omits a
    # property is worse than a slice that is a few hundred materials larger:
    # the whole point is that every panel the UI can render has something to
    # render. --limit only decides how far to top up beyond the cover.
    print(
        f"  cover: {len(chosen):,} materials, {len(target_owners) - len(uncovered):,}"
        f"/{len(target_owners):,} targets ({time.time()-started:.0f}s)",
        flush=True,
    )
    if uncovered:
        raise SystemExit(f"BUG: {len(uncovered):,} targets left uncovered")
    if len(chosen) > limit:
        print(
            f"  note: full coverage needs {len(chosen):,} materials, above the"
            f" --limit {limit:,} top-up target; keeping all of them.",
            flush=True,
        )

    # Elements get a targeted pass rather than a coverage target of their own:
    # material_elements holds ~40M rows, and folding all of them into the
    # wanted/target_owners maps costs gigabytes to cover a handful of noble
    # gases and actinides. The periodic table is this UI's main control, so an
    # element that selects nothing is a visibly dead button.
    have = {
        row[0] for row in db.execute(
            "SELECT DISTINCT element FROM material_elements WHERE material_pk IN"
            f" ({','.join('?' * len(chosen))})", chosen
        )
    } if chosen else set()
    all_elements = {row[0] for row in db.execute(
        "SELECT DISTINCT element FROM material_elements"
    )}
    for element in sorted(all_elements - have):
        row = db.execute(
            "SELECT material_pk FROM material_elements WHERE element = ? LIMIT 1",
            (element,),
        ).fetchone()
        if row and row[0] not in seen:
            seen.add(row[0])
            chosen.append(row[0])
    print(f"  + elements: {len(all_elements)} covered, {len(chosen):,} materials",
          flush=True)

    # Top up with a deterministic spread so listings and facets look normal.
    # Ordering by pk % a large prime scatters across the pool without random().
    if len(chosen) < limit:
        need = limit - len(chosen)
        for (pk,) in db.execute(
            "SELECT pk FROM materials ORDER BY (pk * 2654435761) % 4294967296 LIMIT ?",
            (need + len(chosen),),
        ):
            if pk not in seen:
                seen.add(pk)
                chosen.append(pk)
                if len(chosen) >= limit:
                    break
    print(f"  final: {len(chosen):,} materials ({time.time()-started:.0f}s)", flush=True)
    return chosen


def build(out_dir: Path, limit: int) -> None:
    src_db_path = SOURCE_INDEX / "materials.sqlite"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_db_path = out_dir / "materials.sqlite"
    for stale in (out_db_path, out_dir / "structures.blob", out_dir / "curves.blob"):
        stale.unlink(missing_ok=True)
    for stale in out_dir.glob("materials.sqlite-*"):
        stale.unlink()

    db = _connect_ro(src_db_path)
    print("selecting materials...", flush=True)
    pks = choose_materials(db, limit)
    pk_set = set(pks)

    out = sqlite3.connect(out_db_path)
    out.executescript(SCHEMA.read_text(encoding="utf-8"))

    # Reference tables come over whole: they are tiny, and a source_defs row
    # with no rows left in the slice still documents what the full index holds.
    for table, cols in (
        ("source_defs", "id, key, name, license, url"),
        ("property_defs", "id, name, unit, kind"),
    ):
        rows = db.execute(f"SELECT {cols} FROM {table}").fetchall()
        out.executemany(
            f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' * len(cols.split(',')))})",
            rows,
        )

    material_cols = [r[1] for r in db.execute("PRAGMA table_info(materials)")]
    placeholders = ",".join("?" * len(material_cols))
    off_i = material_cols.index("blob_offset")
    len_i = material_cols.index("blob_length")

    print("copying structures...", flush=True)
    src_blob = (SOURCE_INDEX / "structures.blob").open("rb")
    out_blob = (out_dir / "structures.blob").open("wb")
    batch = []
    for pk in pks:
        row = list(db.execute(
            f"SELECT {','.join(material_cols)} FROM materials WHERE pk = ?", (pk,)
        ).fetchone())
        src_blob.seek(row[off_i])
        payload = src_blob.read(row[len_i])
        row[off_i] = out_blob.tell()
        out_blob.write(payload)
        batch.append(tuple(row))
    out.executemany(
        f"INSERT INTO materials ({','.join(material_cols)}) VALUES ({placeholders})", batch
    )
    src_blob.close()
    out_blob.close()

    print("copying curves...", flush=True)
    src_curves = (SOURCE_INDEX / "curves.blob").open("rb")
    out_curves = (out_dir / "curves.blob").open("wb")
    curve_rows = []
    for row in db.execute(
        "SELECT id, material_pk, curve_type, fmt, source_id, native_id, method, label,"
        " blob_offset, blob_length FROM material_curves"
    ):
        if row[1] not in pk_set:
            continue
        src_curves.seek(row[8])
        payload = src_curves.read(row[9])
        curve_rows.append((*row[:8], out_curves.tell(), len(payload)))
        out_curves.write(payload)
    out.executemany(
        "INSERT INTO material_curves (id, material_pk, curve_type, fmt, source_id,"
        " native_id, method, label, blob_offset, blob_length)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        curve_rows,
    )
    src_curves.close()
    out_curves.close()

    print("copying properties, refs and elements...", flush=True)
    counts = {"material_curves": len(curve_rows)}
    for table, cols in (
        ("material_elements", "material_pk, element"),
        ("material_properties",
         "material_pk, property_id, source_id, native_id, value_num, value_text, method"),
        ("material_source_refs", "material_pk, source_id, native_id, match_via"),
    ):
        n = 0
        insert = (
            f"INSERT INTO {table} ({cols})"
            f" VALUES ({','.join('?' * len(cols.split(',')))})"
        )
        chunk: list[tuple] = []
        for row in db.execute(f"SELECT {cols} FROM {table}"):
            if row[0] not in pk_set:
                continue
            chunk.append(tuple(row))
            n += 1
            if len(chunk) >= 20_000:
                out.executemany(insert, chunk)
                chunk.clear()
        if chunk:
            out.executemany(insert, chunk)
        counts[table] = n
        print(f"  {table}: {n:,}", flush=True)

    dataset_counts = dict(out.execute(
        "SELECT dataset, COUNT(*) FROM materials GROUP BY dataset"
    ))
    # Same seven facets, in the same order, that RepositoryLayout.stats()
    # computes on the slow path -- the API reads them straight out of metadata.
    facet_names = (
        "spacegroup", "pbes_gap", "density", "formation_energy",
        "energy_above_hull", "magnetism", "elasticity",
    )
    facet_values = out.execute(
        "SELECT COUNT(spacegroup_number), COUNT(pbes_gap), COUNT(density),"
        " COUNT(formation_energy_per_atom), COUNT(energy_above_hull),"
        " COUNT(CASE WHEN magnetic_ordering IS NOT NULL"
        "   OR total_magnetization IS NOT NULL THEN 1 END),"
        " COUNT(CASE WHEN bulk_modulus IS NOT NULL"
        "   OR shear_modulus IS NOT NULL THEN 1 END) FROM materials"
    ).fetchone()
    property_counts = dict(zip(facet_names, facet_values))
    out.executemany(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
        (
            ("experimental_count", str(dataset_counts.get("experimental", 0))),
            ("candidate_count", str(dataset_counts.get("candidate", 0))),
            ("property_counts", json.dumps(property_counts, sort_keys=True)),
            ("property_row_count", str(counts["material_properties"])),
            ("curve_count", str(counts["material_curves"])),
            ("slice_of", "MateriaViva full index"),
        ),
    )
    out.commit()
    out.execute("VACUUM")
    out.close()
    db.close()

    sizes = {
        p.name: p.stat().st_size
        for p in sorted(out_dir.iterdir())
        if p.is_file()
    }
    manifest = {
        "materials": len(pks),
        **counts,
        "datasets": dataset_counts,
        "bytes": sizes,
        "total_bytes": sum(sizes.values()),
    }
    (out_dir / "slice-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "slice")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    if shutil.disk_usage(args.out.parent).free < 2 << 30:
        raise SystemExit("less than 2 GiB free; refusing to build a slice")
    build(args.out, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
