"""FAIR-MOFs: solvent-removed experimental CSD MOF structures with zeo++
porosity, RCSR topology and DFT framework bond-dissociation energies.

Only the experimental set FAIR-MOFs_exp.zip is ingested (45,7xx members named
``<REFCODE>_fair.cif``); CIF text passes through verbatim and every record is
experimental. CSD refcodes are not in the matching pool, so no match_ids are
emitted and matching relies on hashing (always_hash).

Property joins by refcode:

* ``porosity_of_unoptimised_mof.json`` (37,452 entries keyed ``<REFCODE>_fair``)
  and ``porosity_data_of_optimised_mof.json`` (21,993 entries, 21,026 of which
  reach an ingested refcode) — the same six Zeo++ scalars run twice, once on
  the published solvent-removed cell and once on its DFT-optimised geometry.
  Both are ingested, told apart by method "zeo++ (unoptimised)" versus
  "zeo++ (DFT-optimised)"; the optimised run opens the pores up noticeably
  (median void fraction 0.012 against 0.000, median LCD 5.55 Å against
  3.67 Å), so the two sets are genuinely different measurements of one
  framework rather than duplicates.

  Of the eight keys per entry, ``ASA_A^2`` and ``AV_A^3`` are left out: both
  are absolute per-cell quantities, and the cell volume they would have to be
  divided by is already ~100% covered pool-wide as a structure-derived column,
  with ``AV_A^3`` additionally redundant with the ingested
  ``AV_Volume_fraction``. Neither file carries a gravimetric surface area, so
  the volumetric ``ASA_m^2/cm^3`` is the only surface area available.
  ``lfpd_A`` is Zeo++'s Dif, the largest sphere that can travel through the
  channels; it satisfies PLD <= lfpd <= LCD on all but 4 of the 37,452
  unoptimised entries, confirming the label.
* ``Topology.csv`` (keyed bare refcode) — RCSR topology code; the sentinels
  UNKNOWN / ERROR / NA / MISMATCH (and CSV-quoting debris) are skipped.
* ``mof_formation_energy_ligand.json`` / ``_sbu.json`` (keyed bare refcode) —
  ``bde_n_atoms`` (verified equal to ``bde``/``n_atom`` on every entry) is
  stored as the new property ``framework_bond_dissociation_energy`` in
  eV/atom. The two files are bit-identical on every shared refcode (the sbu
  file is a subset of the ligand file), so the ligand value is stored for all
  entries under method "DFT ligand-based" and an sbu-based row is only added
  when the sbu value actually differs. The distribution has a sane core
  (median -0.36 eV/atom) plus a broken tail reaching +/-2e5 eV/atom; values
  with |bde/atom| > 20 eV are dropped (~5% of entries).
"""

from __future__ import annotations

import csv
import json
import re
import sys
import zipfile
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

#: sanity window for bde per atom (eV/atom); outside is corrupted data
_BDE_MAX_ABS = 20.0

_TOPO_SENTINELS = {"UNKNOWN", "ERROR", "NA", "MISMATCH"}
_TOPO_OK = re.compile(r"^[A-Za-z0-9*\-]{1,20}$")

#: json key -> (canonical name, unit, plausibility window). The windows admit
#: every value in the unoptimised file that the adapter already staged (its
#: observed spans are 0-3643 m²/cm³, 0-0.953, 0-71.6 Å and 0-71.5 Å), so the
#: four fields ingested before this audit stage exactly as they did.
_POROSITY_FIELDS = (
    ("ASA_m^2/cm^3", "surface_area_volumetric", "m²/cm³", (0.0, 1.0e4)),
    ("AV_Volume_fraction", "void_fraction", None, (0.0, 1.0)),
    ("LCD_A", "largest_cavity_diameter", "Å", (0.0, 500.0)),
    ("PLD_A", "pore_limiting_diameter", "Å", (0.0, 500.0)),
    ("lfpd_A", "largest_free_path_diameter", "Å", (0.0, 500.0)),
    ("Number_of_channels", "pore_channel_count", None, (0.0, 1000.0)),
)

