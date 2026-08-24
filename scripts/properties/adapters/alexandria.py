"""Alexandria: PBE/PBEsol/SCAN periodic DFT database (3D/2D/1D subsets).

Raw layout under data/raw/acquired/alexandria/:

* pbe-3d-2025.07.02/  alexandria_000*.json.bz2   PBE, 3D (58 shards x 100k)
* pbe-2d/             alexandria_2d_*.json.bz2   PBE, 2D (agm2* ids)
* pbe-1d/             alexandria_1d_*.json.bz2   PBE, 1D (agm1* ids)
* pbesol-3d/          alexandria_ps_*.json.bz2   PBEsol re-runs of agm0* ids
* scan-3d/            alexandria_scan_*.json.bz2 SCAN re-runs of agm0* ids

convex_hull*.json.bz2 files are duplicate subsets and are skipped.

Each shard is one JSON object {"entries": [...]}; entries are streamed with an
incremental JSONDecoder so honoring ``limit`` never decompresses a whole shard.

native_id is the bare mat_id for the PBE sets (3d/2d/1d ids are disjoint:
agm0*/agm2*/agm1*); the PBEsol and SCAN re-runs of the same agm ids get a
``:pbesol`` / ``:scan`` suffix so their property rows stay distinct. All
records carry an ('alexandria', mat_id) match id: the agm id *is* the pool
structure, so the default always_hash=False skips hashing on a hit.

Verified on samples: data.energy_total is the total energy of the *cell*
(e.g. SrRh2Cd10, 13 sites, energy_total=-27.53 eV ~= sum of elemental
references + 13*e_form), so total_energy_per_atom = energy_total / nsites.
Note the SCAN set uses different pseudopotential references (~-90 eV/atom is
normal there); totals are not comparable across functionals, which the method
tag preserves. data.total_mag is per cell, not per formula unit, hence the
μB/cell unit and the 'per cell' note in the method string.
"""

from __future__ import annotations

import bz2
import json
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

#: (subdir, shard prefix, method, native_id suffix, dimensionality)
_SUBSETS: tuple[tuple[str, str, str, str | None, str | None], ...] = (
    ("pbe-3d-2025.07.02", "alexandria_", "PBE", None, None),
    ("pbe-2d", "alexandria_2d_", "PBE", None, "2D"),
    ("pbe-1d", "alexandria_1d_", "PBE", None, "1D"),
    ("pbesol-3d", "alexandria_ps_", "PBEsol", "pbesol", None),
    ("scan-3d", "alexandria_scan_", "SCAN", "scan", None),
)

_CHUNK = 1 << 20  # 1 MiB of decompressed text per read


def _iter_shard_entries(path) -> Iterator[dict]:
    """Stream the objects of the shard's top-level "entries" array."""

    decoder = json.JSONDecoder()
    with bz2.open(path, "rt", encoding="utf-8") as handle:
        buffer = ""
        # Find the start of the entries array without parsing the whole file.
        while True:
            key = buffer.find('"entries"')
            if key >= 0:
                start = buffer.find("[", key)
                if start >= 0:
                    buffer = buffer[start + 1 :]
                    break
            chunk = handle.read(_CHUNK)
            if not chunk:
                return
            buffer += chunk
        while True:
            buffer = buffer.lstrip(" \t\r\n,")
            if buffer.startswith("]"):
                return
            try:
                entry, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    return
                buffer += chunk
                continue
            buffer = buffer[end:]
            yield entry


def _to_structure(struct_dict: dict):
    """pymatgen Structure from an entry's structure dict.

    Per-site properties (magmom/charge/forces arrays) are dropped up front:
    they are not ingested and slow from_dict down considerably.
    """

    from pymatgen.core import Structure

    for site in struct_dict.get("sites", ()):
        site.pop("properties", None)
    try:
        return Structure.from_dict(struct_dict)
    except Exception:  # noqa: BLE001 - keep the property-only record
        return None


class AlexandriaAdapter(SourceAdapter):
    source_key = "alexandria"
    # defaults kept explicit: an agm id match IS the pool structure, and
    # unmatched records (2d/1d/newer 3d) may enter the pool as new structures.
    always_hash = False
    properties_only = False

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        for subdir, prefix, method, suffix, dimensionality in _SUBSETS:
            directory = self.root / subdir
            if not directory.is_dir():
                continue
            shards = sorted(
                path
                for path in directory.iterdir()
                if path.name.startswith(prefix)
                and path.name.endswith(".json.bz2")
                and not path.name.startswith("convex_hull")
            )
            for shard in shards:
                for entry in _iter_shard_entries(shard):
                    if limit is not None and count >= limit:
                        return
                    record = self._build_record(
                        entry, method, suffix, dimensionality
                    )
                    if record is None:
                        continue
                    count += 1
                    yield record

    def _build_record(
        self,
        entry: dict,
        method: str,
        suffix: str | None,
        dimensionality: str | None,
    ) -> SourceRecord | None:
        data = entry.get("data") or {}
        mat_id = str(data.get("mat_id") or "").strip()
        if not mat_id:
            return None

        properties: list[PropertyValue] = []
        for name, key, unit in (
            ("formation_energy_per_atom", "e_form", "eV/atom"),
            ("energy_above_hull", "e_above_hull", "eV/atom"),
            ("band_gap", "band_gap_ind", "eV"),
            ("band_gap_direct", "band_gap_dir", "eV"),
        ):
            value = safe_float(data.get(key))
            if value is not None:
                properties.append(PropertyValue(name, value, unit, method))

        total_mag = safe_float(data.get("total_mag"))
        if total_mag is not None:
            properties.append(
                PropertyValue(
                    "total_magnetization", total_mag, "μB",
                    f"{method} per cell",
                )
            )

        energy_total = safe_float(data.get("energy_total"))
        nsites = safe_float(data.get("nsites"))
        if energy_total is not None and nsites:
            properties.append(
                PropertyValue(
                    "total_energy_per_atom", energy_total / nsites,
                    "eV/atom", method,
                )
            )

        spacegroup = safe_float(data.get("spg"))
        if spacegroup:
            properties.append(
                PropertyValue("spacegroup_number", int(spacegroup), None, method)
            )

        if dimensionality:
            properties.append(
                PropertyValue("dimensionality", dimensionality, None, method)
            )

        match_ids = []
        pair = normalize_match_id("alexandria", mat_id)
        if pair:
            match_ids.append(pair)

        struct_dict = entry.get("structure")
        structure = _to_structure(struct_dict) if struct_dict else None

        return SourceRecord(
            native_id=f"{mat_id}:{suffix}" if suffix else mat_id,
            properties=properties,
            structure=structure,
            match_ids=match_ids,
        )
