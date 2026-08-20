"""OBELiX: experimental room-temperature Li-ion conductivities (599 entries).

One CSV; the accompanying CIFs carry partial occupancies and are out of pool
scope, so this source is properties_only with structure=None. Entries with a
numeric ICSD ID match the experimental pool by id; where that column is empty
the ``Cif ref_1``/``Cif ref_2`` provenance notes sometimes still name the ICSD
entry the CIF was taken from ("155950-ICSD", "ICSD-111757"), which recovers a
handful of matches.

``IC (Bulk)`` is the bulk-only conductivity of the 28 entries that report the
grain-interior and total values separately, and is staged as a second
ionic_conductivity row whose method says "bulk" (27 of the 28 differ from the
total, by up to a factor of 25). ``IC (Total)`` is NOT staged: on all 29 rows
that carry it, it is byte-identical to the ``Ionic conductivity (S cm-1)``
column already mapped.
"""

from __future__ import annotations

import re
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)


#: provenance notes name the source entry either way round, sometimes with a
#: trailing comment ("155950-ICSD; appendix")
_CIF_REF_ICSD = (
    re.compile(r"(?<!\d)(\d{3,7})\s*-\s*ICSD\b", re.I),
    re.compile(r"\bICSD\s*-\s*(\d{3,7})(?!\d)", re.I),
)


def _icsd_from_cif_ref(*values) -> str | None:
    for value in values:
        text = safe_text(value)
        if not text:
            continue
        for pattern in _CIF_REF_ICSD:
            match = pattern.search(text)
            if match:
                return match.group(1)
    return None


class ObelixAdapter(SourceAdapter):
    source_key = "obelix"
    properties_only = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        import pandas as pd

        frame = pd.read_csv(self.root / "all.csv", dtype=str)
        count = 0
        for _, row in frame.iterrows():
            if limit is not None and count >= limit:
                return
            native_id = safe_text(row.get("ID"))
            if not native_id:
                continue
            properties = []
            conductivity = safe_float(row.get("Ionic conductivity (S cm-1)"))
            if conductivity is not None and conductivity > 0:
                properties.append(
                    PropertyValue(
                        "ionic_conductivity", conductivity, "S/cm",
                        "experiment RT total",
                    )
                )
            bulk = safe_float(row.get("IC (Bulk)"))
            if bulk is not None and bulk > 0:
                properties.append(
                    PropertyValue(
                        "ionic_conductivity", bulk, "S/cm",
                        "experiment RT bulk",
                    )
                )
            spacegroup = safe_float(row.get("Space group #"))
            if spacegroup is not None and spacegroup > 0:
                properties.append(
                    PropertyValue(
                        "spacegroup_number", int(spacegroup), None, "experiment"
                    )
                )
            if not properties:
                continue
            match_ids = []
            icsd_raw = safe_float(row.get("ICSD ID"))  # stored as '155950.0'
            if icsd_raw is not None and icsd_raw > 0 and icsd_raw == int(icsd_raw):
                icsd = normalize_match_id("icsd", int(icsd_raw))
                if icsd:
                    match_ids.append(icsd)
            if not match_ids:
                code = _icsd_from_cif_ref(
                    row.get("Cif ref_1"), row.get("Cif ref_2")
                )
                icsd = normalize_match_id("icsd", code) if code else None
                if icsd:
                    match_ids.append(icsd)
            count += 1
            yield SourceRecord(
                native_id=native_id,
                properties=properties,
                structure=None,
                match_ids=match_ids,
            )
