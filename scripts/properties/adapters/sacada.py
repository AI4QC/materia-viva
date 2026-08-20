"""SACADA: Samara Carbon Allotrope Database.

1,661 hypothetical/known carbon allotropes: one metadata JSON (string-valued
fields) plus one zip per structure whose relaxed CIF is the member NOT ending
in '_IN.cif'. 17 ids ship no archive and are yielded property-only with
structure=None. All numeric properties are DFT values from the SACADA
pipeline; 'energy' is the energy relative to diamond in eV/atom. The
'topology' field is the ToposPro net symbol and is stored as the structure
prototype. 'space_group' is a Hermann-Mauguin symbol without a number, so it
goes through the shared symbol->number lookup, which resolves all 225 distinct
symbols in the file (the alternate settings I2/m, P21/c, An, ... and the
bar-less cubic spellings Fd3m, Ia3d, ... included). 'pearson' is the Pearson
symbol. 'e_gap' is empty on every one of the 1,661 rows; cn / cn_sort /
transitivity / sp_atoms describe the ToposPro net rather than the material and
stay out.
"""

from __future__ import annotations

import json
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import (
    safe_float,
    safe_text,
    spacegroup_number_from_symbol,
)
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_METHOD = "DFT (SACADA)"


class SacadaAdapter(SourceAdapter):
    source_key = "sacada"

    def _read_cif(self, native_id: str) -> str | None:
        try:
            archive = self.root / "structures" / f"{int(native_id):06d}.zip"
        except ValueError:
            return None
        if not archive.exists():
            return None
        try:
            with zipfile.ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    if name.endswith(".cif") and not name.endswith("_IN.cif"):
                        return bundle.read(name).decode("utf-8", errors="replace")
        except (OSError, zipfile.BadZipFile):
            return None
        return None

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        with open(self.root / "sacada-metadata.json", encoding="utf-8") as handle:
            rows = json.load(handle)["data"]
        for count, row in enumerate(rows):
            if limit is not None and count >= limit:
                return
            native_id = safe_text(row.get("id"))
            if not native_id:
                continue
            properties = []
            for name, key, unit in (
                ("density", "density", "g/cm³"),
                ("bulk_modulus_vrh", "bulk_mod", "GPa"),
                ("hardness_vickers", "vicker_hard", "GPa"),
                ("relative_energy_to_diamond", "energy", "eV/atom"),
            ):
                value = safe_float(row.get(key))
                if value is not None:
                    properties.append(PropertyValue(name, value, unit, _METHOD))
            topology = safe_text(row.get("topology"))
            if topology:
                properties.append(
                    PropertyValue("structure_prototype", topology, None, "ToposPro")
                )
            pearson = safe_text(row.get("pearson"))
            if pearson:
                properties.append(
                    PropertyValue("pearson_symbol", pearson, None, _METHOD)
                )
            spacegroup = spacegroup_number_from_symbol(row.get("space_group"))
            if spacegroup is not None:
                properties.append(
                    PropertyValue(
                        "spacegroup_number", spacegroup, None,
                        "SACADA symmetry symbol",
                    )
                )
            yield SourceRecord(
                native_id=native_id,
                properties=properties,
                structure=self._read_cif(native_id),
            )
