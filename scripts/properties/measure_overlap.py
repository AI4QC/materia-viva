#!/usr/bin/env python3
"""Measure how much of a pulled candidate the pool already holds.

The admission gate needs a number, not a reading of the upstream documentation:
`open-materials-db` was declined because someone judged that COD already covered
it, and that judgement is exactly the kind an agent can fake. Overlap cannot be
faked.

Input is the fingerprint file `scripts/properties/hashing.py` already produces
(`native_id`, `n_sites`, `formula`, `bawl_hash`, failures written as
`FAIL:<reason>`), so nothing here re-implements the fingerprint protocol. The
pool side comes from `hash_map` in `data/props_work/match_map.sqlite`, opened
read-only.

Note what this deliberately does not need: a property adapter. Deciding whether
to admit a dataset takes its structures only, so the expensive mapping work
never happens for a candidate that gets rejected.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATCH_MAP = PROJECT_ROOT / "data" / "props_work" / "match_map.sqlite"


def read_fingerprints(path: Path) -> tuple[set[str], int, Counter]:
    """Return the distinct fingerprints, how many rows carried one, and why the
    rest failed.

    Only the distinct set and the row count are ever used, so the fingerprints
    are not kept in a list: a trajectory dump repeats the same structure
    thousands of times, and holding every row would scale memory with the dump
    rather than with the structures in it.
    """
    opener = gzip.open if path.suffix == ".gz" else open
    fingerprints: set[str] = set()
    rows_with_a_fingerprint = 0
    failures: Counter = Counter()
    with opener(path, "rt", encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        try:
            column = header.index("bawl_hash")
        except ValueError:
            raise SystemExit(f"{path} has no bawl_hash column: {header}")
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) <= column:
                failures["MALFORMED_ROW"] += 1
                continue
            value = fields[column]
            if value.startswith("FAIL:"):
                # keep the reason, drop the payload that follows a second colon
                failures[value[5:].split(":", 1)[0]] += 1
            elif value:
                fingerprints.add(value)
                rows_with_a_fingerprint += 1
            else:
                failures["EMPTY"] += 1
    return fingerprints, rows_with_a_fingerprint, failures


def measure(unique: set[str], rows_with_a_fingerprint: int, match_map: Path) -> dict[str, Any]:
    """Split the candidate's distinct fingerprints into already-held and new."""
    db = sqlite3.connect(":memory:", uri=True)
    db.execute(f"ATTACH DATABASE 'file:{match_map}?mode=ro' AS pool")
    db.execute("CREATE TABLE candidate (hash TEXT PRIMARY KEY)")
    db.executemany("INSERT OR IGNORE INTO candidate VALUES (?)", ((h,) for h in unique))

    held = db.execute(
        "SELECT count(*) FROM candidate c "
        "WHERE EXISTS (SELECT 1 FROM pool.hash_map h WHERE h.hash = c.hash)"
    ).fetchone()[0]

    # id_map carries no index on material_id, so this is one scan of it joined
    # against the overlapping material ids; a single pass is the price of the
    # per-source breakdown
    db.execute(
        "CREATE TABLE overlapping_material (material_id TEXT PRIMARY KEY)"
    )
    db.execute(
        "INSERT OR IGNORE INTO overlapping_material "
        "SELECT h.material_id FROM pool.hash_map h "
        "JOIN candidate c ON c.hash = h.hash"
    )
    by_source = db.execute(
        "SELECT i.source, count(DISTINCT i.material_id) FROM pool.id_map i "
        "JOIN overlapping_material o ON o.material_id = i.material_id "
        "GROUP BY i.source ORDER BY 2 DESC"
    ).fetchall()
    db.close()

    return {
        "rows_with_a_fingerprint": rows_with_a_fingerprint,
        "unique_fingerprints": len(unique),
        "already_in_the_pool": held,
        "new_to_the_pool": len(unique) - held,
        "new_fraction_of_unique": round((len(unique) - held) / len(unique), 4) if unique else None,
        "overlap_by_existing_source": [{"source": s, "materials": n} for s, n in by_source],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hashes", type=Path, required=True,
                        help="hashes.tsv(.gz) from scripts/properties/hashing.py")
    parser.add_argument("--match-map", type=Path, default=DEFAULT_MATCH_MAP)
    parser.add_argument("--source", default=None, help="source id, for the report only")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.match_map.exists():
        parser.error(
            f"no pool fingerprint map at {args.match_map}; build it with "
            "scripts/properties/match_map.py on the machine holding the index"
        )

    fingerprints, rows_with_a_fingerprint, failures = read_fingerprints(args.hashes)
    report: dict[str, Any] = {
        "source": args.source,
        "hashes_file": str(args.hashes),
        "rows_read": rows_with_a_fingerprint + sum(failures.values()),
        "parse_failures": sum(failures.values()),
        "parse_failures_by_reason": dict(failures.most_common()),
    }
    if fingerprints:
        report.update(measure(fingerprints, rows_with_a_fingerprint, args.match_map))
    total = report["rows_read"]
    report["parse_failure_fraction"] = round(report["parse_failures"] / total, 4) if total else None

    label = args.source or args.hashes.name
    print(f"\n{label}")
    print(f"  读入 {total} 行，解析失败 {report['parse_failures']} "
          f"({report['parse_failure_fraction']})")
    if report["parse_failures_by_reason"]:
        for reason, count in list(report["parse_failures_by_reason"].items())[:5]:
            print(f"    FAIL:{reason} × {count}")
    if fingerprints:
        print(f"  唯一指纹 {report['unique_fingerprints']}，"
              f"池中已有 {report['already_in_the_pool']}，"
              f"新增 {report['new_to_the_pool']} ({report['new_fraction_of_unique']})")
        for row in report["overlap_by_existing_source"][:8]:
            print(f"    与 {row['source']} 重叠 {row['materials']} 个材料")
    out = args.out or (args.hashes.parent / f"overlap-{label}.json")
    out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
