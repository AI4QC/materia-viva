#!/usr/bin/env python3
"""Backfill `materials.formula_sort` on an index built before it existed.

Sorting by formula compared the stored text, so `Al12P12O48` came before
`Al1As1`: comparison reaches `'2'` against `'A'`, and a digit sorts below a
letter. The fix is a column holding the formula with each count zero-padded, so
text order and chemical order agree.

The key is a pure function of the formula, so this needs nothing but the index
itself — no source data, no rebuild. It reads every row, writes the key back and
creates the index over it.

    PYTHONPATH=backend python scripts/migrate_formula_sort.py data/index/materials.sqlite

Idempotent: running it twice is a no-op the second time. Without `--apply` it
reports what it would do and changes nothing.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from materials_api.formula import sort_key  # noqa: E402

BATCH = 20_000


def has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in connection.execute(f"PRAGMA table_info({table})"))


def migrate(database: Path, *, apply: bool) -> int:
    connection = sqlite3.connect(database)
    try:
        total = connection.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        fresh = not has_column(connection, "materials", "formula_sort")
        if fresh:
            print(f"  adding materials.formula_sort ({total:,} rows to backfill)")
        else:
            pending = connection.execute(
                "SELECT COUNT(*) FROM materials WHERE formula_sort IS NULL"
            ).fetchone()[0]
            if not pending:
                print(f"  already migrated: {total:,} rows carry a sort key")
                return 0
            print(f"  resuming: {pending:,} of {total:,} rows still need a key")

        if not apply:
            print("  --apply not given; nothing written")
            return 0

        if fresh:
            connection.execute("ALTER TABLE materials ADD COLUMN formula_sort TEXT")

        done = 0
        while True:
            rows = connection.execute(
                "SELECT pk, formula FROM materials WHERE formula_sort IS NULL LIMIT ?", (BATCH,)
            ).fetchall()
            if not rows:
                break
            connection.executemany(
                "UPDATE materials SET formula_sort = ? WHERE pk = ?",
                [(sort_key(formula), pk) for pk, formula in rows],
            )
            connection.commit()
            done += len(rows)
            print(f"  {done:,} rows", end="\r", flush=True)

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_materials_formula_sort ON materials(formula_sort, pk)"
        )
        connection.commit()
        print(f"  {done:,} rows written, index created")
        return 0
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="write the column; without it, only report")
    args = parser.parse_args(argv)
    if not args.database.is_file():
        raise SystemExit(f"no index at {args.database}")
    return migrate(args.database, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
