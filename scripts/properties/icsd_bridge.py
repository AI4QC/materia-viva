#!/usr/bin/env python3
"""Bridge ICSD collection codes into the match map after the icsd fingerprint run.

Only 73,823 of the ICSD dump's 203,830 collection codes reached the pool
directly from the local ICSD half of the merge, so only those carry an
('icsd', 'icsd-<code>') entry in the match map's id_map. The other ~130,005
codes have no link even though a large share of them ARE in the pool: they
arrived as MP / COD / OQMD / Alexandria structures that were originally
ICSD-derived. Every ICSD-keyed property source (webmineral, amdb, obelix,
spse, 3dsc, snumat, mc3d, ...) silently drops its rows for those codes.

The icsd adapter now stages the local CIF for each unlinked code, so once the
driver has run::

    python scripts/properties/pipeline.py icsd --stage adapt
    python scripts/properties/pipeline.py icsd --stage hash --nproc 24
    python scripts/properties/pipeline.py icsd --stage match

``data/props_work/icsd/matched.tsv.gz`` holds both the pre-existing id matches
(via ``id:icsd``) and the newly recovered fingerprint matches (via ``hash``).
This script registers every ('icsd', '<native_id>') -> material_id pair from
that file into id_map, skipping pairs that are already there (so it is safe to
re-run, and the ~73,823 id rows cost nothing). Afterwards the dependent
sources must be re-adapted to collect the cascade.

LICENCE — no FIZ Karlsruhe structure is admitted or published by this script.
It only writes id -> material_id links, and every material_id it writes
already exists in the pool from a redistributable source: the icsd adapter is
``properties_only``, so stage_match drops unmatched fingerprints instead of
admitting them and matched.tsv.gz can only name structures the pool holds.

Usage::

    python scripts/properties/icsd_bridge.py --dry-run   # report, write nothing
    python scripts/properties/icsd_bridge.py             # register the pairs
"""

from __future__ import annotations

import argparse
import gzip
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATCHED = PROJECT_ROOT / "data" / "props_work" / "icsd" / "matched.tsv.gz"
MATCH_MAP = PROJECT_ROOT / "data" / "props_work" / "match_map.sqlite"

SOURCE = "icsd"
#: pool notation for an ICSD collection code, as produced by normalize_match_id
NATIVE = re.compile(r"^icsd-\d+$")
BATCH = 50_000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matched", type=Path, default=MATCHED)
    parser.add_argument("--match-map", type=Path, default=MATCH_MAP)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count the pairs that would be added, write nothing",
    )
    args = parser.parse_args()

    if not args.matched.exists():
        raise SystemExit(
            f"icsd matched.tsv.gz missing: {args.matched}\n"
            "run pipeline.py icsd --stage adapt/hash/match first"
        )
    if args.dry_run:
        db = sqlite3.connect(f"file:{args.match_map}?mode=ro", uri=True)
    else:
        db = sqlite3.connect(args.match_map)
    existing = {
        (row[0], row[1])
        for row in db.execute(
            "SELECT native_id, material_id FROM id_map WHERE source = ?", (SOURCE,)
        )
    }

    counters: Counter[str] = Counter()
    added = 0
    seen: set[tuple[str, str]] = set()
    batch: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal added
        if not batch:
            return
        if not args.dry_run:
            db.executemany(
                f"INSERT INTO id_map VALUES ('{SOURCE}', ?, ?)", batch
            )
        added += len(batch)
        batch.clear()

    with gzip.open(args.matched, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            native_id, material_id, via = line.rstrip("\n").split("\t")
            counters[f"rows_via_{via.replace(':', '_')}"] += 1
            if not NATIVE.match(native_id):
                counters["skipped_bad_id"] += 1
                continue
            key = (native_id, material_id)
            if key in existing:
                counters["already_present"] += 1
                continue
            if key in seen:
                counters["duplicate_row"] += 1
                continue
            seen.add(key)
            batch.append(key)
            if len(batch) >= BATCH:
                flush()
    flush()

    if not args.dry_run:
        db.commit()
    db.close()

    verb = "would register" if args.dry_run else "registered"
    print(
        f"icsd bridge: {verb} {added:,} new (icsd, code) -> material pairs "
        f"for {len({native for native, _ in seen}):,} distinct collection codes "
        f"({counters['already_present']:,} already present, "
        f"{len(existing):,} icsd rows in id_map before)"
    )
    for key in sorted(counters):
        print(f"  {key}: {counters[key]:,}")
    if not counters["rows_via_hash"]:
        print(
            "  WARNING: matched.tsv.gz has no via=hash rows — the icsd hash and "
            "match stages have not been run yet, so there is nothing to bridge.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
