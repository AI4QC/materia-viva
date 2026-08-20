"""MOFX-DB: Zeo++ geometry and GCMC gas uptakes for MOF/zeolite frameworks.

Per-subset zip64 archives of per-MOF JSON files (Info-ZIP chokes on them, so
they are streamed with python zipfile member by member). The hMOF subset is
skipped entirely — its 137,953 records are already ingested by the ``hmof``
source. Remaining subsets: CoREMOF-2014, CoREMOF-2019, IZA, PCOD-syn and
Tobacco (~30.6k records).

Structures are the verbatim ``cif`` text from each JSON. CoREMOF entries are
CSD-derived experimentally synthesised MOFs and IZA entries are real zeolite
frameworks (experimental pool); PCOD-syn and Tobacco are hypothetical.
PCOD-syn ids look like deem-zeolites pcod ids, but nothing in the pool
references the pcod scheme, so no match_ids are emitted anywhere.

Isotherm *arrays* are still not ingested: per record, per adsorbate and per
simulated temperature, exactly one scalar is kept — the data point closest to
1 bar — and its method string names the temperature, the actual pressure and
the molecule forcefield, so the several rows a record contributes to the same
canonical property stay distinguishable. ``heats[]`` are skipped.

What the raw archives actually contain (surveyed across all five subsets):

===============  =========  ==============  =============  ================
subset           T (K)      adsorbate       pressureUnits  adsorptionUnits
===============  =========  ==============  =============  ================
CoREMOF-2014/19  77         N2              Pa             cm3(STP)/g
CoREMOF-2014/19  87         Ar              Pa             cm3(STP)/g
IZA, PCOD-syn    77 … 276   H2              bar            g/l
Tobacco          77 … 243   H2              bar            g/l
Tobacco          298        Xe + Kr binary  bar            mmol/g
Tobacco          298        CH4             bar            cm3(STP)/cm3
===============  =========  ==============  =============  ================

The previous filter accepted only ``pressureUnits == 'bar'``, only mol/kg and
mg/g adsorption units, only single-adsorbate isotherms and only 273-313 K, so
it matched nothing at all in the table above and this gas-adsorption source
staged zero uptake rows. All four gates are fixed here:

* pressures are converted to bar from the units actually present (bar, Pa)
  plus the obvious neighbours, instead of being rejected;
* ``cm3(STP)/g`` is gravimetric, not volumetric — it converts to mol/kg by
  dividing by the molar volume of an ideal gas at STP, 22.414 L/mol;
* the temperature window is widened to 50-400 K, which admits the 77 K N2 /
  87 K Ar porosimetry isotherms that make up both CoREMOF subsets; the
  temperature is part of every method string, so the rows stay self-describing;
* multi-adsorbate isotherms are read per species out of ``species_data``
  rather than dropped, with the mixture and the species' gas-phase mole
  fraction in the method string (Tobacco's 298 K Xe/Kr separation runs).

Units are pinned by the canonical registry, which stores one unit per property
name: every ``*_uptake`` is mol/kg except ``h2_uptake``, whose canonical unit
is the volumetric g/L that MOFX-DB's H2 isotherms already use, so those pass
through unconverted. Volumetric values for the mol/kg properties
(``cm3(STP)/cm3``, ``v/v``) are skipped rather than guessing framework
densities, and a gravimetric H2 isotherm would likewise be skipped rather than
mixing units under one property name (none occurs in these archives).
"""

from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_SUBSET_PREFIXES = ("CoREMOF-2014", "CoREMOF-2019", "IZA", "PCOD-syn", "Tobacco")

_GEOMETRY_METHOD = "zeo++ (MOFX-DB)"
# native key -> (canonical name, unit, skip exact zero)
_GEOMETRY_FIELDS = (
    ("lcd", "largest_cavity_diameter", "Å", False),
    ("pld", "pore_limiting_diameter", "Å", False),
    ("void_fraction", "void_fraction", None, False),
    ("surface_area_m2g", "surface_area_gravimetric", "m²/g", True),
    ("surface_area_m2cm3", "surface_area_volumetric", "m²/cm³", True),
)

# adsorbate formula -> (canonical property, molar mass g/mol, canonical unit)
_ADSORBATES = {
    "CO2": ("co2_uptake", 44.010, "mol/kg"),
    "CH4": ("ch4_uptake", 16.043, "mol/kg"),
    "N2": ("n2_uptake", 28.014, "mol/kg"),
    "H2": ("h2_uptake", 2.016, "g/L"),
    "XE": ("xe_uptake", 131.293, "mol/kg"),
    "KR": ("kr_uptake", 83.798, "mol/kg"),
    "AR": ("ar_uptake", 39.948, "mol/kg"),
    "H2O": ("h2o_uptake", 18.015, "mol/kg"),
}
# fallback when only the trivial name is present
_ADSORBATE_NAMES = {
    "carbon dioxide": "CO2",
    "methane": "CH4",
    "nitrogen": "N2",
    "hydrogen": "H2",
    "xenon": "XE",
    "krypton": "KR",
    "argon": "AR",
    "water": "H2O",
}

