#!/usr/bin/env python3
"""Bridge selected loaded-source refs into the match map's id_map.

Lets later sources id-match records that reference entries of an
already-loaded source:

* ('csd', REFCODE)      from fair-mofs native ids (bare refcodes) and
                        mofx-db CoREMOF ids ('CoREMOF 2019:REFCODE_clean')
* ('superband', id)     every superband group already matched into the pool
* ('aflow', auid)       every AFLOW record matched into the pool

Idempotent: existing (source, native_id, material_id) triples are skipped.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_DB = PROJECT_ROOT / "data" / "index" / "materials.sqlite"
MATCH_MAP = PROJECT_ROOT / "data" / "props_work" / "match_map.sqlite"

REFCODE = re.compile(r"^[A-Z]{6}(\d{2})?$")


def main() -> int:
    live = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
    match_db = sqlite3.connect(MATCH_MAP)
    existing = {
        (source, native_id, material_id)
        for source, native_id, material_id in match_db.execute(
            "SELECT source, native_id, material_id FROM id_map "
            "WHERE source IN ('csd', 'superband', 'aflow')"
        )
    }
    batch: list[tuple[str, str, str]] = []

    def add(source: str, native_id: str, material_id: str) -> None:
        key = (source, native_id, material_id)
        if key not in existing:
            existing.add(key)
            batch.append(key)

    rows = live.execute(
        "SELECT s.key, r.native_id, m.material_id "
        "FROM material_source_refs r "
        "JOIN source_defs s ON s.id = r.source_id "
        "JOIN materials m ON m.pk = r.material_pk "
        "WHERE s.key IN ('fair-mofs', 'mofx-db', 'superband', 'aflow')"
    )
    counts = {"csd": 0, "superband": 0, "aflow": 0}
    for source_key, native_id, material_id in rows:
        if source_key == "fair-mofs":
            code = native_id.strip().upper()
            if REFCODE.match(code):
                add("csd", code, material_id)
                counts["csd"] += 1
        elif source_key == "mofx-db":
            if native_id.startswith("CoREMOF"):
                name = native_id.split(":", 1)[-1]
                code = re.sub(r"(_clean|_fair|_charged|_ion_b|_manual|_auto)+$",
                              "", name).upper()
                # CoREMOF names may carry numeric suffixes beyond the refcode
                code = code.split("_")[0]
                if REFCODE.match(code):
                    add("csd", code, material_id)
                    counts["csd"] += 1
        elif source_key == "superband":
            add("superband", native_id, material_id)
            counts["superband"] += 1
        elif source_key == "aflow":
            add("aflow", native_id, material_id)
            counts["aflow"] += 1

    for start in range(0, len(batch), 100_000):
        match_db.executemany(
            "INSERT INTO id_map VALUES (?, ?, ?)", batch[start:start + 100_000]
        )
    match_db.commit()
    total = match_db.execute(
        "SELECT COUNT(*) FROM id_map WHERE source IN ('csd','superband','aflow')"
    ).fetchone()[0]
    match_db.close()
    live.close()
    print(f"bridged {len(batch):,} new entries "
          f"(seen: csd {counts['csd']:,}, superband {counts['superband']:,}, "
          f"aflow {counts['aflow']:,}); id_map bridge rows now {total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
