"""GNoME: DeepMind's stable-crystal discovery set (554k PBE-relaxed structures).

Two CSVs plus one zip of per-material CIFs:

* ``stable_materials_summary.csv`` — one row per MaterialId with PBE energetics
  and band gaps; this drives iteration.
* ``stable_materials_r2scan.csv`` — r2SCAN re-relaxations for a subset
  (139,541 rows, every energetic column populated); they join the matching
  summary record with ``r2SCAN GNoME`` method tags. r2SCAN-only ids (no summary
  row / no CIF) are skipped and counted.
* ``by_id.zip`` member ``by_id/<MaterialId>.CIF`` — passed through verbatim as
  the record structure. Summary rows without a CIF are still yielded with
  structure=None (the pipeline counts them as unmatched).

Both CSVs publish FOUR decomposition energies per row, each measured against a
different reference set of competing phases, so each is staged as its own
``decomposition_energy`` row with the hull named in the method string. The
plain column keeps its original bare method for backwards compatibility.

``Corrected Energy`` is a cell total (MP2020-compatible corrections applied);
dividing by ``NSites`` gives the ``total_energy_per_atom`` GNoME otherwise
never contributes. ``Uncorrected Energy`` is deliberately skipped as redundant
with it, as are the per-row provenance path, the train/test flag, and the
structure-derived Volume/Density/Space Group/Crystal System columns.

No cross-database ids are published, so every record goes through hashing
anyway (always_hash stays False — there are no id matches to short-circuit).
"""

from __future__ import annotations

import csv
import zipfile
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_PBE_FIELDS = (
    ("Formation Energy Per Atom", "formation_energy_per_atom", "eV/atom"),
    ("Decomposition Energy Per Atom", "decomposition_energy", "eV/atom"),
    ("Bandgap", "band_gap", "eV"),
)

#: (csv column, method suffix naming the convex hull the value is measured
#: against). "All" is GNoME's hull over every reference set including its own
#: predictions; "MP" and "MP OQMD" restrict the competing phases to those
#: databases. The bare "Decomposition Energy Per Atom" column keeps the plain
#: method above and is not repeated here.
_DECOMPOSITION_HULLS = (
    ("Decomposition Energy Per Atom MP", "vs MP hull"),
    ("Decomposition Energy Per Atom MP OQMD", "vs MP+OQMD hull"),
    ("Decomposition Energy Per Atom All", "vs GNoME hull"),
)

#: r2SCAN columns staged from stable_materials_r2scan.csv, in cache order.
#: The first entry reproduces the adapter's original single mapping verbatim.
_R2SCAN_FIELDS = (
    ("Formation Energy Per Atom", "formation_energy_per_atom", "r2SCAN GNoME"),
    ("Decomposition Energy Per Atom", "decomposition_energy", "r2SCAN GNoME"),
    (
        "Decomposition Energy Per Atom MP",
        "decomposition_energy",
        "r2SCAN GNoME vs MP hull",
    ),
    (
        "Decomposition Energy Per Atom MP OQMD",
        "decomposition_energy",
        "r2SCAN GNoME vs MP+OQMD hull",
    ),
    (
        "Decomposition Energy Per Atom All",
        "decomposition_energy",
        "r2SCAN GNoME vs GNoME hull",
    ),
)

#: Cheon's dimensionality classifier labels. The raw column also carries a
#: literal "inf" for ~0.06% of rows (classifier failure), which is dropped.
_DIMENSIONALITY_LABELS = {
    "0D",
    "1D",
    "2D",
    "3D",
    "intercalated ion",
    "intercalated molecule",
}

#: physically plausible windows; anything outside is dropped and counted
_DECOMPOSITION_RANGE = (-50.0, 50.0)  # eV/atom
_TOTAL_ENERGY_RANGE = (-500.0, 50.0)  # eV/atom, r2SCAN totals reach -71


