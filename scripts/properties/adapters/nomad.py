"""NOMAD Repository and Archive: relaxed structures plus catalog scalars.

The 2026-09-05 export has four stages; three are complete and are what this
adapter reads.  ``archive/structures/`` holds one final relaxed structure per
NOMAD material (4,330,434 of them, the representative entry chosen by the export's
selection stage), and ``catalog/`` holds the scalar properties of all 19,400,649
entries.  The fourth stage, ``archive/properties/``, is still downloading and
carries only curves and tensors, so nothing here depends on it.

NOMAD aggregates uploads from AFLOW, the Materials Project, OQMD and many
individual groups, so a large share of these structures are already in the pool
under their original provenance.  That is what ``always_hash`` is for: every
record is fingerprinted, matched structurally, and only genuinely new geometries
are admitted.  No identifier match is attempted, because a NOMAD entry's
``mainfile`` names the upload it came from ("aflowlib_data/...") without carrying
the source database's own accession number.

Scalars come from ``catalog_scalars.sqlite``, built by
``scripts/properties/nomad_catalog_scalars.py``; see that file for what is and is
not mapped onto the property registry.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path
from typing import Iterator

import numpy as np

from scripts.properties.base import (
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
)

#: NOMAD stores lengths in metres
M_PER_ANGSTROM = 1e-10

#: NOMAD's ``labels`` are whatever the parser found in the input, which for VASP
#: uploads is the POTCAR tag rather than the element: ``Sr_sv``, ``Mo_pv``,
#: ``Er_3``.  The ``species`` list holds atomic numbers and is present on every
#: record checked, so it is the authoritative source and labels are only a
#: fallback.
Z_TO_SYMBOL = (None, 'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg',
    'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe',
    'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr',
    'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe',
    'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er',
    'Tm', 'Yb', 'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb',
    'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U', 'Np', 'Pu', 'Am', 'Cm',
    'Bk', 'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr', 'Rf', 'Db', 'Sg', 'Bh', 'Hs', 'Mt', 'Ds',
    'Rg', 'Cn', 'Nh', 'Fl', 'Mc', 'Lv', 'Ts', 'Og')

_SYMBOL_SET = frozenset(s for s in Z_TO_SYMBOL if s)

#: registry unit per property this adapter emits
UNITS = {
    "band_gap": "eV",
    "max_residual_force": "eV/\u00c5",
    "bulk_modulus_vrh": "GPa",
    "bulk_modulus_voigt": "GPa",
    "bulk_modulus_reuss": "GPa",
    "shear_modulus_vrh": "GPa",
    "shear_modulus_voigt": "GPa",
    "shear_modulus_reuss": "GPa",
    "volume_per_atom": "\u00c5\u00b3/atom",
    "surface_area_gravimetric": "m\u00b2/g",
}


def _symbols(atoms: dict) -> list[str] | None:
    """Element symbols for one record, from atomic numbers where possible."""
    species = atoms.get("species")
    if species:
        try:
            out = [Z_TO_SYMBOL[int(z)] for z in species]
        except (IndexError, TypeError, ValueError):
            out = None
        if out and all(out):
            return out
    labels = atoms.get("labels")
    if not labels:
        return None
    # strip a POTCAR suffix and verify what is left is a real element
    cleaned = [str(label).split("_", 1)[0].strip() for label in labels]
    if all(symbol in _SYMBOL_SET for symbol in cleaned):
        return cleaned
    return None


def cif_from_cell(labels: list[str], lattice: np.ndarray,
                  cart: np.ndarray, name: str) -> str | None:
    """A minimal P1 CIF, written directly rather than through pymatgen.

    pymatgen's CifWriter costs several milliseconds per structure, which over
    4.3 million structures is hours of wall clock for a file that is parsed
    straight back in by the hashing stage.  A cell is fully specified by its six
    parameters plus fractional coordinates, which is all a P1 CIF carries, so
    emitting those directly is exact and about a hundred times faster.  Cell
    orientation is not preserved, and does not need to be: the fingerprint
    primitive-reduces before hashing.
    """
    lengths = np.linalg.norm(lattice, axis=1)
    if not np.all(np.isfinite(lengths)) or np.any(lengths <= 1e-6):
        return None
    volume = float(abs(np.linalg.det(lattice)))
    if not np.isfinite(volume) or volume <= 1e-6:
        return None
    cosines = np.array([
        np.dot(lattice[1], lattice[2]) / (lengths[1] * lengths[2]),
        np.dot(lattice[0], lattice[2]) / (lengths[0] * lengths[2]),
        np.dot(lattice[0], lattice[1]) / (lengths[0] * lengths[1]),
    ])
    angles = np.degrees(np.arccos(np.clip(cosines, -1.0, 1.0)))
    if not np.all(np.isfinite(angles)):
        return None
    try:
        frac = cart @ np.linalg.inv(lattice)
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(frac)):
        return None
    frac = np.mod(frac, 1.0)

    out = [
        f"data_{name}",
        f"_cell_length_a {lengths[0]:.8f}",
        f"_cell_length_b {lengths[1]:.8f}",
        f"_cell_length_c {lengths[2]:.8f}",
        f"_cell_angle_alpha {angles[0]:.6f}",
        f"_cell_angle_beta {angles[1]:.6f}",
        f"_cell_angle_gamma {angles[2]:.6f}",
        "_symmetry_space_group_name_H-M 'P 1'",
        "_symmetry_Int_Tables_number 1",
        "loop_",
        " _symmetry_equiv_pos_as_xyz",
        "  'x, y, z'",
        "loop_",
        " _atom_site_type_symbol",
        " _atom_site_label",
        " _atom_site_fract_x",
        " _atom_site_fract_y",
        " _atom_site_fract_z",
        " _atom_site_occupancy",
    ]
    for i, (symbol, (fx, fy, fz)) in enumerate(zip(labels, frac)):
        out.append(f"  {symbol}  {symbol}{i}  {fx:.8f}  {fy:.8f}  {fz:.8f}  1.0")
    return "\n".join(out) + "\n"


class NomadAdapter(SourceAdapter):
    source_key = "nomad"
    always_hash = True

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(
            root or PROJECT_ROOT / "data" / "raw" / "acquired" / "nomad" / "2026-09-05"
        )
        self.scalars_db = (
            PROJECT_ROOT / "data" / "props_work" / "nomad" / "catalog_scalars.sqlite"
        )

    def _scalar_lookup(self, db, material_ids: list[str]) -> dict[str, list]:
        out: dict[str, list] = {}
        for start in range(0, len(material_ids), 400):
            chunk = material_ids[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            for material_id, prop, method, value in db.execute(
                f"SELECT material_id, prop, method, value FROM scalars "
                f"WHERE material_id IN ({placeholders})", chunk
            ):
                out.setdefault(material_id, []).append((prop, method, value))
        return out

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        pages = sorted(self.root.glob("archive/structures/page-*.json.gz"))
        if not pages:
            raise SystemExit(f"no structure pages under {self.root}")
        db = None
        if self.scalars_db.exists():
            db = sqlite3.connect(f"file:{self.scalars_db}?mode=ro", uri=True)
            db.execute("PRAGMA query_only = ON")
        emitted = 0
        seen: set[str] = set()

        for page in pages:
            with gzip.open(page, "rt", encoding="utf-8") as handle:
                rows = json.load(handle)["data"]

            staged: list[tuple[str, str]] = []
            for row in rows:
                archive = row.get("archive") or {}
                material = ((archive.get("results") or {}).get("material")) or {}
                material_id = material.get("material_id")
                if not material_id or material_id in seen:
                    continue
                # the pool holds periodic bulk crystals; surfaces, molecules and
                # low-dimensional entries are out of scope rather than failures
                if material.get("structural_type") not in (None, "bulk"):
                    continue
                try:
                    atoms = archive["run"][0]["system"][0]["atoms"]
                    lattice = np.asarray(atoms["lattice_vectors"], dtype=float)
                    cart = np.asarray(atoms["positions"], dtype=float)
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                labels = _symbols(atoms)
                if not labels or lattice.shape != (3, 3) or cart.shape[0] != len(labels):
                    continue
                periodic = atoms.get("periodic")
                if periodic is not None and not all(bool(p) for p in periodic):
                    continue
                cif = cif_from_cell(labels, lattice / M_PER_ANGSTROM,
                                    cart / M_PER_ANGSTROM, material_id)
                if cif is None:
                    continue
                seen.add(material_id)
                staged.append((material_id, cif))

            scalars = self._scalar_lookup(db, [m for m, _ in staged]) if db else {}
            for material_id, cif in staged:
                values = [
                    PropertyValue(name=prop, value=value,
                                  unit=UNITS.get(prop), method=method)
                    for prop, method, value in scalars.get(material_id, ())
                    if prop in UNITS
                ]
                yield SourceRecord(
                    native_id=material_id,
                    properties=values,
                    structure=cif,
                    experimental=False,
                )
                emitted += 1
                if limit and emitted >= limit:
                    return
