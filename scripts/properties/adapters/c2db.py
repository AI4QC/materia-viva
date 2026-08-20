"""C2DB: computational 2D materials database (PBE electronic structure).

One zip, one JSON list of 3,520 records with jarvis 'atoms' dicts. Native
uids (e.g. B2F2O2Zr3-1ca00ae0eaaa) carry no cross-database meaning, so there
are no id matches; matching is by structure fingerprint only. ``etot`` (total
energy of the full cell, not per atom) and the raman payload are skipped.
"""

from __future__ import annotations

import json
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import (
    jarvis_atoms_to_structure,
    safe_float,
)
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

METHOD = "PBE (C2DB)"


class C2dbAdapter(SourceAdapter):
    source_key = "c2db"

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        archive = self.root / "c2db_atoms.json.zip"
        with zipfile.ZipFile(archive) as bundle:
            with bundle.open("c2db_atoms.json") as handle:
                records = json.load(handle)
        for count, row in enumerate(records):
            if limit is not None and count >= limit:
                return
            properties = [PropertyValue("dimensionality", "2D", None, METHOD)]
            for name, key in (
                ("band_gap", "gap"),
                ("work_function", "wf"),
                ("fermi_energy", "efermi"),
            ):
                value = safe_float(row.get(key))
                if value is not None:
                    properties.append(PropertyValue(name, value, "eV", METHOD))
            try:
                structure = jarvis_atoms_to_structure(row["atoms"])
            except Exception:  # noqa: BLE001 - keep the property-only record
                structure = None
            yield SourceRecord(
                native_id=str(row.get("id") or f"c2db-{count}"),
                properties=properties,
                structure=structure,
            )
