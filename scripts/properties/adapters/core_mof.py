"""CoRE MOF: curated experimentally reported metal-organic frameworks.

Two tar.gz archives streamed sequentially: ``ASR-public_12020.tar.gz``
(12,020 all-solvent-removed CIFs) and ``FSR-public_7061.tar.gz`` (7,061
free-solvent-removed CIFs), each holding ``structure_*/`` and ``disorder_*/``
members. CIF text is passed through verbatim; native id is
``ASR:<basename>`` / ``FSR:<basename>``. ``CoREMOFDBSI_0613.zip``
(charge-assigned duplicates of the same structures) is deliberately skipped.

Most basenames start with the CSD refcode of the parent deposit (6 uppercase
letters plus an optional 2-digit family suffix, e.g. ``ACOCOM_clean`` or
``ABAVIJ01_charged``); those records get a ('csd', refcode) match id into
the experimental pool. The cleaned structure may still differ from the CSD
deposit (solvent removal), hence always_hash. Every record is an
experimentally reported MOF; the 'mof' family label is applied by the loader
from registry.SOURCE_FAMILY.

Properties come from the two Zeo++ tables published beside the archives in
Zenodo record 3677685 (raw/acquired/core-mof/), whose ``filename`` column is
exactly the CIF basename: they join 12020/12020 and 7061/7061.

ASR strips bound and free solvent, FSR only the free solvent, so the FSR cell
of a framework that had bound solvent is the tighter one. 6,416 frameworks are
shipped as a ``<name>_clean`` / ``<name>_freeONLY`` pair and 559 more under one
basename in both archives (``_charged``, ``_manual``, ``_auto``); of those
6,975 pairs 2,574 differ, and on those FSR carries the lower void fraction
2,407 times (median 0.496 against 0.553, median LCD 5.53 A against 6.11 A).
The remaining 4,401 are identical because there was no bound solvent to tell
the two treatments apart. Either way the pair may collapse onto one pool
material once hashed, so the method string names the subset and not only the
code that produced the numbers.

The method string alone still does not separate every row: distinct CSD
refcodes are aliased onto one pool material, so several hundred materials draw
two or more native ids *from the same subset* and therefore carry the same
property under the same method with different values. ``native_id`` is what
tells those apart, which is why dedupe_exact_props keys on it.

``cm3_g`` is the crystal density in g/cm3 despite the inverted header: it
reproduces ``ASA_m2_cm3 / ASA_m2_g`` on every row with a non-zero surface area
(max relative deviation 1.2e-5) and pymatgen's own cell density on the CIFs.
The remaining columns are left out for want of a canonical name: the
non-accessible ``NASA_*`` / ``NAV_cm3_g`` (zero on the median structure), and
the ``All_Metals`` / ``Has_OMS`` open-metal-site annotations. The internal
ASR/FSR spreadsheets of the same record are not downloaded -- they describe
structures the public archives do not ship.
"""

from __future__ import annotations

import csv
import re
import sys
import tarfile
from collections import Counter
from pathlib import Path
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import (
    ACQUIRED_ROOT,
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
)

_DATA_ROOT = (
    PROJECT_ROOT / "data" / "raw" / "external_structs" / "frameworks" / "core_mof"
)

_PROPS_ROOT = ACQUIRED_ROOT / "core-mof"

# subset -> structure archive, Zeo++ table, method string
_ARCHIVES = (
    (
        "ASR",
        "ASR-public_12020.tar.gz",
        "2019-11-01-ASR-public_12020.csv",
        "Zeo++ ASR (all solvent removed)",
    ),
    (
        "FSR",
        "FSR-public_7061.tar.gz",
        "2019-11-01-FSR-public_7061.csv",
        "Zeo++ FSR (free solvent removed)",
    ),
)

#: csv column -> (canonical name, unit, plausibility window). Every unit is
#: already the canonical one, so no conversion happens; the windows are guards
#: that admit both published tables whole (observed spans 0.73-71.6 A for the
#: three diameters, 0.057-7.46 g/cm3, 0-3566 m2/cm3, 0-8318 m2/g, 0.158-0.969
#: and 0.027-17.0 cm3/g).
_POROSITY_FIELDS = (
    ("LCD", "largest_cavity_diameter", "Å", (0.0, 500.0)),
    ("PLD", "pore_limiting_diameter", "Å", (0.0, 500.0)),
    ("LFPD", "largest_free_path_diameter", "Å", (0.0, 500.0)),
    ("cm3_g", "density", "g/cm³", (0.0, 25.0)),
    ("ASA_m2_cm3", "surface_area_volumetric", "m²/cm³", (0.0, 1.0e4)),
    ("ASA_m2_g", "surface_area_gravimetric", "m²/g", (0.0, 1.0e4)),
    ("AV_VF", "void_fraction", None, (0.0, 1.0)),
    ("AV_cm3_g", "pore_volume", "cm³/g", (0.0, 100.0)),
)

# CSD refcode at the start of the basename: 6 uppercase letters + optional
# 2-digit family suffix, validated by requiring a boundary right after (so
# 7+-letter tokens and 3-digit runs are rejected, not truncated into a bogus
# code). base.normalize_match_id has no 'csd' pattern; the pair is
# constructed directly, and codes absent from the match map simply miss.
_RE_REFCODE = re.compile(r"^([A-Z]{6}\d{0,2})(?![A-Z0-9])")


class CoreMofAdapter(SourceAdapter):
    source_key = "core-mof"
    always_hash = True

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root or _DATA_ROOT)

    def _load_porosity(
        self, filename: str, method: str
    ) -> dict[str, list[PropertyValue]]:
        table: dict[str, list[PropertyValue]] = {}
        with (_PROPS_ROOT / filename).open(
            newline="", encoding="utf-8", errors="replace"
        ) as handle:
            for row in csv.DictReader(handle):
                basename = (row.get("filename") or "").strip()
                if not basename:
                    continue
                properties = []
                for key, name, unit, (low, high) in _POROSITY_FIELDS:
                    value = safe_float(row.get(key))
                    if value is None:
                        continue
                    if not low <= value <= high:
                        self.drops[f"{key}:{method}"] += 1
                        continue
                    properties.append(PropertyValue(name, value, unit, method))
                if properties:
                    table[basename] = properties
        return table

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        self.drops: Counter[str] = Counter()
        try:
            yield from self._iter_records(limit)
        finally:
            if self.drops:
                print(
                    f"[core-mof] out-of-range values dropped: {dict(self.drops)}",
                    file=sys.stderr,
                    flush=True,
                )

    def _iter_records(self, limit: int | None) -> Iterator[SourceRecord]:
        count = 0
        for subset, archive, table_file, method in _ARCHIVES:
            porosity = self._load_porosity(table_file, method)
            with tarfile.open(self.root / archive, "r|gz") as bundle:
                for member in bundle:
                    if not member.isfile() or not member.name.endswith(".cif"):
                        continue
                    if limit is not None and count >= limit:
                        return
                    handle = bundle.extractfile(member)
                    if handle is None:
                        continue
                    text = handle.read().decode("utf-8", errors="replace")
                    basename = member.name.rsplit("/", 1)[-1][: -len(".cif")]
                    match_ids = []
                    refcode = _RE_REFCODE.match(basename)
                    if refcode:
                        match_ids.append(("csd", refcode.group(1)))
                    yield SourceRecord(
                        native_id=f"{subset}:{basename}",
                        properties=porosity.get(basename, []),
                        structure=text,
                        match_ids=match_ids,
                        experimental=True,
                    )
                    count += 1
