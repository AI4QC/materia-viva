"""3DSC: SuperCon Tc labels matched to Materials Project / ICSD structures.

Properties-only source: the shipped "synth_doped" CIFs are artificial
partial-occupancy constructions, so no structure is ever ingested; records
attach through their MP / ICSD match ids alone (structure=None, no hashing).

Two files inside 3DSC-main.zip:
- superconductors_3D/data/final/MP/3DSC_MP.csv (one '#' comment line, then a
  92-column header; quoted fields contain embedded newlines, handled by the
  csv module) -> MP variant with ('materials-project', material_id_2) plus one
  ('icsd', n) per entry of the icsd_ids_2 python-list string.
- superconductors_3D/data/final/ICSD/3DSC_ICSD_only_IDs.csv (one quoted
  comment line that does NOT start with '#', then the header) -> ICSD variant
  with ('icsd', database_id_2), values like "ICSD-604645".

Rows with tc <= 0 (SuperCon's labeled non-superconductors: 1,778 of 5,773 MP
rows and 20,580 of 86,490 ICSD rows) are skipped entirely: emitting 0 K would
read as a real transition temperature, and a properties-only record without
properties is useless.

``sc_class`` (SuperCon's family label: Other / Cuprate / Ferrite /
Heavy_fermion / Oxide / Chevrel / Carbon and the handful of concatenated
double labels) is staged as ``superconductor_class`` on the MP file only —
the 4-column ICSD-only file does not carry it. Everything named ``*_2`` is
Materials Project data relabelled (band_gap_2, e_above_hull_2, density_2,
total_magnetization_2, spacegroup_2, ...) and is never ingested: the pool
already holds it from the materials-project source itself.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_MP_MEMBER = "3DSC-main/superconductors_3D/data/final/MP/3DSC_MP.csv"
_ICSD_MEMBER = "3DSC-main/superconductors_3D/data/final/ICSD/3DSC_ICSD_only_IDs.csv"
_METHOD_MAX = 60


def _method(formula: str) -> str:
    """Self-describing per-row tag: one material carries many doped entries."""

    return f"SuperCon-matched; doped formula {formula}"[:_METHOD_MAX]


def _tc_property(row: dict, formula: str) -> PropertyValue | None:
    tc = safe_float(row.get("tc"))
    if tc is None or tc <= 0:
        return None
    return PropertyValue("tc_superconducting", tc, "K", _method(formula))


def _class_property(row: dict, formula: str) -> PropertyValue | None:
    label = safe_text(row.get("sc_class"))
    if not label:
        return None
    return PropertyValue(
        "superconductor_class", label, None, _method(formula)
    )


class ThreeDscAdapter(SourceAdapter):
    source_key = "3dsc"
    properties_only = True
    always_hash = False

    def _rows(self, bundle: zipfile.ZipFile, member: str) -> Iterator[tuple[int, dict]]:
        """Yield (file row index, row dict), skipping the one comment line."""

        with bundle.open(member) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", newline="")
            text.readline()  # comment line (may be quoted, so not comment='#')
            reader = csv.DictReader(text)
            yield from enumerate(reader)

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        with zipfile.ZipFile(self.root / "3DSC-main.zip") as bundle:
            for index, row in self._rows(bundle, _MP_MEMBER):
                if limit is not None and count >= limit:
                    return
                formula = safe_text(row.get("formula_sc")) or ""
                mp_id = safe_text(row.get("material_id_2"))
                prop = _tc_property(row, formula)
                if prop is None:
                    continue
                properties = [prop]
                sc_class = _class_property(row, formula)
                if sc_class is not None:
                    properties.append(sc_class)
                match_ids = []
                mp_match = normalize_match_id("materials-project", mp_id)
                if mp_match:
                    match_ids.append(mp_match)
                for code in re.findall(r"\d+", row.get("icsd_ids_2") or ""):
                    icsd = normalize_match_id("icsd", code)
                    if icsd:
                        match_ids.append(icsd)
                count += 1
                yield SourceRecord(
                    native_id=f"mp:{formula}:{mp_id}:{index}",
                    properties=properties,
                    structure=None,
                    match_ids=match_ids,
                )
            for index, row in self._rows(bundle, _ICSD_MEMBER):
                if limit is not None and count >= limit:
                    return
                formula = safe_text(row.get("formula_sc")) or ""
                icsd_id = safe_text(row.get("database_id_2"))
                prop = _tc_property(row, formula)
                if prop is None:
                    continue
                match_ids = []
                icsd = normalize_match_id("icsd", icsd_id)
                if icsd:
                    match_ids.append(icsd)
                count += 1
                yield SourceRecord(
                    native_id=f"icsd:{formula}:{icsd_id}:{index}",
                    properties=[prop],
                    structure=None,
                    match_ids=match_ids,
                )