#: pressure unit -> bar. Only 'bar' and 'pa' occur in the archives; the rest
#: are exact conversions kept so a future MOFX-DB dump cannot silently drop
#: back to zero rows the way the bar-only test did.
_PRESSURE_TO_BAR = {
    "bar": 1.0,
    "pa": 1e-5,
    "kpa": 1e-2,
    "mpa": 10.0,
    "mbar": 1e-3,
    "atm": 1.01325,
    "torr": 1.3332236842e-3,
    "mmhg": 1.3332236842e-3,
}

#: molar volume of an ideal gas at STP (0 °C, 1 atm), L/mol
_STP_MOLAR_VOLUME = 22.414

#: gravimetric adsorption unit -> factor to mol/kg. ``None`` means the factor
#: depends on the adsorbate's molar mass M and is computed per isotherm.
_GRAVIMETRIC_TO_MOL_PER_KG: dict[str, float | None] = {
    "mol/kg": 1.0,
    "mmol/g": 1.0,
    "mol/g": 1000.0,
    "mmol/kg": 1e-3,
    "cm3(stp)/g": 1.0 / _STP_MOLAR_VOLUME,
    "mg/g": None,  # 1/M
    "g/g": None,  # 1000/M
}

#: volumetric adsorption unit -> canonical unit it may pass through as
_VOLUMETRIC_UNITS = {"g/l": "g/L", "g/liter": "g/L"}

_TARGET_T = 298.0  # K, only used to order equally valid duplicates
_TARGET_P = 1.0  # bar
_T_MIN, _T_MAX = 50.0, 400.0  # K, cryogenic porosimetry through ambient

#: Plausibility windows on the converted value, by canonical unit. The upper
#: bounds are deliberately loose: the most porous CoREMOF entry (BAZGAM_clean,
#: 96.5% void, 6581 m²/g, ~7.6 cm³/g of pore volume) genuinely takes up 257
#: mol/kg of Ar at 87 K, which is liquid argon filling the pores, so anything
#: below ~500 mol/kg is reachable. Liquid H2 is 71 g/L.
_VALUE_RANGE = {"mol/kg": (0.0, 500.0), "g/L": (0.0, 300.0)}


def _adsorbate_key(adsorbate: dict) -> str | None:
    formula = safe_text(adsorbate.get("formula"))
    if formula and formula.upper() in _ADSORBATES:
        return formula.upper()
    name = safe_text(adsorbate.get("name"))
    if name:
        return _ADSORBATE_NAMES.get(name.lower())
    return None


def _species_factor(formula: str, units_lower: str) -> tuple[float, str] | None:
    """Return (factor, canonical unit) for one adsorbate's adsorption unit."""

    canonical_unit = _ADSORBATES[formula][2]
    if units_lower in _GRAVIMETRIC_TO_MOL_PER_KG:
        if canonical_unit != "mol/kg":
            # e.g. a gravimetric H2 isotherm: h2_uptake is stored in g/L and a
            # property name carries exactly one unit, so do not mix them.
            return None
        factor = _GRAVIMETRIC_TO_MOL_PER_KG[units_lower]
        if factor is None:
            molar_mass = _ADSORBATES[formula][1]
            factor = (1000.0 if units_lower == "g/g" else 1.0) / molar_mass
        return factor, "mol/kg"
    passthrough = _VOLUMETRIC_UNITS.get(units_lower)
    if passthrough is not None and passthrough == canonical_unit:
        return 1.0, canonical_unit
    return None  # volumetric for a gravimetric property, or unknown


