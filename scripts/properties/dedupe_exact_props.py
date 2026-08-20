#!/usr/bin/env python3
"""Delete exact duplicate property rows left by a record ingested twice.

``material_source_refs`` has a PRIMARY KEY over (material_pk, source_id,
native_id), so a record that reached the loader twice contributes one ref.
``material_properties`` has no uniqueness constraint at all, so the same record
contributes its whole property set twice -- indistinguishable rows that inflate
counts and are served twice in the detail view.

"Exact" is deliberately strict: rows are collapsed only when
(material_pk, property_id, source_id, native_id, method, value_num, value_text)
all agree. Two rows that differ in *method* are a functional or catalogue pair
(Alexandria's PBE/PBEsol/SCAN, AFLOW's ICSD_WEB vs LIB) and must both survive;
two rows differing only in value are a genuine data conflict worth keeping
visible rather than silently resolving. NULLs are compared as equal, which
plain SQL GROUP BY already does.

Reports what it would delete under --dry-run (the default is to act, so the
supervisor can call it unattended).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.properties.load import connect  # noqa: E402


def dedupe(source: str | None, dry_run: bool) -> int:
    db = connect()
    db.execute("PRAGMA busy_timeout = 600000")
    if source:
        row = db.execute(
            "SELECT id FROM source_defs WHERE key = ?", (source,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"unknown source: {source}")
        where = "WHERE source_id = ?"
        params: tuple = (row[0],)
    else:
        where, params = "", ()

    started = time.time()
    # rowid is the tie-breaker: keep the first physical row of each group.
    victims = [
        r[0]
        for r in db.execute(
            f"""
            SELECT rowid FROM material_properties {where}
            EXCEPT
            SELECT MIN(rowid) FROM material_properties {where}
             GROUP BY material_pk, property_id, source_id, native_id,
                      method, value_num, value_text
            """,
            params + params,
        )
    ]
    print(
        f"[{source or 'all'}] {len(victims):,} exact duplicate rows"
        f" ({time.time() - started:.0f}s)",
        flush=True,
    )
    if victims and not dry_run:
        for start in range(0, len(victims), 50_000):
            chunk = victims[start : start + 50_000]
            db.executemany(
                "DELETE FROM material_properties WHERE rowid = ?",
                [(v,) for v in chunk],
            )
            db.commit()
        print(f"[{source or 'all'}] deleted {len(victims):,} rows", flush=True)
    db.close()
    return len(victims)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=None, help="limit to one source key")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dedupe(args.source, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
