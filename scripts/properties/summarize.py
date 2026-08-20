#!/usr/bin/env python3
"""Emit a markdown summary table of the integrated property sources.

Reads the live index and prints, per source: property rows, distinct
materials annotated, new structures contributed, and licence — ready to paste
into docs/property-integration.md. Re-run after any load to refresh the docs.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_DB = PROJECT_ROOT / "data" / "index" / "materials.sqlite"


def _publish_counts(property_rows: int, curves: int) -> None:
    """Cache the two big row counts in ``metadata`` for /api/stats to read.

    The API must never COUNT(*) material_properties on a page load, so it reads
    these keys instead; this is the only place they are refreshed. Opened as a
    separate writable connection because the summary itself runs read-only.

    Failure is swallowed on purpose: summarising is a reporting step that runs
    at the tail of every load chain, and it must not become something that can
    block or fail a load just because the index is momentarily write-locked.
    """

    try:
        writable = sqlite3.connect(INDEX_DB, timeout=30)
        writable.execute("PRAGMA busy_timeout = 30000")
        writable.executemany(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (("property_row_count", str(property_rows)), ("curve_count", str(curves))),
        )
        writable.commit()
        writable.close()
    except sqlite3.Error as exc:
        print(f"(could not cache counts in metadata: {exc})", file=sys.stderr)


def main() -> int:
    db = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
    rows = db.execute(
        """
        SELECT s.key, s.name, s.license,
               (SELECT COUNT(*) FROM material_properties mp
                 WHERE mp.source_id = s.id) AS prop_rows,
               (SELECT COUNT(DISTINCT r.material_pk) FROM material_source_refs r
                 WHERE r.source_id = s.id) AS materials,
               (SELECT COUNT(*) FROM material_source_refs r
                 WHERE r.source_id = s.id AND r.match_via = 'origin')
                 AS new_structures
        FROM source_defs s
        ORDER BY prop_rows DESC
        """
    ).fetchall()
    total_props = db.execute("SELECT COUNT(*) FROM material_properties").fetchone()[0]
    total_annotated = db.execute(
        "SELECT COUNT(DISTINCT material_pk) FROM material_properties"
    ).fetchone()[0]
    n_props = db.execute("SELECT COUNT(*) FROM property_defs").fetchone()[0]
    counts = dict(db.execute("SELECT dataset, COUNT(*) FROM materials GROUP BY dataset"))
    n_curves = db.execute("SELECT COUNT(*) FROM material_curves").fetchone()[0]
    db.close()
    _publish_counts(total_props, n_curves)

    print("| Source | Property rows | Materials touched | New structures | Licence |")
    print("|---|---:|---:|---:|---|")
    for key, name, license_, prop_rows, materials, new_structures in rows:
        print(
            f"| {name} (`{key}`) | {prop_rows:,} | {materials:,} "
            f"| {new_structures:,} | {license_ or '—'} |"
        )
    print()
    print(
        f"Totals: **{total_props:,}** property rows over **{n_props}** distinct "
        f"properties, **{total_annotated:,}** materials carrying at least one "
        f"cross-database property; pool now {counts.get('experimental', 0):,} "
        f"experimental + {counts.get('candidate', 0):,} candidate structures."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
