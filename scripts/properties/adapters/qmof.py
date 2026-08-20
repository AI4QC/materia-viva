"""QMOF: DFT-relaxed metal-organic frameworks with multi-functional band gaps.

One outer zip (``qmof_database.zip``) holding ``qmof.csv`` (20,372 rows) and a
nested ``relaxed_structures.zip`` with one CIF per record, named
``relaxed_structures/<qmof_id>.cif``; every CSV row has a CIF. The 3.15 GB
``qmof_structure_data.json`` is deliberately never touched. The CSV is
streamed out of the outer archive and the nested structure zip is inflated
into memory (~119 MB) lazily, on the first record that needs a CIF; CIF text
passes through verbatim.

16,040 rows come from the CSD (``info.source == "CSD"``); their ``name`` is
always ``<REFCODE>_FSR``, so the bare refcode (6 letters + optional 2 digits,
regex-validated) is emitted as a ``("csd", REFCODE)`` match id into the
experimental bridge. The CSD parent is only the experimental ancestor of the
DFT-relaxed derivative, hence always_hash: QMOF's own relaxed cell may still
be a distinct candidate-pool structure. ``experimental`` stays False for the
same reason.

Properties, all four functionals sharing one method string per functional so
their rows stay distinguishable on the same material: band gaps (PBE for all
rows, HLE17 / HSE06 / HSE06*10HF for the ~10.8k subset with hybrid
follow-ups), the matching ``is_gap_direct`` flag from ``outputs.<f>.directgap``,
and ``total_energy_per_atom`` from ``outputs.<f>.energy_total / info.natoms``.
Plus net cell magnetization (PBE); zeo++ PLD / LCD / density; the MOFid
topology code (sentinels ERROR, UNKNOWN, MISMATCH, TIMEOUT skipped); and
``experimentally_observed`` True where ``info.synthesized`` is TRUE. CBM/VBM
and the per-spin gap arrays are deliberately not ingested.

Caution — the HLE17 single points report total energies on a completely
different, much deeper energy reference than the other three functionals:
over the 10,756 rows that carry one, the median is -62 eV/atom and the tail
reaches -532 eV/atom, against -6.7 eV/atom (median) and -8.3 eV/atom (deepest)
for PBE on the very same cells, and the offset tracks the heavy elements
present. Those numbers are not total energies per atom in any comparable
sense, so the plausibility window below rejects every one of them while
leaving PBE / HSE06 / HSE06*10HF untouched (deepest observed: -10.05 eV/atom).
The HLE17 *band gaps* are unaffected and still ingested.
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PROJECT_ROOT,
    PropertyValue,
    SourceAdapter,
    SourceRecord,
)

_ARCHIVE = "qmof_database.zip"
_CSV_MEMBER = "qmof_database/qmof.csv"
_STRUCTS_MEMBER = "qmof_database/relaxed_structures.zip"

#: bare CSD refcode: six letters plus an optional two-digit suffix
_REFCODE = re.compile(r"^[A-Z]{6}(?:[0-9]{2})?$")

_TOPO_SENTINELS = {"UNKNOWN", "ERROR", "MISMATCH", "TIMEOUT", "NA"}

# csv column -> band-gap method string. The functional key is sliced back out
# of the column name so the directgap flag and the total energy of the same
# functional reuse the identical method string.
_GAP_COLUMNS = (
    ("outputs.pbe.bandgap", "PBE (QMOF)"),
    ("outputs.hle17.bandgap", "HLE17 (QMOF)"),
    ("outputs.hse06.bandgap", "HSE06 (QMOF)"),
    ("outputs.hse06_10hf.bandgap", "HSE06*10HF (QMOF)"),
)

#: VASP PAW total energies per atom for these frameworks sit around
#: -6 to -10 eV/atom; anything outside this window is on a different energy
#: reference (see the module docstring on HLE17) rather than a deeper minimum.
_ENERGY_PER_ATOM_RANGE = (-15.0, 5.0)

_BOOLEANS = {"TRUE": True, "FALSE": False}

# csv column -> (canonical name, unit) for the zeo++ geometry block
_GEOMETRY_COLUMNS = (
    ("info.pld", "pore_limiting_diameter", "Å"),
    ("info.lcd", "largest_cavity_diameter", "Å"),
    ("info.density", "density", "g/cm³"),
)


class QmofAdapter(SourceAdapter):
    source_key = "qmof"
    always_hash = True
    properties_only = False

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(
            root
            or PROJECT_ROOT / "data" / "raw" / "external_structs" / "frameworks" / "qmof"
        )
        self._structs: zipfile.ZipFile | None = None
        #: values rejected by the plausibility window, by reason
        self.drops: Counter[str] = Counter()

    def _structure_cif(self, outer: zipfile.ZipFile, qmof_id: str) -> str | None:
        if self._structs is None:
            # The nested zip is deflated inside the outer archive, so random
            # access through a ZipExtFile would re-inflate from the start on
            # every member; one in-memory copy is cheap and fast instead.
            self._structs = zipfile.ZipFile(
                io.BytesIO(outer.read(_STRUCTS_MEMBER))
            )
        member = f"relaxed_structures/{qmof_id}.cif"
        try:
            payload = self._structs.read(member)
        except KeyError:
            return None
        return payload.decode("utf-8", errors="replace")

    @staticmethod
    def _topology(raw: str | None) -> str | None:
        text = safe_text(raw)
        if not text:
            return None
        # Interpenetrated frameworks list one code per component; keep the
        # resolvable, deduplicated parts and drop pure-sentinel entries.
        parts: list[str] = []
        for part in text.split(","):
            part = part.strip()
            if not part or part.upper() in _TOPO_SENTINELS:
                continue
            if part not in parts:
                parts.append(part)
        return ",".join(parts) or None

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        try:
            yield from self._iter_records(limit)
        finally:
            if self.drops:
                print(
                    f"[qmof] out-of-range values dropped: {dict(self.drops)}",
                    file=sys.stderr,
                    flush=True,
                )

    def _iter_records(self, limit: int | None) -> Iterator[SourceRecord]:
        with zipfile.ZipFile(self.root / _ARCHIVE) as outer:
            with outer.open(_CSV_MEMBER) as handle:
                reader = csv.DictReader(
                    io.TextIOWrapper(handle, encoding="utf-8", newline="")
                )
                for count, row in enumerate(reader):
                    if limit is not None and count >= limit:
                        return
                    qmof_id = (row.get("qmof_id") or "").strip()
                    if not qmof_id:
                        continue

                    natoms = safe_float(row.get("info.natoms"))
                    if natoms is not None and natoms < 1:
                        natoms = None

                    properties: list[PropertyValue] = []
                    for column, method in _GAP_COLUMNS:
                        functional = column.split(".")[1]
                        value = safe_float(row.get(column))
                        if value is not None:
                            properties.append(
                                PropertyValue("band_gap", value, "eV", method)
                            )
                        direct = _BOOLEANS.get(
                            (row.get(f"outputs.{functional}.directgap") or "")
                            .strip()
                            .upper()
                        )
                        if direct is not None:
                            properties.append(
                                PropertyValue("is_gap_direct", direct, None, method)
                            )
                        total = safe_float(
                            row.get(f"outputs.{functional}.energy_total")
                        )
                        if total is not None and natoms is not None:
                            per_atom = total / natoms
                            low, high = _ENERGY_PER_ATOM_RANGE
                            if low <= per_atom <= high:
                                properties.append(
                                    PropertyValue(
                                        "total_energy_per_atom",
                                        per_atom,
                                        "eV/atom",
                                        method,
                                    )
                                )
                            else:
                                self.drops[f"energy:{functional}"] += 1
                    magmom = safe_float(row.get("outputs.pbe.net_magmom"))
                    if magmom is not None:
                        properties.append(
                            PropertyValue(
                                "total_magnetization",
                                magmom,
                                "μB",
                                "PBE (QMOF) (per cell)",
                            )
                        )
                    for column, name, unit in _GEOMETRY_COLUMNS:
                        value = safe_float(row.get(column))
                        if value is not None:
                            properties.append(
                                PropertyValue(name, value, unit, "zeo++ (QMOF)")
                            )
                    topology = self._topology(row.get("info.mofid.topology"))
                    if topology:
                        properties.append(
                            PropertyValue(
                                "structure_prototype",
                                topology,
                                None,
                                "MOFid topology",
                            )
                        )
                    if (row.get("info.synthesized") or "").strip().upper() == "TRUE":
                        properties.append(
                            PropertyValue(
                                "experimentally_observed", True, None, "CSD-derived"
                            )
                        )

                    match_ids: list[tuple[str, str]] = []
                    if (row.get("info.source") or "").strip() == "CSD":
                        # names are "<REFCODE>_FSR"; normalize_match_id has no
                        # csd pattern, so validate and build the pair here.
                        refcode = (row.get("name") or "").split("_", 1)[0].upper()
                        if _REFCODE.match(refcode):
                            match_ids.append(("csd", refcode))

                    yield SourceRecord(
                        native_id=qmof_id,
                        properties=properties,
                        structure=self._structure_cif(outer, qmof_id),
                        match_ids=match_ids,
                    )
