"""Group properties by the calculation they require, then read off coverage.

The tiers are a statement about cost, not about interest: everything in tier 1
falls out of a single self-consistent run that a database performs anyway,
while tier 4 needs a separate anharmonic, transport or beyond-semilocal
calculation per material. Properties whose domain is a single material family
(gas uptake, mineralogy) are held out, because their low coverage measures the
size of that family rather than the price of the calculation.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parents[1] / "data"

TIERS: dict[int, tuple[str, tuple[str, ...]]] = {
    1: ("single self-consistent run", (
        "total_energy_per_atom", "formation_energy_per_atom", "energy_above_hull",
        "band_gap", "total_magnetization", "magnetization_per_atom", "is_metal",
        "is_stable", "magnetic_ordering", "dos_at_fermi", "fermi_energy",
        "decomposition_energy", "cohesive_energy_per_atom", "heat_of_formation",
        "phase_separation_energy", "magnetization_per_volume",
        "band_gap_direct", "is_gap_direct", "cbm", "vbm")),
    2: ("a few extra self-consistent runs", (
        "work_function",
        "effective_mass_electron", "effective_mass_hole", "surface_energy",
        "exfoliation_energy", "interlayer_binding_energy", "electron_affinity",
        "ionization_potential", "d_band_center", "spillage",
        "grain_boundary_energy", "work_of_separation")),
    3: ("linear response or finite differences", (
        "bulk_modulus_vrh", "shear_modulus_vrh", "youngs_modulus", "poisson_ratio",
        "elastic_anisotropy", "bulk_modulus_voigt", "bulk_modulus_reuss",
        "shear_modulus_voigt", "shear_modulus_reuss", "sound_velocity_transverse",
        "sound_velocity_longitudinal", "debye_temperature",
        "dielectric_constant_total", "dielectric_constant_electronic",
        "dielectric_constant_ionic", "born_effective_charge_max",
        "piezoelectric_modulus", "phonon_max_frequency", "phonon_min_frequency",
        "has_imaginary_phonon", "eos_bulk_modulus", "bulk_modulus_pressure_derivative",
        "spontaneous_polarization")),
    4: ("anharmonic, transport or beyond-semilocal", (
        "lattice_thermal_conductivity", "lattice_thermal_conductivity_particle",
        "lattice_thermal_conductivity_coherence", "thermal_conductivity",
        "thermal_expansion", "heat_capacity", "seebeck_coefficient", "power_factor",
        "zt", "electrical_conductivity", "slme", "shg_coefficient", "birefringence",
        "refractive_index", "gllbsc_derivative_discontinuity", "tc_superconducting",
        "electron_phonon_coupling", "phonon_log_average_frequency",
        "magnetic_anisotropy_energy", "curie_temperature", "neel_temperature",
        "migration_barrier")),
}

rows = {r["property"]: r for r in csv.DictReader((DATA / "properties.csv").open())}
NMAT = 13_543_277
out = []
report = {}
for tier, (label, names) in TIERS.items():
    cov, present = [], []
    for n in names:
        r = rows.get(n)
        if r is None or int(r["n_materials"]) == 0:
            continue
        c = int(r["n_materials"]) / NMAT
        cov.append(c)
        present.append(n)
        out.append((tier, label, n, int(r["n_materials"]), c, int(r["n_sources"])))
    cov = np.array(cov)
    report[tier] = {
        "label": label, "n_properties": len(present),
        "median_coverage": float(np.median(cov)),
        "max_coverage": float(cov.max()), "min_coverage": float(cov.min()),
        "median_materials": int(np.median([int(rows[n]["n_materials"]) for n in present])),
        "max_property": present[int(np.argmax(cov))],
        "max_materials": int(rows[present[int(np.argmax(cov))]]["n_materials"]),
    }
with (DATA / "cost_tiers.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["tier", "tier_label", "property", "n_materials", "coverage", "n_sources"])
    w.writerows(out)
(DATA / "cost_tiers.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
for t, d in report.items():
    print(f"tier {t}  {d['n_properties']:2d} props  median {d['median_coverage']*100:7.3f}%"
          f"  max {d['max_coverage']*100:6.2f}% ({d['max_property']})"
          f"  min {d['min_coverage']*100:7.4f}%   [{d['label']}]")
c1 = np.array([c for t, _, _, _, c, _ in out if t == 1])
crest = np.array([c for t, _, _, _, c, _ in out if t != 1])
print(f"\ntier 1: {len(c1)} properties, median {np.median(c1)*100:.2f}%")
print(f"tiers 2-4: {len(crest)} properties, median {np.median(crest)*100:.3f}%")
print(f"ratio of medians: {np.median(c1)/np.median(crest):.0f}x")
print(f"tier 1 properties above 10% coverage: {(c1 > 0.10).sum()} / {len(c1)}")
print(f"tiers 2-4 properties above 10% coverage: {(crest > 0.10).sum()} / {len(crest)}")
print(f"tiers 2-4 properties below 1% coverage: {(crest < 0.01).sum()} / {len(crest)}")
