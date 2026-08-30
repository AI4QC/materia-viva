#!/usr/bin/env python3
"""Export per-property training targets from the MateriaViva index.

Design note: one sequential pass, no random reads
-------------------------------------------------
``material_properties`` holds ~121.6M rows.  The obvious implementation --
loop over properties and run ``WHERE property_id = ?`` with a join to
``materials`` -- turns into tens of millions of random rowid seeks into a
21 GB database and takes hours.  Instead this script does exactly two
sequential scans:

1. ``materials`` (13.5M rows) -> ``materials.parquet``, the shared structure
   index every per-property table joins against.  It carries the
   ``blob_offset``/``blob_length`` pair, so a trainer can pull the CIF for any
   row straight out of ``structures.blob`` without reopening SQLite.
2. ``material_properties`` -> ``targets/<property>.parquet``, fanned out to
   one open Parquet writer per property while the scan streams past.

Targets are written in LONG format: one row per (material, source, method).
Conflicting values from different databases are NOT collapsed here, because
the right collapse depends on the property -- see ``make_training_sets.py``,
which applies the resolution policy and writes the actual model-ready tables.
Keeping the raw multiplicity means a disagreement between two sources stays
visible instead of being silently averaged away.

Disk: the whole targets tree is ~2-3 GB; ``materials.parquet`` is ~0.9 GB.
Structures are NOT copied -- point the trainer at the existing 9.1 GB
``structures.blob``.

Usage
-----
    python scripts/ml/export_targets.py \
        --db data/index/materials.sqlite --out data/ml/export
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from method_groups import theory_level  # noqa: E402

MATERIALS_SCHEMA = pa.schema(
    [
        ("pk", pa.int64()),
        ("material_id", pa.string()),
        ("formula", pa.string()),
        ("chemical_system", pa.string()),
        ("dataset", pa.string()),
        ("is_experimental", pa.int8()),
        ("material_family", pa.string()),
        ("n_elements", pa.int16()),
        ("n_atoms", pa.int16()),
        ("spacegroup_number", pa.int16()),
        ("crystal_system", pa.string()),
        ("density", pa.float32()),
        ("volume", pa.float32()),
        # carried so prediction_sets.py can gate the `gapped` and `magnetic`
        # domains on evidence already in the index instead of deferring them
        ("pbes_gap", pa.float32()),
        ("total_magnetization", pa.float32()),
        ("is_metal", pa.int8()),
        ("blob_offset", pa.int64()),
        ("blob_length", pa.int32()),
    ]
)

TARGET_SCHEMA = pa.schema(
    [
        ("material_pk", pa.int64()),
        ("source", pa.string()),
        ("native_id", pa.string()),
        ("method", pa.string()),
        ("theory_level", pa.string()),
        ("value_num", pa.float64()),
        ("value_text", pa.string()),
    ]
)

FLUSH_ROWS = 200_000


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def export_materials(con: sqlite3.Connection, out: Path) -> int:
    path = out / "materials.parquet"
    writer = pq.ParquetWriter(path, MATERIALS_SCHEMA, compression="zstd")
    cursor = con.execute(
        """
        SELECT pk, material_id, formula, chemical_system, dataset, is_experimental,
               material_family, n_elements, n_atoms, spacegroup_number, crystal_system,
               density, volume, pbes_gap, total_magnetization, is_metal,
               blob_offset, blob_length
        FROM materials
        """
    )
    total = 0
    while True:
        rows = cursor.fetchmany(200_000)
        if not rows:
            break
        cols = list(zip(*rows))
        batch = pa.record_batch(
            [
                pa.array(cols[0], pa.int64()),
                pa.array(cols[1], pa.string()),
                pa.array(cols[2], pa.string()),
                pa.array(cols[3], pa.string()),
                pa.array(cols[4], pa.string()),
                pa.array(cols[5], pa.int8()),
                pa.array(cols[6], pa.string()),
                pa.array(cols[7], pa.int16()),
                pa.array([int(v) for v in cols[8]], pa.int16()),
                pa.array(cols[9], pa.int16()),
                pa.array(cols[10], pa.string()),
                pa.array(cols[11], pa.float32()),
                pa.array(cols[12], pa.float32()),
                pa.array(cols[13], pa.float32()),
                pa.array(cols[14], pa.float32()),
                pa.array(cols[15], pa.int8()),
                pa.array(cols[16], pa.int64()),
                pa.array(cols[17], pa.int32()),
            ],
            schema=MATERIALS_SCHEMA,
        )
        writer.write_batch(batch)
        total += len(rows)
        print(f"  materials {total:,}", end="\r", file=sys.stderr, flush=True)
    writer.close()
    print(f"  materials {total:,} -> {path}", file=sys.stderr)
    return total


class PropertyWriter:
    """One Parquet writer per property, flushed as the single scan streams by."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._writer: pq.ParquetWriter | None = None
        self.buf: list[tuple] = []
        self.n_rows = 0

    def add(self, row: tuple) -> None:
        self.buf.append(row)
        if len(self.buf) >= FLUSH_ROWS:
            self.flush()

    def flush(self) -> None:
        if not self.buf:
            return
        cols = list(zip(*self.buf))
        batch = pa.record_batch(
            [
                pa.array(cols[0], pa.int64()),
                pa.array(cols[1], pa.string()),
                pa.array(cols[2], pa.string()),
                pa.array(cols[3], pa.string()),
                pa.array(cols[4], pa.string()),
                pa.array(cols[5], pa.float64()),
                pa.array(cols[6], pa.string()),
            ],
            schema=TARGET_SCHEMA,
        )
        if self._writer is None:
            self._writer = pq.ParquetWriter(
                self.path, TARGET_SCHEMA, compression="zstd"
            )
        self._writer.write_batch(batch)
        self.n_rows += len(self.buf)
        self.buf.clear()

    def close(self) -> None:
        self.flush()
        if self._writer is not None:
            self._writer.close()


