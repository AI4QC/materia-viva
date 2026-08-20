"""Boyd 2019 wet flue-gas carbon-capture MOFs (Materials Cloud 2018.0016/v3).

Two archives: ``screening_data.tar.gz`` member ``all_MOFs_screening_data.csv``
(324,426 rows keyed by MOFname; the CSV column headers carry the units) and
``MOF_database.tar.gz`` with one ``<MOFname>.cif`` per MOF (fapswitch CIFs
with partial charges, passed through verbatim).

The CSV (~few floats per row) is loaded into a dict first; the 1.2 GB CIF
tar is then streamed strictly sequentially (``r|gz``) so ``--limit`` stops
after decompressing only the head of the archive. The table holds one plain
tuple of already-scaled floats per MOF (not PropertyValue objects, which cost
~4x the memory over 324k rows); the objects are built per record on yield.

Units, verified against the CSV headers:
- uptakes / working capacities: mmol/g == mol/kg (matches canonical unit);
- heat of adsorption: kcal/mol in the CSV, converted here to kJ/mol
  (x 4.184); values are positive magnitudes of the (exothermic) adsorption
  enthalpy and the sign is kept as published;
- void volume: cm^3/g, ingested as ``pore_volume``;
- geometry from Zeo++: diameters in Å, surface area in m²/g.

The screening ran GCMC at three single-component CO2 conditions
(0.15 bar/298 K, 0.10 bar/363 K, 0.70 bar/413 K) and one binary CO2/N2
flue-gas mixture (CO2 at 0.15 bar, N2 at 0.85 bar, 298 K), each with its own
uptake and heat of adsorption. Every row therefore carries several values of
the same canonical property, so each method string names the exact partial
pressure and temperature, and the binary rows say so.

The two working capacities are exact differences of the uptake columns
(verified row-by-row on the full CSV):
``vacuum swing = n(0.15 bar, 298 K) - n(0.10 bar, 363 K)`` and
``temperature swing = n(0.15 bar, 298 K) - n(0.70 bar, 413 K)``; the swing
endpoints are named in the temperature-swing method string (the vacuum-swing
method predates this and is left untouched).

Caution — the three sphere-diameter column labels are permuted relative to
Zeo++ semantics: taken literally they give PLD >= LCD for every MOF, which
is geometrically impossible. Over the full CSV the ordering
``largest_free_sphere [col] >= largest_included_sphere [col] >=
largest_included_sphere_along_free_sphere_path [col]`` holds without
exception, matching Zeo++'s Di >= Dif >= Df output order under the shifted
labels. We therefore ingest the ``largest_free_sphere_diameter`` column as
the largest cavity diameter (Di) and the
``largest_included_sphere_along_free_sphere_path_diameter`` column as the
pore-limiting diameter (Df). The remaining ``largest_included_sphere_diameter``
column would be Dif under the same shift; it is left out because the label
permutation makes that assignment the least certain of the three.

Deliberately not ingested: the ``*_error_*`` Monte-Carlo error bars; the
``excess_*`` uptakes (the same measurement minus the bulk gas in the pore
volume, and visibly corrupted — one excess column reaches 363 mmol/g against
an absolute maximum of 6); ``volume``/``weight`` (structure-derived, already
~100% covered pool-wide); and the ``metal_linker`` / ``organic_linker1`` /
``organic_linker2`` / ``functional_groups`` building-block indices, which are
construction provenance rather than measured quantities.

Only the sane scalar subset below is ingested. No cross-database ids.
"""

from __future__ import annotations

import csv
import io
import sys
import tarfile
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_PROPS_TAR = "screening_data.tar.gz"
_PROPS_MEMBER = "all_MOFs_screening_data.csv"
_STRUCTS_TAR = "MOF_database.tar.gz"

_KCAL_TO_KJ = 4.184

