"""EC-MOF Phase-I: PBE properties of electrically conductive MOFs.

1,071 structure/property pairs scraped from ec-mof.njit.edu:
``structures/<name>.cif`` (passed through verbatim) plus
``properties/<name>.html`` holding one fixed 15-cell table row
(name, Volume, Density, AV_Void Fraction, GSA, VSA, LCD,
POAV_Void Fraction, E_f, E_b, Band_Gap, DBC_Up, DBC_Down, Metal, Linker).

Names come as ``<MOF>_Bulk`` / ``<MOF>_Mono``; monolayer records get
``dimensionality='2D'`` and leave the geometry cells empty on the site.

Units, as printed in the table header: E_f is eV/atom (so the canonical
``formation_energy_per_atom`` applies), E_b is an interlayer binding energy
in meV/Å² (new property ``interlayer_binding_energy``), Band_Gap in eV
(small negative band overlaps of metallic frameworks are clamped to 0.0),
GSA in m²/g, VSA in m²/cm³, LCD in Å, Density in g/cm³, DBC_Up/DBC_Down in
eV. The table carries two Zeo++ void fractions computed with different probe
conventions - AV (accessible volume) in cell 3 and POAV (probe-occupiable
accessible volume) in cell 7, genuinely different numbers (0.038 vs 0.161 on
CoHAT_Bulk) - so the POAV column is staged under its own method string.
DBC_Up/DBC_Down are the spin-up/spin-down d-band centres relative to E_F and
are staged as ``d_band_center`` with the spin channel in the method. The
Metal/Linker labels and the Volume cell (structure-derived) are not ingested.

No cross-database ids; every record is fingerprinted (always_hash).
"""

from __future__ import annotations

import re
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_TD = re.compile(r"<td>(.*?)</td>", re.S)
_METHOD = "PBE (EC-MOF)"

# cell index in the 15-cell row -> (name, unit); indices 0/13/14 are labels
_CELLS = (
    (2, "density", "g/cm³"),
    (3, "void_fraction", None),
    (4, "surface_area_gravimetric", "m²/g"),
    (5, "surface_area_volumetric", "m²/cm³"),
    (6, "largest_cavity_diameter", "Å"),
    (8, "formation_energy_per_atom", "eV/atom"),
    (9, "interlayer_binding_energy", "meV/Å²"),
)


class EcMofAdapter(SourceAdapter):
    source_key = "ec-mof"
    always_hash = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        cif_paths = sorted((self.root / "structures").glob("*.cif"))
        for count, cif_path in enumerate(cif_paths):
            if limit is not None and count >= limit:
                return
            name = cif_path.stem
            properties = []
            html_path = self.root / "properties" / f"{name}.html"
            cells: list[str] = []
            if html_path.is_file():
                cells = _TD.findall(html_path.read_text(encoding="utf-8"))
            if len(cells) == 15 and cells[0].strip() == name:
                for index, prop, unit in _CELLS:
                    value = safe_float(cells[index])
                    if value is not None:
                        properties.append(
                            PropertyValue(prop, value, unit, _METHOD)
                        )
                poav = safe_float(cells[7])
                if poav is not None and 0.0 <= poav <= 1.0:
                    properties.append(
                        PropertyValue(
                            "void_fraction", poav, None, f"{_METHOD} POAV"
                        )
                    )
                for index, spin in ((11, "spin-up"), (12, "spin-down")):
                    centre = safe_float(cells[index])
                    if centre is not None and -50.0 < centre < 50.0:
                        properties.append(
                            PropertyValue(
                                "d_band_center", centre, "eV",
                                f"{_METHOD} {spin}",
                            )
                        )
                gap = safe_float(cells[10])
                if gap is not None:
                    # negative values are metallic band overlaps
                    properties.append(
                        PropertyValue("band_gap", max(gap, 0.0), "eV", _METHOD)
                    )
            if name.endswith("_Mono"):
                properties.append(
                    PropertyValue("dimensionality", "2D", None, _METHOD)
                )
            yield SourceRecord(
                native_id=name,
                properties=properties,
                structure=cif_path.read_text(encoding="utf-8"),
            )
