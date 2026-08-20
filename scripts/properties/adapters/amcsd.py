"""AMCSD: American Mineralogist Crystal Structure Database.

One zip of ~21,700 experimental mineral CIFs (the '__original__' as-published
duplicates are skipped). CIF text is passed through verbatim; records with
disordered/partial occupancies are expected to fail at the hash stage, which
is fine. Every record is experimental. Native id is the 7-digit
_database_code_amcsd, pulled by regex — files also carry mineral name and
measured (diffraction) density.
"""

from __future__ import annotations

import re
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_RE_CODE = re.compile(r"^_database_code_amcsd[ \t]+(\d{7})", re.M)
_RE_MINERAL = re.compile(r"^_chemical_name_mineral[ \t]+(.+?)[ \t\r]*$", re.M)
_RE_DENSITY = re.compile(r"^_exptl_crystal_density_diffrn[ \t]+(\S+)", re.M)


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    return text.strip()


class AmcsdAdapter(SourceAdapter):
    source_key = "amcsd"
    always_hash = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        with zipfile.ZipFile(self.root / "cif.zip") as bundle:
            for name in sorted(bundle.namelist()):
                if not name.endswith(".cif") or "__original__" in name:
                    continue
                if limit is not None and count >= limit:
                    return
                text = bundle.read(name).decode("utf-8", errors="replace")
                code_match = _RE_CODE.search(text)
                if not code_match:
                    continue
                properties = []
                mineral_match = _RE_MINERAL.search(text)
                if mineral_match:
                    mineral = safe_text(_unquote(mineral_match.group(1)))
                    if mineral:
                        properties.append(
                            PropertyValue("mineral_name", mineral, None, "experiment")
                        )
                density_match = _RE_DENSITY.search(text)
                if density_match:
                    density = safe_float(_unquote(density_match.group(1)))
                    if density is not None and density > 0:
                        properties.append(
                            PropertyValue(
                                "density", density, "g/cm³",
                                "experiment diffraction",
                            )
                        )
                yield SourceRecord(
                    native_id=code_match.group(1),
                    properties=properties,
                    structure=text,
                    experimental=True,
                )
                count += 1
