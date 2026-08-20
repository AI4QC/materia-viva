"""hMOF: hypothetical MOFs with GCMC CO2 adsorption and Zeo++ geometry.

One zip holding one JSON array of 137,652 dicts (JARVIS packaging of the
Wilmer/Snurr hypothetical-MOF database, 2021-09-18 snapshot). The array is
streamed with ijson so ``--limit`` never decompresses the whole 388 MB
archive. Structures are jarvis-tools Atoms dicts; the per-pressure CO2
isotherm arrays (``co2_pressures`` / ``co2_absp``) are deliberately not
ingested (no arrays in the property store) — only the two scalar isotherm
endpoints ``max_co2_adsp`` / ``min_co2_adsp`` are kept, in mol/kg per the
JARVIS hMOF documentation.

The pressure grid was checked over all 137,652 records and is the single
constant list (0.01, 0.05, 0.1, 0.5, 2.5) bar, five points every time, so the
two endpoints are the 2.5 bar and 0.01 bar uptakes. The low-pressure point is
the Henry-regime value and is *not* redundant with the high-pressure one
(median 0.033 vs 4.58 mol/kg). The 'max over pressures' method string of the
already-loaded rows is left exactly as it was; the new row names its pressure.

No cross-database ids exist, so matching is purely by structure hash — and
that fingerprint is ambiguous here: 46,891 of the records share a BAWL hash
with an earlier one while being different hypothetical frameworks. See
scripts/properties/hmof_composite_admit.py, which re-admits them under a
composite (hash, volume-per-site) key.
"""

from __future__ import annotations

import zipfile
from typing import Iterator

from scripts.properties.adapters._util import jarvis_atoms_to_structure, safe_float
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_ARCHIVE = "hmof_db_9_18_2021.json.zip"
_MEMBER = "hmof_db_9_18_2021.json"

# native key -> (canonical name, unit, method)
_FIELDS = (
    ("lcd", "largest_cavity_diameter", "Å", "zeo++"),
    ("pld", "pore_limiting_diameter", "Å", "zeo++"),
    ("void_fraction", "void_fraction", None, "zeo++"),
    ("surface_area_m2g", "surface_area_gravimetric", "m²/g", "zeo++"),
    ("surface_area_m2cm3", "surface_area_volumetric", "m²/cm³", "zeo++"),
    ("max_co2_adsp", "co2_uptake", "mol/kg", "GCMC (hMOF) max over pressures"),
    ("min_co2_adsp", "co2_uptake", "mol/kg", "GCMC (hMOF) 0.01 bar"),
)

#: sanity ceiling for the uptake columns. Checked over the whole archive:
#: max_co2_adsp tops out at 43.8 and min_co2_adsp at 13.6 mol/kg, so this is
#: a pure guard and drops nothing that the loaded rows already contain.
_CO2_UPTAKE_MAX = 1000.0


class HmofAdapter(SourceAdapter):
    source_key = "hmof"
    always_hash = False

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        import ijson

        with zipfile.ZipFile(self.root / _ARCHIVE) as bundle:
            with bundle.open(_MEMBER) as handle:
                for count, row in enumerate(
                    ijson.items(handle, "item", use_float=True)
                ):
                    if limit is not None and count >= limit:
                        return
                    properties = []
                    for key, name, unit, method in _FIELDS:
                        value = safe_float(row.get(key))
                        # geometry/adsorption values below zero are sentinels
                        if value is None or value < 0:
                            continue
                        if name == "co2_uptake" and value > _CO2_UPTAKE_MAX:
                            continue
                        properties.append(PropertyValue(name, value, unit, method))
                    try:
                        structure = jarvis_atoms_to_structure(row["atoms"])
                    except Exception:  # noqa: BLE001 - keep properties
                        structure = None
                    yield SourceRecord(
                        native_id=str(row.get("id") or f"hmof-row-{count}"),
                        properties=properties,
                        structure=structure,
                    )
