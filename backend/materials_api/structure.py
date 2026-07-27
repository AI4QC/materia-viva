"""Lazy CIF parsing for the interactive crystal viewer."""

from __future__ import annotations

import math
import warnings
from typing import Any

from ase.data import covalent_radii
from ase.data.colors import jmol_colors
from pymatgen.core import Structure


class StructureParseError(ValueError):
    pass


def parse_cif_structure(cif: str, *, max_sites: int = 1_000) -> dict[str, Any]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            structure = Structure.from_str(cif, fmt="cif")
    except Exception as exc:
        raise StructureParseError(f"CIF could not be parsed: {exc}") from exc
    if len(structure) > max_sites:
        raise StructureParseError(
            f"structure has {len(structure)} sites, exceeding the viewer limit of {max_sites}"
        )

    sites: list[dict[str, Any]] = []
    radii: list[float] = []
    for index, site in enumerate(structure):
        species, occupancy = max(site.species.items(), key=lambda item: item[1])
        element = getattr(species, "element", species)
        atomic_number = int(element.Z)
        radius = float(covalent_radii[atomic_number])
        radii.append(radius)
        sites.append({
            "index": index,
            "element": element.symbol,
            "species": str(species),
            "occupancy": float(occupancy),
            "atomic_number": atomic_number,
            "fractional": [float(value) for value in site.frac_coords],
            "cartesian": [float(value) for value in site.coords],
            "color": [float(value) for value in jmol_colors[atomic_number]],
            "radius": radius,
        })

    bonds: list[dict[str, Any]] = []
    for first in range(len(structure)):
        for second in range(first + 1, len(structure)):
            # The browser draws one explicit unit cell. A minimum-image bond
            # would connect two distant on-screen atoms across the whole cell;
            # reserve periodic bonds for OVITO, which renders their images.
            distance = math.dist(structure[first].coords, structure[second].coords)
            cutoff = 1.2 * (radii[first] + radii[second])
            if 0.1 < distance <= cutoff:
                bonds.append({"from": first, "to": second, "distance": distance})

    lattice = structure.lattice
    return {
        "formula": structure.composition.reduced_formula,
        "site_count": len(structure),
        "lattice": {
            "matrix": [[float(value) for value in vector] for vector in lattice.matrix],
            "a": float(lattice.a),
            "b": float(lattice.b),
            "c": float(lattice.c),
            "alpha": float(lattice.alpha),
            "beta": float(lattice.beta),
            "gamma": float(lattice.gamma),
            "volume": float(lattice.volume),
        },
        "sites": sites,
        "bonds": bonds,
    }
