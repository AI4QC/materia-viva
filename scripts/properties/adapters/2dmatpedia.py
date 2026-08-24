"""2DMatPedia: 2D materials screened/exfoliated from bulk parents (PBE).

One zip, one JSON list of 6,351 records with jarvis 'atoms' dicts. The
``source_id`` (e.g. mp-30033) names the PARENT 3D bulk the layer was
exfoliated from, not this 2D structure itself, so it must NOT become a match
id; matching is by structure fingerprint only.

``exfoliation_energy_per_atom`` ships in eV/atom (median 0.089, typical 2D
exfoliation energies are tens-to-hundreds of meV/atom) and is converted
x1000 into the canonical meV/atom. ``total_magnetization`` is per unit cell.
"""

from __future__ import annotations

import json
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import (
    jarvis_atoms_to_structure,
    safe_float,
)
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

METHOD = "PBE (2DMatPedia)"


class TwoDMatPediaAdapter(SourceAdapter):
    source_key = "2dmatpedia"

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        archive = self.root / "twodmatpd.json.zip"
        with zipfile.ZipFile(archive) as bundle:
            with bundle.open("twodmatpd.json") as handle:
                records = json.load(handle)
        for count, row in enumerate(records):
            if limit is not None and count >= limit:
                return
            properties = [PropertyValue("dimensionality", "2D", None, METHOD)]
            gap = safe_float(row.get("bandgap"))
            if gap is not None:
                properties.append(PropertyValue("band_gap", gap, "eV", METHOD))
            exfoliation = safe_float(row.get("exfoliation_energy_per_atom"))
            if exfoliation is not None:
                # source unit is eV/atom; canonical unit is meV/atom
                properties.append(
                    PropertyValue(
                        "exfoliation_energy", exfoliation * 1000.0,
                        "meV/atom", METHOD,
                    )
                )
            magnetization = safe_float(row.get("total_magnetization"))
            if magnetization is not None:
                properties.append(
                    PropertyValue(
                        "total_magnetization", magnetization, "μB",
                        f"{METHOD} per cell",
                    )
                )
            energy = safe_float(row.get("energy_per_atom"))
            if energy is not None:
                properties.append(
                    PropertyValue(
                        "total_energy_per_atom", energy, "eV/atom", METHOD
                    )
                )
            try:
                structure = jarvis_atoms_to_structure(row["atoms"])
            except Exception:  # noqa: BLE001 - keep the property-only record
                structure = None
            yield SourceRecord(
                native_id=str(row.get("material_id") or f"2dm-x{count}"),
                properties=properties,
                structure=structure,
            )
