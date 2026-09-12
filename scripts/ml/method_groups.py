#!/usr/bin/env python3
"""Normalise the free-form ``material_properties.method`` string.

Why this module exists
----------------------
``method`` was written by 54 independent adapters and is not a controlled
vocabulary.  It ranges from a bare functional (``PBE``) through a functional
plus a code and a caveat (``PBEsol DFPT (PhononDB)``) to strings that carry
*per-record* payload (``SuperCon-matched; doped formula Ta0.05V2Zr0.95`` --
thousands of distinct values for one property).

Training on the raw string is impossible (the cardinality is unbounded) and
ignoring it is worse: a band gap corpus that silently mixes PBE, HSE06, mBJ
and experiment has a systematic ~1 eV spread that no GNN can resolve from the
structure alone, so the model learns the source prior instead of the physics.
This module collapses the string to a **theory level** -- the axis that
actually shifts the target -- and keeps the raw string alongside so nothing is
lost.

The mapping is deliberately ordered: the first pattern that matches wins, so
the more specific hybrids and meta-GGAs are tested before the bare GGA
fallback.
"""

from __future__ import annotations

import re

# (regex, theory_level).  Order matters -- first match wins.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.I), level)
    for pattern, level in (
        # measurement beats every calculation; check it first
        (r"\bexperiment|\bmeasured|\bsupercon-matched|\brruff|\bamcsd|"
         r"\bwebmineral|\bicsd\b|\bcod\b|\bobserved\b", "experiment"),
        # hybrids
        (r"\bhse\s*06|\bhse\b", "hse06"),
        (r"\bpbe0\b|\bb3lyp\b|\bhsesol\b", "hybrid-other"),
        # NOMAD names the family rather than the functional: its metadata
        # records `xc_functional_type`, which is "hybrid" or "meta-GGA" with no
        # further detail.  No other adapter writes either word.
        (r"\bhybrid\b", "hybrid-other"),
        (r"\bgw\b|\bbse\b", "gw-bse"),
        # meta-GGA / modified potentials
        (r"\bmbj\b|\btbmbj\b|\bmodified becke", "mbj"),
        # must precede the bare-GGA fallback: `\bgga\b` matches inside
        # "meta-GGA" (the hyphen is a word boundary), which silently filed
        # 866,509 NOMAD rows -- SCAN- and r2SCAN-class band gaps among them --
        # at the GGA level and made them disagree with every GGA database.
        (r"\bmeta[-_ ]?gga\b", "meta-gga"),
        (r"\br2scan\b", "r2scan"),
        (r"\bscan\b", "scan"),
        (r"\bgllb", "gllbsc"),
        # vdW-corrected GGA -- a distinct level, JARVIS's default
        (r"optb88|optb86|vdw-df|\bdf2\b|\bd3\b|\btsvdw\b", "gga-vdw"),
        # plain GGA family, PBEsol split out because lattice constants differ
        (r"pbesol", "pbesol"),
        (r"\bpbe\b\+?u|\bgga\s*\+\s*u", "gga+u"),
        (r"\bpbe\b|\bgga\b", "gga"),
        (r"\blda\b|\bpz\b\b|\bcaperley", "lda"),
        # tight binding / semi-empirical / classical
        (r"\bqetb\b|tight[- ]binding|\bdftb\b", "tight-binding"),
        (r"\bzeo\+\+|\bpore|\bgeometric", "geometric"),
        (r"\bgcmc\b|\braspa\b|\bmonte carlo|\bhenry\b", "gcmc"),
        (r"force ?field|\bgulp\b|\buff\b|\bdreiding\b|\bslc\b|\bmlip\b|"
         r"\breaxff\b|\bbvse\b|\bbvel\b", "forcefield"),
        (r"\bboltztrap|\bamset\b", "transport-postproc"),
        (r"\bdfpt\b|\bphonopy\b|finite displacement", "dfpt-phonon"),
        (r"\bml\b|\bgnn\b|predicted|\bmodel\b", "ml-predicted"),
    )
)


