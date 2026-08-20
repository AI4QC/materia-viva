"""SPSE: solid-state electrolyte screening database (BVSE barriers + literature).

One zip of Mongo-export JSONL files. Structures (cifs.json) are ICSD-derived
and not redistributable, so this source is properties_only with structure=None;
records with origin 'icsd' match the experimental pool via their ICSD number.

Ingested files:
- bvse.json: bond-valence migration barriers along the 1D/2D/3D percolation
  channels, in two flavours that the file stores side by side. ``bvse_*`` is
  the bond-valence *site energy* barrier (cation-framework interaction only);
  ``bvel_*`` is the bond-valence *energy landscape* barrier, which adds the
  Coulomb repulsion of the mobile-ion sublattice and is the value normally
  compared with NEB/experiment. Both are eV and both are staged as
  migration_barrier rows, told apart by their method strings
  'BVSE 1D/2D/3D <ion>' and 'BVEL 1D/2D/3D <ion>'.
- literature_properties.json: experimental conductivities / activation
  energies / band gaps hand-collected from papers. Values are messy strings
  (fullwidth tildes, parenthetical uncertainties or atmospheres, python-list
  strings paired with temperature lists) and are cleaned conservatively.

Skipped: cifs.json (structures), cavd.json (geometric channel descriptors),
conduction_descriptors.json (descriptor soup), hierarchical_calculation_data
(NEB path data).
"""

from __future__ import annotations

import ast
import json
import re
import zipfile
from typing import Any, Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_ARCHIVE = "SPSE_database_data.zip"
_BVSE = "SPSE_database_data/bvse.json"
_LITERATURE = "SPSE_database_data/literature_properties.json"

# strip ~ / fullwidth ～, parenthetical uncertainty "(6)" or atmosphere
# "（Ar）", and "Ea(b)=" style prefixes before parsing a literature number
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")


def _clean_number(value: Any) -> float | None:
    if value is None or isinstance(value, (int, float, bool)):
        return safe_float(value)
    text = str(value).strip().lstrip("~～≈")
    if "=" in text:
        text = text.rsplit("=", 1)[-1]
    text = _PAREN_RE.sub("", text).strip()
    if "/" in text:  # e.g. '0.66/0.529' - ambiguous, drop
        return None
    return safe_float(text)


def _as_list(value: Any) -> list:
    """Literature fields hold either a scalar or a python-list string."""

    if value is None:
        return []
    if isinstance(value, list):
        return value
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            return []
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _temp_method(temp: Any) -> str:
    """'673.15K' -> 'experiment 673.15K'; 'RT' -> 'experiment RT'."""

    if temp is None:
        return "experiment"
    text = str(temp).strip()
    if not text:
        return "experiment"
    if text.upper() == "RT":
        return "experiment RT"
    number = safe_float(text.rstrip("Kk").strip())
    if number is None:
        return "experiment"
    if number == int(number):
        return f"experiment {int(number)}K"
    return f"experiment {number}K"


class SpseAdapter(SourceAdapter):
    source_key = "spse"
    properties_only = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        with zipfile.ZipFile(self.root / _ARCHIVE) as bundle:
            for record in self._iter_bvse(bundle):
                if limit is not None and count >= limit:
                    return
                count += 1
                yield record
            for record in self._iter_literature(bundle):
                if limit is not None and count >= limit:
                    return
                count += 1
                yield record

    @staticmethod
    def _base_record(row: dict) -> SourceRecord:
        origin = str(row.get("origin") or "unknown").strip()
        origin_id = str(row.get("origin_id") or "").strip()
        match_ids = []
        if origin == "icsd":
            icsd = normalize_match_id("icsd", origin_id)
            if icsd:
                match_ids.append(icsd)
        return SourceRecord(
            native_id=f"{origin}:{origin_id}",
            structure=None,
            match_ids=match_ids,
        )

    def _iter_bvse(self, bundle: zipfile.ZipFile) -> Iterator[SourceRecord]:
        with bundle.open(_BVSE) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                ion = str(row.get("transport_ion") or "").strip()
                properties = []
                for key, flavour, dim in (
                    ("bvse_1d", "BVSE", "1D"),
                    ("bvse_2d", "BVSE", "2D"),
                    ("bvse_3d", "BVSE", "3D"),
                    ("bvel_1d", "BVEL", "1D"),
                    ("bvel_2d", "BVEL", "2D"),
                    ("bvel_3d", "BVEL", "3D"),
                ):
                    value = safe_float(row.get(key))
                    # 20000.0 is the 'no percolation path' sentinel; real
                    # grid values top out around 20 eV
                    if value is not None and 0 < value < 1000:
                        method = f"{flavour} {dim}" + (f" {ion}" if ion else "")
                        properties.append(
                            PropertyValue("migration_barrier", value, "eV", method)
                        )
                if not properties:
                    continue
                record = self._base_record(row)
                record.properties = properties
                yield record

    def _iter_literature(self, bundle: zipfile.ZipFile) -> Iterator[SourceRecord]:
        with bundle.open(_LITERATURE) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                properties = []
                # experimental ionic conductivity, paired with temperatures
                values = _as_list(row.get("conductivity_experimental_value"))
                temps = _as_list(row.get("conductivity_experimental_value_temp"))
                if len(temps) != len(values):
                    temps = [
                        temps[0] if len(temps) == 1 else None
                        for _ in values
                    ]
                for raw, temp in zip(values, temps):
                    value = _clean_number(raw)
                    if value is not None and value > 0:
                        properties.append(
                            PropertyValue(
                                "ionic_conductivity", value, "S/cm",
                                _temp_method(temp),
                            )
                        )
                # experimental activation energy -> migration barrier
                for raw in _as_list(row.get("activation_energy_experimental_value")):
                    value = _clean_number(raw)
                    # cap guards obvious typos, e.g. '026(2)' meaning 0.26
                    if value is not None and 0 < value < 5:
                        properties.append(
                            PropertyValue(
                                "migration_barrier", value, "eV",
                                "experiment activation energy",
                            )
                        )
                gap = safe_float(row.get("band_gap"))
                if gap is not None and gap >= 0:
                    properties.append(
                        PropertyValue("band_gap", gap, "eV", "literature")
                    )
                if not properties:
                    continue
                record = self._base_record(row)
                record.properties = properties
                yield record
