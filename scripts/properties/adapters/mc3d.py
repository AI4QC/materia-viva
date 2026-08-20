"""MC3D: Materials Cloud 3D crystals, PBEsol-v2 relaxed structures.

One CIF tarball (33,142 files, the latest pbesol-v2 set; the overlapping
pbesol-v1 and pbe-v1 sets are skipped), a metadata JSON keyed by
``mc3d-<n>/pbesol-v2`` and ``mc3d-source-duplicates.json`` mapping every
MC3D id to its experimental source-database entries (``icsd|<ver>|<n>``,
``cod|<ver>|<n>``, ``mpds|...``). ICSD/COD parents become id matches into
the experimental pool; mpds entries are ignored. Geometries are DFT-relaxed,
so each record is also fingerprinted (always_hash) and any brand-new
structure joins the candidate pool (experimental stays False).
"""

from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Iterator

from scripts.properties.base import (
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_CIF_NAME = re.compile(r"^(mc3d-\d+)_pbesol-v2\.cif$")


class Mc3dAdapter(SourceAdapter):
    source_key = "mc3d"
    always_hash = True

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(
            root or PROJECT_ROOT / "data" / "raw" / "external_structs" / "mc3d"
        )

    def _load_match_ids(self) -> dict[str, list[tuple[str, str]]]:
        """mc3d-<n> -> deduped (icsd|cod, pool-id) pairs; mpds is skipped."""

        path = self.root / "mc3d-source-duplicates.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, list[tuple[str, str]]] = {}
        for mc3d_id, tokens in raw.items():
            pairs: dict[tuple[str, str], None] = {}
            for token in tokens:
                parts = str(token).split("|")
                if len(parts) != 3 or parts[0] not in {"icsd", "cod"}:
                    continue
                pair = normalize_match_id(parts[0], parts[2])
                if pair:
                    pairs[pair] = None
            if pairs:
                result[mc3d_id] = list(pairs)
        return result

    def _load_spacegroups(self) -> dict[str, int]:
        """mc3d-<n> -> spacegroup number from the pbesol-v2 metadata JSON."""

        path = self.root / "mc3d-pbesol-v2-metadata.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, int] = {}
        for key, meta in raw.items():
            spacegroup = meta.get("spacegroup_number")
            if isinstance(spacegroup, int) and 1 <= spacegroup <= 230:
                result[key.split("/", 1)[0]] = spacegroup
        return result

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        match_ids = self._load_match_ids()
        spacegroups = self._load_spacegroups()
        archive = self.root / "mc3d-pbesol-v2-cifs.tar.gz"
        count = 0
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                if limit is not None and count >= limit:
                    return
                if not member.isfile():
                    continue
                matched = _CIF_NAME.match(PurePosixPath(member.name).name)
                if not matched:
                    continue
                native_id = matched.group(1)
                handle = bundle.extractfile(member)
                if handle is None:
                    continue
                cif = handle.read().decode("utf-8", errors="replace")
                properties = []
                spacegroup = spacegroups.get(native_id)
                if spacegroup is not None:
                    properties.append(
                        PropertyValue(
                            "spacegroup_number", spacegroup, None, "PBEsol (MC3D)"
                        )
                    )
                count += 1
                yield SourceRecord(
                    native_id=native_id,
                    properties=properties,
                    structure=cif,
                    match_ids=match_ids.get(native_id, []),
                )