#: plausibility windows applied to the newly mapped columns. The eight columns
#: that were already ingested keep ``None`` so their staged values stay
#: byte-for-byte identical to previous runs (they include -1 "not computed"
#: diameter sentinels, which are left as published rather than silently
#: changing what earlier loads recorded).
_UPTAKE_RANGE = (0.0, 200.0)  # mol/kg
_HEAT_RANGE = (-50.0, 200.0)  # kJ/mol, small negatives are published GCMC noise
_CAPACITY_RANGE = (-50.0, 200.0)  # mol/kg, a swing may be slightly negative
_PORE_VOLUME_RANGE = (0.0, 50.0)  # cm³/g

# CSV column -> (canonical/new name, unit, method, scale, bounds)
_COLUMNS = (
    (
        "CO2_uptake_P0.15bar_T298K [mmol/g]",
        "co2_uptake", "mol/kg", "GCMC 0.15bar 298K", 1.0, None,
    ),
    (
        "heat_adsorption_CO2_P0.15bar_T298K [kcal/mol]",
        "co2_heat_of_adsorption", "kJ/mol", "GCMC 0.15bar 298K", _KCAL_TO_KJ, None,
    ),
    (
        "CO2_uptake_P0.10bar_T363K [mmol/g]",
        "co2_uptake", "mol/kg", "GCMC 0.10bar 363K", 1.0, _UPTAKE_RANGE,
    ),
    (
        "heat_adsorption_CO2_P0.10bar_T363K [kcal/mol]",
        "co2_heat_of_adsorption", "kJ/mol", "GCMC 0.10bar 363K", _KCAL_TO_KJ,
        _HEAT_RANGE,
    ),
    (
        "CO2_uptake_P0.70bar_T413K [mmol/g]",
        "co2_uptake", "mol/kg", "GCMC 0.70bar 413K", 1.0, _UPTAKE_RANGE,
    ),
    (
        "heat_adsorption_CO2_P0.70bar_T413K [kcal/mol]",
        "co2_heat_of_adsorption", "kJ/mol", "GCMC 0.70bar 413K", _KCAL_TO_KJ,
        _HEAT_RANGE,
    ),
    (
        "CO2_binary_uptake_P0.15bar_T298K [mmol/g]",
        "co2_uptake", "mol/kg", "GCMC binary CO2/N2 0.15bar 298K", 1.0,
        _UPTAKE_RANGE,
    ),
    (
        "heat_adsorption_CO2_binary_P0.15bar_T298K [kcal/mol]",
        "co2_heat_of_adsorption", "kJ/mol", "GCMC binary CO2/N2 0.15bar 298K",
        _KCAL_TO_KJ, _HEAT_RANGE,
    ),
    (
        "N2_binary_uptake_P0.85bar_T298K [mmol/g]",
        "n2_uptake", "mol/kg", "GCMC binary CO2/N2 0.85bar 298K", 1.0,
        _UPTAKE_RANGE,
    ),
    (
        "heat_adsorption_N2_binary_P0.85bar_T298K [kcal/mol]",
        "n2_heat_of_adsorption", "kJ/mol", "GCMC binary CO2/N2 0.85bar 298K",
        _KCAL_TO_KJ, _HEAT_RANGE,
    ),
    (
        "CO2/N2_selectivity",
        "co2_n2_selectivity", None, "GCMC binary 0.15/0.85bar 298K", 1.0, None,
    ),
    (
        "working_capacity_vacuum_swing [mmol/g]",
        "working_capacity_vacuum_swing", "mol/kg", "GCMC VSA", 1.0, None,
    ),
    (
        "working_capacity_temperature_swing [mmol/g]",
        "working_capacity_temperature_swing", "mol/kg",
        "GCMC TSA 0.15bar 298K -> 0.70bar 413K", 1.0, _CAPACITY_RANGE,
    ),
    (
        "surface_area [m^2/g]",
        "surface_area_gravimetric", "m²/g", "zeo++", 1.0, None,
    ),
    ("void_fraction", "void_fraction", None, "zeo++", 1.0, None),
    (
        "void_volume [cm^3/g]",
        "pore_volume", "cm³/g", "zeo++", 1.0, _PORE_VOLUME_RANGE,
    ),
    # column labels are permuted vs Zeo++ Di/Df/Dif — see module docstring
    (
        "largest_free_sphere_diameter [A]",
        "largest_cavity_diameter", "Å", "zeo++", 1.0, None,
    ),
    (
        "largest_included_sphere_along_free_sphere_path_diameter [A]",
        "pore_limiting_diameter", "Å", "zeo++", 1.0, None,
    ),
)

