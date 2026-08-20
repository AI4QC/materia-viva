"""Materials Project: 2026-07-26 summary dump (155 pages, 154,377 docs).

Each ``page-*.json.gz`` holds a ``data`` list of MP summary docs. Records
carry their own relaxed structure (Structure.from_dict) plus ICSD parent ids
when MP matched one; the ICSD ids point at *related* experimental entries, so
the adapter keeps always_hash so the MP relaxation itself is fingerprinted
into the candidate pool as well.

Band edges (``cbm``/``vbm``, ~60% populated — the non-metals) are staged as
their own canonical properties on the calculation's energy zero, alongside the
``efermi`` already mapped there. ``equilibrium_reaction_energy_per_atom`` is
MP's decomposition energy for on-hull entries and is staged as
``decomposition_energy`` under its own method string.
``uncorrected_energy_per_atom`` is skipped: it is redundant with the
``energy_per_atom`` already staged as ``total_energy_per_atom``, differing only
by the MP2020 correction MP itself considers the reference value.

Property-family side tables (2026-08-19 snapshots)
--------------------------------------------------
``summary`` is only MP's front page. Eight further property endpoints were
acquired by ``scripts/datasets/mp_properties.py`` into sibling snapshot
directories and are joined here on ``material_id``, exactly as the gnome
adapter joins its r2SCAN CSV: each table is read once into
``material_id -> [PropertyValue]`` and appended to the matching summary record.

* ``oxidation_states``     per-element mean site valence (154,377 docs)
* ``chemenv``              coordination polyhedra per cation species
* ``insertion_electrodes`` battery figures of merit, keyed by ``material_ids``
  so one electrode contributes to both its charged and discharged endpoint;
  a host that cycles several ions gets one row set per ion
* ``elasticity``           the Voigt/Reuss bounds, Debye temperature, sound
  velocities and Clarke/Cahill minimum thermal conductivities that summary
  does not carry (summary already gives the VRH averages, the Poisson ratio
  and the universal anisotropy, which are therefore not restaged)
* ``piezoelectric``        the direction of the maximum response only;
  ``e_ij_max`` is already staged from summary
* ``eos``                  Murnaghan energy-volume fit, keyed by a bare
  ``task_id`` whose material id is ``mp-<task_id>``
* ``surface_properties``   per-facet surface energies / work functions,
  reduced to their extremes with the facet named in the method string
* ``grain_boundaries``     per-boundary energies, reduced to their extremes

Deliberately not staged: every per-site array (``possible_valences``, the
ChemEnv per-site lists), every tensor (elastic, compliance, dielectric,
piezoelectric), and the whole ``dielectric`` endpoint, whose four scalars
(``e_total``, ``e_ionic``, ``e_electronic``, ``n``) summary already provides
for the same materials. Elasticity docs are filtered to ``state ==
"successful"`` and not deprecated: the raw collection reaches bulk moduli of
-9e11 GPa in its failed fits.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

METHOD = "PBE(+U) MP2026"
SURFACE_METHOD = "PBE surface-weighted"
#: MP's equilibrium reaction energy is the decomposition energy of a stable
#: entry: the (negative) energy of the reaction that forms it from the
#: competing phases it would decompose into. Only populated for hull entries,
#: so it needs its own method string to stay apart from the sign-flipped
#: hull distance that other sources stage as decomposition_energy.
EQ_REACTION_METHOD = "PBE(+U) MP2026 equilibrium reaction energy"

# (native field, canonical name, unit) — plain scalars at METHOD level
_SCALARS = (
    ("band_gap", "band_gap", "eV"),
    ("cbm", "cbm", "eV"),
    ("vbm", "vbm", "eV"),
    ("efermi", "fermi_energy", "eV"),
    ("formation_energy_per_atom", "formation_energy_per_atom", "eV/atom"),
    ("energy_above_hull", "energy_above_hull", "eV/atom"),
    ("energy_per_atom", "total_energy_per_atom", "eV/atom"),
    ("homogeneous_poisson", "poisson_ratio", None),
    ("universal_anisotropy", "elastic_anisotropy", None),
    ("e_total", "dielectric_constant_total", None),
    ("e_ionic", "dielectric_constant_ionic", None),
    ("e_electronic", "dielectric_constant_electronic", None),
    ("n", "refractive_index", None),
    ("e_ij_max", "piezoelectric_modulus", "C/m²"),
)

#: Uncorrected DFT total energy, kept beside the MP2020-corrected one that
#: `energy_per_atom` carries; the correction scheme is named in the method so
#: the two rows stay distinguishable on the same material.
UNCORRECTED_METHOD = "PBE(+U) MP2026 uncorrected"

_BOOLS = (
    ("is_gap_direct", "is_gap_direct"),
    ("is_metal", "is_metal"),
    ("is_stable", "is_stable"),
)

#: plausibility windows for the newly mapped scalars; names absent here keep
#: their original unguarded behaviour so already-loaded rows never change
_RANGES: dict[str, tuple[float, float]] = {
    "cbm": (-100.0, 100.0),
    "vbm": (-100.0, 100.0),
    "decomposition_energy": (-50.0, 50.0),
    # insertion electrodes
    "average_voltage": (-25.0, 40.0),
    "capacity_gravimetric": (0.0, 5_000.0),
    "capacity_volumetric": (0.0, 30_000.0),
    "energy_density_gravimetric": (-10_000.0, 20_000.0),
    "energy_density_volumetric": (-40_000.0, 60_000.0),
    "max_voltage_step": (0.0, 25.0),
    "num_voltage_steps": (1.0, 100.0),
    "electrode_stability_charged": (0.0, 20.0),
    "electrode_stability_discharged": (0.0, 20.0),
    "electrode_volume_change": (0.0, 1_000.0),
    # elasticity
    "bulk_modulus_voigt": (0.0, 2_000.0),
    "bulk_modulus_reuss": (0.0, 2_000.0),
    "shear_modulus_voigt": (0.0, 2_000.0),
    "shear_modulus_reuss": (0.0, 2_000.0),
    "debye_temperature": (0.0, 5_000.0),
    "sound_velocity_transverse": (0.0, 30_000.0),
    "sound_velocity_longitudinal": (0.0, 30_000.0),
    "lattice_thermal_conductivity": (0.0, 1_000.0),
    # equation of state
    "bulk_modulus_eos": (0.0, 2_000.0),
    "bulk_modulus_pressure_derivative": (0.0, 20.0),
    # chemenv
    "continuous_symmetry_measure": (0.0, 100.0),
    # surfaces and grain boundaries
    "surface_anisotropy": (0.0, 100.0),
    "wulff_shape_factor": (0.0, 1_000.0),
    "grain_boundary_energy": (0.0, 20.0),
    "work_of_separation": (0.0, 20.0),
}

#: snapshot suffix of the property-family directories acquired beside summary
FAMILY_SNAPSHOT = "2026-08-19"

#: MP's oxidation-state builder names the analysis it managed to run
OXIDATION_METHOD = "MP oxidation-state analysis"
#: the ChemEnv strategy every populated chemenv doc reports verbatim
CHEMENV_METHOD = (
    "MP ChemEnv SimplestChemenvStrategy "
    "(distance_cutoff=1.4, angle_cutoff=0.3, CSM cutoff 10)"
)
ELECTRODE_METHOD = "PBE(+U) MP2026 insertion electrode"
ELASTICITY_METHOD = "PBE MP elasticity (finite-difference, 2nd order)"
PIEZO_METHOD = "PBE MP piezoelectric (DFPT)"
EOS_METHOD = "PBE MP energy-volume fit (Murnaghan)"
SURFACE_FACET_METHOD = "PBE MP surface slab"
GRAIN_BOUNDARY_METHOD = "PBE MP grain boundary"

#: (native field, canonical name, unit) for the elasticity side table; the VRH
#: averages, the Poisson ratio and the universal anisotropy are NOT repeated
#: here because summary already stages them.
_ELASTIC_MODULI = (
    ("bulk_modulus", "voigt", "bulk_modulus_voigt"),
    ("bulk_modulus", "reuss", "bulk_modulus_reuss"),
    ("shear_modulus", "voigt", "shear_modulus_voigt"),
    ("shear_modulus", "reuss", "shear_modulus_reuss"),
)

#: insertion-electrode figures of merit: (native field, canonical name, unit)
_ELECTRODE_SCALARS = (
    ("average_voltage", "average_voltage", "V"),
    ("capacity_grav", "capacity_gravimetric", "mAh/g"),
    ("capacity_vol", "capacity_volumetric", "mAh/cm³"),
    ("energy_grav", "energy_density_gravimetric", "Wh/kg"),
    ("energy_vol", "energy_density_volumetric", "Wh/L"),
    ("max_voltage_step", "max_voltage_step", "V"),
    ("num_steps", "num_voltage_steps", None),
    ("stability_charge", "electrode_stability_charged", "eV/atom"),
    ("stability_discharge", "electrode_stability_discharged", "eV/atom"),
    ("max_delta_volume", "electrode_volume_change", "fraction"),
)

#: facet-level windows applied inside the surface loader only, so the
#: Wulff-weighted surface_energy/work_function already staged from summary keep
#: their original unguarded behaviour
_FACET_SURFACE_ENERGY = (0.0, 20.0)  # J/m²
_FACET_WORK_FUNCTION = (0.0, 15.0)  # eV


def _element(value) -> str | None:
    """Element symbol, without safe_text's 'na' -> missing sentinel.

    ``safe_text`` reads the string "Na" as the missing-value marker "na", which
    would silently strip sodium from the 416 Na insertion electrodes.
    """

    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"none", "null", "nan"} else None


def _miller(index) -> str | None:
    """[2, 1, 0] -> '(2 1 0)'."""

    if not isinstance(index, (list, tuple)) or not index:
        return None
    try:
        return "(" + " ".join(str(int(value)) for value in index) + ")"
    except (TypeError, ValueError):
        return None


class MaterialsProjectAdapter(SourceAdapter):
    source_key = "materials-project"
    always_hash = True
    properties_only = False

    def __init__(self, root=None) -> None:
        super().__init__(root)
        self.drops: Counter[str] = Counter()

    def _guard(self, value: float | None, name: str) -> float | None:
        """Drop (and count) values outside the window declared for `name`."""

        window = _RANGES.get(name)
        if value is None or window is None:
            return value
        if not (window[0] <= value <= window[1]):
            self.drops[name] += 1
            return None
        return value

    def _bounded(
        self, value: float | None, window: tuple[float, float], tag: str
    ) -> float | None:
        """Guard against an explicit window (for values with no _RANGES name)."""

        if value is None:
            return None
        if not (window[0] <= value <= window[1]):
            self.drops[tag] += 1
            return None
        return value

    # ------------------------------------------------------------------
    # property-family side tables, joined on material_id
    # ------------------------------------------------------------------

    def _family_dir(self, family: str) -> Path:
        return self.root / f"{family}-{FAMILY_SNAPSHOT}"

    def _family_docs(self, family: str) -> Iterator[dict]:
        """Stream the docs of one acquired property family, if it is present."""

        directory = self._family_dir(family)
        if not directory.exists():
            self.drops[f"missing_family:{family}"] += 1
            return
        for page in sorted(directory.glob("page-*.json.gz")):
            with gzip.open(page, "rt", encoding="utf-8") as handle:
                for doc in json.load(handle).get("data") or []:
                    if isinstance(doc, dict):
                        yield doc

    @staticmethod
    def _attach(table: dict[str, list[PropertyValue]], material_id, prop) -> None:
        key = safe_text(material_id)
        if not key or prop is None:
            return
        table.setdefault(key, []).append(prop)

    def _load_oxidation_states(self, table: dict[str, list[PropertyValue]]) -> None:
        """Per-element mean site valence, e.g. 'Fe+2.67, O-2'."""

        for doc in self._family_docs("oxidation_states"):
            if doc.get("deprecated"):
                continue
            averages = doc.get("average_oxidation_states")
            if not isinstance(averages, dict) or not averages:
                continue
            parts = []
            for element in sorted(averages):
                value = safe_float(averages[element])
                if value is None or not (-10.0 <= value <= 10.0):
                    continue
                parts.append(f"{element}{value:+.3g}")
            if not parts:
                continue
            analysis = safe_text(doc.get("method"))
            method = (
                f"{OXIDATION_METHOD} ({analysis})" if analysis else OXIDATION_METHOD
            )
            self._attach(
                table,
                doc.get("material_id"),
                PropertyValue(
                    "average_oxidation_states", ", ".join(parts)[:120], None, method
                ),
            )

    def _load_chemenv(self, table: dict[str, list[PropertyValue]]) -> None:
        """Coordination polyhedra per cation species, plus the mean CSM.

        The endpoint publishes four parallel per-site arrays; only the distinct
        ``species + environment`` pairs are kept (never the arrays themselves),
        and the continuous symmetry measure is averaged over the sites.
        """

        for doc in self._family_docs("chemenv"):
            symbols = doc.get("chemenv_symbol")
            species = doc.get("species")
            if not isinstance(symbols, list) or not symbols:
                continue
            if not isinstance(species, list) or len(species) != len(symbols):
                species = [None] * len(symbols)
            seen: dict[str, None] = {}
            for site_species, symbol in zip(species, symbols):
                environment = safe_text(symbol)
                if not environment:
                    continue
                label = _element(site_species)
                pair = f"{label} {environment}" if label else environment
                seen.setdefault(pair, None)
            if not seen:
                continue
            self._attach(
                table,
                doc.get("material_id"),
                PropertyValue(
                    "coordination_environments",
                    ", ".join(seen)[:120],
                    None,
                    CHEMENV_METHOD,
                ),
            )
            measures = [
                value
                for raw in (doc.get("csm") or [])
                if (value := safe_float(raw)) is not None
            ]
            if measures:
                mean = self._guard(
                    sum(measures) / len(measures), "continuous_symmetry_measure"
                )
                if mean is not None:
                    self._attach(
                        table,
                        doc.get("material_id"),
                        PropertyValue(
                            "continuous_symmetry_measure",
                            mean,
                            None,
                            f"{CHEMENV_METHOD}, mean over cation sites",
                        ),
                    )

    def _load_insertion_electrodes(self, table: dict[str, list[PropertyValue]]) -> None:
        """Battery figures of merit, attached to every material of the couple.

        One doc describes one (framework, working ion) electrode and lists the
        charged and discharged materials it was built from, so both endpoints
        receive the values. A host that cycles several ions therefore collects
        one row set per ion, kept apart by the ion in the method string (no
        material carries two electrodes of the same ion in this snapshot).
        """

        for doc in self._family_docs("insertion_electrodes"):
            ion = _element(doc.get("working_ion"))
            method = f"{ELECTRODE_METHOD} ({ion})" if ion else ELECTRODE_METHOD
            properties: list[PropertyValue] = []
            for field, name, unit in _ELECTRODE_SCALARS:
                value = self._guard(safe_float(doc.get(field)), name)
                if value is not None:
                    properties.append(PropertyValue(name, value, unit, method))
            if ion:
                properties.append(PropertyValue("working_ion", ion, None, method))
            formula = safe_text(doc.get("battery_formula"))
            if formula:
                properties.append(
                    PropertyValue("battery_formula", formula[:80], None, method)
                )
            if not properties:
                continue
            material_ids = doc.get("material_ids")
            if not isinstance(material_ids, list):
                material_ids = [doc.get("id_charge"), doc.get("id_discharge")]
            for material_id in dict.fromkeys(material_ids):
                for prop in properties:
                    self._attach(table, material_id, prop)

    def _load_elasticity(self, table: dict[str, list[PropertyValue]]) -> None:
        """Only what summary lacks, and only from converged fits."""

        for doc in self._family_docs("elasticity"):
            # the raw collection keeps the failed fits, whose moduli reach
            # -9e11 GPa; MP itself only surfaces the successful ones
            if doc.get("deprecated") or safe_text(doc.get("state")) != "successful":
                continue
            material_id = doc.get("material_id")
            for field, bound, name in _ELASTIC_MODULI:
                moduli = doc.get(field)
                if not isinstance(moduli, dict):
                    continue
                value = self._guard(safe_float(moduli.get(bound)), name)
                if value is not None:
                    self._attach(
                        table,
                        material_id,
                        PropertyValue(name, value, "GPa", ELASTICITY_METHOD),
                    )
            debye = self._guard(
                safe_float(doc.get("debye_temperature")), "debye_temperature"
            )
            if debye is not None:
                self._attach(
                    table,
                    material_id,
                    PropertyValue("debye_temperature", debye, "K", ELASTICITY_METHOD),
                )
            velocities = doc.get("sound_velocity")
            if isinstance(velocities, dict):
                for field, name in (
                    ("transverse", "sound_velocity_transverse"),
                    ("longitudinal", "sound_velocity_longitudinal"),
                ):
                    value = self._guard(safe_float(velocities.get(field)), name)
                    if value is not None:
                        self._attach(
                            table,
                            material_id,
                            PropertyValue(name, value, "m/s", ELASTICITY_METHOD),
                        )
            # Clarke and Cahill are two closed-form estimates of the glassy
            # lower limit of the lattice thermal conductivity, both derived
            # from the elastic moduli; each keeps its model in the method.
            conductivity = doc.get("thermal_conductivity")
            if isinstance(conductivity, dict):
                for field, model in (("clarke", "Clarke"), ("cahill", "Cahill")):
                    value = self._guard(
                        safe_float(conductivity.get(field)),
                        "lattice_thermal_conductivity",
                    )
                    if value is not None:
                        self._attach(
                            table,
                            material_id,
                            PropertyValue(
                                "lattice_thermal_conductivity",
                                value,
                                "W/m·K",
                                f"{ELASTICITY_METHOD}, {model} minimum model",
                            ),
                        )

    def _load_piezoelectric(self, table: dict[str, list[PropertyValue]]) -> None:
        """Direction of the maximum response; e_ij_max comes from summary."""

        for doc in self._family_docs("piezoelectric"):
            if doc.get("deprecated"):
                continue
            direction = _miller(doc.get("max_direction"))
            if direction:
                self._attach(
                    table,
                    doc.get("material_id"),
                    PropertyValue(
                        "piezoelectric_max_direction", direction, None, PIEZO_METHOD
                    ),
                )

    def _load_eos(self, table: dict[str, list[PropertyValue]]) -> None:
        """Murnaghan B0/B0' from the energy-volume fit.

        The endpoint is keyed by a bare task id whose material id is
        ``mp-<task_id>`` (232 of the 233 resolve into the summary dump). Six
        further fits of the same E(V) points are skipped: ``vinet`` and
        ``mie_gruneisen`` disagree with the rest by a constant factor of ~9,
        ``birch_euler`` returns an unphysical B0' (median 0.5), and
        ``tait``/``pack_evans_james``/``birch_lagrange`` reproduce Murnaghan to
        within a few per cent. The E(V) points themselves are a curve, not a
        scalar, and are left to the curve pipeline.
        """

        # B0 comes out of the fit in eV/Å³ (energies in eV, volumes in Å³)
        ev_per_cubic_angstrom_to_gpa = 160.21766208
        for doc in self._family_docs("eos"):
            task_id = safe_text(doc.get("task_id"))
            if not task_id:
                continue
            material_id = task_id if task_id.startswith("mp-") else f"mp-{task_id}"
            fit = next(
                (
                    item
                    for item in (doc.get("eos") or [])
                    if isinstance(item, dict) and item.get("model") == "murnaghan"
                ),
                None,
            )
            if fit is None:
                continue
            raw = safe_float(fit.get("B0"))
            modulus = self._guard(
                None if raw is None else raw * ev_per_cubic_angstrom_to_gpa,
                "bulk_modulus_eos",
            )
            if modulus is not None:
                self._attach(
                    table,
                    material_id,
                    PropertyValue("bulk_modulus_eos", modulus, "GPa", EOS_METHOD),
                )
            derivative = self._guard(
                safe_float(fit.get("B1")), "bulk_modulus_pressure_derivative"
            )
            if derivative is not None:
                self._attach(
                    table,
                    material_id,
                    PropertyValue(
                        "bulk_modulus_pressure_derivative", derivative, None, EOS_METHOD
                    ),
                )

    def _load_surface_properties(self, table: dict[str, list[PropertyValue]]) -> None:
        """Reduce the per-facet slab table to its extremes.

        The Wulff-weighted surface energy and work function are already staged
        from summary; what is new here is the spread across facets, so the
        lowest- and highest-energy facet (and the same for the work function)
        are staged with their Miller index written into the method string.
        """

        for doc in self._family_docs("surface_properties"):
            material_id = doc.get("material_id")
            facets = doc.get("surfaces")
            if isinstance(facets, list):
                energies: list[tuple[float, str | None]] = []
                functions: list[tuple[float, str | None]] = []
                for facet in facets:
                    if not isinstance(facet, dict):
                        continue
                    index = _miller(facet.get("miller_index"))
                    if index and facet.get("is_reconstructed"):
                        # MP computes both slabs for a reconstructing facet, so
                        # the same Miller index can be the extreme twice over
                        index = f"{index} reconstructed"
                    energy = self._bounded(
                        safe_float(facet.get("surface_energy")),
                        _FACET_SURFACE_ENERGY,
                        "facet_surface_energy",
                    )
                    if energy is not None:
                        energies.append((energy, index))
                    work = self._bounded(
                        safe_float(facet.get("work_function")),
                        _FACET_WORK_FUNCTION,
                        "facet_work_function",
                    )
                    if work is not None:
                        functions.append((work, index))
                for values, name, unit in (
                    (energies, "surface_energy", "J/m²"),
                    (functions, "work_function", "eV"),
                ):
                    if not values:
                        continue
                    if len(values) == 1:
                        chosen = [(None, values[0])]
                    else:
                        chosen = [
                            ("lowest", min(values, key=lambda item: item[0])),
                            ("highest", max(values, key=lambda item: item[0])),
                        ]
                    for extreme, (value, index) in chosen:
                        label = f"facet {index}" if index else "unnamed facet"
                        method = (
                            f"{SURFACE_FACET_METHOD}, {label}"
                            if extreme is None
                            else f"{SURFACE_FACET_METHOD}, {extreme} of "
                            f"{len(values)} facets ({label})"
                        )
                        self._attach(
                            table,
                            material_id,
                            PropertyValue(name, value, unit, method),
                        )
            for field, name in (
                ("surface_anisotropy", "surface_anisotropy"),
                ("shape_factor", "wulff_shape_factor"),
            ):
                value = self._guard(safe_float(doc.get(field)), name)
                if value is not None:
                    self._attach(
                        table,
                        material_id,
                        PropertyValue(name, value, None, SURFACE_FACET_METHOD),
                    )
            reconstructed = doc.get("has_reconstructed")
            if isinstance(reconstructed, bool):
                self._attach(
                    table,
                    material_id,
                    PropertyValue(
                        "has_reconstructed_surface",
                        reconstructed,
                        None,
                        SURFACE_FACET_METHOD,
                    ),
                )

    def _load_grain_boundaries(self, table: dict[str, list[PropertyValue]]) -> None:
        """One doc per computed boundary, reduced per material to extremes."""

        per_material: dict[str, list[dict]] = {}
        for doc in self._family_docs("grain_boundaries"):
            material_id = safe_text(doc.get("material_id"))
            if material_id:
                per_material.setdefault(material_id, []).append(doc)

        for material_id, boundaries in per_material.items():
            energies = [
                (value, doc)
                for doc in boundaries
                if (
                    value := self._guard(
                        safe_float(doc.get("gb_energy")), "grain_boundary_energy"
                    )
                )
                is not None
            ]
            if energies:
                if len(energies) == 1:
                    chosen = [(None, energies[0])]
                else:
                    chosen = [
                        ("lowest", min(energies, key=lambda item: item[0])),
                        ("highest", max(energies, key=lambda item: item[0])),
                    ]
                for extreme, (value, doc) in chosen:
                    sigma = safe_float(doc.get("sigma"))
                    kind = safe_text(doc.get("type")) or "boundary"
                    label = f"Σ{int(sigma)} {kind}" if sigma else kind
                    method = (
                        f"{GRAIN_BOUNDARY_METHOD} {label}"
                        if extreme is None
                        else f"{GRAIN_BOUNDARY_METHOD}, {extreme} of "
                        f"{len(energies)} boundaries ({label})"
                    )
                    self._attach(
                        table,
                        material_id,
                        PropertyValue("grain_boundary_energy", value, "J/m²", method),
                    )
            separations = [
                value
                for doc in boundaries
                if (
                    value := self._guard(
                        safe_float(doc.get("w_sep")), "work_of_separation"
                    )
                )
                is not None
            ]
            if separations:
                self._attach(
                    table,
                    material_id,
                    PropertyValue(
                        "work_of_separation",
                        max(separations),
                        "J/m²",
                        f"{GRAIN_BOUNDARY_METHOD}, maximum over "
                        f"{len(separations)} boundaries",
                    ),
                )
            labels: dict[str, None] = {}
            for doc in boundaries:
                sigma = safe_float(doc.get("sigma"))
                kind = safe_text(doc.get("type"))
                if sigma and kind:
                    labels.setdefault(f"Σ{int(sigma)} {kind}", None)
            if labels:
                self._attach(
                    table,
                    material_id,
                    PropertyValue(
                        "grain_boundary_types",
                        ", ".join(sorted(labels))[:120],
                        None,
                        GRAIN_BOUNDARY_METHOD,
                    ),
                )

    def side_tables(self) -> dict[str, list[PropertyValue]]:
        """material_id -> the property rows contributed by the family dumps."""

        table: dict[str, list[PropertyValue]] = {}
        for load in (
            self._load_oxidation_states,
            self._load_chemenv,
            self._load_insertion_electrodes,
            self._load_elasticity,
            self._load_piezoelectric,
            self._load_eos,
            self._load_surface_properties,
            self._load_grain_boundaries,
        ):
            load(table)
        print(
            f"[materials-project] property side tables: {len(table):,} materials, "
            f"{sum(len(rows) for rows in table.values()):,} rows",
            flush=True,
        )
        return table

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        from pymatgen.core import Structure

        sides = self.side_tables()
        pages = sorted((self.root / "summary-2026-07-26").glob("page-*.json.gz"))
        count = 0
        for page in pages:
            with gzip.open(page, "rt", encoding="utf-8") as handle:
                docs = json.load(handle)["data"]
            for doc in docs:
                if limit is not None and count >= limit:
                    return
                if doc.get("deprecated"):
                    continue
                native_id = safe_text(doc.get("material_id"))
                if not native_id:
                    continue

                properties: list[PropertyValue] = []
                for field, name, unit in _SCALARS:
                    value = self._guard(safe_float(doc.get(field)), name)
                    if value is not None:
                        properties.append(PropertyValue(name, value, unit, METHOD))
                eq_reaction = self._guard(
                    safe_float(doc.get("equilibrium_reaction_energy_per_atom")),
                    "decomposition_energy",
                )
                if eq_reaction is not None:
                    properties.append(
                        PropertyValue(
                            "decomposition_energy",
                            eq_reaction,
                            "eV/atom",
                            EQ_REACTION_METHOD,
                        )
                    )
                for field, name in _BOOLS:
                    value = doc.get(field)
                    if isinstance(value, bool):
                        properties.append(PropertyValue(name, value, None, METHOD))

                # total magnetization: prefer per-formula-unit normalization
                mag_fu = safe_float(
                    doc.get("total_magnetization_normalized_formula_units")
                )
                if mag_fu is not None:
                    properties.append(
                        PropertyValue("total_magnetization", mag_fu, "μB/f.u.", METHOD)
                    )
                else:
                    mag_cell = safe_float(doc.get("total_magnetization"))
                    if mag_cell is not None:
                        properties.append(
                            PropertyValue(
                                "total_magnetization",
                                mag_cell,
                                "μB/cell",
                                f"{METHOD} μB/cell",
                            )
                        )

                ordering = safe_text(doc.get("ordering"))
                if ordering and ordering.lower() != "unknown":
                    properties.append(
                        PropertyValue("magnetic_ordering", ordering, None, METHOD)
                    )

                for field, name in (
                    ("bulk_modulus", "bulk_modulus_vrh"),
                    ("shear_modulus", "shear_modulus_vrh"),
                ):
                    moduli = doc.get(field)
                    if isinstance(moduli, dict):
                        value = safe_float(moduli.get("vrh"))
                        if value is not None:
                            properties.append(
                                PropertyValue(name, value, "GPa", METHOD)
                            )

                work_function = safe_float(doc.get("weighted_work_function"))
                if work_function is not None:
                    properties.append(
                        PropertyValue("work_function", work_function, "eV", SURFACE_METHOD)
                    )
                surface_energy = safe_float(doc.get("weighted_surface_energy"))
                if surface_energy is not None:
                    properties.append(
                        PropertyValue("surface_energy", surface_energy, "J/m²", SURFACE_METHOD)
                    )

                uncorrected = safe_float(doc.get("uncorrected_energy_per_atom"))
                if uncorrected is not None and -500 < uncorrected < 50:
                    properties.append(
                        PropertyValue(
                            "total_energy_per_atom", uncorrected, "eV/atom",
                            UNCORRECTED_METHOD,
                        )
                    )

                mag_vol = safe_float(doc.get("total_magnetization_normalized_vol"))
                if mag_vol is not None:
                    properties.append(
                        PropertyValue(
                            "magnetization_per_volume", mag_vol, "μB/Å³", METHOD
                        )
                    )

                # oxidation states MP resolved for the structure, e.g. 'Mg2+'
                species = doc.get("possible_species") or []
                if species:
                    text = ", ".join(str(item) for item in species)[:120]
                    properties.append(
                        PropertyValue(
                            "oxidation_states", text, None,
                            f"{METHOD} BVAnalyzer",
                        )
                    )

                magnetic_species = doc.get("types_of_magnetic_species") or []
                if magnetic_species:
                    properties.append(
                        PropertyValue(
                            "magnetic_species",
                            ", ".join(str(item) for item in magnetic_species)[:80],
                            None, METHOD,
                        )
                    )

                # what an unstable entry decomposes into, e.g. 'MgO + Mg3N2'
                decomposes = doc.get("decomposes_to") or []
                if decomposes:
                    formulas = [
                        str(item.get("formula"))
                        for item in decomposes
                        if isinstance(item, dict) and item.get("formula")
                    ]
                    if formulas:
                        properties.append(
                            PropertyValue(
                                "decomposes_to", " + ".join(formulas)[:120],
                                None, METHOD,
                            )
                        )

                theoretical = doc.get("theoretical")
                if isinstance(theoretical, bool):
                    properties.append(
                        PropertyValue(
                            "experimentally_observed",
                            not theoretical,
                            None,
                            "ICSD-matched",
                        )
                    )

                # rows from the property-family snapshots, joined on material_id
                properties.extend(sides.get(native_id, ()))

                match_ids = []
                database_ids = doc.get("database_IDs") or {}
                for entry in database_ids.get("icsd") or []:
                    pair = normalize_match_id("icsd", entry)
                    if pair:
                        match_ids.append(pair)

                try:
                    structure = Structure.from_dict(doc["structure"])
                except Exception:  # noqa: BLE001 - keep the property-only record
                    structure = None

                count += 1
                yield SourceRecord(
                    native_id=native_id,
                    properties=properties,
                    structure=structure,
                    match_ids=match_ids,
                )
        print(
            "[materials-project] value drops: "
            + (str(dict(self.drops)) if self.drops else "none"),
            flush=True,
        )
