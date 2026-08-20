"""Shared helpers for source adapters."""

from __future__ import annotations

import math
import re
import warnings
from typing import Any


def safe_float(value: Any) -> float | None:
    """Parse numbers while treating na/None/'' sentinels as missing."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip()
    if not text or text.lower() in {"na", "none", "null", "nan", "?", "-", "."}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"na", "none", "null", "nan"}:
        return None
    return text


#: Hermann-Mauguin symbols pymatgen's tables do not carry, mapped to the
#: number of the standard-setting group they are an alternate setting of.
#: Monoclinic I/A cells are the C-centred groups in another cell choice; the
#: glide-only names are Cc/Pc variants; Cmca is the old name of Cmce.
_SPACEGROUP_SETTING_ALIASES = {
    "Im": 8, "I2": 5, "I2/m": 12, "I2/a": 15, "I2/c": 15,
    "Ia": 9, "Ic": 9, "An": 9, "A2/n": 15,
    "Pn": 7, "P2/n": 13, "P2/m1": 10,
    "P21": 4, "P21/m": 11, "P21/c": 14, "P21/n": 14,
    "Cmca": 64,
}

#: bar-less cubic symbols (Pm3m for Pm-3m) are written that way by several
#: legacy sources; the 3 of a cubic short symbol is always a -3
_BARLESS_CUBIC = re.compile(r"^([PIFABC])([mnad])3")


def spacegroup_number_from_symbol(symbol: Any) -> int | None:
    """Hermann-Mauguin symbol -> space-group number, or None if unreadable.

    Handles the two spellings legacy sources use in place of pymatgen's:
    cubic symbols with the overline dropped (``Pm3m``) and non-standard cell
    choices / screw-axis spellings listed in ``_SPACEGROUP_SETTING_ALIASES``.
    """

    from pymatgen.symmetry.groups import SpaceGroup

    text = safe_text(symbol)
    if not text:
        return None
    text = text.replace(" ", "")
    alias = _SPACEGROUP_SETTING_ALIASES.get(text)
    if alias is not None:
        return alias
    candidates = [text]
    barless = _BARLESS_CUBIC.sub(r"\1\2-3", text)
    if barless != text:
        candidates.append(barless)
    for candidate in candidates:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                number = SpaceGroup(candidate).int_number
        except Exception:  # noqa: BLE001 - unknown symbol, try the next form
            continue
        if 1 <= number <= 230:
            return number
    return None


def jarvis_atoms_to_structure(atoms: dict):
    """Convert a jarvis-tools Atoms dict into a pymatgen Structure."""

    from pymatgen.core import Lattice, Structure

    return Structure(
        Lattice(atoms["lattice_mat"]),
        atoms["elements"],
        atoms["coords"],
        coords_are_cartesian=bool(atoms.get("cartesian", False)),
    )


def fast_cif(structure) -> str:
    """P1 CIF text ~50x faster than pymatgen's CifWriter.

    Only for ordered pymatgen Structures; matches the explicit-site style the
    pool already stores, and round-trips through Structure.from_str(fmt='cif').
    """

    lattice = structure.lattice
    composition = structure.composition
    lines = [
        "# generated using pymatgen",
        f"data_{composition.reduced_formula}",
        "_symmetry_space_group_name_H-M   'P 1'",
        f"_cell_length_a   {lattice.a:.8f}",
        f"_cell_length_b   {lattice.b:.8f}",
        f"_cell_length_c   {lattice.c:.8f}",
        f"_cell_angle_alpha   {lattice.alpha:.8f}",
        f"_cell_angle_beta   {lattice.beta:.8f}",
        f"_cell_angle_gamma   {lattice.gamma:.8f}",
        "_symmetry_Int_Tables_number   1",
        f"_chemical_formula_structural   {composition.reduced_formula}",
        f"_chemical_formula_sum   '{composition.formula}'",
        f"_cell_volume   {lattice.volume:.8f}",
        f"_cell_formula_units_Z   {int(composition.get_reduced_composition_and_factor()[1])}",
        "loop_",
        " _symmetry_equiv_pos_site_id",
        " _symmetry_equiv_pos_as_xyz",
        "  1  'x, y, z'",
        "loop_",
        " _atom_site_type_symbol",
        " _atom_site_label",
        " _atom_site_symmetry_multiplicity",
        " _atom_site_fract_x",
        " _atom_site_fract_y",
        " _atom_site_fract_z",
        " _atom_site_occupancy",
    ]
    for index, site in enumerate(structure):
        symbol = site.specie.symbol
        a, b, c = site.frac_coords
        lines.append(
            f"  {symbol}  {symbol}{index}  1  {a:.8f}  {b:.8f}  {c:.8f}  1"
        )
    return "\n".join(lines) + "\n"
