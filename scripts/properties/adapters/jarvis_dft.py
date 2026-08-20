"""JARVIS-DFT 3D: NIST's OptB88vdW database (93,902 records, 9-24-2025 dump).

One zip, one JSON list. 'na' strings mark missing values everywhere, hence
safe_float/safe_text on every field. Records reference their Materials
Project parent (mp-/mvc-) and comma-separated ICSD codes; the JARVIS
structure is its own relaxation, so always_hash keeps it a pool candidate
even when an id match hits. The file is streamed with ijson so a small
--limit never parses the whole 600 MB payload.

Units verified against the dump before mapping:

* ``optb88vdw_total_energy`` is **per atom** (-10.5 .. +5.5 eV, flat in
  ``nat``: mean -1.99 eV at nat=1 and -4.04 eV at nat=12, so it cannot be a
  cell total). Positive values are real: they come from PAW references of
  d10/closed-shell elements (HgF3, Cd, CdXe).
* ``mepsx/y/z`` is the TBmBJ electronic dielectric tensor: Si 10.74
  (exp. ε∞ 11.7), GaAs 10.21 (exp. 10.9), GaN 4.47 (exp. 5.3) — all much
  closer to experiment than the OptB88vdW ``epsx/y/z`` of the same records
  (13.49 / 34.39 / 5.83), exactly as TBmBJ should be.
* ``avg_elec_mass`` / ``avg_hole_mass`` are the mean of the three
  ``effective_masses_300K`` eigenvalues in units of m_e (verified: PdSe8Cl2
  n = [1.96, 2.94, 0.6] -> 1.8333). Si 0.31 / 0.45 and GaN 0.19 match the
  measured conductivity masses. 80% of the records carry an exact 0.0, which
  is the "not resolved" sentinel (metals), so the guard drops non-positive
  values — and, because an unresolved *direction* is also written as 0.0
  inside the triple, averages built on one (see _effective_mass_properties).
* ``max_efg`` is in 10²¹ V/m²: corundum's Al site gives |Vzz| = 6.03 after
  diagonalising its ``efg`` tensor, against 6.78 x 10²¹ V/m² from the
  measured 27Al Cq of 2.40 MHz. It is the largest *component* of the raw
  Cartesian tensors over all sites, not max |Vzz|.
* ``dfpt_piezo_max_dielectric{,_electronic,_ionic}`` are the three parts of
  one DFPT run, each reported as the largest component of its own tensor, so
  the unsuffixed field is the total: GaN gives 11.31584 = 6.06579
  (electronic) + 5.25005 (ionic) exactly, and the sum identity only breaks
  where a different tensor component dominates each part (MoW3Se2S6:
  11.302 vs 11.216 + 0.896). Near-metallic entries diverge (GaAs, gap
  0.085 eV, reports ε∞ = 3098) and the ionic part reaches 4.6e6; the guard
  keeps the window at 1e4.
* ``modes`` is the sorted Γ-point phonon spectrum in cm⁻¹ of the cell the
  phonon run used (a supercell for 2/3 of the records, so ``len(modes)`` is
  not 3*nat and degeneracies are partly collapsed — min and max survive
  that unharmed). Si tops out at 499.5 cm⁻¹ (exp. 520), GaN at 669.6,
  GaAs at 253.6.

Deliberately not staged: ``ncond``/``pcond``/``nkappa``/``pkappa`` (BoltzTraP
transport coefficients published divided by the relaxation time, and the dump
never states the τ normalisation, so the numbers are not comparable to any
other source's conductivity); ``max_ir_mode``/``min_ir_mode`` (they do not
match min/max of ``modes`` — 6 of 3,307 records agree — and their median of
1.96 makes them intensities rather than frequencies); ``magmom_outcar``
(duplicate of the already-mapped ``magmom_oszicar``); ``dfpt_piezo_max_dij``
(no canonical name and the dump does not fix pC/N vs pm/V); ``efg``
(per-site), ``cfid``/``desc`` (ML descriptors), ``encut``/``kpoint_length_unit``
/``maxdiff_*`` (convergence bookkeeping), ``density``/``nat``/``crys``
(structure-derived and already pool-wide).
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import (
    jarvis_atoms_to_structure,
    safe_float,
    safe_text,
)
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_MP_REF = re.compile(r"^(?:mp|mvc)-\d+$")

#: cm^-1 -> THz, the unit the phonon canonical names are declared in
CM1_TO_THZ = 0.029979245800
#: the dump's EFG unit (10^21 V/m^2) -> the canonical V/m^2
EFG_TO_V_PER_M2 = 1e21
#: acoustic Γ modes carry a few tenths of a cm^-1 of numerical noise, so the
#: imaginary flag needs a tolerance; it is named in the method string
IMAGINARY_TOLERANCE_CM1 = -5.0

# native field -> (canonical name, unit, method)
_SCALAR_MAP: tuple[tuple[str, str, str | None, str], ...] = (
    ("formation_energy_peratom", "formation_energy_per_atom", "eV/atom", "OptB88vdW"),
    ("optb88vdw_bandgap", "band_gap", "eV", "OptB88vdW"),
    ("mbj_bandgap", "band_gap", "eV", "TBmBJ"),
    ("hse_gap", "band_gap", "eV", "HSE06"),
    ("ehull", "energy_above_hull", "eV/atom", "OptB88vdW"),
    ("magmom_oszicar", "total_magnetization", "μB/cell", "OptB88vdW"),
    ("bulk_modulus_kv", "bulk_modulus_vrh", "GPa", "OptB88vdW ElaStic"),
    ("shear_modulus_gv", "shear_modulus_vrh", "GPa", "OptB88vdW ElaStic"),
    ("poisson", "poisson_ratio", None, "OptB88vdW ElaStic"),
    ("n-Seebeck", "seebeck_coefficient", "μV/K", "BoltzTraP n-type"),
    ("p-Seebeck", "seebeck_coefficient", "μV/K", "BoltzTraP p-type"),
    ("n-powerfact", "power_factor", "μW/cm·K²", "BoltzTraP n-type"),
    ("p-powerfact", "power_factor", "μW/cm·K²", "BoltzTraP p-type"),
    ("slme", "slme", "%", "OptB88vdW"),
    ("spillage", "spillage", None, "OptB88vdW"),
    ("Tc_supercon", "tc_superconducting", "K", "McMillan-Allen-Dynes"),
    ("exfoliation_energy", "exfoliation_energy", "meV/atom", "OptB88vdW"),
    ("dfpt_piezo_max_eij", "piezoelectric_modulus", "C/m²", "DFPT"),
)

# fields added after the first ingest; guarded and counted, see _RANGES
_ADDED_MAP: tuple[tuple[str, str, str | None, str], ...] = (
    ("optb88vdw_total_energy", "total_energy_per_atom", "eV/atom", "OptB88vdW"),
    ("dfpt_piezo_max_dielectric", "dielectric_constant_total", None, "DFPT"),
    (
        "dfpt_piezo_max_dielectric_electronic",
        "dielectric_constant_electronic",
        None,
        "DFPT",
    ),
    ("dfpt_piezo_max_dielectric_ionic", "dielectric_constant_ionic", None, "DFPT"),
)

#: native field -> plausible window in the *dump's* units. Only the fields
#: added after the first ingest are guarded; the pre-existing mappings are left
#: untouched so their staged rows stay byte-identical.
_RANGES: dict[str, tuple[float, float]] = {
    # per-atom PAW total energy; the dump spans -10.5 .. +5.5
    "optb88vdw_total_energy": (-50.0, 20.0),
    # m_e; 0.0 is the "not resolved" sentinel, the dump caps the value at 3.0
    "avg_elec_mass": (1e-6, 50.0),
    "avg_hole_mass": (1e-6, 50.0),
    # dielectric constants: near-metallic DFPT runs diverge, 1e4 is the cut
    "meps_avg": (0.0, 1e4),
    "dfpt_piezo_max_dielectric": (0.0, 1e4),
    "dfpt_piezo_max_dielectric_electronic": (0.0, 1e4),
    "dfpt_piezo_max_dielectric_ionic": (0.0, 1e4),
    # 10^21 V/m^2; the dump spans 0 .. 199.9 and cubic sites are legitimately 0
    "max_efg": (0.0, 1e4),
    # cm^-1; 200 THz is ~6,670 cm^-1, above any lattice mode (the dump tops out
    # at 4,328 cm^-1 on a hydride and bottoms out at -2,163 cm^-1)
    "modes_max": (1e-9, 200.0 / CM1_TO_THZ),
    "modes_min": (-200.0 / CM1_TO_THZ, 200.0 / CM1_TO_THZ),
}


def _guard(value: float | None, key: str, drops: Counter | None) -> float | None:
    """Drop (and count) values outside the window declared for `key`."""

    window = _RANGES.get(key)
    if value is None or window is None:
        return value
    if not (window[0] <= value <= window[1]):
        if drops is not None:
            drops[key] += 1
        return None
    return value


def scalar_properties(row: dict, drops: Counter | None = None) -> list[PropertyValue]:
    """The JARVIS field vocabulary shared by the 3D dump and the 2D update."""

    properties: list[PropertyValue] = []
    for key, name, unit, method in _SCALAR_MAP:
        value = safe_float(row.get(key))
        if value is not None:
            properties.append(PropertyValue(name, value, unit, method))
    for key, name, unit, method in _ADDED_MAP:
        value = _guard(safe_float(row.get(key)), key, drops)
        if value is not None:
            properties.append(PropertyValue(name, value, unit, method))

    eps = [safe_float(row.get(k)) for k in ("epsx", "epsy", "epsz")]
    if all(component is not None for component in eps):
        properties.append(
            PropertyValue(
                "dielectric_constant_electronic",
                sum(eps) / 3.0,
                None,
                "OptB88vdW avg xyz",
            )
        )
    meps = [safe_float(row.get(k)) for k in ("mepsx", "mepsy", "mepsz")]
    if all(component is not None for component in meps):
        average = _guard(sum(meps) / 3.0, "meps_avg", drops)
        if average is not None:
            properties.append(
                PropertyValue(
                    "dielectric_constant_electronic",
                    average,
                    None,
                    "TBmBJ avg xyz",
                )
            )
    properties.extend(_effective_mass_properties(row, drops))
    efg = _guard(safe_float(row.get("max_efg")), "max_efg", drops)
    if efg is not None:
        properties.append(
            PropertyValue(
                "nmr_efg_max",
                efg * EFG_TO_V_PER_M2,
                "V/m²",
                "OptB88vdW (largest EFG tensor component)",
            )
        )
    properties.extend(_phonon_properties(row, drops))
    return properties


#: BoltzTraP eigenvalue key -> (canonical name, native average field)
_MASS_CHANNELS = (
    ("n", "effective_mass_electron", "avg_elec_mass"),
    ("p", "effective_mass_hole", "avg_hole_mass"),
)
_MASS_METHOD = "BoltzTraP 300K (avg of mass-tensor eigenvalues)"


def _effective_mass_properties(
    row: dict, drops: Counter | None
) -> list[PropertyValue]:
    """avg_elec_mass / avg_hole_mass, refusing averages built on 0 sentinels.

    The published average is the plain mean of the three
    ``effective_masses_300K`` eigenvalues, and an unresolved direction is
    written as 0.0 rather than omitted, so a triple like [0.55, 0.0, 0.0]
    yields a plausible-looking 0.183 that is really 0.55/3 (228 of the 3,568
    non-zero averages in the 3D dump are contaminated this way). Where the
    triple is published the guard demands three resolved directions; the 40
    records that carry only the average keep it on the positivity guard alone.
    """

    triples = row.get("effective_masses_300K")
    if not isinstance(triples, dict):
        triples = {}
    properties: list[PropertyValue] = []
    for key, name, field in _MASS_CHANNELS:
        value = _guard(safe_float(row.get(field)), field, drops)
        if value is None:
            continue
        eigenvalues = triples.get(key)
        if isinstance(eigenvalues, list) and len(eigenvalues) == 3:
            resolved = [safe_float(item) for item in eigenvalues]
            if any(item is None or item <= 0.0 for item in resolved):
                if drops is not None:
                    drops[f"{field}_unresolved_direction"] += 1
                continue
        properties.append(PropertyValue(name, value, "m_e", _MASS_METHOD))
    return properties


def _phonon_properties(row: dict, drops: Counter | None) -> list[PropertyValue]:
    """max/min Γ frequency and the imaginary flag out of the `modes` list."""

    modes = row.get("modes")
    if not isinstance(modes, list) or not modes:
        return []
    values = [
        value
        for value in modes
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if len(values) != len(modes):
        if drops is not None:
            drops["modes_nonnumeric"] += 1
        return []
    # A cell whose Γ spectrum is nothing but the three acoustic modes at ~0
    # (74 records, mostly monatomic) says nothing about the vibrations: it has
    # neither a real optical mode nor a real imaginary one, and staging
    # has_imaginary_phonon=False off it would read as "dynamically stable"
    # on no evidence at all. 50 such records are skipped whole; the other 24
    # do carry genuinely imaginary modes and keep the minimum and the flag.
    if not (max(values) > 0.0 or min(values) < IMAGINARY_TOLERANCE_CM1):
        if drops is not None:
            drops["modes_all_acoustic_noise"] += 1
        return []
    properties: list[PropertyValue] = []
    highest = _guard(max(values), "modes_max", drops)
    if highest is not None:
        properties.append(
            PropertyValue(
                "phonon_max_frequency",
                highest * CM1_TO_THZ,
                "THz",
                "DFPT Γ-point",
            )
        )
    lowest = _guard(min(values), "modes_min", drops)
    if lowest is not None:
        properties.append(
            PropertyValue(
                "phonon_min_frequency",
                lowest * CM1_TO_THZ,
                "THz",
                "DFPT Γ-point",
            )
        )
        properties.append(
            PropertyValue(
                "has_imaginary_phonon",
                lowest < IMAGINARY_TOLERANCE_CM1,
                None,
                "DFPT Γ-point (imaginary below -5 cm⁻¹)",
            )
        )
    return properties


def extract_properties(row: dict, drops: Counter | None = None) -> list[PropertyValue]:
    """Map one raw JARVIS-DFT dict onto canonical PropertyValues."""

    properties = scalar_properties(row, drops)
    spacegroup = safe_float(row.get("spg_number"))
    if spacegroup:
        properties.append(
            PropertyValue("spacegroup_number", int(spacegroup), None, "OptB88vdW")
        )
    dimensionality = safe_text(row.get("dimensionality"))
    if dimensionality:
        properties.append(
            PropertyValue("dimensionality", dimensionality, None, "OptB88vdW")
        )
    return properties


def extract_match_ids(row: dict) -> list[tuple[str, str]]:
    match_ids: list[tuple[str, str]] = []
    reference = safe_text(row.get("reference"))
    if reference and _MP_REF.match(reference):
        pair = normalize_match_id("materials-project", reference)
        if pair:
            match_ids.append(pair)
    icsd_field = safe_text(row.get("icsd"))
    if icsd_field:
        for code in icsd_field.split(","):
            code = code.strip()
            if code.isdigit():
                pair = normalize_match_id("icsd", code)
                if pair:
                    match_ids.append(pair)
    return match_ids


class JarvisDftAdapter(SourceAdapter):
    source_key = "jarvis-dft"
    always_hash = True

    def __init__(self, root=None) -> None:
        super().__init__(root)
        self.drops: Counter[str] = Counter()

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        import json

        # stdlib json, not ijson: the dump contains bare NaN tokens (invalid
        # strict JSON) that ijson's lexer rejects; json.load parses them into
        # float('nan'), which safe_float then discards per value.
        archive = self.root / "jdft_3d-9-24-2025.json.zip"
        try:
            with zipfile.ZipFile(archive) as bundle:
                with bundle.open(bundle.namelist()[0]) as handle:
                    rows = json.load(handle)
                    for count, row in enumerate(rows):
                        if limit is not None and count >= limit:
                            return
                        try:
                            structure = jarvis_atoms_to_structure(row["atoms"])
                        except Exception:  # noqa: BLE001 - keep property-only record
                            structure = None
                        yield SourceRecord(
                            native_id=str(row.get("jid") or f"jarvis-dft-{count}"),
                            properties=extract_properties(row, self.drops),
                            structure=structure,
                            match_ids=extract_match_ids(row),
                        )
        finally:
            print(
                "[jarvis-dft] value drops: "
                + (str(dict(self.drops)) if self.drops else "none"),
                flush=True,
            )
