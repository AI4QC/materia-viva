"""FIZ ICSD detail records: chemical/mineral names and calculated density.

LICENCE — LOCAL-ONLY DATA, STRUCTURES NEVER ADMITTED: the ICSD is licensed
from FIZ Karlsruhe. Neither its structures nor the property rows staged here
may ever be published to the public MateriaViva snapshot; they enrich the
local pool only, and every staged value must be excluded from any export or
redistribution.

This adapter attaches the local CIF to each record, but ``properties_only``
stays ``True`` and must never be flipped: it is the hard licence guarantee.
With that flag set, ``pipeline.stage_match`` *drops* every record whose
fingerprint finds no pool structure (``unmatched_dropped``) instead of writing
it to ``new_structs.jsonl.gz``, so no FIZ structure can ever enter the pool or
a published snapshot. The CIF is staged for one purpose only: to compute a
BAWL fingerprint that LINKS an ICSD collection code to a structure the pool
already holds from a redistributable source (MP / COD / OQMD / Alexandria
entries that were originally ICSD-derived). The staged CIF text lives only in
the local working tree under ``data/props_work/icsd/`` and is never loaded.

Why the structures matter: only 73,823 of the 203,830 collection codes reached
the pool directly from the local ICSD dump and therefore carry an
('icsd', 'icsd-<code>') id-map entry. The remaining ~130,005 have no such
link, so every ICSD-keyed property source (webmineral, amdb, obelix, spse,
3dsc, snumat, mc3d, ...) silently loses those rows. Fingerprint-matching the
local CIFs recovers the missing links; ``icsd_bridge.py`` then registers them
into the match map so the dependent sources resolve them on a re-run.

Data layout: ``data/raw/ICSD_data.zip`` holds two parallel halves, ``cif/``
(icsd_<code>.cif, extracted to ``data/raw/icsd_extracted/cif/``, 203,830
files) and ``detail/`` (icsd_<code>.txt, 203,831 members, not extracted). Each
detail file is a fixed-format text record: the field label occupies columns
0-11 ("Chem Name   ", "D(calc)     ", ...), the value starts at column 12, and
continuation lines are indented by 12 spaces. Parsing stops at the
"Symmetry" label; everything ingested here appears before it.

Ingested fields (method 'ICSD record (local-only)'):
- ``Chem Name``  -> chemical_name (text, trailing '*' marker stripped,
  capped at 120 chars)
- ``Min Name``   -> mineral_name (text; ~13% of records)
- ``D(calc)``    -> density in g/cm3 (sanity window 0.5-25)

Bibliography fields (Title/Author(s)/Reference) are deliberately skipped.
Records match the pool by collection code via ('icsd', 'icsd-<code>') first;
only records that miss on the id are handed to the hash stage (``always_hash``
stays False), and records whose CIF is missing or unreadable keep
``structure=None`` and are simply dropped.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_ARCHIVE = "ICSD_data.zip"
_EXTRACTED_DETAIL = "icsd_extracted/detail"
_EXTRACTED_CIF = "icsd_extracted/cif"
_METHOD = "ICSD record (local-only)"
_FIELDS = ("Coll Code", "Chem Name", "Min Name", "D(calc)")
_NAME_CAP = 120


def _parse_detail(text: str) -> dict[str, str]:
    """Fixed-format header fields; label cols 0-11, value col 12+."""

    fields: dict[str, str] = {}
    key: str | None = None
    for line in text.splitlines():
        if line.startswith("*"):
            continue
        if line[:1] in ("", " "):
            # 12-space-indented continuation of the previous field
            if key in _FIELDS and line.strip():
                fields[key] = f"{fields[key]} {line.strip()}"
            continue
        key = line[:12].rstrip()
        if key == "Symmetry":
            break
        if key in _FIELDS:
            fields[key] = line[12:].strip()
    return fields


def _chemical_name(raw: str | None) -> str | None:
    """Collapse whitespace, drop the trailing '*' marker, cap at 120."""

    text = safe_text(raw)
    if text is None:
        return None
    text = " ".join(text.split()).rstrip("*").rstrip()
    if len(text) > _NAME_CAP:
        text = text[:_NAME_CAP].rstrip()
    return text or None


class IcsdAdapter(SourceAdapter):
    source_key = "icsd"
    # LICENCE: never admit an ICSD structure into the pool. With this flag set,
    # stage_match drops (never writes to new_structs.jsonl.gz) any record whose
    # fingerprint misses; staged CIFs can only LINK codes to structures the pool
    # already holds from redistributable sources. Do not set this to False.
    properties_only = True

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root or PROJECT_ROOT / "data" / "raw")
        self.cif_dir = self.root / _EXTRACTED_CIF

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        for code, text in self._iter_details():
            record = self._build_record(code, text)
            if record is None:
                continue
            if limit is not None and count >= limit:
                return
            count += 1
            yield record

    def _iter_details(self) -> Iterator[tuple[int, str]]:
        """Yield (collection_code, detail_text); prefers an extracted tree."""

        detail_dir = self.root / _EXTRACTED_DETAIL
        if detail_dir.is_dir():
            paths = sorted(
                detail_dir.glob("icsd_*.txt"),
                key=lambda p: int(p.stem.rsplit("_", 1)[-1]),
            )
            for path in paths:
                yield (
                    int(path.stem.rsplit("_", 1)[-1]),
                    path.read_text(encoding="utf-8", errors="replace"),
                )
            return
        with zipfile.ZipFile(self.root / _ARCHIVE) as bundle:
            for name in bundle.namelist():
                if not (name.startswith("detail/") and name.endswith(".txt")):
                    continue
                stem = name.rsplit("/", 1)[-1][: -len(".txt")]
                code_text = stem.rsplit("_", 1)[-1]
                if not code_text.isdigit():
                    continue
                yield (
                    int(code_text),
                    bundle.read(name).decode("utf-8", errors="replace"),
                )

    def _read_cif(self, file_code: int) -> str | None:
        """Local CIF text for a collection code, or None when unusable.

        Licence note: this text is only ever fingerprinted, and is dropped by
        stage_match unless the pool already holds the same structure from a
        redistributable source (see the module docstring).
        """

        path = self.cif_dir / f"icsd_{file_code}.cif"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return text if text.strip() else None

    def _build_record(self, code: int, text: str) -> SourceRecord | None:
        # the CIF half of the archive is keyed by the *file* code; the detail
        # half's Coll Code agrees with it, but keep the filename for the lookup
        file_code = code
        fields = _parse_detail(text)
        # Coll Code always matches the filename; trust the file when present
        coll = fields.get("Coll Code", "").strip()
        if coll.isdigit():
            code = int(coll)

        properties = []
        mineral = safe_text(fields.get("Min Name"))
        if mineral is not None:
            properties.append(
                PropertyValue("mineral_name", mineral, None, _METHOD)
            )
        chemical = _chemical_name(fields.get("Chem Name"))
        if chemical is not None:
            properties.append(
                PropertyValue("chemical_name", chemical, None, _METHOD)
            )
        density = safe_float(fields.get("D(calc)"))
        if density is not None and 0.5 <= density <= 25:
            properties.append(
                PropertyValue("density", density, "g/cm³", _METHOD)
            )
        if not properties:
            return None

        match_ids = []
        pair = normalize_match_id("icsd", code)
        if pair:
            match_ids.append(pair)
        return SourceRecord(
            native_id=f"icsd-{code}",
            properties=properties,
            structure=self._read_cif(file_code),
            match_ids=match_ids,
        )
