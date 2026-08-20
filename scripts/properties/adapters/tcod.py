"""TCOD: Theoretical Crystallography Open Database.

~7,400 per-record CIF files under data/raw/acquired/tcod/{10,20,30}/**/*.cif.
CIF text is passed through verbatim. Records on publication hold publish only
'? ? ? ?' atom sites and are skipped, as are pathological >5MB trajectory-style
files. Many records declare the COD entry their coordinates started from
(_tcod_initial_coordinate_db_code); that is an id match into the pool, but the
relaxed structure itself may differ, hence always_hash.

Mapped CIF tags: _dft_band_gap and _dft_dielectric_constant (both carry the
record's _dft_XC_functional as their method, so the many DFT levels in the
archive stay apart) and _exptl_crystal_density_diffrn, the density the
depositor computed from the refined cell and contents.

_tcod_total_energy and _dft_lattice_energy are deliberately NOT ingested: they
are per-cell values with an undefined (code/pseudopotential-specific)
reference.
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

_MAX_BYTES = 5 * 1024 * 1024
_HOLD_MARKER = "? ? ? ?"

_RE_COD_CODE = re.compile(r"^_tcod_initial_coordinate_db_code[ \t]+(\S+)", re.M)
_RE_DB_ABBREV = re.compile(r"^_tcod_initial_coordinate_db_abbrev[ \t]+(\S+)", re.M)
_RE_BAND_GAP = re.compile(r"^_dft_band_gap[ \t]+(\S+)", re.M)
_RE_DIELECTRIC = re.compile(r"^_dft_dielectric_constant[ \t]+(\S+)", re.M)
_RE_DENSITY = re.compile(r"^_exptl_crystal_density_diffrn[ \t]+(\S+)", re.M)
# exact tag only: must not catch _dft_XC_functional_type / _citation_id
_RE_XC = re.compile(r"^_dft_XC_functional[ \t]+(.+?)[ \t]*$", re.M)


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    return text.strip()


class TcodAdapter(SourceAdapter):
    source_key = "tcod"
    always_hash = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        for shard in ("10", "20", "30"):
            base = self.root / shard
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.cif")):
                if limit is not None and count >= limit:
                    return
                try:
                    if path.stat().st_size > _MAX_BYTES:
                        continue
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if _HOLD_MARKER in text:
                    continue  # publication-hold record without coordinates

                properties = []
                xc_match = _RE_XC.search(text)
                method = (
                    safe_text(_unquote(xc_match.group(1)))
                    if xc_match
                    else None
                ) or "DFT"
                gap_match = _RE_BAND_GAP.search(text)
                if gap_match:
                    gap = safe_float(_unquote(gap_match.group(1)))
                    if gap is not None:
                        properties.append(
                            PropertyValue("band_gap", gap, "eV", method)
                        )
                dielectric_match = _RE_DIELECTRIC.search(text)
                if dielectric_match:
                    dielectric = safe_float(_unquote(dielectric_match.group(1)))
                    if dielectric is not None and 1.0 <= dielectric <= 1e4:
                        properties.append(
                            PropertyValue(
                                "dielectric_constant_total", dielectric,
                                None, method,
                            )
                        )
                density_match = _RE_DENSITY.search(text)
                if density_match:
                    density = safe_float(_unquote(density_match.group(1)))
                    if density is not None and 0.3 <= density <= 25.0:
                        properties.append(
                            PropertyValue(
                                "density", density, "g/cm³",
                                "diffraction (calculated from refined cell)",
                            )
                        )

                match_ids = []
                code_match = _RE_COD_CODE.search(text)
                if code_match:
                    abbrev_match = _RE_DB_ABBREV.search(text)
                    abbrev = (
                        _unquote(abbrev_match.group(1)).upper()
                        if abbrev_match
                        else "COD"
                    )
                    if abbrev == "COD":
                        pair = normalize_match_id(
                            "cod", _unquote(code_match.group(1))
                        )
                        if pair:
                            match_ids.append(pair)

                yield SourceRecord(
                    native_id=path.stem,
                    properties=properties,
                    structure=text,
                    match_ids=match_ids,
                )
                count += 1
