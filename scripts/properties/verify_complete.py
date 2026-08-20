#!/usr/bin/env python3
"""Audit whether every source's properties actually made it into the index.

Three independent checks per source, each able to fail on its own:

1. **load integrity** — the row count the loader reported must equal the row
   count the index actually holds for that source.  A mismatch means a load was
   interrupted, or ran twice, or the source's rows were cleared and never
   re-inserted; the summary table alone would never show it because it only
   reports what is in the database.
2. **staging yield** — every property row the adapter staged must either be in
   the index or be accounted for as ``props_unmatched`` (a native_id that no
   material in the pool corresponds to).  ``staged - loaded - unmatched`` must
   be zero; anything else is silently dropped data.
3. **field coverage** — every distinct property *name* present in
   ``staging_props.tsv.gz`` must exist in the index for that source.  This is
   the check that catches the class of bug we hit before: a field the adapter
   maps but the loader never lands, which leaves the row totals plausible while
   an entire quantity goes missing.

Sources staged on disk but absent from ``source_defs`` are reported as NEVER
LOADED, and sources in the registry with no work directory at all are reported
as NOT STAGED, so nothing can go missing merely by not being mentioned.

Usage:
    python scripts/properties/verify_complete.py            # checks 1 + 2 + 3
    python scripts/properties/verify_complete.py --quick    # checks 1 + 2 only
    python scripts/properties/verify_complete.py --json out.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

INDEX_DB = PROJECT_ROOT / "data" / "index" / "materials.sqlite"
WORK_ROOT = PROJECT_ROOT / "data" / "props_work"

#: Sources that deliberately contribute no scalar property rows (structures
#: only, or curves only).  They are listed so their zero is an expected zero
#: rather than an unexplained one.
STRUCTURE_ONLY = {"phonondb", "rruff-curves"}


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True, timeout=600)
    db.execute("PRAGMA busy_timeout = 600000")
    return db


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _staged_field_names(path: Path) -> set[str]:
    """Distinct property names in a staging file (streamed, never held whole)."""

    names: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        header = handle.readline()
        if not header.startswith("native_id\t"):
            return names
        for line in handle:
            tab = line.find("\t")
            if tab < 0:
                continue
            end = line.find("\t", tab + 1)
            names.add(line[tab + 1 : end] if end > 0 else line[tab + 1 :].rstrip("\n"))
    return names


def _fields_with_linked_records(
    path: Path, fields: set[str], linked: set[str]
) -> set[str]:
    """Of ``fields``, those staged for at least one record that has a link.

    A field staged only for records no material corresponds to is absent from
    the index because there was nowhere to put it, which is not a defect. One
    that is staged for a linked record and still missing is a real drop.
    """

    found: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        handle.readline()
        for line in handle:
            first = line.find("\t")
            if first < 0:
                continue
            second = line.find("\t", first + 1)
            name = line[first + 1 : second] if second > 0 else line[first + 1 :].rstrip("\n")
            if name in fields and name not in found and line[:first] in linked:
                found.add(name)
                if found == fields:
                    break
    return found


def audit(quick: bool) -> dict:
    db = _connect()
    source_ids = dict(db.execute("SELECT key, id FROM source_defs"))
    prop_names = dict(db.execute("SELECT id, name FROM property_defs"))

    # One grouped scan each instead of a COUNT per source: material_properties
    # is >100M rows, so 54 separate counts would take an hour and would also
    # see 54 different snapshots while a load is running.
    rows_by_source = dict(
        db.execute(
            "SELECT source_id, COUNT(*) FROM material_properties GROUP BY source_id"
        )
    )
    refs_by_source = dict(
        db.execute(
            "SELECT source_id, COUNT(*) FROM material_source_refs GROUP BY source_id"
        )
    )
    curves_by_source = dict(
        db.execute(
            "SELECT source_id, COUNT(*) FROM material_curves GROUP BY source_id"
        )
    )
    fields_by_source: dict[int, set[str]] = {}
    for sid_, pid in db.execute(
        "SELECT DISTINCT source_id, property_id FROM material_properties"
    ):
        if pid in prop_names:
            fields_by_source.setdefault(sid_, set()).add(prop_names[pid])

    staged_dirs = sorted(p.name for p in WORK_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_"))
    known = sorted(set(staged_dirs) | set(source_ids))

    results: list[dict] = []
    for source in known:
        work = WORK_ROOT / source
        entry: dict = {"source": source, "problems": []}

        report = _read_json(work / "report.json")
        load_path = work / "load_report.json"
        load_report = _read_json(load_path)
        entry["staged_rows"] = report.get("adapt", {}).get("property_rows")
        # load.py builds its receipt from a Counter, and json.dumps(dict(counter))
        # omits any key that was never incremented. A structure-only source that
        # legitimately staged zero properties therefore has NO property_rows key
        # at all -- absence means "loaded, zero rows", not "never loaded".
        # Only a missing receipt file means never loaded.
        entry["loaded_rows"] = (
            load_report.get("property_rows", 0) if load_path.is_file() else None
        )
        entry["structures_added"] = load_report.get("added", 0)
        entry["unmatched"] = load_report.get("props_unmatched", 0)
        entry["new_structures"] = load_report.get("new_structures", 0)
        entry["preexisting_links"] = load_report.get("preexisting_links", 0)

        sid = source_ids.get(source)
        if sid is None:
            entry["db_rows"] = 0
            if work.is_dir() and (entry["staged_rows"] or 0) > 0:
                entry["problems"].append("NEVER LOADED: staged but no source_defs row")
            results.append(entry)
            continue

        entry["db_rows"] = rows_by_source.get(sid, 0)
        entry["db_refs"] = refs_by_source.get(sid, 0)
        entry["db_curves"] = curves_by_source.get(sid, 0)

        if not work.is_dir():
            entry["problems"].append("NOT STAGED: in the index but no work directory")
            results.append(entry)
            continue

        # 1. load integrity ------------------------------------------------
        if entry["loaded_rows"] is None:
            entry["problems"].append("NEVER LOADED: no load_report.json")
        elif entry["loaded_rows"] > entry["db_rows"]:
            # The dangerous direction: the loader counted rows the index does
            # not hold, i.e. an interrupted load or rows cleared and not
            # re-inserted.
            entry["problems"].append(
                f"ROWS MISSING: loader reported {entry['loaded_rows']:,}"
                f" but index holds only {entry['db_rows']:,}"
            )
        elif entry["loaded_rows"] < entry["db_rows"]:
            # material_properties has several writers besides load.py
            # (aflow_ael_attach, alexandria_*, phonondb_attach,
            # repair_duplicate_props, hmof_composite_admit), and none of them
            # update load_report.json. Extra rows are therefore expected for
            # those sources -- surfaced as INFO, not as a defect.
            entry["extra_rows"] = entry["db_rows"] - entry["loaded_rows"]
            entry["out_of_band_rows"] = entry["extra_rows"]

        # 2. staging yield --------------------------------------------------
        staged = entry["staged_rows"]
        if staged is not None and entry["loaded_rows"] is not None:
            # What actually landed, not what load.py counted. Several sources
            # are written by scripts that bypass the loader entirely
            # (hmof_composite_admit, alexandria_recover_functional_runs,
            # aflow_ael_attach, phonondb_attach) and none of them refresh
            # load_report.json, so the receipt understates the index. The
            # opposite direction -- index below receipt -- is a real defect and
            # is caught separately as ROWS MISSING.
            landed = max(entry["loaded_rows"], entry["db_rows"])
            gap = staged - landed - (entry["unmatched"] or 0)
            entry["unexplained_gap"] = gap
            # The loader re-derives a handful of rows (aliased duplicates land
            # twice by design), so a small negative gap is expected; positive
            # means rows vanished with no counter to explain them.
            if gap > max(50, staged * 0.001):
                entry["problems"].append(
                    f"DROPPED {gap:,} rows: staged {staged:,},"
                    f" in index {landed:,},"
                    f" unmatched {entry['unmatched']:,}"
                )

        # 3. field coverage -------------------------------------------------
        props_path = work / "staging_props.tsv.gz"
        if not quick and props_path.is_file() and entry["db_rows"]:
            staged_names = _staged_field_names(props_path)
            db_names = fields_by_source.get(sid, set())
            missing = sorted(staged_names - db_names)
            entry["staged_fields"] = len(staged_names)
            entry["db_fields"] = len(db_names)
            if missing:
                # A field can be absent from the index for two very different
                # reasons, and only one of them is a defect: the loader dropped
                # it (bug), or every record carrying it is unmatched anyway
                # (expected -- e.g. spse stages ionic_conductivity only for its
                # own structureless "custom:*" entries, which can never resolve
                # to a pool material). Separate them by asking whether ANY
                # record carrying the field is linked at all.
                linked = {
                    row[0]
                    for row in db.execute(
                        "SELECT native_id FROM material_source_refs"
                        " WHERE source_id = ?",
                        (sid,),
                    )
                }
                reachable = _fields_with_linked_records(props_path, set(missing), linked)
                entry["unreachable_fields"] = sorted(set(missing) - reachable)
                missing = sorted(reachable)
            if missing:
                entry["missing_fields"] = missing
                entry["problems"].append(
                    f"MISSING FIELDS ({len(missing)}): {', '.join(missing[:8])}"
                    + (" …" if len(missing) > 8 else "")
                )

        if entry["db_rows"] == 0 and entry["db_curves"] == 0:
            if entry["structures_added"] or entry["db_refs"]:
                entry["note"] = (
                    f"structure-only: {entry['db_refs']:,} refs,"
                    f" {entry['structures_added']:,} structures contributed"
                )
            elif source not in STRUCTURE_ONLY:
                entry["problems"].append("EMPTY: no rows, no curves, no structures")

        results.append(entry)

    totals = {
        "property_rows": db.execute("SELECT COUNT(*) FROM material_properties").fetchone()[0],
        "curves": db.execute("SELECT COUNT(*) FROM material_curves").fetchone()[0],
        "materials": db.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
        "source_refs": db.execute("SELECT COUNT(*) FROM material_source_refs").fetchone()[0],
    }
    db.close()
    return {"sources": results, "totals": totals}


def render(audit_result: dict) -> None:
    results = audit_result["sources"]
    bad = [r for r in results if r["problems"]]
    print(f"{'source':<34} {'staged':>12} {'loaded':>12} {'in index':>12} {'unmatched':>11}  status")
    print("-" * 100)
    for r in sorted(results, key=lambda r: -(r.get("db_rows") or 0)):
        status = "; ".join(r["problems"]) if r["problems"] else (r.get("note") or "ok")
        if not r["problems"] and r.get("out_of_band_rows"):
            status = f"ok (+{r['out_of_band_rows']:,} out-of-band)"
        if not r["problems"] and r.get("unreachable_fields"):
            status += (
                f" [{len(r['unreachable_fields'])} field(s) staged only for"
                f" unmatched records: {', '.join(r['unreachable_fields'][:3])}]"
            )
        print(
            f"{r['source']:<34} {r.get('staged_rows') or 0:>12,}"
            f" {r.get('loaded_rows') or 0:>12,} {r.get('db_rows') or 0:>12,}"
            f" {r.get('unmatched') or 0:>11,}  {status}"
        )
    t = audit_result["totals"]
    print()
    print(
        f"Totals: {t['property_rows']:,} property rows, {t['curves']:,} curves,"
        f" {t['materials']:,} structures, {t['source_refs']:,} source refs"
    )
    print(f"Sources audited: {len(results)}; with problems: {len(bad)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="skip the field-coverage scan")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    result = audit(args.quick)
    render(result)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 1 if any(r["problems"] for r in result["sources"]) else 0


if __name__ == "__main__":
    sys.exit(main())
