"""Matbench Discovery: WBM test-set energetics plus an MP snapshot bridge.

Part 1 — WBM: ``2023-12-13-wbm-summary.csv.gz`` (256,963 rows keyed
``wbm-N-M``) carries MP2020-corrected formation energies, hull distances and
PBE band gaps. Structures come from the per-material members of
``2024-08-04-wbm-relaxed-atoms.extxyz.zip`` (``<material_id>.extxyz``), read
with ase and converted to pymatgen.

The summary carries TWO independent energetics sets per row: the MP2020-corrected
values referenced to the Materials Project pattern-decomposition hull, and the
WBM authors' own uncorrected values referenced to the WBM hull. They are not
redundant — 40% of rows disagree by more than 10 meV/atom (up to 6 eV/atom) —
so both are staged, each with the correction scheme and hull named in its
method string. ``uncorrected_energy`` (a cell total) over ``n_sites`` gives the
total energy per atom, and ``wyckoff_spglib`` is the AFLOW-style protostructure
label of the relaxed cell. Deliberately skipped: the per-atom correction terms
(derivable from the two energy sets), ``uncorrected_energy_from_cse``
(redundant), the initial-structure Wyckoff label, the init/final site-statistics
fingerprint (an ML descriptor) and ``unique_prototype`` (a benchmark split flag).

Part 2 — MP snapshot bridge: ``2023-02-07-mp-computed-structure-entries.json.gz``
(pandas ``columns``-orient JSON, 154,718 ComputedStructureEntry dicts) is
streamed with ijson. These records carry NO properties on purpose: they exist
only to bridge legacy ``mp-XXXX`` ids into the pool by id match and
fingerprint, hence always_hash=True for the whole source.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
import zipfile
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_MP_ID = re.compile(r"^(mp-\d+|mvc-\d+)")

_WBM_FIELDS = (
    (
        "e_form_per_atom_mp2020_corrected",
        "formation_energy_per_atom",
        "eV/atom",
        "PBE (WBM) MP2020-corrected",
    ),
    (
        "e_above_hull_mp2020_corrected_ppd_mp",
        "energy_above_hull",
        "eV/atom",
        "PBE (WBM) MP2020-corrected",
    ),
    ("bandgap_pbe", "band_gap", "eV", "PBE (WBM)"),
    (
        "e_form_per_atom_wbm",
        "formation_energy_per_atom",
        "eV/atom",
        "PBE (WBM) uncorrected, WBM reference",
    ),
    (
        "e_above_hull_wbm",
        "energy_above_hull",
        "eV/atom",
        "PBE (WBM) uncorrected, WBM hull",
    ),
)

#: canonical name -> physically plausible window; outside is dropped and counted
_RANGES = {
    "formation_energy_per_atom": (-20.0, 20.0),
    "energy_above_hull": (-20.0, 20.0),
    "band_gap": (0.0, 30.0),
    "total_energy_per_atom": (-500.0, 50.0),
}


class MatbenchDiscoveryAdapter(SourceAdapter):
    source_key = "matbench-discovery"
    always_hash = True
    properties_only = False

    def __init__(self, root=None) -> None:
        super().__init__(root)
        self.drops: Counter[str] = Counter()

    def _guard(self, value: float | None, name: str) -> float | None:
        """Return value when finite and physically plausible, else None."""

        if value is None:
            return None
        low, high = _RANGES[name]
        if not (low <= value <= high):
            self.drops[name] += 1
            return None
        return value

    def _iter_wbm(self, budget: int | None) -> Iterator[SourceRecord]:
        from ase.io import read as ase_read
        from pymatgen.io.ase import AseAtomsAdaptor

        summary = self.root / "2023-12-13-wbm-summary.csv.gz"
        archive = self.root / "2024-08-04-wbm-relaxed-atoms.extxyz.zip"
        count = 0
        missing_structs = 0
        with zipfile.ZipFile(archive) as bundle:
            members = set(bundle.namelist())
            with gzip.open(summary, "rt", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    if budget is not None and count >= budget:
                        return
                    material_id = safe_text(row.get("material_id"))
                    if not material_id:
                        continue
                    properties = []
                    for column, name, unit, method in _WBM_FIELDS:
                        value = self._guard(safe_float(row.get(column)), name)
                        if value is not None:
                            properties.append(
                                PropertyValue(name, value, unit, method)
                            )
                    total = safe_float(row.get("uncorrected_energy"))
                    n_sites = safe_float(row.get("n_sites"))
                    if total is not None and n_sites is not None and n_sites > 0:
                        value = self._guard(
                            total / n_sites, "total_energy_per_atom"
                        )
                        if value is not None:
                            properties.append(
                                PropertyValue(
                                    "total_energy_per_atom",
                                    value,
                                    "eV/atom",
                                    "PBE (WBM) uncorrected",
                                )
                            )
                    prototype = safe_text(row.get("wyckoff_spglib"))
                    if prototype:
                        properties.append(
                            PropertyValue(
                                "structure_prototype",
                                prototype,
                                None,
                                "AFLOW Wyckoff label (spglib, WBM relaxed)",
                            )
                        )
                    structure = None
                    member = f"{material_id}.extxyz"
                    if member in members:
                        try:
                            atoms = ase_read(
                                io.StringIO(bundle.read(member).decode("utf-8")),
                                format="extxyz",
                            )
                            structure = AseAtomsAdaptor.get_structure(atoms)
                        except Exception:  # noqa: BLE001 - keep property record
                            structure = None
                    if structure is None:
                        missing_structs += 1
                    yield SourceRecord(
                        native_id=material_id,
                        properties=properties,
                        structure=structure,
                    )
                    count += 1
        if missing_structs:
            print(
                f"[matbench-discovery] {missing_structs:,} WBM rows without "
                "a relaxed structure",
                flush=True,
            )
        print(
            "[matbench-discovery] value drops: "
            + (str(dict(self.drops)) if self.drops else "none"),
            flush=True,
        )

    def _iter_mp_bridge(self, budget: int | None) -> Iterator[SourceRecord]:
        import ijson
        from pymatgen.core import Structure

        path = self.root / "2023-02-07-mp-computed-structure-entries.json.gz"
        count = 0
        skipped = 0
        with gzip.open(path, "rb") as handle:
            # use_float=True: Decimal values break Structure.from_dict
            for _, entry in ijson.kvitems(handle, "entry", use_float=True):
                if budget is not None and count >= budget:
                    return
                data = entry.get("data") or {}
                material_id = safe_text(data.get("material_id"))
                if not material_id:
                    hit = _MP_ID.match(str(entry.get("entry_id") or ""))
                    material_id = hit.group(1) if hit else None
                if not material_id:
                    skipped += 1
                    continue
                try:
                    structure = Structure.from_dict(entry["structure"])
                except Exception:  # noqa: BLE001 - skip broken entries
                    skipped += 1
                    continue
                match_ids = []
                pair = normalize_match_id("materials-project", material_id)
                if pair:
                    match_ids.append(pair)
                yield SourceRecord(
                    native_id=material_id,
                    properties=[],  # bridge records carry no property values
                    structure=structure,
                    match_ids=match_ids,
                )
                count += 1
        if skipped:
            print(
                f"[matbench-discovery] {skipped:,} MP bridge entries skipped",
                flush=True,
            )

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        for record in self._iter_wbm(limit):
            yield record
            count += 1
        remaining = None if limit is None else max(limit - count, 0)
        if remaining == 0:
            return
        yield from self._iter_mp_bridge(remaining)