#: three-letter RCSR net the hypothetical framework was assembled on
_TOPOLOGY_COLUMN = "topology"
_TOPOLOGY_METHOD = "RCSR topology (construction)"
_TOPOLOGY_OK = frozenset(
    {"acs", "bcu", "etb", "fof", "nbo", "pcu", "pts", "rht", "sra", "tbo", "the"}
)


class MofCarbonCaptureAdapter(SourceAdapter):
    source_key = "mof-carbon-capture"
    always_hash = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        #: per-column count of values rejected by the plausibility windows
        self.drops: Counter[str] = Counter()

    def _load_screening(self) -> tuple[dict[str, tuple], dict[str, str]]:
        table: dict[str, tuple] = {}
        topologies: dict[str, str] = {}
        with tarfile.open(self.root / _PROPS_TAR, "r:gz") as tar:
            handle = tar.extractfile(_PROPS_MEMBER)
            if handle is None:
                raise FileNotFoundError(_PROPS_MEMBER)
            reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8"))
            for row in reader:
                name = (row.get("MOFname") or "").strip()
                if not name:
                    continue
                values: list[float | None] = []
                for column, _prop, _unit, _method, scale, bounds in _COLUMNS:
                    value = safe_float(row.get(column))  # 'N/A'/inf/nan -> None
                    if value is not None:
                        value *= scale
                        if bounds is not None and not bounds[0] <= value <= bounds[1]:
                            self.drops[column] += 1
                            value = None
                    values.append(value)
                table[name] = tuple(values)
                topology = safe_text(row.get(_TOPOLOGY_COLUMN))
                if topology and topology.lower() in _TOPOLOGY_OK:
                    topologies[name] = topology.lower()
                elif topology:
                    self.drops[_TOPOLOGY_COLUMN] += 1
        return table, topologies

    @staticmethod
    def _properties(values: tuple, topology: str | None) -> list[PropertyValue]:
        properties = [
            PropertyValue(prop, value, unit, method)
            for value, (_column, prop, unit, method, _scale, _bounds) in zip(
                values, _COLUMNS
            )
            if value is not None
        ]
        if topology:
            properties.append(
                PropertyValue(
                    "structure_prototype", topology, None, _TOPOLOGY_METHOD
                )
            )
        return properties

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        screening, topologies = self._load_screening()
        count = 0
        try:
            # r|gz streams the tar member-by-member without seeking.
            with tarfile.open(self.root / _STRUCTS_TAR, "r|gz") as tar:
                for member in tar:
                    if not member.isfile() or not member.name.endswith(".cif"):
                        continue
                    if limit is not None and count >= limit:
                        return
                    name = member.name.rsplit("/", 1)[-1][: -len(".cif")]
                    handle = tar.extractfile(member)
                    if handle is None:
                        continue
                    cif = handle.read().decode("utf-8", "replace")
                    count += 1
                    yield SourceRecord(
                        native_id=name,
                        properties=self._properties(
                            screening.pop(name, ()), topologies.pop(name, None)
                        ),
                        structure=cif,
                    )
        finally:
            if self.drops:
                print(
                    f"[mof-carbon-capture] out-of-range values dropped: "
                    f"{dict(self.drops)}",
                    file=sys.stderr,
                    flush=True,
                )