def _uptake_candidates(isotherm: dict, drops: Counter) -> list[tuple]:
    """Scalars from one isotherm: (property, value, unit, T, p bar, method tail).

    One entry per adsorbate, taken at the isotherm data point whose pressure is
    closest to 1 bar.
    """

    forcefield = safe_text(isotherm.get("molecule_forcefield"))
    if not forcefield:
        return []  # digitised experimental isotherm, no simulation provenance
    temperature = safe_float(isotherm.get("temperature"))
    if temperature is None or not _T_MIN <= temperature <= _T_MAX:
        return []
    pressure_units = safe_text(isotherm.get("pressureUnits"))
    if not pressure_units:
        return []
    to_bar = _PRESSURE_TO_BAR.get(pressure_units.lower().replace(" ", ""))
    if to_bar is None:
        drops[f"pressure_unit:{pressure_units}"] += 1
        return []
    units = safe_text(isotherm.get("adsorptionUnits"))
    if not units:
        return []
    units_lower = units.lower().replace(" ", "")

    adsorbates = isotherm.get("adsorbates") or []
    formulas = [_adsorbate_key(entry) for entry in adsorbates]
    if not formulas or any(formula is None for formula in formulas):
        return []
    # species_data rows carry a trivial name and an InChIKey but no formula;
    # both are resolved through the isotherm's own adsorbate list.
    by_key: dict[str, str] = {}
    labels: list[str] = []
    for entry, formula in zip(adsorbates, formulas):
        for field in ("InChIKey", "name"):
            value = safe_text(entry.get(field))
            if value:
                by_key[value.lower()] = formula
        labels.append(safe_text(entry.get("formula")) or formula)
    mixture = "/".join(labels)

    # the pressure grid is shared by every species, so pick the point once
    best: tuple[float, float, dict] | None = None  # (|p-1|, p bar, point)
    for point in isotherm.get("isotherm_data") or []:
        if not isinstance(point, dict):
            continue
        pressure = safe_float(point.get("pressure"))
        if pressure is None or pressure < 0:
            continue
        pressure *= to_bar
        key = abs(pressure - _TARGET_P)
        if best is None or key < best[0]:
            best = (key, pressure, point)
    if best is None:
        return []
    _, pressure, point = best

    if len(formulas) == 1:
        readings = [(formulas[0], safe_float(point.get("total_adsorption")), None)]
    else:
        readings = []
        for species in point.get("species_data") or []:
            if not isinstance(species, dict):
                continue
            formula = None
            for field in ("InChIKey", "name"):
                value = safe_text(species.get(field))
                if value and value.lower() in by_key:
                    formula = by_key[value.lower()]
                    break
            if formula is None:
                drops["species_unresolved"] += 1
                continue
            readings.append(
                (
                    formula,
                    safe_float(species.get("adsorption")),
                    safe_float(species.get("composition")),
                )
            )

    out = []
    for formula, value, composition in readings:
        if value is None or value < 0:
            continue
        converted = _species_factor(formula, units_lower)
        if converted is None:
            drops[f"adsorption_unit:{units}"] += 1
            continue
        factor, unit = converted
        value *= factor
        low, high = _VALUE_RANGE[unit]
        if not low <= value <= high:
            drops[f"out_of_range:{_ADSORBATES[formula][0]}"] += 1
            continue
        method = f"GCMC {temperature:g}K ~{pressure:g}bar"
        if composition is not None:
            method += f" in {mixture} y={composition:g}"
        method = f"{method} {forcefield[:40]}".rstrip()
        out.append(
            (_ADSORBATES[formula][0], value, unit, temperature, pressure, method)
        )
    return out


class MofxDbAdapter(SourceAdapter):
    source_key = "mofx-db"
    properties_only = False
    always_hash = False

    def _archives(self) -> list:
        archives = []
        for prefix in _SUBSET_PREFIXES:
            archives.extend(sorted(self.root.glob(f"{prefix}-*.zip")))
        return archives

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        self.malformed = 0
        #: rejected values, by reason
        self.drops: Counter[str] = Counter()
        #: staged uptake rows, by canonical property
        self.uptakes: Counter[str] = Counter()
        count = 0
        try:
            for archive in self._archives():
                with zipfile.ZipFile(archive) as bundle:
                    for member in bundle.namelist():
                        if not member.endswith(".json"):
                            continue
                        if limit is not None and count >= limit:
                            return
                        try:
                            with bundle.open(member) as handle:
                                row = json.load(handle)
                            record = self._build_record(row)
                        except Exception:  # noqa: BLE001 - malformed member
                            self.malformed += 1
                            continue
                        if record is None:
                            self.malformed += 1
                            continue
                        count += 1
                        yield record
        finally:
            print(
                f"[mofx-db] uptake rows: {dict(self.uptakes)}; "
                f"malformed: {self.malformed}; dropped: {dict(self.drops)}",
                file=sys.stderr,
                flush=True,
            )

    def _build_record(self, row: dict) -> SourceRecord | None:
        database = safe_text(row.get("database"))
        name = safe_text(row.get("name"))
        if not database or not name:
            return None

        properties = []
        for key, canonical, unit, skip_zero in _GEOMETRY_FIELDS:
            value = safe_float(row.get(key))
            if value is None or value < 0 or (skip_zero and value == 0):
                continue
            properties.append(PropertyValue(canonical, value, unit, _GEOMETRY_METHOD))

        # One scalar per (adsorbate, temperature): a record may hold the same
        # gas at several simulated temperatures, and each is a separate row
        # whose method names its temperature. Duplicated conditions keep the
        # point closest to 1 bar, then the isotherm closest to 298 K.
        best: dict[tuple[str, float], tuple[tuple[float, float], tuple]] = {}
        for isotherm in row.get("isotherms") or []:
            if not isinstance(isotherm, dict):
                continue
            for candidate in _uptake_candidates(isotherm, self.drops):
                prop, _value, _unit, temperature, pressure, _method = candidate
                key = (prop, round(temperature, 3))
                rank = (abs(pressure - _TARGET_P), abs(temperature - _TARGET_T))
                if key not in best or rank < best[key][0]:
                    best[key] = (rank, candidate)
        for key in sorted(best):
            _, (prop, value, unit, _t, _p, method) = best[key]
            properties.append(PropertyValue(prop, value, unit, method))
            self.uptakes[prop] += 1

        return SourceRecord(
            native_id=f"{database}:{name}",
            properties=properties,
            structure=safe_text(row.get("cif")),
            match_ids=[],
            experimental=database.startswith("CoREMOF") or database == "IZA",
        )