def theory_level(method: str | None) -> str:
    """Collapse a raw method string to a coarse theory level.

    Returns ``"unspecified"`` when the adapter left the field empty and
    ``"other"`` when the string is present but matches no known family --
    both are kept as explicit buckets so a caller can decide to drop them
    rather than having them silently merged into a physical level.
    """

    if method is None:
        return "unspecified"
    text = method.strip()
    if not text:
        return "unspecified"
    for pattern, level in _RULES:
        if pattern.search(text):
            return level
    return "other"


# Levels whose values are directly comparable for a band gap, formation
# energy or lattice-derived quantity.  Anything outside a single set is a
# different target and belongs in a different model (or needs a per-level
# offset term).
COMPARABLE_SETS = {
    "gga-family": {"gga", "gga+u", "pbesol", "gga-vdw"},
    "hybrid-family": {"hse06", "hybrid-other"},
    "meta-gga-family": {"scan", "r2scan", "mbj", "meta-gga"},
    "experiment": {"experiment"},
}


# --------------------------------------------------------------------------
# Condition keys
# --------------------------------------------------------------------------

#: Per-record payload that must come OUT of the method string before it can be
#: used as a grouping key: 3dsc writes the doped composition into `method`
#: (7,151 distinct values for tc_superconducting alone) and pcod writes the
#: record id.  Left in, every record becomes its own group.
_RECORD_NOISE = (
    re.compile(r";?\s*doped formula\s+\S+", re.I),
    re.compile(r"\s*\((?:PCOD|JVASP|mp)[-\s]?\d+\)", re.I),
)


def condition_key(method: str | None) -> str:
    """The method string reduced to a stable *experimental condition*.

    Some properties are not one target but several.  ``co2_uptake`` holds four
    GCMC conditions per MOF (0.10 bar/363 K, 0.15 bar/298 K, 0.70 bar/413 K and
    a binary CO2/N2 mixture); ``decomposition_energy`` holds the same PBE energy
    against four different reference hulls; ``migration_barrier`` holds BVSE and
    BVEL barriers along 1D, 2D and 3D pathways per working ion.  Collapsing
    those to one number per material -- by median or otherwise -- produces a
    target that is not a physical quantity.  Grouping on this key instead turns
    each condition into its own regression task.
    """

    if not method:
        return "(unspecified)"
    text = method.strip()
    for pattern in _RECORD_NOISE:
        text = pattern.sub("", text)
    return " ".join(text.split()) or "(unspecified)"


#: Properties whose rows differ by CONDITION, not by disagreement, and which
#: must therefore be split per condition rather than resolved to one value.
#: Derived from the census: every property here carries >2 rows per material
#: with a small, meaningful set of distinct method strings.
CONDITION_SPLIT_PROPERTIES = {
    "co2_uptake", "ch4_uptake", "h2_uptake", "n2_uptake", "h2o_uptake",
    "xe_uptake", "kr_uptake", "ar_uptake", "co2_heat_of_adsorption",
    "n2_heat_of_adsorption", "henry_coefficient_co2",
    "working_capacity_vacuum_swing", "working_capacity_temperature_swing",
    "decomposition_energy", "migration_barrier", "ionic_conductivity",
    "poisson_ratio", "youngs_modulus", "topology_class", "topology_invariant",
    "seebeck_coefficient", "power_factor", "electrical_conductivity", "zt",
    "surface_energy", "grain_boundary_energy", "work_of_separation",
}


def comparable_set(level: str) -> str:
    for name, members in COMPARABLE_SETS.items():
        if level in members:
            return name
    return level


if __name__ == "__main__":  # tiny smoke check
    samples = [
        "PBE", "HSE06", "PBEsol DFPT (PhononDB)", "OptB88vdW avg xyz",
        "TBmBJ", "experiment", "zeo++ (QMOF)", "BoltzTraP p-type",
        "SuperCon-matched; doped formula Ta0.05V2Zr0.95", "", None, "GGA+U",
        "GCMC 0.15bar 298K", "GULP SLC forcefield (nu_zy)", "BVSE 1D Na",
        "PBE GNoME vs MP hull", "DFT / meta-GGA / VASP / dos",
        "DFT / hybrid / FHI-aims / band_structure", "DFT / GGA / VASP / dos / spin 1",
    ]
    for s in samples:
        print(f"{str(s)!r:<50} -> {theory_level(s):<16} | {condition_key(s)}")
