"""odbx: OPTIMADE dumps of the odbx databases (CAMD misc + curated odbx).

Two page dumps of OPTIMADE structure documents:

* ``odbx-misc-2026-07-26`` (276 pages, 137,853 docs) — the CAMD dataset with
  ``_odbx_formation_energy`` / ``_odbx_hull_distance`` scalars (eV/atom;
  sampled magnitudes: formation energy -4.4..+4.8, mean -0.54; hull
  distance 0..6.3 — consistent with eV/atom).
* ``odbx-2026-07-26`` (56 docs) — structure-only records, no properties.

ids like ``camd-oqmd_646432`` are relaxations seeded from OQMD entries and
ids containing ``_icsd_<n>_`` are derived from ICSD parents, so both id
matches point at *related* entries while the stored structure may differ:
always_hash=True.
"""

from __future__ import annotations

import gzip
import json
import re
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_OQMD_RE = re.compile(r"^camd-oqmd_(\d+)$")
_ICSD_RE = re.compile(r"_icsd_(\d+)_")


def optimade_structure(attributes: dict):
    """Build a pymatgen Structure from OPTIMADE structure attributes."""

    from pymatgen.core import Lattice, Structure

    return Structure(
        Lattice(attributes["lattice_vectors"]),
        attributes["species_at_sites"],
        attributes["cartesian_site_positions"],
        coords_are_cartesian=True,
    )


class OdbxAdapter(SourceAdapter):
    source_key = "odbx"
    always_hash = True

    _DATASETS = ("odbx-misc-2026-07-26", "odbx-2026-07-26")

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        for dataset in self._DATASETS:
            directory = self.root / dataset
            if not directory.is_dir():
                continue
            for page in sorted(directory.glob("page-*.json.gz")):
                with gzip.open(page, "rt", encoding="utf-8") as handle:
                    docs = json.load(handle)["data"]
                for doc in docs:
                    if limit is not None and count >= limit:
                        return
                    record = self._build(doc)
                    if record is None:
                        continue
                    count += 1
                    yield record

    def _build(self, doc: dict) -> SourceRecord | None:
        native_id = str(doc.get("id") or "").strip()
        attributes = doc.get("attributes") or {}
        if not native_id:
            return None

        properties = []
        formation = safe_float(attributes.get("_odbx_formation_energy"))
        if formation is not None:
            properties.append(
                PropertyValue(
                    "formation_energy_per_atom", formation, "eV/atom",
                    "PBE (CAMD)",
                )
            )
        hull = safe_float(attributes.get("_odbx_hull_distance"))
        if hull is not None:
            properties.append(
                PropertyValue(
                    "energy_above_hull", hull, "eV/atom", "PBE (CAMD)"
                )
            )

        match_ids = []
        oqmd = _OQMD_RE.match(native_id)
        if oqmd:
            pair = normalize_match_id("oqmd", oqmd.group(1))
            if pair:
                match_ids.append(pair)
        icsd = _ICSD_RE.search(native_id)
        if icsd:
            pair = normalize_match_id("icsd", icsd.group(1))
            if pair:
                match_ids.append(pair)

        try:
            structure = optimade_structure(attributes)
        except Exception:  # noqa: BLE001 - keep the property-only record
            structure = None
        return SourceRecord(
            native_id=native_id,
            properties=properties,
            structure=structure,
            match_ids=match_ids,
        )
