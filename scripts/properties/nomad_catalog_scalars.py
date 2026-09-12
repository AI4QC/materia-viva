#!/usr/bin/env python3
"""Reduce the 19.4M-row NOMAD catalog to one scalar table keyed by material.

The catalog is the only NOMAD stage that carries scalar properties for the whole
repository and it is complete, so it can be ingested without waiting for the
``properties`` archive (which holds curves and tensors and is still downloading).

One NOMAD material typically has many entries -- different functionals, programs
and convergence settings for the same crystal -- so the reduction key is
(material, property, method) rather than (material, property).  Method carries
the level of theory, the program and, for band gaps, whether the value was read
off a density of states or a band structure; entries that agree on all of that
are the same calculation repeated, and the first one seen is kept.  ``n_entries``
records how many backed each value so the collapse is reportable rather than
silent.

Deliberately not ingested: lattice parameters and cell volumes (geometry, already
carried by the structure itself), convergence tolerances and ``n_calculations``
(run metadata, not material properties).  Everything that does map onto a
registry property is listed in SCALAR_MAP below.

    python scripts/properties/nomad_catalog_scalars.py --out <work>/catalog_scalars.sqlite
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOMAD_ROOT = PROJECT_ROOT / "data" / "raw" / "acquired" / "nomad" / "2026-09-05"

#: NOMAD archives are SI throughout: metres, joules, newtons, pascals.
J_PER_EV = 1.602176634e-19
M_PER_ANGSTROM = 1e-10
N_PER_EV_PER_ANGSTROM = J_PER_EV / M_PER_ANGSTROM
PA_PER_GPA = 1e9

#: NOT ingested: the optoelectronic solar-cell family (efficiency, open-circuit
#: voltage, short-circuit current density, fill factor), about 43,000 entries
#: across the catalog.  Measured on a 780-page spread, 0 of 5,115 solar-cell
#: entries carry a ``results.material.material_id``: they are device
#: measurements, not crystal calculations, and NOMAD does not tie them to a
#: material.  Attaching them to this database would mean matching on composition,
#: which is the one join this project never makes, so they stay in raw.

#: elastic-average label -> registry property, for bulk and shear separately
MODULUS_TYPE = {
    "voigt_reuss_hill_average": "vrh",
    "voigt_average": "voigt",
    "reuss_average": "reuss",
}


def _dig(node, path: str):
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    return node


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def method_string(results: dict, *qualifiers: str) -> str:
    """Level of theory for one entry, plus any per-value qualifier."""
    method = results.get("method") or {}
    sim = method.get("simulation") or {}
    dft = sim.get("dft") or {}
    bits = [method.get("method_name"), dft.get("xc_functional_type"),
            sim.get("program_name")]
    names = dft.get("xc_functional_names")
    if names:
        bits.append("+".join(sorted(names)))
    bits.extend(q for q in qualifiers if q)
    return " / ".join(str(b) for b in bits if b) or "unspecified"


def scalars_of(results: dict):
    """Yield (property, value, method_qualifiers) for one catalog row."""
    props = results.get("properties") or {}

    # --- electronic band gap: joules, one row per spin channel / provenance
    for item in _as_list(_dig(props, "electronic.band_gap")):
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not _finite(value):
            continue
        label = _dig(item, "provenance.label")
        index = item.get("index")
        spin = f"spin {index}" if isinstance(index, int) and index > 0 else None
        yield "band_gap", value / J_PER_EV, (label, spin)

    # --- geometry-optimisation residual force: newtons
    force = _dig(props, "geometry_optimization.final_force_maximum")
    if _finite(force):
        yield "max_residual_force", force / N_PER_EV_PER_ANGSTROM, ()

    # --- elastic moduli: pascals, three averaging schemes per record
    for family, stem in (("bulk_modulus", "bulk_modulus"),
                         ("shear_modulus", "shear_modulus")):
        for item in _as_list(_dig(props, f"mechanical.{family}")):
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if not _finite(value):
                continue
            suffix = MODULUS_TYPE.get(item.get("type"))
            if suffix is None:
                continue
            yield f"{stem}_{suffix}", value / PA_PER_GPA, ()

    # --- catalyst specific surface area: already a registry property
    area = _dig(props, "catalytic.catalyst.surface_area")
    if _finite(area):
        yield "surface_area_gravimetric", area, ()

    # --- volume per site, from the conventional cell when NOMAD gives one
    for cell in ("conventional", "primitive", "original"):
        volume = _dig(props, f"structures.structure_{cell}.cell_volume")
        sites = _dig(props, f"structures.structure_{cell}.n_sites")
        if _finite(volume) and isinstance(sites, int) and sites > 0:
            yield ("volume_per_atom",
                   volume / (M_PER_ANGSTROM ** 3) / sites, (f"{cell} cell",))
            break


SCHEMA = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;
CREATE TABLE IF NOT EXISTS scalars (
    material_id TEXT NOT NULL,
    prop        TEXT NOT NULL,
    method      TEXT NOT NULL,
    value       REAL NOT NULL,
    n_entries   INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (material_id, prop, method)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS progress (page TEXT PRIMARY KEY);
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=NOMAD_ROOT)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit-pages", type=int, default=None)
    args = ap.parse_args()

    pages = sorted(args.root.glob("catalog/page-*.json.gz"))
    if args.limit_pages:
        pages = pages[: args.limit_pages]
    if not pages:
        raise SystemExit(f"no catalog pages under {args.root}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(args.out)
    db.executescript(SCHEMA)
    done = {row[0] for row in db.execute("SELECT page FROM progress")}
    print(f"{len(pages)} catalog pages, {len(done)} already done", flush=True)

    started = time.time()
    rows = kept = skipped_no_material = 0
    for n, page in enumerate(pages, 1):
        if page.name in done:
            continue
        batch: list[tuple] = []
        with gzip.open(page, "rt", encoding="utf-8") as handle:
            for row in json.load(handle)["data"]:
                rows += 1
                results = row.get("results") or {}
                material_id = _dig(results, "material.material_id")
                if not material_id:
                    skipped_no_material += 1
                    continue
                for prop, value, quals in scalars_of(results):
                    batch.append((material_id, prop,
                                  method_string(results, *quals), value))
        # first entry seen for a (material, property, method) wins; later ones
        # only bump the counter, so the collapse stays visible
        db.executemany(
            "INSERT INTO scalars(material_id, prop, method, value) VALUES (?,?,?,?) "
            "ON CONFLICT(material_id, prop, method) DO UPDATE SET "
            "n_entries = n_entries + 1", batch)
        db.execute("INSERT OR IGNORE INTO progress(page) VALUES (?)", (page.name,))
        db.commit()
        kept += len(batch)
        if n % 100 == 0 or n == len(pages):
            rate = rows / max(time.time() - started, 1e-9)
            print(f"  page {n}/{len(pages)}  rows {rows:,}  staged {kept:,}  "
                  f"{rate:,.0f} rows/s", flush=True)

    stored = db.execute("SELECT COUNT(*) FROM scalars").fetchone()[0]
    materials = db.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM scalars GROUP BY material_id)"
    ).fetchone()[0]
    print(f"\ncatalog rows read      {rows:,}")
    print(f"rows without material  {skipped_no_material:,}")
    print(f"scalar rows staged     {kept:,}")
    print(f"scalar rows stored     {stored:,}  (after the method-level collapse)")
    print(f"distinct materials     {materials:,}")
    for prop, count, mats in db.execute(
            "SELECT prop, COUNT(*), COUNT(DISTINCT material_id) FROM scalars "
            "GROUP BY prop ORDER BY 2 DESC"):
        print(f"  {prop:<24} {count:>12,} rows  {mats:>12,} materials")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