#: porosity file -> method string
_POROSITY_FILES = (
    ("porosity_of_unoptimised_mof.json", "zeo++ (unoptimised)"),
    ("porosity_data_of_optimised_mof.json", "zeo++ (DFT-optimised)"),
)


class FairMofsAdapter(SourceAdapter):
    source_key = "fair-mofs"
    always_hash = True
    properties_only = False

    def _load_json(self, name: str) -> dict:
        path = self.root / name
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _load_topology(self) -> dict[str, str]:
        topology: dict[str, str] = {}
        with (self.root / "Topology.csv").open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                refcode = safe_text((row.get("Refcode") or "").strip().strip('"'))
                raw = (row.get("Topology") or "").strip().strip('"')
                if not refcode or not raw:
                    continue
                # Interpenetrated frameworks list one code per component
                # ("fes,UNKNOWN"); keep the resolvable, deduplicated parts.
                parts: list[str] = []
                for part in raw.split(","):
                    part = part.strip().strip('"')
                    if not part or part.upper() in _TOPO_SENTINELS:
                        continue
                    if not _TOPO_OK.match(part):
                        continue
                    if part not in parts:
                        parts.append(part)
                if parts:
                    topology[refcode] = ",".join(parts)
        return topology

    @staticmethod
    def _bde_per_atom(entry: dict | None) -> float | None:
        if not entry:
            return None
        value = safe_float(entry.get("bde_n_atoms"))
        if value is None or abs(value) > _BDE_MAX_ABS:
            return None
        return value

    def _porosity_properties(
        self, pore: dict | None, method: str
    ) -> list[PropertyValue]:
        if not pore:
            return []
        properties = []
        for key, name, unit, (low, high) in _POROSITY_FIELDS:
            value = safe_float(pore.get(key))
            if value is None:
                continue
            if not low <= value <= high:
                self.drops[f"{key}:{method}"] += 1
                continue
            properties.append(PropertyValue(name, value, unit, method))
        return properties

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        self.drops: Counter[str] = Counter()
        try:
            yield from self._iter_records(limit)
        finally:
            if self.drops:
                print(
                    f"[fair-mofs] out-of-range values dropped: {dict(self.drops)}",
                    file=sys.stderr,
                    flush=True,
                )

    def _iter_records(self, limit: int | None) -> Iterator[SourceRecord]:
        porosity = [
            (self._load_json(filename), method)
            for filename, method in _POROSITY_FILES
        ]
        bde_ligand = self._load_json("mof_formation_energy_ligand.json")
        bde_sbu = self._load_json("mof_formation_energy_sbu.json")
        topology = self._load_topology()

        count = 0
        seen: set[str] = set()
        with zipfile.ZipFile(self.root / "FAIR-MOFs_exp.zip") as bundle:
            for member in bundle.namelist():
                if limit is not None and count >= limit:
                    return
                filename = member.rsplit("/", 1)[-1]
                if not filename.endswith("_fair.cif"):
                    continue
                refcode = filename[: -len("_fair.cif")]
                if not refcode or refcode in seen:
                    continue
                seen.add(refcode)

                properties: list[PropertyValue] = []
                for table, method in porosity:
                    properties.extend(
                        self._porosity_properties(table.get(f"{refcode}_fair"), method)
                    )
                topo = topology.get(refcode)
                if topo:
                    properties.append(
                        PropertyValue("structure_prototype", topo, None, "RCSR topology")
                    )
                ligand = self._bde_per_atom(bde_ligand.get(refcode))
                sbu = self._bde_per_atom(bde_sbu.get(refcode))
                if ligand is not None:
                    properties.append(
                        PropertyValue(
                            "framework_bond_dissociation_energy",
                            ligand,
                            "eV/atom",
                            "DFT ligand-based",
                        )
                    )
                if sbu is not None and sbu != ligand:
                    properties.append(
                        PropertyValue(
                            "framework_bond_dissociation_energy",
                            sbu,
                            "eV/atom",
                            "DFT sbu-based",
                        )
                    )

                cif_text = bundle.read(member).decode("utf-8", errors="replace")
                count += 1
                yield SourceRecord(
                    native_id=refcode,
                    properties=properties,
                    structure=cif_text,
                    experimental=True,
                )