class GnomeAdapter(SourceAdapter):
    source_key = "gnome"
    always_hash = False
    properties_only = False

    def __init__(self, root=None) -> None:
        super().__init__(root)
        self.drops: Counter[str] = Counter()

    def _guard(self, value: float | None, window: tuple[float, float], tag: str):
        """Return value when finite and inside window, else None (counted)."""

        if value is None:
            return None
        low, high = window
        if not (low <= value <= high):
            self.drops[tag] += 1
            return None
        return value

    def _energy_per_atom(self, row: dict) -> float | None:
        """Corrected cell energy / NSites, guarded."""

        total = safe_float(row.get("Corrected Energy"))
        sites = safe_float(row.get("NSites"))
        if total is None or sites is None or sites <= 0:
            return None
        return self._guard(total / sites, _TOTAL_ENERGY_RANGE, "total_energy_per_atom")

    def _r2scan_values(self) -> dict[str, tuple]:
        """MaterialId -> (values for _R2SCAN_FIELDS..., total energy per atom)."""

        cache: dict[str, tuple] = {}
        path = self.root / "stable_materials_r2scan.csv"
        if not path.exists():
            return cache
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                material_id = safe_text(row.get("MaterialId"))
                if not material_id:
                    continue
                values = []
                for column, name, _method in _R2SCAN_FIELDS:
                    value = safe_float(row.get(column))
                    if name == "decomposition_energy":
                        value = self._guard(
                            value, _DECOMPOSITION_RANGE, "r2scan_decomposition_energy"
                        )
                    values.append(value)
                values.append(self._energy_per_atom(row))
                if any(value is not None for value in values):
                    cache[material_id] = tuple(values)
        return cache

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        r2scan = self._r2scan_values()
        summary = self.root / "stable_materials_summary.csv"
        count = 0
        missing_cif = 0
        with zipfile.ZipFile(self.root / "by_id.zip") as bundle:
            members = set(bundle.namelist())
            with summary.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if limit is not None and count >= limit:
                        break
                    material_id = safe_text(row.get("MaterialId"))
                    if not material_id:
                        continue
                    properties = []
                    for column, name, unit in _PBE_FIELDS:
                        value = safe_float(row.get(column))
                        if value is not None:
                            properties.append(
                                PropertyValue(name, value, unit, "PBE GNoME")
                            )
                    for column, hull in _DECOMPOSITION_HULLS:
                        value = self._guard(
                            safe_float(row.get(column)),
                            _DECOMPOSITION_RANGE,
                            "pbe_decomposition_energy",
                        )
                        if value is not None:
                            properties.append(
                                PropertyValue(
                                    "decomposition_energy",
                                    value,
                                    "eV/atom",
                                    f"PBE GNoME {hull}",
                                )
                            )
                    energy_per_atom = self._energy_per_atom(row)
                    if energy_per_atom is not None:
                        properties.append(
                            PropertyValue(
                                "total_energy_per_atom",
                                energy_per_atom,
                                "eV/atom",
                                "PBE GNoME MP2020-corrected",
                            )
                        )
                    dimensionality = safe_text(row.get("Dimensionality Cheon"))
                    if dimensionality in _DIMENSIONALITY_LABELS:
                        properties.append(
                            PropertyValue(
                                "dimensionality",
                                dimensionality,
                                None,
                                "Cheon classifier (GNoME)",
                            )
                        )
                    elif dimensionality is not None:
                        self.drops["dimensionality_label"] += 1
                    r2scan_values = r2scan.pop(material_id, None)
                    if r2scan_values is not None:
                        for (_column, name, method), value in zip(
                            _R2SCAN_FIELDS, r2scan_values
                        ):
                            if value is not None:
                                properties.append(
                                    PropertyValue(name, value, "eV/atom", method)
                                )
                        if r2scan_values[-1] is not None:
                            properties.append(
                                PropertyValue(
                                    "total_energy_per_atom",
                                    r2scan_values[-1],
                                    "eV/atom",
                                    "r2SCAN GNoME",
                                )
                            )
                    member = f"by_id/{material_id}.CIF"
                    if member in members:
                        structure = bundle.read(member).decode("utf-8")
                    else:
                        structure = None
                        missing_cif += 1
                    yield SourceRecord(
                        native_id=material_id,
                        properties=properties,
                        structure=structure,
                    )
                    count += 1
        # Full pass finished: whatever is left in the r2scan map has no
        # summary row (hence no CIF in by_id.zip) and is skipped by design.
        # (On a --limit run the leftovers are simply the untouched tail.)
        print(
            f"[gnome] {missing_cif:,} summary rows without CIF, "
            f"{len(r2scan):,} r2SCAN-only ids skipped"
            + (f", drops: {dict(self.drops)}" if self.drops else ", no value drops"),
            flush=True,
        )
