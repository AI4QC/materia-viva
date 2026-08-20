#!/usr/bin/env python3
"""Load non-scalar properties (spectra / curves) into the curve store.

Payload conventions (zlib-compressed into data/index/curves.blob, offsets in
the ``material_curves`` table):

* fmt ``xy``    — JSON {"x": [...], "y": [...], "x_label", "y_label",
                  "x_unit", "y_unit", "series"?: [{"name", "y": [...]}]}
* fmt ``peaks`` — JSON {"x": [...], "y": [...], "hkl"?: [...], "d"?: [...],
                  "x_label", "y_label", "x_unit"} (stick pattern)
* fmt ``svg``   — raw SVG text (pre-rendered plot, served verbatim)

Per-source extractors live in scripts/properties/curve_sources/<source>.py and
expose ``iter_curves(resolver, limit)`` yielding CurveRecord objects; this CLI
resolves materials, appends payloads to the blob and inserts rows. A source's
curves are replaced wholesale on re-run (delete + insert), which keeps curve
loading idempotent.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.properties.load import (  # noqa: E402
    INDEX_DB,
    _source_def,
    connect,
    migrate,
)

CURVES_BLOB = INDEX_DB.parent / "curves.blob"

VALID_TYPES = {
    "xrd", "band_structure", "dos", "phonon_dos", "raman", "ir",
    "kappa_spectral", "kappa_cumulative",
    # X-ray absorption (XANES / EXAFS / stitched XAFS) and optical absorption
    # coefficient vs photon energy, both introduced by the Materials Project
    # spectra source.
    "xas", "absorption",
}
VALID_FMTS = {"xy", "peaks", "svg"}


@dataclass
class CurveRecord:
    """One spectrum attached to one already-matched material."""

    material_id: str        #: pool material id (exp-…/pool-…)
    curve_type: str
    fmt: str
    payload: str | bytes    #: JSON text (xy/peaks) or SVG text
    native_id: str | None = None
    method: str | None = None
    label: str | None = None


class MaterialResolver:
    """material_id -> pk plus (source, native_id) -> material_ids helpers."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        match_map = PROJECT_ROOT / "data" / "props_work" / "match_map.sqlite"
        self.match_db = sqlite3.connect(f"file:{match_map}?mode=ro", uri=True)

    def pk(self, material_id: str) -> int | None:
        row = self.db.execute(
            "SELECT pk FROM materials WHERE material_id = ?", (material_id,)
        ).fetchone()
        return row[0] if row else None

    def by_native_id(self, source: str, native_id: str) -> list[str]:
        return [
            row[0]
            for row in self.match_db.execute(
                "SELECT material_id FROM id_map WHERE source = ? AND native_id = ?",
                (source, native_id),
            )
        ]

    def matched_pairs(self, source: str):
        """Yield (native_id, material_id) from the source's matched.tsv.gz."""

        import gzip

        matched = (
            PROJECT_ROOT / "data" / "props_work" / source / "matched.tsv.gz"
        )
        with gzip.open(matched, "rt", encoding="utf-8") as handle:
            next(handle)
            for line in handle:
                native_id, material_id, _via = line.rstrip("\n").split("\t")
                yield native_id, material_id


def load_source(source: str, limit: int | None) -> None:
    module = importlib.import_module(
        f"scripts.properties.curve_sources.{source.replace('-', '_')}"
    )
    db = connect()
    migrate(db)
    source_def_id = _source_def(db, source)
    db.commit()
    resolver = MaterialResolver(db)

    existing = db.execute(
        "SELECT COUNT(*) FROM material_curves WHERE source_id = ?",
        (source_def_id,),
    ).fetchone()[0]
    if existing:
        print(f"[{source}] replacing {existing:,} existing curves", flush=True)
        db.execute(
            "DELETE FROM material_curves WHERE source_id = ?", (source_def_id,)
        )
        db.commit()

    started = time.time()
    inserted = skipped = 0
    batch: list[tuple] = []
    with CURVES_BLOB.open("ab") as blob:
        for record in module.iter_curves(resolver, limit=limit):
            if record.curve_type not in VALID_TYPES:
                raise SystemExit(f"invalid curve_type: {record.curve_type}")
            if record.fmt not in VALID_FMTS:
                raise SystemExit(f"invalid fmt: {record.fmt}")
            material_pk = resolver.pk(record.material_id)
            if material_pk is None:
                skipped += 1
                continue
            payload = record.payload
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            if record.fmt in {"xy", "peaks"}:
                json.loads(payload)  # fail fast on malformed JSON
            compressed = zlib.compress(payload, 6)
            offset = blob.tell()
            blob.write(compressed)
            batch.append((
                material_pk, record.curve_type, record.fmt, source_def_id,
                record.native_id, record.method, record.label,
                offset, len(compressed),
            ))
            inserted += 1
            if len(batch) >= 500:
                blob.flush()
                db.executemany(
                    "INSERT INTO material_curves (material_pk, curve_type, fmt,"
                    " source_id, native_id, method, label, blob_offset,"
                    " blob_length) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                db.commit()
                batch.clear()
                if inserted % 5_000 < 500:
                    print(
                        f"[{source}] {inserted:,} curves "
                        f"({time.time() - started:.0f}s)",
                        flush=True,
                    )
        blob.flush()
    if batch:
        db.executemany(
            "INSERT INTO material_curves (material_pk, curve_type, fmt,"
            " source_id, native_id, method, label, blob_offset, blob_length)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )
    db.commit()
    db.close()
    print(
        f"[{source}] DONE: {inserted:,} curves inserted, {skipped:,} skipped "
        f"in {(time.time() - started) / 60:.1f} min",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    load_source(args.source, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
