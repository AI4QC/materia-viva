"""OQMD v1.8: GGA(+U) thermodynamics, band gaps and magnetization.

Reads ``data/props_work/oqmd/extracted.sqlite`` produced by
``scripts/properties/adapters/oqmd_extract.py`` (a two-pass stream parse of
the 21GB MySQL dump; run that first).  One row per non-duplicate OQMD entry,
carrying the entry-level formation energy / stability plus the band gap,
total energy and magnetization of the best converged calculation
('static' preferred, then 'standard'), and that calculation's final output
structure.

Records match the pool by oqmd id first; the pool's oqmd ids (via
LeMat-Bulk immutable ids) are qmdb *structure* ids, so the pair carries the
chosen calculation's output_id, not the entry id (entry ids live in a lower
numeric range and would only ever collide by accident - verified: 475,932 of
the pool's 577,442 oqmd ids are exactly our chosen output ids).  ICSD-derived
entries additionally match their parent ICSD id.  Unmatched records enter
the candidate pool with the relaxed structure, so no always_hash and no
properties_only.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import (
    WORK_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

METHOD = "GGA(+U) OQMD v1.8"
EXTRACTED = WORK_ROOT / "oqmd" / "extracted.sqlite"

# derived value -> canonical property (unit per registry.py); formation
# energy and hull distance prefer the fit-'standard' formation_energies row
# (fe_*), falling back to the sparse entries-table copies
PROPERTY_MAP = (
    ("formation", "formation_energy_per_atom", "eV/atom"),
    ("hull", "energy_above_hull", "eV/atom"),
    ("band_gap", "band_gap", "eV"),
    ("energy_pa", "total_energy_per_atom", "eV/atom"),
    ("magmom_pa", "magnetization_per_atom", "μB/atom"),
)


def _build_structure(lattice_json: str | None, sites_json: str | None):
    """pymatgen Structure from extracted lattice + sites, or None.

    Sites are [element, fx, fy, fz, occupancy, magmom]; any partial
    occupancy disqualifies the structure (no ordered cell to hash).
    """

    if not lattice_json or not sites_json:
        return None
    sites = json.loads(sites_json)
    if not sites:
        return None
    for site in sites:
        occupancy = site[4]
        if occupancy is None or abs(occupancy - 1.0) > 1e-6:
            return None
    from pymatgen.core import Lattice, Structure

    return Structure(
        Lattice(json.loads(lattice_json)),
        [site[0] for site in sites],
        [site[1:4] for site in sites],
        coords_are_cartesian=False,
    )


class OqmdAdapter(SourceAdapter):
    source_key = "oqmd"
    # id match means "this record IS that pool structure": no re-hashing on a
    # hit, and unmatched records are admitted as new candidates.
    always_hash = False
    properties_only = False

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        if not EXTRACTED.exists():
            raise SystemExit(
                f"{EXTRACTED} missing - run scripts/properties/adapters/"
                "oqmd_extract.py first"
            )
        db = sqlite3.connect(f"file:{EXTRACTED}?mode=ro", uri=True)
        try:
            sql = (
                "SELECT entry_id, icsd, output_id, delta_e, stability,"
                " fe_delta_e, fe_stability, band_gap, energy_pa, magmom_pa,"
                " lattice, sites FROM entry ORDER BY entry_id"
            )
            if limit is not None:
                sql += f" LIMIT {int(limit)}"
            for (entry_id, icsd, output_id, delta_e, stability, fe_delta_e,
                 fe_stability, band_gap, energy_pa, magmom_pa, lattice_json,
                 sites_json) in db.execute(sql):
                native_id = f"oqmd-{entry_id}"
                gap = safe_float(band_gap)
                # OQMD stability is negative for hull members (depth below the
                # hull of competing phases); energy_above_hull is 0 for them
                hull = safe_float(
                    fe_stability if fe_stability is not None else stability
                )
                if hull is not None and hull < 0.0:
                    hull = 0.0
                row = {
                    "formation": safe_float(
                        fe_delta_e if fe_delta_e is not None else delta_e
                    ),
                    "hull": hull,
                    # a handful of calculations carry unphysical negative gaps
                    "band_gap": gap if gap is None or gap >= 0.0 else None,
                    "energy_pa": safe_float(energy_pa),
                    "magmom_pa": safe_float(magmom_pa),
                }
                properties = []
                for key, name, unit in PROPERTY_MAP:
                    value = row[key]
                    if value is not None:
                        properties.append(PropertyValue(name, value, unit, METHOD))
                match_ids = []
                if output_id is not None:
                    # pool oqmd ids are qmdb structure ids (LeMat-Bulk)
                    oqmd_pair = normalize_match_id("oqmd", f"oqmd-{output_id}")
                    if oqmd_pair:
                        match_ids.append(oqmd_pair)
                icsd_pair = normalize_match_id("icsd", icsd)
                if icsd_pair:
                    match_ids.append(icsd_pair)
                try:
                    structure = _build_structure(lattice_json, sites_json)
                except Exception:  # noqa: BLE001 - keep the property record
                    structure = None
                yield SourceRecord(
                    native_id=native_id,
                    properties=properties,
                    structure=structure,
                    match_ids=match_ids,
                )
        finally:
            db.close()
