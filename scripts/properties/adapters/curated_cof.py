"""CURATED-COFs: synthesized covalent organic frameworks from the literature.

984 CIFs under ``cifs/``, one per COF id (e.g. ``05000N2``); CIF text is
passed through verbatim. ``cof-frameworks.csv`` covers the 874 curated ids;
the other 110 CIFs appear in ``cof-discarded.csv`` (stacking-mode doubts and
similar curation notes) but are still literature-reported structures and are
kept. The framework name (COF-1, TpPa-1, ...) is unique and non-empty across
the curated rows and is staged as ``structure_prototype``; the DOI/paper
metadata in ``cof-papers.csv`` is provenance only and not ingested.

Every record is a synthesized COF (experimental pool); the 'cof' family
label is applied by the loader from registry.SOURCE_FAMILY. No
cross-database ids, so matching is purely by structure hash.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from scripts.properties.adapters._util import safe_text
from scripts.properties.base import (
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
)

_DATA_ROOT = (
    PROJECT_ROOT / "data" / "raw" / "external_structs" / "frameworks" / "curated_cofs"
)


class CuratedCofAdapter(SourceAdapter):
    source_key = "curated-cof"

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root or _DATA_ROOT)

    def _names(self) -> dict[str, str]:
        """COF id -> literature framework name, from the curated table."""

        names: dict[str, str] = {}
        table = self.root / "cof-frameworks.csv"
        if not table.is_file():
            return names
        with table.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                cof_id = safe_text(row.get("CURATED-COFs ID"))
                name = safe_text(row.get("Name"))
                if cof_id and name:
                    names[cof_id] = name
        return names

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        names = self._names()
        for count, cif_path in enumerate(sorted((self.root / "cifs").glob("*.cif"))):
            if limit is not None and count >= limit:
                return
            cof_id = cif_path.stem
            properties = []
            name = names.get(cof_id)
            if name:
                properties.append(
                    PropertyValue("structure_prototype", name, None, "CURATED-COFs")
                )
            yield SourceRecord(
                native_id=cof_id,
                properties=properties,
                structure=cif_path.read_text(encoding="utf-8", errors="replace"),
                experimental=True,
            )
