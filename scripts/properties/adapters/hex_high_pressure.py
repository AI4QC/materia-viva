"""HEX: elemental hexagonal phases under pressure (0-300 GPa).

One zip; 457 CIFs at HEX/HEX/DB_{GS,EA,MISS}/DB_*_{000,100,200,300}/
<El>_<P>_<cat>.cif. DB_GS holds USPEX ground states; DB_EA/DB_MISS hold the
best hexagonal structure found (evolutionary search / missed-by-GS). The
search pressure comes from the path; the FINDSYM header of each CIF also
states the space group it symmetrised the relaxed cell into, which is the one
scalar in the file body. CIF text passthrough, always_hash (no cross-database
ids).
"""

from __future__ import annotations

import re
import zipfile
from typing import Iterator

from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_MEMBER = re.compile(
    r"^HEX/HEX/DB_(GS|EA|MISS)/DB_\1_(000|100|200|300)/"
    r"([A-Za-z]{1,2})_(\d+)_(GS|EA|MISS)\.cif$"
)

_SPACEGROUP = re.compile(r"^_symmetry_Int_Tables_number\s+(\d+)\s*$", re.M)

_METHODS = {
    "GS": "DFT USPEX ground-state search",
    "EA": "DFT USPEX best-hexagonal",
    "MISS": "DFT USPEX best-hexagonal",
}


class HexHighPressureAdapter(SourceAdapter):
    source_key = "hex-high-pressure"
    always_hash = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        with zipfile.ZipFile(self.root / "HEX.zip") as bundle:
            for name in sorted(bundle.namelist()):
                if "__MACOSX" in name:
                    continue
                member = _MEMBER.match(name)
                if not member:
                    continue
                if limit is not None and count >= limit:
                    return
                element = member.group(3)
                pressure = member.group(4)  # keep the file's 000/100/... token
                category = member.group(5)
                text = bundle.read(name).decode("utf-8", errors="replace")
                properties = [
                    PropertyValue(
                        "measurement_pressure",
                        float(int(pressure)),
                        "GPa",
                        _METHODS[category],
                    )
                ]
                spacegroup = _SPACEGROUP.search(text)
                if spacegroup:
                    number = int(spacegroup.group(1))
                    if 1 <= number <= 230:
                        properties.append(
                            PropertyValue(
                                "spacegroup_number", number, None,
                                f"FINDSYM ({_METHODS[category]}, {int(pressure)} GPa)",
                            )
                        )
                yield SourceRecord(
                    native_id=f"{element}_{pressure}_{category}",
                    properties=properties,
                    structure=text,
                )
                count += 1
