"""NOVOMAG (magdb-v1): DFT magnetic properties of ferromagnet candidates.

One JSONL file of pymatgen ComputedStructureEntry records (plus one stats
line, skipped). Structures are relaxed in-house even when an MP parent is
named, hence always_hash. All values are PBE (Quantum ESPRESSO / LMTO
workflow), tagged 'PBE (NOVOMAG)'.

``data.total_energy`` is the Quantum ESPRESSO PAW total energy in rydberg,
normalised per 'cell' on 3,823 records and per 'atom' on 3; both forms are
converted to eV/atom (a PAW total energy has no physical zero, so only the
method string makes it comparable). ``data.spacegroup.number`` is spglib's
number for the relaxed cell. ``data.magnetic_anisotropy.energy`` is skipped:
it is the same anisotropy in meV/cell that ``constant`` already carries in
MJ/m³. So are the J_ij exchange tables (per-pair arrays), the kappa hardness
parameter (derived from the mapped K and Ms) and the notes/provenance block.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

METHOD = "PBE (NOVOMAG)"
RY_TO_EV = 13.605693122994


def _site_count(record: dict, structure) -> int | None:
    """Atoms in the stored cell, from the structure or the composition."""

    if structure is not None:
        return len(structure)
    composition = record.get("composition")
    if isinstance(composition, dict):
        total = 0.0
        for value in composition.values():
            amount = safe_float(value)
            if amount is None:
                return None
            total += amount
        rounded = round(total)
        if rounded > 0 and abs(total - rounded) < 1e-6:
            return rounded
    return None


def _dig(record: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(record, dict):
            return None
        record = record.get(key)
    return record


class NovomagAdapter(SourceAdapter):
    source_key = "novomag"
    always_hash = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        path = self.root / "magdb-v1.json"
        count = 0
        with open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if limit is not None and count >= limit:
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if (
                    record.get("@class") != "ComputedStructureEntry"
                    or "stats_id" in record
                ):
                    continue
                native_id = safe_text(record.get("entry_id"))
                if not native_id:
                    continue
                count += 1

                data = record.get("data") or {}
                properties: list[PropertyValue] = []

                polarization = safe_float(
                    _dig(data, "magnetic_moment", "magnetic_polarization", "value")
                )
                if polarization is not None:
                    properties.append(
                        PropertyValue(
                            "magnetic_polarization", polarization, "T", METHOD
                        )
                    )

                moment = _dig(data, "magnetic_moment", "total_magnetic_moment")
                if isinstance(moment, dict):
                    value = safe_float(moment.get("value"))
                    unit = safe_text(moment.get("unit")) or ""
                    per = safe_text(moment.get("per")) or ""
                    if (
                        value is not None
                        and unit.lower() == "bohr_magneton"
                        and per.lower() == "cell"
                    ):
                        properties.append(
                            PropertyValue(
                                "total_magnetization", value, "μB/cell", METHOD
                            )
                        )

                ordering = safe_text(
                    _dig(data, "magnetic_moment", "magnetic_ordering")
                )
                if ordering:
                    properties.append(
                        PropertyValue("magnetic_ordering", ordering, None, METHOD)
                    )

                constant = _dig(data, "magnetic_anisotropy", "constant")
                if isinstance(constant, dict):
                    best_value = None
                    best_direction = None
                    for direction, raw in constant.items():
                        if direction == "unit":
                            continue
                        value = safe_float(raw)
                        if value is None:
                            continue
                        if best_value is None or abs(value) > abs(best_value):
                            best_value = value
                            best_direction = direction
                    if best_value is not None:
                        properties.append(
                            PropertyValue(
                                "magnetic_anisotropy_constant",
                                best_value,
                                "MJ/m³",
                                f"{METHOD} {best_direction}",
                            )
                        )
                easy_axis = safe_text(_dig(data, "magnetic_anisotropy", "easy_axis"))
                if easy_axis:
                    properties.append(
                        PropertyValue("easy_axis", easy_axis, None, METHOD)
                    )

                hull = _dig(data, "formation_energy", "above_hull")
                if isinstance(hull, dict):
                    value = safe_float(hull.get("value"))
                    if value is not None:
                        unit = (safe_text(hull.get("unit")) or "").lower()
                        if unit.startswith("mev"):
                            value /= 1000.0
                        properties.append(
                            PropertyValue(
                                "energy_above_hull", value, "eV/atom", METHOD
                            )
                        )

                decomposition = _dig(data, "formation_energy", "decomposition")
                if isinstance(decomposition, dict):
                    value = safe_float(decomposition.get("value"))
                    unit = (safe_text(decomposition.get("unit")) or "").lower()
                    per = (safe_text(decomposition.get("per")) or "").lower()
                    if value is not None and per == "atom":
                        if unit.startswith("mev"):
                            value /= 1000.0
                        elif not unit.startswith("ev"):
                            value = None
                    else:
                        value = None
                    if value is not None and -100.0 < value < 100.0:
                        properties.append(
                            PropertyValue(
                                "decomposition_energy", value, "eV/atom", METHOD
                            )
                        )

                for key, name in (
                    ("Curie_temperature", "curie_temperature"),
                    ("Neel_temperature", "neel_temperature"),
                ):
                    value = safe_float(
                        _dig(data, "critical_temperature", key, "value")
                    )
                    if value is not None and 0.0 <= value < 1e5:
                        properties.append(PropertyValue(name, value, "K", METHOD))

                spacegroup = safe_float(_dig(data, "spacegroup", "number"))
                if spacegroup is not None and 1 <= spacegroup <= 230:
                    properties.append(
                        PropertyValue(
                            "spacegroup_number", int(spacegroup), None,
                            "spglib (NOVOMAG relaxed cell)",
                        )
                    )

                match_ids = []
                mp = normalize_match_id(
                    "materials-project", _dig(data, "notes", "mpid")
                )
                if mp:
                    match_ids.append(mp)

                structure = None
                raw_structure = record.get("structure")
                if isinstance(raw_structure, dict):
                    try:
                        from pymatgen.core import Structure

                        structure = Structure.from_dict(raw_structure)
                    except Exception:  # noqa: BLE001 - keep the property-only record
                        structure = None

                total_energy = _dig(data, "total_energy")
                if isinstance(total_energy, dict):
                    value = safe_float(total_energy.get("value"))
                    unit = (safe_text(total_energy.get("unit")) or "").lower()
                    per = (safe_text(total_energy.get("per")) or "").lower()
                    if value is not None and unit == "ry":
                        if per == "cell":
                            sites = _site_count(record, structure)
                            value = value / sites if sites else None
                        elif per != "atom":
                            value = None
                        if value is not None:
                            value *= RY_TO_EV
                            # QE PAW total energies have no universal zero but
                            # stay far inside these bounds per atom
                            if -1e6 < value < 0.0:
                                properties.append(
                                    PropertyValue(
                                        "total_energy_per_atom", value,
                                        "eV/atom", f"{METHOD} QE PAW",
                                    )
                                )

                yield SourceRecord(
                    native_id=native_id,
                    properties=properties,
                    structure=structure,
                    match_ids=match_ids,
                )
