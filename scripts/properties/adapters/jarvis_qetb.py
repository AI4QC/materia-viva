"""JARVIS-QETB: NIST's universal tight-binding database (829,576 records).

One 948 MB JSON array (single line) of QETB (Quantum Espresso Tight-Binding)
calculations, jids "JQE-*", structures as jarvis Atoms dicts. The dataset is a
TB fitting set full of deliberately non-equilibrium geometries (volume scans,
distortions, random structures), so positive formation energies are
legitimate, not errors. Everything is a lower-fidelity tight-binding result:
every property row carries method "QETB (tight-binding)" so the fidelity gap
to the DFT sources stays visible.

Column semantics, verified on 75 records sampled across the whole file plus a
full-file regex scan:

* ``f_enp`` is a formation energy per atom in eV. The linear model
  f_enp = energy_per_atom - sum_e x_e * mu_e holds to <1 meV: elemental
  references solved from two Mg-F records predict a third record's f_enp to
  0.3 meV, and an FeSe polymorph pair has delta-f_enp == delta-energy_per_atom
  to the printed precision. Near-ground-state elemental Li sits at +0.14,
  MgF2 at -3.0/-3.1 eV/atom (OptB88vdW: about -3.7), ionic oxides negative,
  distorted structures positive - formation-energy behaviour, so it is stored
  as canonical ``formation_energy_per_atom``. Full-file range [-4.15, +10596];
  the 65 records with |f_enp| >= 20 are extreme volume-scan points (heavily
  compressed elemental Ag/Al/Au and the like - still consistent with the
  linear model, but useless as material-level formation energies) and are
  dropped by the sanity filter.
* ``indir_gap`` is a band gap in eV: 0 for every sampled metal/intermetallic,
  6.08/5.33 for MgF2, 3.91 for NaSiO2. Full-file range [0.0, 25.9], never
  negative, never null.
* ``energy_per_atom`` is the QETB total energy in eV/atom in a deep
  atomic-reference frame (Fe is about -3402 eV/atom); it equals
  ``final_energy`` (Hartree per cell) x 27.211385 / natoms exactly, so
  final_energy is redundant and skipped. Exactly 2 records have a positive
  value (max +8676, the most extreme scan points); the ``v < 0`` guard drops
  them (no other value is above -5).

Streaming: ijson would be ideal, but the dump contains bare NaN (111) and
Infinity (99) tokens - all of them in the unused ``formula`` field, a pandas
round-trip artifact where real formulas such as "NaN" were coerced to floats -
and ijson's lexer rejects the first one around byte 226M. The iterator
therefore streams with ijson while it can (small --limit runs never reach the
bad region) and, on a lexical error, falls back to one stdlib ``json.load``
(parses NaN/Infinity natively, ~10 GB RSS briefly) resuming at the first
record ijson did not yield; ijson only raises between complete items, so the
resume index is exact.

Records carry no cross-database ids (source_folder only names the POSCAR the
geometry started from), so matching is purely by fingerprint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from scripts.properties.adapters._util import jarvis_atoms_to_structure, safe_float
from scripts.properties.base import (
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
)

_METHOD = "QETB (tight-binding)"


def _method_for(row: dict) -> str:
    """Method tag carrying the cell volume per atom.

    QETB is a fitting set: one crystal appears many times as a volume scan or
    a distortion, and those records share a fingerprint. They therefore land on
    the same pool material, where a constant method string would leave dozens
    of mutually inconsistent formation energies indistinguishable. Tagging the
    volume per atom is what makes an equation-of-state point self-describing.
    """

    atoms = row.get("atoms") or {}
    try:
        from pymatgen.core import Lattice

        volume = Lattice(atoms["lattice_mat"]).volume
        n_sites = len(atoms.get("elements") or ())
        if n_sites:
            return f"{_METHOD} @ {volume / n_sites:.2f} Å³/atom"
    except Exception:  # noqa: BLE001 - fall back to the bare tag
        pass
    return _METHOD


def extract_properties(row: dict) -> list[PropertyValue]:
    """Map one raw JARVIS-QETB dict onto canonical PropertyValues."""

    method = _method_for(row)
    properties: list[PropertyValue] = []
    f_enp = safe_float(row.get("f_enp"))
    if f_enp is not None and abs(f_enp) < 20:
        properties.append(
            PropertyValue("formation_energy_per_atom", f_enp, "eV/atom", method)
        )
    gap = safe_float(row.get("indir_gap"))
    if gap is not None and gap >= 0:
        properties.append(PropertyValue("band_gap", gap, "eV", method))
    epa = safe_float(row.get("energy_per_atom"))
    if epa is not None and epa < 0:
        properties.append(
            PropertyValue("total_energy_per_atom", epa, "eV/atom", method)
        )
    return properties


class JarvisQetbAdapter(SourceAdapter):
    source_key = "jarvis-qetb"

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root or PROJECT_ROOT / "data" / "raw" / "legacy-material-data")

    @property
    def dump_path(self) -> Path:
        return self.root / "jqe_tb_folder.json"

    def _iter_rows(self, limit: int | None) -> Iterator[dict[str, Any]]:
        """Stream rows with ijson; resume via json.load past the bad tokens."""

        import ijson

        yielded = 0
        try:
            with open(self.dump_path, "rb") as handle:
                for row in ijson.items(handle, "item", use_float=True):
                    yield row
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
            return
        except ijson.common.JSONError:
            # bare NaN/Infinity in `formula` (see module docstring): fall back
            # to stdlib json and continue with the rows ijson did not deliver.
            pass

        import json

        with open(self.dump_path, "rb") as handle:
            rows = json.load(handle)
        for row in rows[yielded:]:
            yield row
            yielded += 1
            if limit is not None and yielded >= limit:
                return

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        for count, row in enumerate(self._iter_rows(limit)):
            try:
                structure = jarvis_atoms_to_structure(row["atoms"])
            except Exception:  # noqa: BLE001 - keep property-only record
                structure = None
            yield SourceRecord(
                native_id=str(row.get("jid") or f"jarvis-qetb-{count}"),
                properties=extract_properties(row),
                structure=structure,
            )
