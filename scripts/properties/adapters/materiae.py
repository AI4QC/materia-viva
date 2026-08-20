"""Materiae: symmetry-indicator topology classifications for ICSD/MP materials.

One gzipped JSON object per material under details/MAT*.json.gz. Every record
names its Materials Project parent (mp_id) and the ICSD entries it derives
from; the primitive-cell CIF text ships with the record and is passed through
verbatim. The id matches point at *related* database entries, so records are
always fingerprinted too (always_hash).

Everything is published twice, once with spin-orbit coupling and once without,
so every method string says which of the two a value came from.

``{soc,nsoc}_fermi_dos`` is the DOS at E_F of that calculation in states/eV per
cell (0 .. 488 over a 4,087-record sample; the ~53% of exact zeros are the
insulators and are kept, being a real measurement rather than a sentinel).

``{soc,nsoc}_z2224_ind`` is *not* a duplicate of ``{soc,nsoc}_sym_ind``: the
sym_ind vector is expressed in that material's own indicator group
(``ind_group``: Z2, Z2_Z2_Z4, Z8, Z12, ...) while the z2224 vector is always
the four (Z2,Z2,Z2,Z4) invariants, so the two differ in 695 of the 1,153
sampled records that carry both, and z2224 is present on more records than
sym_ind (2,555 vs 2,440 with SOC). The group is named in the z2224 method
strings because "0,0,0,0" is unreadable without it.

Not staged: ``nsoc_dos``/``soc_dos`` (DOS curves, and their first sample is a
spike artifact), ``BZ`` (reciprocal lattice vectors), ``nelec``/``nsites``
(bookkeeping / structure-derived), ``{soc,nsoc}_efermi`` (each on its own
calculation's energy zero, and the SOC value is pinned to 0.0 for most
records) and ``{soc,nsoc}_band`` (an undocumented flag).
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

#: states/eV per cell; non-negative, and the sampled maximum is 488
_FERMI_DOS_RANGE = (0.0, 1e5)


class MateriaeAdapter(SourceAdapter):
    source_key = "materiae"
    always_hash = True

    def __init__(self, root=None) -> None:
        super().__init__(root)
        self.drops: Counter[str] = Counter()

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        details = self.root / "details"
        count = 0
        try:
            for path in sorted(details.glob("MAT*.json.gz")):
                if limit is not None and count >= limit:
                    return
                try:
                    with gzip.open(path, "rt", encoding="utf-8") as handle:
                        record = json.load(handle)
                except Exception:  # noqa: BLE001 - one corrupt file must not stop the run
                    continue
                native_id = safe_text(record.get("material_id"))
                if not native_id:
                    continue
                count += 1

                properties: list[PropertyValue] = []
                for key, method in (
                    ("soc_topo_class", "PBE+SOC SymTopo"),
                    ("nsoc_topo_class", "PBE SymTopo"),
                ):
                    topo = safe_text(record.get(key))
                    if topo:
                        properties.append(
                            PropertyValue("topology_class", topo, None, method)
                        )
                for key, method in (
                    ("soc_dos_gap", "PBE+SOC DOS"),
                    ("nsoc_dos_gap", "PBE DOS"),
                ):
                    gap = safe_float(record.get(key))
                    if gap is not None:
                        properties.append(PropertyValue("band_gap", gap, "eV", method))
                for key, method in (
                    ("soc_fermi_dos", "PBE+SOC DOS"),
                    ("nsoc_fermi_dos", "PBE DOS"),
                ):
                    dos = safe_float(record.get(key))
                    if dos is None:
                        continue
                    if not (_FERMI_DOS_RANGE[0] <= dos <= _FERMI_DOS_RANGE[1]):
                        self.drops[key] += 1
                        continue
                    properties.append(
                        PropertyValue("dos_at_fermi", dos, "states/eV", method)
                    )
                sym_ind = record.get("soc_sym_ind")
                if isinstance(sym_ind, (list, tuple)) and len(sym_ind):
                    properties.append(
                        PropertyValue(
                            "symmetry_indicators",
                            ",".join(str(part) for part in sym_ind),
                            None,
                            "PBE+SOC SymTopo",
                        )
                    )
                nsoc_sym_ind = record.get("nsoc_sym_ind")
                if isinstance(nsoc_sym_ind, (list, tuple)) and len(nsoc_sym_ind):
                    properties.append(
                        PropertyValue(
                            "symmetry_indicators",
                            ",".join(str(part) for part in nsoc_sym_ind),
                            None,
                            "PBE SymTopo",
                        )
                    )
                for key, method in (
                    ("soc_z2224_ind", "PBE+SOC SymTopo"),
                    ("nsoc_z2224_ind", "PBE SymTopo"),
                ):
                    invariants = record.get(key)
                    if isinstance(invariants, (list, tuple)) and len(invariants):
                        properties.append(
                            PropertyValue(
                                "topology_invariant",
                                ",".join(str(part) for part in invariants),
                                None,
                                f"{method} (z2,z2,z2,z4)",
                            )
                        )
                spacegroup = record.get("spacegroup")
                if isinstance(spacegroup, dict):
                    number = safe_float(spacegroup.get("number"))
                    if number:
                        properties.append(
                            PropertyValue("spacegroup_number", int(number), None, "PBE")
                        )

                match_ids = []
                mp = normalize_match_id("materials-project", record.get("mp_id"))
                if mp:
                    match_ids.append(mp)
                for code in record.get("icsd_ids") or ():
                    icsd = normalize_match_id("icsd", code)
                    if icsd:
                        match_ids.append(icsd)

                yield SourceRecord(
                    native_id=native_id,
                    properties=properties,
                    structure=safe_text(record.get("prim_cif_str")),
                    match_ids=match_ids,
                )
        finally:
            print(
                "[materiae] value drops: "
                + (str(dict(self.drops)) if self.drops else "none"),
                flush=True,
            )
