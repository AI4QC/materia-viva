"""OMDB (Organic Materials Database, OMDB-GAP1): PBE gaps for COD organics.

One zip, one JSON list of 12,500 records with jarvis 'atoms' dicts. Every
record derives from a COD entry (id match into the experimental pool) and
carries its own relaxed structure; always_hash so copies already sitting in
the experimental pool under other provenance are still caught by fingerprint.
"""

from __future__ import annotations

import json
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import (
    jarvis_atoms_to_structure,
    safe_float,
)
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

METHOD = "PBE (OMDB-GAP1)"


class OmdbAdapter(SourceAdapter):
    source_key = "omdb-organic"
    always_hash = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        archive = self.root / "omdbv1.json.zip"
        with zipfile.ZipFile(archive) as bundle:
            with bundle.open("omdbv1.json") as handle:
                records = json.load(handle)
        for count, row in enumerate(records):
            if limit is not None and count >= limit:
                return
            properties = []
            gap = safe_float(row.get("bandgap"))
            if gap is not None:
                properties.append(PropertyValue("band_gap", gap, "eV", METHOD))
            match_ids = []
            cod = normalize_match_id("cod", row.get("cod_id"))
            if cod:
                match_ids.append(cod)
            try:
                structure = jarvis_atoms_to_structure(row["atoms"])
            except Exception:  # noqa: BLE001 - keep the property-only record
                structure = None
            cod_id = str(row.get("cod_id") or count).strip()
            yield SourceRecord(
                native_id=f"omdb-cod-{cod_id}",
                properties=properties,
                structure=structure,
                match_ids=match_ids,
            )
