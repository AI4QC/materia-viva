"""AFLOW: 2.98M PBE relaxations harvested page-wise through the AFLUX API.

299 gzipped page files, each one JSON object whose keys are '<n> of 2981853'
-> record. Structures are rebuilt from geometry [a, b, c, alpha, beta, gamma]
+ positions_fractional, with sites grouped by species in the order of the
element counts parsed from 'compound' (validated: pymatgen spacegroups at
symprec=0.1 agree with spacegroup_relax on 24/25 diverse records plus 15/15
ICSD_WEB records; the single outlier is pseudo-symmetric and agrees at
symprec=0.01). Only ~2% of records carry an ICSD parent id (from the
'_ICSD_<code>' token in aurl), hence always_hash so the rest can join or
match the pool by fingerprint.
"""

from __future__ import annotations

import gzip
import json
import re
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_COMPOUND_TOKEN = re.compile(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)")
_ICSD_TOKEN = re.compile(r"_ICSD_(\d+)")

METHOD = "PBE (AFLOW)"

#: AFLOW catalogs use different calculation settings, and several auids can
#: relax to one crystal from different prototype decorations. Naming the
#: catalog in the method keeps those rows distinguishable instead of
#: collapsing them into indistinguishable repeats — it matters most for
#: ICSD_WEB, whose energies differ from the LIB catalogs by up to 3.7 eV/atom
#: on the same structure.
_CATALOGS = ("ICSD_WEB", "LIB1_WEB", "LIB2_WEB", "LIB3_WEB", "LIB4_WEB",
             "LIB5_WEB", "LIB6_WEB")


def _method_for(aurl: str) -> str:
    for catalog in _CATALOGS:
        if catalog in aurl:
            return f"PBE (AFLOW {catalog.replace('_WEB', '')})"
    return METHOD

#: native field -> (canonical name, unit)
_NUMERIC_FIELDS = (
    ("enthalpy_formation_atom", "formation_energy_per_atom", "eV/atom"),
    ("Egap", "band_gap", "eV"),
    ("energy_atom", "total_energy_per_atom", "eV/atom"),
    ("density", "density", "g/cm³"),
    ("volume_atom", "volume_per_atom", "Å³/atom"),
)


class AflowAdapter(SourceAdapter):
    source_key = "aflow"
    always_hash = True

    def _build_structure(self, rec: dict):
        """Structure from geometry + fractional positions + grouped species.

        Sites follow the element counts parsed from 'compound'; returns None
        (property-only record) when the convention does not hold for a record.
        """

        geometry = rec.get("geometry")
        positions = rec.get("positions_fractional")
        compound = rec.get("compound")
        species_order = rec.get("species")
        if not geometry or not positions or not compound or len(geometry) != 6:
            return None
        tokens = _COMPOUND_TOKEN.findall(compound)
        if not tokens or [element for element, _ in tokens] != species_order:
            return None
        site_species: list[str] = []
        for element, count_text in tokens:
            count = float(count_text)
            if abs(count - round(count)) > 1e-9:  # partial occupancy: skip
                return None
            site_species.extend([element] * int(round(count)))
        natoms = rec.get("natoms")
        if len(site_species) != len(positions):
            return None
        if natoms is not None and len(site_species) != natoms:
            return None
        from pymatgen.core import Lattice, Structure

        a, b, c, alpha, beta, gamma = geometry
        try:
            return Structure(
                Lattice.from_parameters(a, b, c, alpha, beta, gamma),
                site_species,
                positions,
            )
        except Exception:  # noqa: BLE001 - keep the property-only record
            return None

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        pages = sorted((self.root / "aflux-2026-07-26").glob("page-*.json.gz"))
        count = 0
        for page in pages:
            if limit is not None and count >= limit:
                return
            with gzip.open(page, "rt", encoding="utf-8") as handle:
                data = json.load(handle)
            for rec in data.values():
                if limit is not None and count >= limit:
                    return
                auid = safe_text(rec.get("auid"))
                if auid is None:
                    continue
                count += 1

                aurl = rec.get("aurl") or ""
                method = _method_for(aurl)

                properties = []
                for field, name, unit in _NUMERIC_FIELDS:
                    value = safe_float(rec.get(field))
                    if value is not None:
                        properties.append(PropertyValue(name, value, unit, method))
                spacegroup = safe_float(rec.get("spacegroup_relax"))
                if spacegroup is not None and spacegroup > 0:
                    properties.append(
                        PropertyValue(
                            "spacegroup_number", int(spacegroup), None, method
                        )
                    )
                prototype = safe_text(rec.get("prototype"))
                if prototype:
                    properties.append(
                        PropertyValue(
                            "structure_prototype", prototype, None, method
                        )
                    )

                match_ids = []
                if "ICSD_WEB" in aurl:
                    token = _ICSD_TOKEN.search(aurl)
                    if token:
                        icsd = normalize_match_id("icsd", token.group(1))
                        if icsd:
                            match_ids.append(icsd)

                yield SourceRecord(
                    native_id=auid,
                    properties=properties,
                    structure=self._build_structure(rec),
                    match_ids=match_ids,
                )
