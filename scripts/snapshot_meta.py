#!/usr/bin/env python3
"""Describe a published snapshot, and report what changed between two of them.

A snapshot is auditable only if it says what produced it, so `describe` records
the index schema version, the fingerprint algorithm with the parameters that
decide which structures merge, the licence of every source, and each source's
counts alongside the upstream token the probe last saw. `diff` turns two of those
into the change report: sources arriving and leaving with their reason codes, per
source movement in materials and property rows, licence changes, and a
fingerprint algorithm change flagged as the renumbering event it is.

Counts only, deliberately. Naming which materials appeared or vanished, or which
merges changed, needs the previous snapshot's identifier and match tables rather
than its summary; the report says how much moved and leaves the "which" to
whoever asks for it with those tables in hand.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from scripts.properties.hashing import MAX_PRIMITIVE_SITES, MAX_SITES
from scripts.properties.load import FINGERPRINT_UNRELIABLE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = PROJECT_ROOT / "data" / "index" / "materials.sqlite"
DEFAULT_CATALOG = PROJECT_ROOT / "scripts" / "datasets" / "sources.json"


def _normalise_licence(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def fingerprint_identity() -> dict[str, Any]:
    """What has to match for two snapshots to merge structures the same way."""
    try:
        hasher_version = importlib_metadata.version("material-hasher")
    except importlib_metadata.PackageNotFoundError:
        hasher_version = None
    return {
        "algorithm": "bawl",
        "material_hasher": hasher_version,
        "max_sites": MAX_SITES,
        "max_primitive_sites": MAX_PRIMITIVE_SITES,
        # two different lists, both part of the algorithm's definition — a
        # rebuild that loses either merges differently:
        #   the loader refuses to attach properties through these sources' hash
        #   refs, because their fingerprints cannot separate their own records
        "fingerprint_unreliable_sources": sorted(FINGERPRINT_UNRELIABLE),
        #   and these are admitted on (fingerprint, volume per site) instead of
        #   the fingerprint alone; see deem_zeolite_admit.py and
        #   hmof_composite_admit.py, which have no shared constant to import
        "composite_key_admissions": ["deem-zeolites", "hmof"],
    }


def describe(index_db: Path, catalog: Path, probe_file: Path | None) -> dict[str, Any]:
    db = sqlite3.connect(f"file:{index_db}?mode=ro", uri=True)
    meta = dict(db.execute("SELECT key, value FROM metadata"))
    materials, experimental = db.execute(
        "SELECT count(*), coalesce(sum(is_experimental), 0) FROM materials"
    ).fetchone()

    property_rows = dict(
        db.execute(
            "SELECT s.key, count(*) FROM material_properties p "
            "JOIN source_defs s ON s.id = p.source_id GROUP BY 1"
        )
    )
    source_materials = dict(
        db.execute(
            "SELECT s.key, count(DISTINCT r.material_pk) FROM material_source_refs r "
            "JOIN source_defs s ON s.id = r.source_id GROUP BY 1"
        )
    )
    index_licences = dict(db.execute("SELECT key, license FROM source_defs"))
    names = dict(db.execute("SELECT key, name FROM source_defs"))
    db.close()

    catalogued = {s["id"]: s for s in json.loads(catalog.read_text(encoding="utf-8"))["sources"]}
    probes: dict[str, Any] = {}
    if probe_file and probe_file.exists():
        probes = json.loads(probe_file.read_text(encoding="utf-8")).get("probes", {})

    sources = []
    for key in sorted(set(index_licences) | set(property_rows) | set(source_materials)):
        entry = catalogued.get(key, {})
        probe = probes.get(key, {})
        sources.append(
            {
                "source_id": key,
                "name": names.get(key),
                "licence_in_index": index_licences.get(key),
                "licence_in_catalog": entry.get("license"),
                "state": entry.get("state"),
                "reason": entry.get("reason"),
                "materials": source_materials.get(key, 0),
                "property_rows": property_rows.get(key, 0),
                "upstream_seen": probe.get("seen"),
                "upstream_checked_at": probe.get("checked_at"),
            }
        )

    return {
        "index": {
            "schema_version": meta.get("schema_version"),
            "materials": materials,
            "experimental": experimental,
            "computational": materials - experimental,
            "property_rows": int(meta.get("property_row_count") or sum(property_rows.values())),
            "curves": int(meta.get("curve_count") or 0),
        },
        "fingerprint": fingerprint_identity(),
        "sources": sources,
    }


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = {s["source_id"]: s for s in before["sources"]}
    new = {s["source_id"]: s for s in after["sources"]}

    report: dict[str, Any] = {
        "sources_added": [
            {"source_id": k, "state": new[k]["state"], "reason": new[k]["reason"]}
            for k in sorted(set(new) - set(old))
        ],
        "sources_removed": [
            {"source_id": k, "state": old[k]["state"], "reason": old[k]["reason"]}
            for k in sorted(set(old) - set(new))
        ],
        "moved": [],
        "licence_changes": [],
        "state_changes": [],
        "totals": {
            field: {
                "before": before["index"].get(field),
                "after": after["index"].get(field),
                "delta": (after["index"].get(field) or 0) - (before["index"].get(field) or 0),
            }
            for field in ("materials", "experimental", "computational", "property_rows", "curves")
        },
    }

    for key in sorted(set(old) & set(new)):
        was, now = old[key], new[key]
        if was["materials"] != now["materials"] or was["property_rows"] != now["property_rows"]:
            report["moved"].append(
                {
                    "source_id": key,
                    "materials": now["materials"] - was["materials"],
                    "property_rows": now["property_rows"] - was["property_rows"],
                }
            )
        if _normalise_licence(was["licence_in_index"]) != _normalise_licence(
            now["licence_in_index"]
        ):
            report["licence_changes"].append(
                {
                    "source_id": key,
                    "before": was["licence_in_index"],
                    "after": now["licence_in_index"],
                }
            )
        if (was["state"], was["reason"]) != (now["state"], now["reason"]):
            report["state_changes"].append(
                {
                    "source_id": key,
                    "before": [was["state"], was["reason"]],
                    "after": [now["state"], now["reason"]],
                }
            )

    if before["fingerprint"] != after["fingerprint"]:
        # section 6.2: this is the only case that may renumber material ids, and
        # it obliges the snapshot to ship an old-to-new map
        report["fingerprint_changed"] = {
            "before": before["fingerprint"],
            "after": after["fingerprint"],
            "consequence": "material ids may be renumbered; publish an old_id to new_id map",
        }
    if before["index"].get("schema_version") != after["index"].get("schema_version"):
        report["schema_version_changed"] = {
            "before": before["index"].get("schema_version"),
            "after": after["index"].get("schema_version"),
        }
    return report


def _print_report(report: dict[str, Any]) -> None:
    for label, key in (("新增来源", "sources_added"), ("下线来源", "sources_removed")):
        for row in report[key]:
            print(f"  {label}: {row['source_id']} ({row['state']}"
                  + (f"/{row['reason']}" if row["reason"] else "") + ")")
    for row in report["state_changes"]:
        print(f"  状态变化: {row['source_id']} {row['before']} -> {row['after']}")
    for row in report["licence_changes"]:
        print(f"  ⚠️  许可变化: {row['source_id']} {row['before']!r} -> {row['after']!r}")
    for row in report["moved"][:15]:
        print(f"  {row['source_id']:28s} 材料 {row['materials']:+d}  性质行 {row['property_rows']:+d}")
    if len(report["moved"]) > 15:
        print(f"  （另有 {len(report['moved']) - 15} 个来源有变动）")
    for field, values in report["totals"].items():
        if values["delta"]:
            print(f"  合计 {field}: {values['before']} -> {values['after']} ({values['delta']:+d})")
    if "fingerprint_changed" in report:
        print("  ⚠️  指纹算法变了: " + report["fingerprint_changed"]["consequence"])
    if "schema_version_changed" in report:
        c = report["schema_version_changed"]
        print(f"  索引 schema: {c['before']} -> {c['after']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--probe", type=Path, default=None,
                        help="probe seen.json, for the upstream token per source")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--diff", nargs=2, type=Path, metavar=("BEFORE", "AFTER"),
                        help="two describe outputs; print the change report")
    args = parser.parse_args(argv)

    if args.diff:
        before, after = (json.loads(p.read_text(encoding="utf-8")) for p in args.diff)
        report = diff_snapshots(before, after)
        _print_report(report)
        if args.out:
            args.out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
                                + "\n", encoding="utf-8")
            print(f"\nwrote {args.out}")
        return 0

    if not args.index.exists():
        parser.error(f"no index at {args.index}")
    snapshot = describe(args.index, args.catalog, args.probe)
    payload = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
