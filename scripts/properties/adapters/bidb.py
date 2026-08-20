"""BiDB: homobilayer database's monolayer entries (C2DB lineage, PBE).

One ASE db. Only ``number_of_layers==1`` rows (992) are ingested: the
bilayer rows are stacking-variant sweeps of the same monolayers and out of
scope. The parent ``cod_id``/``icsd_id`` keys reference the bulk crystal
the monolayer was exfoliated from, NOT the monolayer itself, so they are
not used as match_ids; matching relies on structure hashing alone.

The slabs are stored with pbc=[True, True, False]; pymatgen Structures
require full periodicity, so pbc is forced to all-True before conversion
(the large vacuum along c is retained, so geometry is unchanged).

Gaps come as a spin-orbit / scalar-relativistic pair (``gap_pbe`` +
``gap_pbe_dir`` include SOC, ``gap_pbe_nosoc`` + ``gap_pbe_dir_nosoc`` do
not). Both halves name their SOC treatment in the method string, otherwise
the two band_gap rows of one monolayer would be indistinguishable. Symmetry
comes as the pair (3D space group, 2D layer group), both numbers staged;
``dipz`` (out-of-plane dipole, no unit published), ``magnetic`` and
``has_inversion_symmetry`` are left alone.
"""

from __future__ import annotations

from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

METHOD = "PBE (BiDB)"
GAP_SOC = "PBE+SOC (BiDB)"
GAP_NOSOC = "PBE no SOC (BiDB)"


class BidbAdapter(SourceAdapter):
    source_key = "bidb"

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        from ase.db import connect
        from pymatgen.io.ase import AseAtomsAdaptor

        db = connect(self.root / "bidb-2026-06-25.db")
        count = 0
        for row in db.select("number_of_layers=1"):
            if limit is not None and count >= limit:
                return
            kvp = row.key_value_pairs
            uid = str(kvp.get("uid") or row.formula)
            properties = []
            for key, name, method in (
                ("gap_pbe", "band_gap", GAP_SOC),
                ("gap_pbe_dir", "band_gap_direct", GAP_SOC),
                ("gap_pbe_nosoc", "band_gap", GAP_NOSOC),
                ("gap_pbe_dir_nosoc", "band_gap_direct", GAP_NOSOC),
            ):
                value = safe_float(kvp.get(key))
                if value is not None and value >= 0:
                    properties.append(PropertyValue(name, value, "eV", method))
            ehull = safe_float(kvp.get("ehull"))
            if ehull is not None:
                properties.append(
                    PropertyValue("energy_above_hull", ehull, "eV/atom", METHOD)
                )
            stable = kvp.get("dynamically_stable")
            if stable is not None:
                properties.append(
                    PropertyValue(
                        "dynamically_stable",
                        str(stable).strip().lower() in {"yes", "true", "1"},
                        None,
                        METHOD,
                    )
                )
            properties.append(
                PropertyValue("dimensionality", "2D", None, METHOD)
            )
            for key, name, highest in (
                ("space_group_number", "spacegroup_number", 230),
                ("layer_group_number", "layer_group_number", 80),
            ):
                value = safe_float(kvp.get(key))
                if value is not None and 1 <= value <= highest:
                    properties.append(
                        PropertyValue(name, int(value), None, "spglib (BiDB)")
                    )
            try:
                atoms = row.toatoms()
                # 2D slab stored with pbc [T, T, F]; pymatgen needs full pbc.
                atoms.pbc = [True, True, True]
                structure = AseAtomsAdaptor.get_structure(atoms)
            except Exception:  # noqa: BLE001 - keep the property-only record
                structure = None
            count += 1
            yield SourceRecord(
                native_id=uid,
                properties=properties,
                structure=structure,
                match_ids=[],
            )
