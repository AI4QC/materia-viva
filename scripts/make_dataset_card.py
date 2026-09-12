#!/usr/bin/env python3
"""Generate the Hugging Face dataset card for AI4QC/MateriaViva.

Written from the live index rather than by hand. Every hardcoded figure in this
project's prose has gone stale at least once -- the landing page was still
advertising 13.08 million structures against a live 13.5 million, and its
"79 million property records" against 121 million -- so the numbers here are
read out of the database at generation time and the card is regenerated
whenever the index changes.

    python scripts/make_dataset_card.py --out data/hf-upload/README.md
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DB = PROJECT_ROOT / "data" / "index" / "materials.sqlite"
SLICE_MANIFEST = PROJECT_ROOT / "data" / "slice" / "slice-manifest.json"

#: Sources whose terms do not permit redistribution, or permit it only
#: non-commercially. Kept explicit so the card can never quietly imply the
#: whole thing is open.
RESTRICTED = {
    "icsd": "FIZ Karlsruhe subscription — redistribution not permitted",
    "aflow": "AFLOW academic non-commercial terms",
    "elementa": "CC BY-NC 4.0 — non-commercial only",
    "gnome": "CC BY-NC 4.0 — non-commercial only",
    # NOMAD carries no single licence: each upload keeps the terms its depositor
    # chose. The default for published data is CC BY 4.0, but it is not uniform
    # and the export does not record the per-entry choice, so the whole source is
    # withheld from redistribution until that is resolved per upload.
    "nomad": "per-upload licence — not uniform, resolve per entry before release",
}


def facts() -> dict:
    db = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True, timeout=600)
    db.execute("PRAGMA busy_timeout = 600000")
    meta = dict(db.execute(
        "SELECT key, value FROM metadata WHERE key IN "
        "('property_row_count', 'curve_count', 'experimental_count', 'candidate_count')"
    ))
    out = {
        "materials": db.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
        "sources": db.execute("SELECT COUNT(*) FROM source_defs").fetchone()[0],
        "property_defs": db.execute("SELECT COUNT(*) FROM property_defs").fetchone()[0],
        "source_refs": db.execute("SELECT COUNT(*) FROM material_source_refs").fetchone()[0],
        "property_rows": int(meta.get("property_row_count", 0)),
        "curves": int(meta.get("curve_count", 0)),
        "experimental": int(meta.get("experimental_count", 0)),
        "candidate": int(meta.get("candidate_count", 0)),
    }
    out["shared_2plus"] = db.execute(
        "SELECT COUNT(*) FROM (SELECT material_pk FROM material_source_refs"
        " GROUP BY material_pk HAVING COUNT(DISTINCT source_id) >= 2)"
    ).fetchone()[0]
    out["curve_types"] = db.execute(
        "SELECT curve_type, COUNT(*) FROM material_curves GROUP BY curve_type"
        " ORDER BY 2 DESC"
    ).fetchall()
    out["families"] = db.execute(
        "SELECT material_family, COUNT(*) FROM materials"
        " WHERE material_family IS NOT NULL GROUP BY material_family ORDER BY 2 DESC"
    ).fetchall()
    # One grouped scan each, not a correlated subquery per source: 54 separate
    # COUNT(*)s over 121M rows takes the better part of an hour and reads a
    # different snapshot for every source.
    rows_by_source = dict(db.execute(
        "SELECT source_id, COUNT(*) FROM material_properties GROUP BY source_id"
    ))
    mats_by_source = dict(db.execute(
        "SELECT source_id, COUNT(DISTINCT material_pk) FROM material_source_refs"
        " GROUP BY source_id"
    ))
    out["table"] = sorted(
        (
            (key, name, lic, rows_by_source.get(sid, 0), mats_by_source.get(sid, 0))
            for sid, key, name, lic in db.execute(
                "SELECT id, key, name, license FROM source_defs"
            )
        ),
        key=lambda r: -r[3],
    )
    db.close()
    return out


def render(f: dict, slice_bytes: int | None, slice_materials: int | None) -> str:
    restricted_rows = [r for r in f["table"] if r[0] in RESTRICTED]
    restricted_props = sum(r[3] for r in restricted_rows)
    lines: list[str] = []
    add = lines.append

    add("---")
    add("license: other")
    add("license_name: mixed-source-see-card")
    add("pretty_name: MateriaViva unified crystal index")
    add("tags:")
    add("  - materials-science")
    add("  - crystal-structures")
    add("  - dft")
    add("  - chemistry")
    add("---")
    add("")
    add("# MateriaViva — unified, deduplicated crystal index")
    add("")
    add(
        f"One SQLite index over **{f['materials']:,} deduplicated crystal structures** "
        f"drawn from **{f['sources']} databases**, carrying "
        f"**{f['property_rows']:,} property values** across "
        f"**{f['property_defs']} distinct properties** and "
        f"**{f['curves']:,} spectra**, every one tagged with the database it came from."
    )
    add("")
    add(
        f"{f['experimental']:,} experimental and {f['candidate']:,} candidate structures. "
        f"**{f['shared_2plus']:,} structures are contributed by two or more source "
        "databases** — that overlap is the point: the same crystal computed by "
        "Materials Project, OQMD, Alexandria and AFLOW is one row here, with four sets "
        "of numbers attached and four provenance records, instead of four near-duplicate "
        "entries you have to reconcile yourself."
    )
    add("")

    add("## ⚠️ Access and licence — read before redistributing")
    add("")
    add(
        "**This repository is private and is not an open-redistribution snapshot.** "
        "It contains the complete working index, including sources whose terms restrict "
        "redistribution:"
    )
    add("")
    add("| Source | Rows | Restriction |")
    add("|---|---:|---|")
    for key, _name, _lic, rows, _mats in restricted_rows:
        add(f"| `{key}` | {rows:,} | {RESTRICTED[key]} |")
    add("")
    add(
        f"That is {restricted_props:,} of {f['property_rows']:,} property rows "
        f"({restricted_props / max(f['property_rows'], 1) * 100:.1f}%). In particular:"
    )
    add("")
    add(
        "- **ICSD** data is licensed from FIZ Karlsruhe per subscriber. Do not share this "
        "repository, or anything derived from it, with anyone who does not hold their own "
        "ICSD licence."
    )
    add(
        "- **CC BY-NC** sources (ELEMENTA, GNoME) and AFLOW's academic terms make the "
        "combined index **non-commercial**."
    )
    add(
        "- Every property row records its `source_id`, so a licence-filtered export is a "
        "single `WHERE source_id NOT IN (...)` away. Do that before any public release."
    )
    add("")

    add("## What is in here")
    add("")
    add("```text")
    add("index/                the full index (~47 GB)")
    add("  materials.sqlite      structures, properties, provenance, curve offsets")
    add("  structures.blob       zlib-compressed CIF text")
    add("  curves.blob           zlib-compressed spectra payloads")
    add("slice/                a small development slice")
    add("  materials.sqlite      same schema, same primary keys")
    add("  structures.blob")
    add("  curves.blob")
    add("  slice-manifest.json")
    add("docs/                 integration and acquisition notes")
    add("```")
    add("")
    if slice_materials:
        add(
            f"The **slice** holds {slice_materials:,} materials in "
            f"{slice_bytes / (1 << 20):.0f} MB and exists so the web UI can be developed "
            "without the 47 GB download. It is not a random sample: it is a greedy set "
            "cover chosen so that **every source, every property name, every curve type "
            "and every material family appears at least once**. A random 1,000 rows out "
            "of 13.5 million would miss almost every rare property, which is exactly the "
            "set of panels most likely to be broken."
        )
        add("")

    add("## Running the web interface")
    add("")
    add("The code is on GitHub; only the data lives here.")
    add("")
    add("```bash")
    add("git clone https://github.com/AI4QC/materia-viva.git")
    add("cd materia-viva")
    add("")
    add("# small slice, enough to develop the UI against")
    add("python scripts/fetch_index.py slice")
    add("python scripts/serve.py --runtime data/slice")
    add("")
    add("# or the full index (~47 GB, needs roughly double that free during download)")
    add("python scripts/fetch_index.py full")
    add("python scripts/serve.py --runtime data/index")
    add("```")
    add("")
    add("Then open <http://127.0.0.1:8000>.")
    add("")

    add("## Schema")
    add("")
    add(
        "`materials` holds one row per deduplicated structure with the headline scalars; "
        "the cross-database layer is four tables:"
    )
    add("")
    add("| Table | What it holds |")
    add("|---|---|")
    add("| `source_defs` | one row per contributing database: key, name, licence, URL |")
    add("| `property_defs` | canonical property vocabulary: name, unit, kind |")
    add(
        "| `material_properties` | one row per (material, property, source) with "
        "`native_id`, value and a `method` string carrying the level of theory |"
    )
    add(
        "| `material_source_refs` | how each source's record was matched: "
        "`id:<db>` (authoritative identifier), `hash` (BAWL fingerprint) or `origin` |"
    )
    add(
        "| `material_curves` | non-scalar data — XRD, band structures, DOS, phonons, "
        "XAS, Raman, IR — as offsets into `curves.blob` |"
    )
    add("")
    add(
        "`method` is never merged away: PBE, PBEsol, SCAN, r2SCAN, HSE06, experiment and "
        "GCMC-at-a-stated-temperature-and-pressure all coexist on one material and stay "
        "distinguishable."
    )
    add("")
    add("### Spectra")
    add("")
    add("| Curve type | Count |")
    add("|---|---:|")
    for ctype, n in f["curve_types"]:
        add(f"| `{ctype}` | {n:,} |")
    add("")
    add("### Structure families")
    add("")
    add("Non-conventional crystal classes are labelled in `materials.material_family`:")
    add("")
    add("| Family | Structures |")
    add("|---|---:|")
    for fam, n in f["families"]:
        add(f"| `{fam}` | {n:,} |")
    add("")
    add("`NULL` means a conventional bulk crystal.")
    add("")

    add("## Deduplication")
    add("")
    add(
        "Structures are deduplicated on the **BAWL fingerprint** "
        "(`material_hasher.hasher.bawl`): parse, cap at 500 sites, reduce to the "
        "primitive cell, cap at 300, hash. Property records attach by a two-step rule — "
        "an authoritative identifier first (`mp-`, `oqmd-`, `agm-`, `icsd-`, `cod-`, …), "
        "then the fingerprint. **Formula-only matching is never used**; it produces "
        "confident, wrong attributions."
    )
    add("")
    add(
        "Two corpora need more than a fingerprint. Enumerated libraries — the Deem "
        "hypothetical zeolites and hMOF — decorate one topology with a menu of "
        "substituents, so sibling frameworks share a bonding graph and collide. They are "
        "admitted on a composite key `(fingerprint, volume per site)` instead, and their "
        "colliding fingerprints are deliberately kept out of the match map so no later "
        "source can resolve through them."
    )
    add("")

    add("## Sources")
    add("")
    add("| Database | Property rows | Materials | Licence |")
    add("|---|---:|---:|---|")
    for key, name, lic, rows, mats in f["table"]:
        mark = " ⚠️" if key in RESTRICTED else ""
        add(f"| {name} (`{key}`){mark} | {rows:,} | {mats:,} | {lic or '—'} |")
    add("")
    add("⚠️ marks a source with redistribution restrictions — see the licence section above.")
    add("")
    add("## Citation")
    add("")
    add(
        "Cite the original databases. Each carries its own citation requirement; "
        "`source_defs.url` and `docs/dataset-acquisition.md` record where every row "
        "came from."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=PROJECT_ROOT / "data" / "hf-upload" / "README.md")
    args = parser.parse_args()

    slice_bytes = slice_materials = None
    if SLICE_MANIFEST.is_file():
        import json
        manifest = json.loads(SLICE_MANIFEST.read_text(encoding="utf-8"))
        slice_bytes = manifest.get("total_bytes")
        slice_materials = manifest.get("materials")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(facts(), slice_bytes, slice_materials), encoding="utf-8")
    print(f"wrote {args.out} ({args.out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
