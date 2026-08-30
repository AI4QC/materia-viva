#!/usr/bin/env python3
"""Applicability domain: which pool structures a given property model may score.

Why this module exists
----------------------
"Fill in every property that is missing from every structure" is not a
well-posed instruction, because many properties are only *defined* for a
subset of the pool.  ``co2_uptake`` is a GCMC adsorption loading: it is
meaningful for a porous framework and meaningless for a dense intermetallic.
Its training set is 100% MOF (287,466 materials, median density 0.73 g/cm3,
every single one containing carbon), while the pool is 13.54M structures with
a median density of ~7 g/cm3.  A model trained on that set and then applied
pool-wide would emit ~13 million numbers that look like data and are not.

The same holds, with different boundaries, for a third of the corpus: 63 of
the 162 built tasks have a training set that is >90% one ``material_family``,
and ``bulk_modulus_vrh__forcefield`` spans exactly **two** chemical systems.

So every task carries a domain, built from two independent sources:

* a **declared** domain (below) -- what the property physically means, written
  down by hand because it does not follow from the numbers;
* an **empirical** domain (:func:`profile`) -- what the training set actually
  covered, measured per task.

They answer different questions and disagreeing is informative: a declared
pool-wide property whose training set is one family means the *labels* are
biased, not the property.  Both are written into ``DATASETS.json``.
"""

from __future__ import annotations

import collections

# --------------------------------------------------------------------------
# Declared domains
# --------------------------------------------------------------------------

#: What a property needs a structure to *be* for its value to mean anything.
#: Keys are property names (the part of a task file name before ``__``).
#: Anything not listed defaults to ``pool-wide``.
DECLARED: dict[str, str] = {}


def _declare(domain: str, *names: str) -> None:
    for name in names:
        DECLARED[name] = domain


# Gas uptake and heats of adsorption are simulated inside accessible pore
# space.  With no pore, there is no isotherm -- not "an uptake of zero", but an
# undefined quantity, because the GCMC cell has nowhere to insert a molecule.
_declare(
    "porous",
    "co2_uptake", "ch4_uptake", "h2_uptake", "n2_uptake", "h2o_uptake",
    "xe_uptake", "kr_uptake", "ar_uptake", "co2_heat_of_adsorption",
    "n2_heat_of_adsorption", "henry_coefficient_co2", "co2_n2_selectivity",
    "working_capacity_vacuum_swing", "working_capacity_temperature_swing",
)

# Framework-topology quantities: defined for a tetrahedral framework (zeolite,
# zeotype, MOF, COF), not for a close-packed solid.
_declare(
    "framework",
    "framework_density", "energy_per_t_atom", "framework_bond_dissociation_energy",
    "pore_channel_count",
)

# Geometric pore descriptors are DIFFERENT from the two groups above: zeo++
# will happily run on any periodic structure and return a well-defined (often
# ~0) answer.  They are pool-wide quantities whose LABELS happen to have been
# computed only for porous materials -- a sampling bias, not a domain limit.
_declare(
    "pool-wide-biased-labels",
    "void_fraction", "pore_limiting_diameter", "largest_cavity_diameter",
    "largest_free_path_diameter", "pore_volume", "surface_area_gravimetric",
    "surface_area_volumetric",
)

# Needs a van der Waals gap / layered stacking to exfoliate or separate.
_declare("layered", "exfoliation_energy", "interlayer_binding_energy")

# Needs a mobile working ion in the structure.
_declare(
    "ion-conducting",
    "migration_barrier", "ionic_conductivity", "average_voltage",
    "capacity_gravimetric", "capacity_volumetric", "energy_density_gravimetric",
    "energy_density_volumetric", "max_voltage_step", "num_voltage_steps",
    "electrode_stability_charged", "electrode_stability_discharged",
    "electrode_volume_change", "working_ion", "battery_formula",
)

# Needs a magnetically ordered ground state.
_declare(
    "magnetic",
    "curie_temperature", "neel_temperature", "magnetic_anisotropy_energy",
    "magnetic_anisotropy_constant", "easy_axis", "magnetic_polarization",
    "altermagnetic_splitting_max", "altermagnetic_splitting_avg",
    "altermagnetic_split_fraction", "magnetic_species",
)

# Undefined or degenerate for a metal: needs a finite band gap.
_declare(
    "gapped",
    "effective_mass_electron", "effective_mass_hole", "slme", "refractive_index",
    "birefringence", "shg_coefficient", "gllbsc_derivative_discontinuity",
    "dielectric_constant_total", "dielectric_constant_electronic",
    "dielectric_constant_ionic", "cbm", "vbm", "band_gap_direct", "is_gap_direct",
    "piezoelectric_modulus", "spontaneous_polarization",
)

