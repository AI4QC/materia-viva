"""SNUMAT: hybrid-functional band gaps for ICSD-derived structures.

One zip, one JSON list of 10,481 records. Every record carries its parent
ICSD number (id match into the experimental pool) and its own relaxed
structure (fingerprinted so SNUMAT-only relaxations can still enter or match
the candidate pool), hence always_hash.

129 records were run with spin-orbit coupling (``SOC`` == 'True'), and many
of them share an ICSD parent with a scalar-relativistic record. The band-gap
and gap-character rows therefore carry the SOC state in their method string
("HSE06+SOC" vs "HSE06"); without it the two runs' gaps would land on one
material as indistinguishable duplicates of the same property.
"""

from __future__ import annotations

import json
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import (
    jarvis_atoms_to_structure,
    safe_float,
    safe_text,
)
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)


class SnumatAdapter(SourceAdapter):
    source_key = "snumat"
    always_hash = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        archive = self.root / "snumat.json.zip"
        with zipfile.ZipFile(archive) as bundle:
            with bundle.open("snumat.json") as handle:
                records = json.load(handle)
        for count, row in enumerate(records):
            if limit is not None and count >= limit:
                return
            properties = []
            soc = (safe_text(row.get("SOC")) or "").strip().lower()
            relativity = "+SOC" if soc in {"true", "1", "yes"} else ""
            for key, method in (
                ("Band_gap_GGA", "GGA"),
                ("Band_gap_HSE", "HSE06"),
                ("Band_gap_GGA_optical", "GGA optical"),
                ("Band_gap_HSE_optical", "HSE06 optical"),
            ):
                value = safe_float(row.get(key))
                if value is not None:
                    properties.append(
                        PropertyValue(
                            "band_gap", value, "eV", f"{method}{relativity}"
                        )
                    )
            for key, method in (
                ("Direct_or_indirect", "GGA"),
                ("Direct_or_indirect_HSE", "HSE06"),
            ):
                verdict = safe_text(row.get(key))
                if verdict and verdict.lower() in {"direct", "indirect"}:
                    properties.append(
                        PropertyValue(
                            "is_gap_direct", verdict.lower() == "direct",
                            None, f"{method}{relativity}",
                        )
                    )
            ordering = safe_text(row.get("Magnetic_ordering"))
            if ordering:
                properties.append(
                    PropertyValue("magnetic_ordering", ordering, None, "GGA")
                )
            spacegroup = safe_float(row.get("Space_group_rlx"))
            if spacegroup:
                properties.append(
                    PropertyValue("spacegroup_number", int(spacegroup), None, "GGA")
                )
            match_ids = []
            icsd = normalize_match_id("icsd", row.get("ICSD_number"))
            if icsd:
                match_ids.append(icsd)
            try:
                structure = jarvis_atoms_to_structure(row["atoms"])
            except Exception:  # noqa: BLE001 - keep the property-only record
                structure = None
            yield SourceRecord(
                native_id=str(row.get("SNUMAT_id") or f"snumat-{count}"),
                properties=properties,
                structure=structure,
                match_ids=match_ids,
            )