def export_targets(con: sqlite3.Connection, out: Path) -> dict:
    props = {
        int(i): (n, u or "", k)
        for i, n, u, k in con.execute("SELECT id,name,unit,kind FROM property_defs")
    }
    sources = {int(i): k for i, k in con.execute("SELECT id,key FROM source_defs")}

    tdir = out / "targets"
    tdir.mkdir(parents=True, exist_ok=True)
    writers: dict[int, PropertyWriter] = {}

    cursor = con.execute(
        """
        SELECT material_pk, property_id, source_id, native_id, value_num,
               value_text, method
        FROM material_properties
        """
    )
    level_cache: dict[str | None, str] = {}
    total = 0
    t0 = time.time()
    while True:
        rows = cursor.fetchmany(100_000)
        if not rows:
            break
        for pk, pid, sid, native, vnum, vtext, method in rows:
            writer = writers.get(pid)
            if writer is None:
                name = props.get(pid, (f"property_{pid}", "", "num"))[0]
                writer = writers[pid] = PropertyWriter(tdir / f"{safe_name(name)}.parquet")
            level = level_cache.get(method)
            if level is None:
                level = level_cache[method] = theory_level(method)
            writer.add((pk, sources.get(sid, "?"), native, method, level, vnum, vtext))
        total += len(rows)
        if total % 5_000_000 < 100_000:
            rate = total / max(time.time() - t0, 1e-9)
            print(
                f"  properties {total:,} ({rate / 1e6:.2f}M rows/s)",
                file=sys.stderr,
                flush=True,
            )

    summary = {}
    for pid, writer in writers.items():
        writer.close()
        name, unit, kind = props.get(pid, (f"property_{pid}", "", "num"))
        summary[name] = {
            "property_id": pid,
            "unit": unit,
            "kind": kind,
            "n_rows": writer.n_rows,
            "file": writer.path.name,
        }
    print(f"  properties {total:,} rows in {time.time() - t0:.0f}s", file=sys.stderr)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=Path("data/index/materials.sqlite"))
    ap.add_argument("--out", type=Path, default=Path("data/ml/export"))
    ap.add_argument("--skip-materials", action="store_true")
    ap.add_argument("--skip-targets", action="store_true")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.execute("PRAGMA cache_size=-1000000")  # 1 GB

    manifest = {"db": str(args.db), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if not args.skip_materials:
        print("exporting materials index...", file=sys.stderr)
        manifest["n_materials"] = export_materials(con, args.out)
    if not args.skip_targets:
        print("exporting property targets...", file=sys.stderr)
        manifest["targets"] = export_targets(con, args.out)

    (args.out / "EXPORT_MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    print(f"wrote {args.out}/EXPORT_MANIFEST.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
