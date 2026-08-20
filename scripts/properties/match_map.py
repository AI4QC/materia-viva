#!/usr/bin/env python3
"""Build data/props_work/match_map.sqlite: fingerprint and id lookups for the pool.

The map answers two questions for every incoming source record:

* hash_map:  primitive-reduced BAWL fingerprint -> pool material_id(s)
* id_map:    (source, native_id)               -> pool material_id(s)

Inputs are the merge metadata files that already accompany the published pool:

* data/sources/experimental/synth_meta.tsv       (index, source, source_id, bawl_hash)
* data/sources/candidate/local_meta_train.tsv    (index, formula, bawl_hash)
* data/sources/candidate/local_meta_val.tsv      (index, formula, bawl_hash)
* data/sources/candidate/lemat_meta.tsv          (index, immutable_id, entalpic_fingerprint, ...)
* data/sources/candidate/elementa_meta.tsv       (index, archive, material, structure, spin, bawl_hash)

plus the live materials.sqlite for (dataset, source_index) -> material_id.
Experimental and candidate pools may legitimately hold the same fingerprint;
both rows are kept and matching attaches properties to every one.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA = PROJECT_ROOT / "data"
DEFAULT_OUT = DATA / "props_work" / "match_map.sqlite"

LOCAL_HASH_LEGACY = Path(
    "/home/zhilong/SSD/workspace_data/matgenbench/data/lemat_merge_work"
)


def _ensure_local_meta() -> list[tuple[Path, str]]:
    """Copy the legacy local-candidate hash TSVs next to the other metadata."""

    out: list[tuple[Path, str]] = []
    for split in ("train", "val"):
        dest = DATA / "sources" / "candidate" / f"local_meta_{split}.tsv"
        if not dest.exists():
            source = LOCAL_HASH_LEGACY / f"local_hashes_{split}.tsv"
            if not source.exists():
                raise SystemExit(f"missing local hash file: {source}")
            dest.write_bytes(source.read_bytes())
        out.append((dest, split))
    return out


def build(out_path: Path, index_db: Path) -> None:
    started = time.time()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    db = sqlite3.connect(out_path)
    db.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE pool (dataset TEXT, source_index TEXT, material_id TEXT);
        CREATE TABLE hash_map (hash TEXT NOT NULL, material_id TEXT NOT NULL);
        CREATE TABLE id_map (source TEXT NOT NULL, native_id TEXT NOT NULL,
                             material_id TEXT NOT NULL);
        """
    )

    with sqlite3.connect(f"file:{index_db}?mode=ro", uri=True) as live:
        rows = live.execute(
            "SELECT dataset, source_index, material_id FROM materials"
        )
        while chunk := rows.fetchmany(100_000):
            db.executemany("INSERT INTO pool VALUES (?, ?, ?)", chunk)
    db.execute("CREATE INDEX ix_pool ON pool(dataset, source_index)")
    print(f"pool rows loaded in {time.time() - started:.0f}s", flush=True)

    def _bulk(sql: str, rows_iter) -> int:
        batch, total = [], 0
        for row in rows_iter:
            batch.append(row)
            if len(batch) >= 100_000:
                db.executemany(sql, batch)
                total += len(batch)
                batch.clear()
        if batch:
            db.executemany(sql, batch)
            total += len(batch)
        return total

    def _tsv(path: Path):
        with path.open(encoding="utf-8") as handle:
            header = next(handle).rstrip("\n").split("\t")
            for line in handle:
                yield dict(zip(header, line.rstrip("\n").split("\t")))

    exp = DATA / "sources" / "experimental" / "synth_meta.tsv"
    n = _bulk(
        "INSERT INTO hash_map SELECT ?, material_id FROM pool "
        "WHERE dataset = 'experimental' AND source_index = ?",
        (
            (row["bawl_hash"], row["index"])
            for row in _tsv(exp)
            if row["bawl_hash"] and not row["bawl_hash"].startswith("FAIL")
        ),
    )
    print(f"experimental hashes: {n:,}", flush=True)
    n = _bulk(
        "INSERT INTO id_map SELECT ?, ?, material_id FROM pool "
        "WHERE dataset = 'experimental' AND source_index = ?",
        ((row["source"], row["source_id"], row["index"]) for row in _tsv(exp)),
    )
    print(f"experimental ids: {n:,}", flush=True)

    for path, split in _ensure_local_meta():
        with path.open(encoding="utf-8") as handle:
            n = _bulk(
                "INSERT INTO hash_map SELECT ?, material_id FROM pool "
                "WHERE dataset = 'candidate' AND source_index = ?",
                (
                    (parts[2], parts[0])
                    for parts in (line.rstrip("\n").split("\t") for line in handle)
                    if len(parts) >= 3 and parts[2] and not parts[2].startswith("FAIL")
                ),
            )
        print(f"local candidate hashes ({split}): {n:,}", flush=True)

    lemat = DATA / "sources" / "candidate" / "lemat_meta.tsv"
    n = _bulk(
        "INSERT INTO hash_map SELECT ?, material_id FROM pool "
        "WHERE dataset = 'candidate' AND source_index = ?",
        (
            (row["entalpic_fingerprint"], row["index"])
            for row in _tsv(lemat)
            if row["entalpic_fingerprint"]
            and not row["entalpic_fingerprint"].startswith("FAIL")
        ),
    )
    print(f"lemat hashes: {n:,}", flush=True)

    def _lemat_source(immutable_id: str) -> str | None:
        if immutable_id.startswith("mp-") or immutable_id.startswith("mvc-"):
            return "materials-project"
        if immutable_id.startswith("oqmd-"):
            return "oqmd"
        if immutable_id.startswith("agm"):
            return "alexandria"
        return None

    n = _bulk(
        "INSERT INTO id_map SELECT ?, ?, material_id FROM pool "
        "WHERE dataset = 'candidate' AND source_index = ?",
        (
            (_lemat_source(row["immutable_id"]), row["immutable_id"], row["index"])
            for row in _tsv(lemat)
            if _lemat_source(row["immutable_id"]) is not None
        ),
    )
    print(f"lemat ids: {n:,}", flush=True)

    elementa = DATA / "sources" / "candidate" / "elementa_meta.tsv"
    n = _bulk(
        "INSERT INTO hash_map SELECT ?, material_id FROM pool "
        "WHERE dataset = 'candidate' AND source_index = ?",
        (
            (row["bawl_hash"], row["index"])
            for row in _tsv(elementa)
            if row["bawl_hash"] and not row["bawl_hash"].startswith("FAIL")
        ),
    )
    print(f"elementa hashes: {n:,}", flush=True)
    n = _bulk(
        "INSERT INTO id_map SELECT 'elementa', ?, material_id FROM pool "
        "WHERE dataset = 'candidate' AND source_index = ?",
        (
            (
                ":".join((row["archive"], row["material"], row["structure"], row["spin"])),
                row["index"],
            )
            for row in _tsv(elementa)
        ),
    )
    print(f"elementa ids: {n:,}", flush=True)

    db.execute("CREATE INDEX ix_hash ON hash_map(hash)")
    db.execute("CREATE INDEX ix_id ON id_map(source, native_id)")
    db.execute("DROP TABLE pool")
    db.commit()
    db.execute("VACUUM")
    counts = {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("hash_map", "id_map")
    }
    db.close()
    print(
        f"match map built in {(time.time() - started) / 60:.1f} min: "
        f"{counts['hash_map']:,} hashes, {counts['id_map']:,} ids -> {out_path}",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--index-db", type=Path, default=DATA / "index" / "materials.sqlite"
    )
    args = parser.parse_args()
    build(args.out, args.index_db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