# Properties of a SURFACE or an INTERFACE, not of the bulk cell the pool
# stores.  A model keyed on the bulk structure is predicting a facet-averaged
# or Wulff-averaged quantity and should say so.
_declare(
    "surface-derived",
    "surface_energy", "work_of_separation", "grain_boundary_energy",
    "grain_boundary_types", "wulff_shape_factor", "surface_anisotropy",
    "has_reconstructed_surface", "work_function", "d_band_center",
)

# Measured, not computed: the label exists only where someone made a sample.
_declare(
    "synthesized-only",
    "tc_superconducting", "superconductor_class", "mohs_hardness",
    "mineral_name", "chemical_name", "measured_chemistry", "r_factor",
    "measurement_temperature", "measurement_pressure", "experimentally_observed",
)


def declared_domain(property_name: str) -> str:
    return DECLARED.get(property_name, "pool-wide")


#: Human-readable gate for each declared domain, and the columns of
#: ``materials.parquet`` a screening pass can evaluate it on.  ``None`` means
#: no cheap structural gate exists and the empirical profile is all we have.
GATE_HINT: dict[str, str] = {
    "porous": "accessible porosity (zeo++ PLD >= the sorbate kinetic diameter; "
              "3.3 A for CO2, 2.9 A for H2). Proxy without zeo++: density below "
              "the training set's 99th percentile",
    "framework": "corner-sharing tetrahedral / node-linker topology; in practice "
                 "material_family in {zeolite, zeotype, mof, cof} or a low "
                 "framework density",
    "pool-wide-biased-labels": "no domain limit -- but the labels come from one "
                               "family, so extrapolation off it is untested",
    "layered": "a van der Waals gap; material_family in {2d-material} or a "
               "dimensionality label of 2D",
    "ion-conducting": "structure must contain the working ion the task was "
                      "trained for (per-task; see empirical always_elements)",
    "magnetic": "non-zero total_magnetization / a magnetic sublattice",
    "gapped": "band_gap > 0 (predict the gap first, then gate on it)",
    "surface-derived": "defined for a facet or boundary, not the bulk cell; the "
                       "target is an average over the parent's surfaces",
    "synthesized-only": "no structural gate; the label's absence is usually "
                        "'nobody measured it', not 'does not apply'",
    "pool-wide": "applies to any periodic crystal",
}


# --------------------------------------------------------------------------
# Empirical domain
# --------------------------------------------------------------------------


def profile(families, chemical_systems, densities, n_atoms, *, top_k: int = 4) -> dict:
    """Measure what a training set actually covered.

    Returned keys are deliberately the ones a screening pass can act on:
    ``always_elements`` (present in every single training structure -- the
    hardest constraint there is), ``family_share`` and ``density_p99``.
    """

    n = len(families)
    fam = collections.Counter(f or "(none)" for f in families)
    top_family, top_n = fam.most_common(1)[0]

    element_counts: collections.Counter = collections.Counter()
    systems = set()
    for system in chemical_systems:
        text = str(system)
        systems.add(text)
        element_counts.update(text.split("-"))

    import numpy as np

    dens = np.asarray(densities, dtype=float)
    dens = dens[np.isfinite(dens)]
    atoms = np.asarray(n_atoms, dtype=float)

    return {
        "n": int(n),
        "family_top": top_family,
        "family_share": round(top_n / n, 4) if n else 0.0,
        "families": dict(fam.most_common(top_k)),
        "n_elements_seen": len(element_counts),
        "n_chemical_systems": len(systems),
        # an element in EVERY training structure is a hard chemical constraint:
        # co2_uptake never saw a carbon-free material, so it cannot be trusted
        # on one
        "always_elements": sorted(e for e, c in element_counts.items() if c == n),
        "density_median": round(float(np.median(dens)), 3) if dens.size else None,
        "density_p99": round(float(np.percentile(dens, 99)), 3) if dens.size else None,
        "n_atoms_p99": int(np.percentile(atoms, 99)) if atoms.size else None,
    }


def verdict(declared: str, empirical: dict) -> str:
    """One line saying how far a model may be trusted off its training set."""

    share = empirical["family_share"]
    family = empirical["family_top"]
    if declared not in ("pool-wide", "pool-wide-biased-labels"):
        return (f"仅适用于 {declared}；训练集 {share:.0%} 为 {family}，"
                f"{empirical['n_chemical_systems']} 个化学体系")
    if family != "(none)" and share > 0.9:
        return (f"性质本身无限制，但标签 {share:.0%} 来自 {family} —— "
                f"离开该族属于外推，未经验证")
    if empirical["n_chemical_systems"] < 50:
        return (f"性质本身无限制，但训练集只覆盖 "
                f"{empirical['n_chemical_systems']} 个化学体系")
    return "可在全池预测"
