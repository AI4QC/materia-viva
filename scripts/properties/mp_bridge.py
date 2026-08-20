#!/usr/bin/env python3
"""Bridge legacy numeric Materials Project ids into the match map.

The current MP snapshot uses alphabetic ids, but many property databases
(phonix, novomag, 3DSC, materiae, jarvis) still reference legacy numeric
mp-#### ids. matbench-discovery ships the 2023 MP snapshot keyed by those
legacy ids; after its pipeline fingerprint-matches that snapshot against the
pool, this script registers every (mp-<legacy> -> material_id) pair under the
'materials-project' source in the match map, so later adapt stages resolve
legacy mp ids directly.
"""

from __future__ import annotations

import gzip
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATCHED = PROJECT_ROOT / "data" / "props_work" / "matbench-discovery" / "matched.tsv.gz"
MATCH_MAP = PROJECT_ROOT / "data" / "props_work" / "match_map.sqlite"

LEGACY = re.compile(r"^(mp|mvc)-\d+$")


def main() -> int:
    if not MATCHED.exists():
        raise SystemExit(f"matbench-discovery matched.tsv.gz missing: {MATCHED}")
    db = sqlite3.connect(MATCH_MAP)
    existing = {
        row[0]
        for row in db.execute(
            "SELECT native_id FROM id_map WHERE source = 'materials-project'"
        )
    }
    added = 0
    seen: set[tuple[str, str]] = set()
    batch: list[tuple[str, str]] = []
    with gzip.open(MATCHED, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, material_id, _via = line.rstrip("\n").split("\t")
            if not LEGACY.match(native_id):
                continue
            key = (native_id, material_id)
            if native_id in existing or key in seen:
                continue
            seen.add(key)
            batch.append(key)
            if len(batch) >= 50_000:
                db.executemany(
                    "INSERT INTO id_map VALUES ('materials-project', ?, ?)", batch
                )
                added += len(batch)
                batch.clear()
    if batch:
        db.executemany(
            "INSERT INTO id_map VALUES ('materials-project', ?, ?)", batch
        )
        added += len(batch)
    db.commit()
    db.close()
    print(f"mp bridge: {added:,} legacy mp ids registered "
          f"({len(existing):,} already present)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
