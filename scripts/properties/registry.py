"""Canonical property names, units and source metadata.

Adapters must map native fields onto the canonical names below whenever one
fits; genuinely source-specific quantities may introduce new snake_case names,
which the loader registers on the fly. The registry only fixes the vocabulary
that more than one database shares, so cross-database comparison stays sane.

Method strings carry the level of theory or measurement conditions
("PBE", "HSE06", "r2SCAN", "experiment", "GCMC 298K 16bar", ...); they are kept
verbatim next to each value and never merged away.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCES_JSON = PROJECT_ROOT / "scripts" / "datasets" / "sources.json"

# name -> (unit, kind) with kind in {"num", "text", "bool"}
CANONICAL_PROPERTIES: dict[str, tuple[str | None, str]] = {
    # electronic structure
    "band_gap": ("eV", "num"),
    "band_gap_direct": ("eV", "num"),
    # band edges on the calculation's own energy zero; only comparable to the
    # fermi_energy of the same method string, never across sources
    "cbm": ("eV", "num"),
    "vbm": ("eV", "num"),
    "is_gap_direct": (None, "bool"),
    "is_metal": (None, "bool"),
    "fermi_energy": ("eV", "num"),
    "dos_at_fermi": ("states/eV", "num"),
    "work_function": ("eV", "num"),
    "electron_affinity": ("eV", "num"),
    "ionization_potential": ("eV", "num"),
    "effective_mass_electron": ("m_e", "num"),
    "effective_mass_hole": ("m_e", "num"),
    # thermodynamics
    "formation_energy_per_atom": ("eV/atom", "num"),
    "energy_above_hull": ("eV/atom", "num"),
    "decomposition_energy": ("eV/atom", "num"),
    "phase_separation_energy": ("eV/atom", "num"),
    "total_energy_per_atom": ("eV/atom", "num"),
    "is_stable": (None, "bool"),
    "cohesive_energy_per_atom": ("eV/atom", "num"),
    "exfoliation_energy": ("meV/atom", "num"),
    # magnetism
    "magnetic_ordering": (None, "text"),
    # normalization (per cell / per f.u.) differs between sources and is
    # recorded in each row's method string, so the shared unit stays neutral
    "total_magnetization": ("μB", "num"),
    "magnetization_per_atom": ("μB/atom", "num"),
    "magnetic_moment": ("μB", "num"),
    "curie_temperature": ("K", "num"),
    "neel_temperature": ("K", "num"),
    "magnetic_anisotropy_energy": ("meV", "num"),
    # altermagnetism screening metrics (AMDB)
    "altermagnetic_splitting_max": ("eV", "num"),
    "altermagnetic_splitting_avg": ("eV", "num"),
    "altermagnetic_split_fraction": ("%", "num"),
    # elasticity / mechanics
    "bulk_modulus_vrh": ("GPa", "num"),
    "shear_modulus_vrh": ("GPa", "num"),
    "youngs_modulus": ("GPa", "num"),
    "poisson_ratio": (None, "num"),
    "elastic_anisotropy": (None, "num"),
    "hardness_vickers": ("GPa", "num"),
    "mohs_hardness": (None, "num"),
    # thermal / vibrational
    "debye_temperature": ("K", "num"),
    "thermal_conductivity": ("W/m·K", "num"),
    "lattice_thermal_conductivity": ("W/m·K", "num"),
    # Wigner decomposition of the lattice thermal conductivity:
    # kappa_lattice = kappa_particle (Peierls / populations, phonon
    # wave-packets propagating between scattering events) + kappa_coherence
    # (wave-like tunnelling between overlapping phonon branches, dominant in
    # complex low-conductivity crystals).
    "lattice_thermal_conductivity_particle": ("W/m·K", "num"),
    "lattice_thermal_conductivity_coherence": ("W/m·K", "num"),
    "thermal_expansion": ("1/K", "num"),
    "heat_capacity": ("J/mol·K", "num"),
    "phonon_max_frequency": ("THz", "num"),
    "phonon_min_frequency": ("THz", "num"),
    "has_imaginary_phonon": (None, "bool"),
    # dielectric / optical / piezo / ferro
    "dielectric_constant_total": (None, "num"),
    "dielectric_constant_electronic": (None, "num"),
    "dielectric_constant_ionic": (None, "num"),
    "refractive_index": (None, "num"),
    "piezoelectric_modulus": ("C/m²", "num"),
    "born_effective_charge_max": ("e", "num"),
    "spontaneous_polarization": ("μC/cm²", "num"),
    "slme": ("%", "num"),
    "spillage": (None, "num"),
    # transport / thermoelectric
    "seebeck_coefficient": ("μV/K", "num"),
    "electrical_conductivity": ("S/cm", "num"),
    "power_factor": ("μW/cm·K²", "num"),
    "zt": (None, "num"),
    "ionic_conductivity": ("S/cm", "num"),
    "migration_barrier": ("eV", "num"),
    # superconductivity
    "tc_superconducting": ("K", "num"),
    "superconductor_class": (None, "text"),
    # Eliashberg electron-phonon pair: lambda is the dimensionless coupling
    # constant and omega_log the logarithmic average phonon frequency, the two
    # inputs the McMillan-Allen-Dynes Tc is built from (the Coulomb
    # pseudopotential mu* belongs in the method string)
    "electron_phonon_coupling": (None, "num"),
    "phonon_log_average_frequency": ("K", "num"),
    # topology
    "topology_class": (None, "text"),
    "topology_invariant": (None, "text"),
    "symmetry_indicators": (None, "text"),
    # porous-material descriptors
    "surface_area_gravimetric": ("m²/g", "num"),
    "surface_area_volumetric": ("m²/cm³", "num"),
    "void_fraction": (None, "num"),
    "pore_volume": ("cm³/g", "num"),
    "pore_limiting_diameter": ("Å", "num"),
    "largest_cavity_diameter": ("Å", "num"),
    # Zeo++ Dif: the largest included sphere along the free-sphere path, i.e.
    # the widest sphere that can travel through the framework's channels
    "largest_free_path_diameter": ("Å", "num"),
    "pore_channel_count": (None, "num"),
    "co2_uptake": ("mol/kg", "num"),
    "ch4_uptake": ("mol/kg", "num"),
    "h2_uptake": ("g/L", "num"),
    "n2_uptake": ("mol/kg", "num"),
    "h2o_uptake": ("mol/kg", "num"),
    "xe_uptake": ("mol/kg", "num"),
    "kr_uptake": ("mol/kg", "num"),
    "ar_uptake": ("mol/kg", "num"),
    "henry_coefficient_co2": ("mol/kg·Pa", "num"),
    "co2_n2_selectivity": (None, "num"),
    "partial_charge_method": (None, "text"),
    # structure-level annotations
    "density": ("g/cm³", "num"),
    "volume_per_atom": ("Å³/atom", "num"),
    "spacegroup_number": (None, "num"),
    "mineral_name": (None, "text"),
    "structure_prototype": (None, "text"),
    "dimensionality": (None, "text"),
    "synthesis_temperature": ("K", "num"),
    "measurement_pressure": ("GPa", "num"),
    # spectroscopy
    "nmr_shielding_range": ("ppm", "num"),
    "nmr_efg_max": ("V/m²", "num"),
    # adapter-introduced names promoted to the canonical vocabulary
    "experimentally_observed": (None, "bool"),
    "dynamically_stable": (None, "bool"),
    "surface_energy": ("J/m²", "num"),
    "heat_of_formation": ("eV/atom", "num"),
    "gllbsc_derivative_discontinuity": ("eV", "num"),
    "framework_bond_dissociation_energy": ("eV/atom", "num"),
    "interlayer_binding_energy": ("meV/Å²", "num"),
    "magnetic_polarization": ("T", "num"),
    "magnetic_anisotropy_constant": ("MJ/m³", "num"),
    "easy_axis": (None, "text"),
    "relative_energy_to_diamond": ("eV/atom", "num"),
    "co2_heat_of_adsorption": ("kJ/mol", "num"),
    "n2_heat_of_adsorption": ("kJ/mol", "num"),
    "working_capacity_vacuum_swing": ("mol/kg", "num"),
    "working_capacity_temperature_swing": ("mol/kg", "num"),
    "elf_max": (None, "num"),
    "shg_coefficient": ("pm/V", "num"),
    "birefringence": (None, "num"),
    "strukturbericht": (None, "text"),
    "measured_chemistry": (None, "text"),
    "chemical_name": (None, "text"),
    "predicted_synthesizable": (None, "bool"),
    "measurement_temperature": ("K", "num"),
    "magnetization_per_volume": ("μB/Å³", "num"),
    "oxidation_states": (None, "text"),
    "magnetic_species": (None, "text"),
    "decomposes_to": (None, "text"),
    # Pearson symbol: lattice-type letter pair + atoms per conventional cell
    # (cF8, hP63, tI84); published verbatim by aflow-prototypes and SACADA.
    "pearson_symbol": (None, "text"),
    # 2D layer group (1-80), the slab analogue of the space group
    "layer_group_number": (None, "num"),
    # tetrahedral (T) atoms per 1000 Å³, the IZA zeolite/zeotype convention
    "framework_density": ("T/1000 Å³", "num"),
    # crystallographic refinement residual R1 (fraction, not per cent)
    "r_factor": (None, "num"),
    # GRINSP's geometric restraint residual, the cost function of a structure
    # *prediction* search: how far the framework's realised distances and
    # angles sit from the ideal targets fed to the optimiser. Deliberately NOT
    # r_factor -- nothing here was ever measured, so there is no observation to
    # be residual against, and the two ranges interleave (0.0001-0.05 here
    # against 0.022-0.078 for real AlPO refinements), so no numeric filter
    # could separate them if they shared a name.
    "structure_prediction_r_factor": (None, "num"),
    # forcefield energy per tetrahedral (T) atom, the ranking quantity of the
    # enumerated-zeolite databases. Not total_energy_per_atom: that is eV per
    # *atom* from a DFT total energy, this is kJ/mol per T site from a
    # forcefield, and the two are neither the same unit nor the same
    # denominator (SiO2 has three atoms per T site).
    "energy_per_t_atom": ("kJ/mol", "num"),
    # spin-resolved d-band centre relative to the Fermi level
    "d_band_center": ("eV", "num"),
    # residuals of the relaxation that produced the structure: how converged
    # the geometry is. Published per trajectory endpoint by ELEMENTA, where
    # they are the criterion for calling an endpoint a relaxed structure.
    "max_residual_force": ("eV/Å", "num"),
    "max_residual_stress": ("eV/Å³", "num"),
    # per-element mean site valence, "Fe+2.67, O-2"; resolves the mixed-valence
    # cases the `oxidation_states` species list only enumerates
    "average_oxidation_states": (None, "text"),
    # coordination polyhedra per cation species, in ChemEnv notation
    # ("Fe2+ O:6" = octahedral iron, "Si4+ T:4" = tetrahedral silicon)
    "coordination_environments": (None, "text"),
    # ChemEnv's continuous symmetry measure: 0 is the ideal polyhedron, larger
    # values a more distorted environment (the assignment cutoff is 10)
    "continuous_symmetry_measure": (None, "num"),
    # insertion-electrode figures of merit; the working ion belongs in the
    # method string, since one host framework may cycle several ions
    "average_voltage": ("V", "num"),
    "capacity_gravimetric": ("mAh/g", "num"),
    "capacity_volumetric": ("mAh/cm³", "num"),
    "energy_density_gravimetric": ("Wh/kg", "num"),
    "energy_density_volumetric": ("Wh/L", "num"),
    "max_voltage_step": ("V", "num"),
    "num_voltage_steps": (None, "num"),
    # hull distance of the charged / discharged electrode composition; kept
    # apart from the host material's own energy_above_hull
    "electrode_stability_charged": ("eV/atom", "num"),
    "electrode_stability_discharged": ("eV/atom", "num"),
    # (V_discharged - V_charged) / V_charged over the cycle
    "electrode_volume_change": ("fraction", "num"),
    "working_ion": (None, "text"),
    "battery_formula": (None, "text"),
    # Voigt (uniform-strain) and Reuss (uniform-stress) bounds on the moduli
    # whose VRH average is already carried by bulk_modulus_vrh/shear_modulus_vrh
    "bulk_modulus_voigt": ("GPa", "num"),
    "bulk_modulus_reuss": ("GPa", "num"),
    "shear_modulus_voigt": ("GPa", "num"),
    "shear_modulus_reuss": ("GPa", "num"),
    "sound_velocity_transverse": ("m/s", "num"),
    "sound_velocity_longitudinal": ("m/s", "num"),
    # B0 and its pressure derivative B0' from an energy-volume equation-of-state
    # fit; not a VRH average of an elastic tensor, hence its own name
    "bulk_modulus_eos": ("GPa", "num"),
    "bulk_modulus_pressure_derivative": (None, "num"),
    # crystallographic direction of the maximum piezoelectric response
    "piezoelectric_max_direction": (None, "text"),
    # spread of the facet surface energies over the Wulff shape, and the
    # dimensionless Wulff shape factor (surface area / volume^(2/3))
    "surface_anisotropy": (None, "num"),
    "wulff_shape_factor": (None, "num"),
    "has_reconstructed_surface": (None, "bool"),
    # grain-boundary energetics: formation energy of the boundary and the work
    # needed to separate the two grains across it
    "grain_boundary_energy": ("J/m²", "num"),
    "work_of_separation": ("J/m²", "num"),
    "grain_boundary_types": (None, "text"),
}

# Structure-family label for sources whose every record belongs to one
# non-conventional crystal class. Mixed sources (e.g. alexandria's 2D/1D
# subsets) are instead labelled from their `dimensionality` property during
# backfill. NULL family means an ordinary bulk crystal.
SOURCE_FAMILY: dict[str, str] = {
    "hmof": "mof",
    "mofx-db": "mof",
    "mof-carbon-capture": "mof",
    "arc-mof": "mof",
    "ec-mof": "mof",
    "fair-mofs": "mof",
    "qmof": "mof",
    "core-mof": "mof",
    "curated-cof": "cof",
    "hofsyn": "hof",
    "deem-zeolites": "zeolite",
    "iza-zeolite": "zeolite",
    "open-framework-aluminophosphate": "zeotype",
    "omdb-organic": "molecular-crystal",
    "ccpnc-magres": "molecular-crystal",
    "sacada": "carbon-allotrope",
    "c2db": "2d-material",
    "2dmatpedia": "2d-material",
    "mc2d": "2d-material",
    "bidb": "2d-material",
    "2dalloys": "2d-material",
    "openmx-2d-ab2": "2d-material",
}

# Sources whose scalar values may fill the fast-filter columns in `materials`,
# in priority order (first hit wins; existing non-NULL column values are never
# overwritten). Keys are source ids from scripts/datasets/sources.json.
SCALAR_BACKFILL_PRIORITY: tuple[str, ...] = (
    "materials-project",
    "alexandria",
    "oqmd",
    "jarvis-dft",
    "aflow",
    "gnome",
    "matbench-discovery",
    "odbx",
    "c2db",
    "2dmatpedia",
    "snumat",
    "atomly",
    "elementa",
    "nomad",
)

# canonical property -> materials-table column it may backfill
SCALAR_COLUMN_MAP: dict[str, str] = {
    "band_gap": "pbes_gap",
    "formation_energy_per_atom": "formation_energy_per_atom",
    "energy_above_hull": "energy_above_hull",
    "is_stable": "is_stable",
    "is_metal": "is_metal",
    "magnetic_ordering": "magnetic_ordering",
    "total_magnetization": "total_magnetization",
    "bulk_modulus_vrh": "bulk_modulus",
    "shear_modulus_vrh": "shear_modulus",
    "poisson_ratio": "poisson_ratio",
}


@lru_cache(maxsize=1)
def source_catalog() -> dict[str, dict]:
    """Machine-readable source catalog keyed by source id."""

    data = json.loads(SOURCES_JSON.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in data["sources"]}


def source_info(source_key: str) -> dict:
    catalog = source_catalog()
    if source_key not in catalog:
        raise KeyError(
            f"source {source_key!r} is not registered in scripts/datasets/sources.json"
        )
    return catalog[source_key]


def property_unit(name: str) -> str | None:
    entry = CANONICAL_PROPERTIES.get(name)
    return entry[0] if entry else None


def property_kind(name: str) -> str:
    entry = CANONICAL_PROPERTIES.get(name)
    return entry[1] if entry else "num"
