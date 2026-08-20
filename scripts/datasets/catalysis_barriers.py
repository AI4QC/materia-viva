#!/usr/bin/env python3
"""Build independent, provenance-rich surface-reaction barrier files.

This module deliberately does not write into the matdata application database.
It preserves every reported label in a raw layer and emits stricter positive and
high-confidence layers so estimated/proxy labels cannot silently become DFT
transition-state targets.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import pickle
import re
import tarfile
from argparse import ArgumentParser
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from scripts.datasets.acquire import default_data_root


OC20NEB_SOURCE_URL = "https://fair-chem.github.io/oc20neb/"
CATAPP_SOURCE_URL = "https://cmr.fysik.dtu.dk/catapp/catapp.html"
CATALYSIS_HUB_SOURCE_URL = "https://www.catalysis-hub.org/"
MEO_METHANE_SOURCE_URL = "https://zenodo.org/records/21226108"
CKINETICSDB_SOURCE_URL = "https://sites.google.com/udel.edu/ckineticsdb/home"
MO2C_FTS_SOURCE_URL = "https://zenodo.org/records/12758711"
SBH17_SOURCE_URL = "https://doi.org/10.1021/acs.jctc.2c00824"
GAME_NET_UQ_SOURCE_URL = "https://doi.org/10.5281/zenodo.17977395"

OC20NEB_NAME = re.compile(
    r"^(?P<reaction_class>desorption|dissociation|transfer)_"
    r"(?P<domain>id|ood)_(?P<task_id>\d+)_(?P<bulk_index>\d+)_"
    r"(?P<reaction_index>\d+)_(?P<facet>.+)-(?P<shift>\d+)_"
    r"neb1(?:\.0)?\.traj$"
)
SURFACE_NAME = re.compile(r"^(?P<formula>.+?)\((?P<facet>[^()]*)\)$")


FIELDNAMES = [
    "source",
    "record_id",
    "source_record_id",
    "reaction_class",
    "reaction_equation",
    "equation_canonical",
    "material_id",
    "material_formula",
    "chemical_composition",
    "facet",
    "surface_shift",
    "site",
    "domain",
    "barrier_eV",
    "reaction_energy_eV",
    "path_max_minus_initial_eV",
    "raw_initial_energy_eV",
    "raw_final_energy_eV",
    "raw_ts_energy_eV",
    "barrierless",
    "converged",
    "label_kind",
    "label_quality",
    "quality_flags",
    "has_structure",
    "structure_ref",
    "publication",
    "method",
    "functional",
    "license",
    "license_url",
    "source_url",
    "duplicate_fingerprint",
    "duplicate_count",
    "duplicate_sources",
]


def _float(value):
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def canonicalize_equation(equation: str) -> str:
    """Normalize superficial gas/spacing differences without reversing a step."""

    value = _text(equation).lower()
    value = value.replace("→", "->")
    value = re.sub(r"\((?:g|gas)\)", "", value)
    value = re.sub(r"\s+", "", value)
    return value


def parse_oc20neb_trajectory_name(name: str) -> dict:
    match = OC20NEB_NAME.fullmatch(Path(name).name)
    if match is None:
        raise ValueError(f"unrecognized OC20NEB trajectory name: {name}")
    fields = match.groupdict()
    for key in ("task_id", "bulk_index", "reaction_index", "shift"):
        fields[key] = int(fields[key])
    return fields


def _records(value) -> list[dict]:
    if hasattr(value, "to_dict"):
        return list(value.to_dict("records"))
    return [dict(row) for row in value]


def _bulk_formula(bulk: Mapping) -> str:
    atoms = bulk.get("atoms")
    if atoms is not None and hasattr(atoms, "get_chemical_formula"):
        return atoms.get_chemical_formula()
    return _text(bulk.get("formula"))


def build_oc20neb_records(
    mappings: Mapping[str, object],
    *,
    reaction_databases: Mapping[str, Sequence[Mapping]],
    bulks: Sequence[Mapping],
    archive_names: set[str],
) -> list[dict]:
    rows = []
    for reaction_class, mapping in mappings.items():
        reactions = reaction_databases[reaction_class]
        for source in _records(mapping):
            trajectory_name = _text(source.get("trajectory_name"))
            parsed = parse_oc20neb_trajectory_name(trajectory_name)
            if parsed["reaction_class"] != reaction_class:
                raise ValueError(
                    f"mapping class mismatch for trajectory {trajectory_name}"
                )
            bulk = bulks[parsed["bulk_index"]]
            reaction = reactions[parsed["reaction_index"]]
            barrier = _float(source.get("Ea"))
            raw_ts = _float(source.get("E_raw_TS"))
            barrierless = bool(source.get("barrierless"))
            flags = []

            if barrierless:
                label_kind = "dft_neb_barrierless"
                label_quality = "high"
            else:
                label_kind = "dft_neb_explicit_barrier"
                label_quality = "high"
                if raw_ts == 0.0:
                    flags.append("raw_ts_zero")
                    label_quality = "invalid"
                if barrier is None or barrier <= 0:
                    flags.append("nonpositive_or_missing_barrier")
                    label_quality = "invalid"
                elif barrier > 10:
                    flags.append("barrier_above_10_eV")
                    label_quality = "invalid"

            has_structure = trajectory_name in archive_names
            if not has_structure:
                flags.append("trajectory_missing_from_archive")

            equation = _text(reaction.get("reaction"))
            rows.append(
                {
                    "source": "oc20neb",
                    "record_id": f"oc20neb:{trajectory_name}",
                    "source_record_id": _text(source.get("neb_id")),
                    "reaction_class": reaction_class,
                    "reaction_equation": equation,
                    "equation_canonical": canonicalize_equation(equation),
                    "material_id": _text(bulk.get("src_id")),
                    "material_formula": _bulk_formula(bulk),
                    "chemical_composition": "",
                    "facet": parsed["facet"],
                    "surface_shift": parsed["shift"],
                    "site": "",
                    "domain": parsed["domain"],
                    "barrier_eV": barrier,
                    "reaction_energy_eV": _float(source.get("E_rxn")),
                    "path_max_minus_initial_eV": _float(
                        source.get("barrier_height")
                    ),
                    "raw_initial_energy_eV": _float(source.get("E_raw_initial")),
                    "raw_final_energy_eV": _float(source.get("E_raw_final")),
                    "raw_ts_energy_eV": raw_ts,
                    "barrierless": barrierless,
                    "converged": bool(source.get("converged")),
                    "label_kind": label_kind,
                    "label_quality": label_quality,
                    "quality_flags": ";".join(flags),
                    "has_structure": has_structure,
                    "structure_ref": trajectory_name if has_structure else "",
                    "publication": "Wander et al., CatTSunami (2024)",
                    "method": "DFT NEB",
                    "functional": "RPBE",
                    "license": "CC BY 4.0",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "source_url": OC20NEB_SOURCE_URL,
                }
            )
    return rows


def _catapp_term(value) -> str:
    term = _text(value)
    if term.lower().startswith("hf") and len(term) > 2:
        return f"0.5{term[2:]}"
    return term


def build_catapp_record(source: Mapping, *, row_number: int) -> dict:
    surface = _text(source.get("surface"))
    match = SURFACE_NAME.fullmatch(surface)
    formula = match.group("formula") if match else surface
    facet = match.group("facet") if match else ""
    ab = _catapp_term(source.get("ab"))
    a = _catapp_term(source.get("a"))
    b = _catapp_term(source.get("b"))
    equation = f"{ab} -> {a} + {b}"
    dataset = _text(source.get("dataset"))
    publication = _text(source.get("reference"))
    barrier = _float(source.get("activation_energy"))
    reaction_energy = _float(source.get("reaction_energy"))
    flags = []

    known_proxy = (
        dataset == "SUNCAT alloys, DACAPO/RPBE"
        and publication == "J. Catal. 293 (2012) 51-60"
    )
    is_bep = "bep" in f"{dataset} {publication}".lower()
    equals_reaction = (
        barrier is not None
        and reaction_energy is not None
        and abs(barrier - reaction_energy) <= 1e-12
    )
    if known_proxy:
        label_kind = "reaction_energy_proxy"
        label_quality = "low"
        flags.append("known_catapp_alloy_proxy")
    elif is_bep:
        label_kind = "bep_estimate"
        label_quality = "low"
        flags.append("bep_labeled_source")
    elif equals_reaction:
        label_kind = "ambiguous_ea_equals_reaction_energy"
        label_quality = "low"
        flags.append("activation_equals_reaction_energy")
    else:
        label_kind = "reported_activation_energy"
        label_quality = "high"

    if barrier is not None and barrier <= 0:
        flags.append("nonpositive_barrier")

    return {
        "source": "catapp",
        "record_id": f"catapp:{row_number}",
        "source_record_id": str(row_number),
        "reaction_class": "",
        "reaction_equation": equation,
        "equation_canonical": canonicalize_equation(equation),
        "material_id": "",
        "material_formula": formula,
        "chemical_composition": "",
        "facet": facet,
        "surface_shift": "",
        "site": "",
        "domain": "",
        "barrier_eV": barrier,
        "reaction_energy_eV": reaction_energy,
        "path_max_minus_initial_eV": "",
        "raw_initial_energy_eV": "",
        "raw_final_energy_eV": "",
        "raw_ts_energy_eV": "",
        "barrierless": "",
        "converged": "",
        "label_kind": label_kind,
        "label_quality": label_quality,
        "quality_flags": ";".join(flags),
        "has_structure": False,
        "structure_ref": "",
        "publication": publication,
        "method": dataset,
        "functional": "",
        "license": "source-specific",
        "license_url": "",
        "source_url": _text(source.get("url")) or CATAPP_SOURCE_URL,
    }


def build_catalysis_hub_record(source: Mapping) -> dict:
    equation = _text(source.get("Equation") or source.get("equation"))
    barrier = _float(source.get("activationEnergy"))
    flags = []
    if barrier is not None and barrier <= 0:
        flags.append("nonpositive_barrier")
    return {
        "source": "catalysis_hub",
        "record_id": f"catalysis_hub:{_text(source.get('id'))}",
        "source_record_id": _text(source.get("id")),
        "reaction_class": "",
        "reaction_equation": equation,
        "equation_canonical": canonicalize_equation(equation),
        "material_id": "",
        "material_formula": _text(source.get("surfaceComposition")),
        "chemical_composition": _text(source.get("chemicalComposition")),
        "facet": _text(source.get("facet")),
        "surface_shift": "",
        "site": _text(source.get("sites")),
        "domain": "",
        "barrier_eV": barrier,
        "reaction_energy_eV": _float(source.get("reactionEnergy")),
        "path_max_minus_initial_eV": "",
        "raw_initial_energy_eV": "",
        "raw_final_energy_eV": "",
        "raw_ts_energy_eV": "",
        "barrierless": "",
        "converged": "",
        "label_kind": "reported_activation_energy",
        "label_quality": "medium",
        "quality_flags": ";".join(flags),
        "has_structure": False,
        "structure_ref": "",
        "publication": _text(source.get("pubId")),
        "method": _text(source.get("dftCode")),
        "functional": _text(source.get("dftFunctional")),
        "license": "source-specific",
        "license_url": "",
        "source_url": CATALYSIS_HUB_SOURCE_URL,
    }


def build_meo_methane_record(source: Mapping) -> dict:
    mechanism = _text(source.get("mechanism"))
    reaction_id = _text(source.get("reaction_id"))
    site = ";".join(
        (
            f"CH4@{_text(source.get('ch4_cation'))}"
            f"[{_text(source.get('ch4_cation_idx'))}]",
            f"CH3@{_text(source.get('ch3_site'))}"
            f"[{_text(source.get('ch3_site_idx'))}]",
            f"H@{_text(source.get('h_site'))}"
            f"[{_text(source.get('h_site_idx'))}]",
        )
    )
    equation = "CH4* -> CH3* + H*"
    return {
        "source": "meo_methane_ci_neb",
        "record_id": f"meo_methane_ci_neb:{reaction_id}",
        "source_record_id": reaction_id,
        "reaction_class": f"methane_dissociation_{mechanism}",
        "reaction_equation": equation,
        "equation_canonical": canonicalize_equation(equation),
        "material_id": "",
        "material_formula": "Mg0.25Zn0.25Ni0.25Cu0.25O",
        "chemical_composition": "Mg0.25Zn0.25Ni0.25Cu0.25O",
        "facet": "100",
        "surface_shift": "",
        "site": site,
        "domain": "",
        "barrier_eV": _float(source.get("Ea_eV")),
        "reaction_energy_eV": "",
        "path_max_minus_initial_eV": "",
        "raw_initial_energy_eV": "",
        "raw_final_energy_eV": "",
        "raw_ts_energy_eV": "",
        "barrierless": False,
        "converged": True,
        "label_kind": "dft_ci_neb_explicit_barrier",
        "label_quality": "high",
        "quality_flags": "",
        "has_structure": False,
        "structure_ref": "",
        "publication": "Methane activation on high-entropy oxide (2026)",
        "method": "DFT CI-NEB",
        "functional": "",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_url": MEO_METHANE_SOURCE_URL,
    }


def _table_data(table: object) -> list[Mapping]:
    if not isinstance(table, Mapping):
        return []
    data = table.get("data", {})
    if isinstance(data, Mapping):
        return [row for row in data.values() if isinstance(row, Mapping)]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    return []


def _state_energy(state: str, energies: Mapping[str, float]) -> float:
    state = state.strip()
    if state in energies:
        return energies[state]
    total = 0.0
    for term in (part.strip() for part in state.split("+")):
        if term in energies:
            total += energies[term]
            continue
        match = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*\*?\s*(.+)", term)
        if match is None or match.group(2).strip() not in energies:
            raise KeyError(f"missing pMuTT energy for state term: {term}")
        total += float(match.group(1)) * energies[match.group(2).strip()]
    return total


def _ckinetics_material(filename: str) -> tuple[str, str]:
    stem = Path(filename).stem
    if "_Input_Data" in stem:
        return stem.split("_Input_Data", 1)[0].replace("_", "/"), ""
    if stem.startswith("Input_Data_"):
        parts = stem.split("_")
        return (parts[2] if len(parts) > 2 else stem), ""
    match = re.fullmatch(r"(.+)_([0-9-]+)", stem)
    if match is None:
        return stem.replace("_", "/"), ""
    return match.group(1).replace("_", "/"), match.group(2)


def build_ckineticsdb_records(documents: Sequence[Mapping]) -> list[dict]:
    """Calculate directional barriers from pMuTT TS and kinetic rows."""

    rows = []
    for document in documents:
        if document.get("file_type") != "pMuttExcels":
            continue
        energies = {}
        for table_name in ("refs", "species"):
            for species in _table_data(document.get(table_name)):
                name = _text(species.get("name"))
                energy = _float(species.get("potentialenergy"))
                if name and energy is not None:
                    energies[name] = energy
        filename = _text(document.get("filename"))
        project = _text(document.get("project"))
        material, facet = _ckinetics_material(filename)
        if project == "Light_alkane_hydrogenolysis_on_Ru":
            material, facet = "Ru", "0001"
        for row_number, reaction in enumerate(
            _table_data(document.get("reactions")), start=1
        ):
            expression = _text(reaction.get("reaction_str"))
            states = [state.strip() for state in expression.split("=")]
            if any(not state for state in states):
                continue

            label_kind = "dft_ts_energy_difference"
            method = "DFT transition-state thermochemistry"
            functional = "PBE" if material == "Ru" else ""
            base_quality = "high"
            base_flags = []
            if len(states) == 3:
                initial, transition, final = states
                try:
                    initial_energy = _state_energy(initial, energies)
                    transition_energy = _state_energy(transition, energies)
                    final_energy = _state_energy(final, energies)
                except KeyError:
                    continue
                forward_barrier = round(transition_energy - initial_energy, 12)
                reaction_energy = round(final_energy - initial_energy, 12)
                reverse_barrier = round(transition_energy - final_energy, 12)
            elif len(states) == 2:
                manual_kcal = _float(reaction.get("notes"))
                is_adsorption = _text(reaction.get("is_adsorption")).lower() in {
                    "true",
                    "1",
                    "yes",
                }
                if manual_kcal is None or manual_kcal <= 0 or is_adsorption:
                    continue
                initial, final = states
                state_energies = dict(energies)
                if material == "Ru":
                    state_energies.update({"Ru(S)": 0.0, "Ru(B)": 0.0})
                try:
                    initial_energy = _state_energy(initial, state_energies)
                    final_energy = _state_energy(final, state_energies)
                except KeyError:
                    continue
                forward_barrier = round(manual_kcal / 23.060548867, 12)
                reaction_energy = round(final_energy - initial_energy, 12)
                reverse_barrier = round(forward_barrier - reaction_energy, 12)
                transition_energy = round(initial_energy + forward_barrier, 12)
                label_kind = "reported_activation_energy_kcal_mol"
                method = "reported kinetic-model activation energy"
                base_quality = "medium"
                base_flags.append("activation_energy_converted_from_kcal_per_mol")
            else:
                continue
            common = {
                "source": "ckineticsdb",
                "source_record_id": f"{project}:{filename}:{row_number}",
                "reaction_class": "surface_elementary_step",
                "material_id": material,
                "material_formula": material,
                "chemical_composition": "",
                "facet": facet,
                "surface_shift": "",
                "site": "",
                "domain": "",
                "path_max_minus_initial_eV": "",
                "raw_initial_energy_eV": initial_energy,
                "raw_final_energy_eV": final_energy,
                "raw_ts_energy_eV": transition_energy,
                "barrierless": False,
                "converged": True,
                "label_kind": label_kind,
                "has_structure": False,
                "structure_ref": "",
                "publication": project,
                "method": method,
                "functional": functional,
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "source_url": CKINETICSDB_SOURCE_URL,
            }
            for direction, start, end, barrier, delta in (
                ("forward", initial, final, forward_barrier, reaction_energy),
                ("reverse", final, initial, reverse_barrier, -reaction_energy),
            ):
                flags = list(base_flags)
                quality = base_quality
                if barrier < 0:
                    flags.append("negative_ts_energy_difference")
                    quality = "invalid"
                elif barrier > 10:
                    flags.append("barrier_above_10_eV")
                    quality = "invalid"
                equation = f"{start} -> {end}"
                rows.append(
                    {
                        **common,
                        "record_id": (
                            f"ckineticsdb:{project}:{filename}:{row_number}:"
                            f"{direction}"
                        ),
                        "reaction_equation": equation,
                        "equation_canonical": canonicalize_equation(equation),
                        "barrier_eV": barrier,
                        "reaction_energy_eV": round(delta, 12),
                        "label_quality": quality,
                        "quality_flags": ";".join(flags),
                    }
                )
    return rows


def build_uar_record(source: Mapping) -> dict:
    datapoint = _text(source.get("datapoint"))
    return {
        "source": "uar_literature_compilation",
        "record_id": f"uar:{datapoint}",
        "source_record_id": datapoint,
        "reaction_class": "",
        "reaction_equation": "",
        "equation_canonical": "",
        "material_id": "",
        "material_formula": "",
        "chemical_composition": "",
        "facet": "",
        "surface_shift": "",
        "site": "",
        "domain": "",
        "barrier_eV": _float(source.get("original [eV]")),
        "reaction_energy_eV": "",
        "path_max_minus_initial_eV": "",
        "raw_initial_energy_eV": "",
        "raw_final_energy_eV": "",
        "raw_ts_energy_eV": "",
        "barrierless": "",
        "converged": "",
        "label_kind": "literature_compilation_barrier_identity_withheld",
        "label_quality": "unusable",
        "quality_flags": "missing_reaction_and_surface_identity",
        "has_structure": False,
        "structure_ref": "",
        "publication": "Hutton et al., JCIM 2023, 10.1021/acs.jcim.3c00740",
        "method": "literature compilation; mixed DFT methods",
        "functional": "mixed",
        "license": "CC BY-NC 4.0",
        "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "source_url": "https://acs.figshare.com/articles/dataset/24158651",
    }


def _species_composition(token: str) -> Counter:
    """Return elemental counts for the compact CHO labels in the Mo2C table."""

    match = re.fullmatch(r"(?:(\d+))?((?:[A-Z][a-z]?\d*)+)", token)
    if match is None:
        raise ValueError(f"unrecognized Mo2C reaction token: {token}")
    multiplier = int(match.group(1) or 1)
    composition = Counter()
    for element, count in re.findall(r"([A-Z][a-z]?)(\d*)", match.group(2)):
        composition[element] += multiplier * int(count or 1)
    return composition


def _mo2c_equation(name: str) -> tuple[str, str]:
    tokens = _text(name).removeprefix("NEB_").split("_")
    candidates = []
    for split in range(1, len(tokens)):
        left = sum((_species_composition(token) for token in tokens[:split]), Counter())
        right = sum((_species_composition(token) for token in tokens[split:]), Counter())
        if left == right:
            candidates.append(split)
    if len(candidates) != 1:
        raise ValueError(f"cannot uniquely split Mo2C reaction name: {name}")
    split = candidates[0]

    def state(parts: Sequence[str]) -> str:
        return " + ".join(f"{part}*" for part in parts)

    return state(tokens[:split]), state(tokens[split:])


def load_mo2c_fts_records(path: Path) -> list[dict]:
    """Load both directions of the 35 published Mo2C Gibbs-energy paths."""

    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        lines = [line for line in handle if line.lstrip().startswith("Elementary Step") or re.match(r"^\d+\t", line)]
    reader = csv.DictReader(lines, delimiter="\t")
    rows = []
    for source in reader:
        source = {str(key).strip(): value for key, value in source.items()}
        step = _text(source.get("Elementary Step"))
        name = _text(source.get("Name"))
        initial, final = _mo2c_equation(name)
        initial_energy = _float(source.get("initial G (eV)"))
        ts_energy = _float(source.get("TS G(eV)"))
        final_energy = _float(source.get("final G (eV) "))
        if final_energy is None:
            final_energy = _float(source.get("final G (eV)"))
        reaction_energy = _float(source.get("Erxn (eV)"))
        forward_barrier = _float(source.get("barrier (eV)"))
        reverse_barrier = _float(source.get("reverse barrier (eV)"))
        common = {
            "source": "mo2c_fts_35",
            "source_record_id": step,
            "reaction_class": "surface_elementary_step",
            "material_id": "2D-Mo2C",
            "material_formula": "Mo2C",
            "chemical_composition": "Mo2C",
            "facet": "0001",
            "surface_shift": "",
            "site": "",
            "domain": "",
            "path_max_minus_initial_eV": "",
            "raw_initial_energy_eV": initial_energy,
            "raw_final_energy_eV": final_energy,
            "raw_ts_energy_eV": ts_energy,
            "converged": True,
            "label_kind": "dft_gibbs_activation_free_energy",
            "has_structure": False,
            "structure_ref": "",
            "publication": "Kountoupi et al., 2D-Mo2C Fischer-Tropsch (2024)",
            "method": "DFT NEB plus vibrational Gibbs correction",
            "functional": "PBE-D3",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source_url": MO2C_FTS_SOURCE_URL,
        }
        for direction, start, end, barrier, delta in (
            ("forward", initial, final, forward_barrier, reaction_energy),
            (
                "reverse",
                final,
                initial,
                reverse_barrier,
                None if reaction_energy is None else -reaction_energy,
            ),
        ):
            flags = []
            quality = "high"
            if barrier is None:
                flags.append("missing_barrier")
                quality = "invalid"
            elif barrier < 0:
                flags.append("negative_reported_barrier")
                quality = "invalid"
            elif barrier > 10:
                flags.append("barrier_above_10_eV")
                quality = "invalid"
            equation = f"{start} -> {end}"
            rows.append(
                {
                    **common,
                    "record_id": f"mo2c_fts_35:{step}:{direction}",
                    "reaction_equation": equation,
                    "equation_canonical": canonicalize_equation(equation),
                    "barrier_eV": barrier,
                    "reaction_energy_eV": delta,
                    "barrierless": barrier is not None and barrier <= 0,
                    "label_quality": quality,
                    "quality_flags": ";".join(flags),
                }
            )
    return rows


SBH17_DATA = (
    ("H2", "Cu", "111", "bridge", "SRP43", 0.628),
    ("H2", "Cu", "100", "bridge", "SRP43", 0.740),
    ("H2", "Cu", "110", "short-bridge", "optPBE-vdW-DF1", 0.789),
    ("H2", "Pt", "111", "top (early)", "PBEalpha57-vdW-DF2", -0.008),
    ("H2", "Pt", "211", "top", "PBEalpha57-vdW-DF2", -0.083),
    ("H2", "Ru", "0001", "top (early)", "PBE-vdW-DF2", 0.004),
    ("H2", "Ni", "111", "top (early)", "PBE-vdW-DF2", 0.024),
    ("H2", "Ag", "111", "bridge", "MS-PBEl-rVV10", 1.082),
    ("N2", "Ru", "0001", "bridge", "RPBE", 1.840),
    ("N2", "Ru", "10-10", "", "experiment", 0.40),
    ("CH4", "Ni", "111", "top", "SRP32-vdW-DF1", 1.015),
    ("CH4", "Ni", "100", "", "experiment", 0.76),
    ("CH4", "Ni", "211", "top", "SRP32-vdW-DF1", 0.699),
    ("CH4", "Pt", "111", "top", "SRP32-vdW-DF1", 0.815),
    ("CH4", "Pt", "211", "top", "SRP32-vdW-DF1", 0.559),
    ("CH4", "Ir", "111", "top", "SRP32-vdW-DF1", 0.836),
    ("CH4", "Ru", "0001", "", "experiment", 0.80),
)


def build_sbh17_records() -> list[dict]:
    """Return the 17 CC-BY benchmark dissociative-chemisorption barriers."""

    equations = {
        "H2": "H2(g) + 2* -> 2H*",
        "N2": "N2(g) + 2* -> 2N*",
        "CH4": "CH4(g) + 2* -> CH3* + H*",
    }
    rows = []
    for index, (molecule, metal, facet, site, functional, barrier) in enumerate(
        SBH17_DATA, start=1
    ):
        equation = equations[molecule]
        flags = "submerged_barrier" if barrier < 0 else ""
        rows.append(
            {
                "source": "sbh17",
                "record_id": f"sbh17:{index}",
                "source_record_id": str(index),
                "reaction_class": "dissociative_chemisorption",
                "reaction_equation": equation,
                "equation_canonical": canonicalize_equation(equation),
                "material_id": metal,
                "material_formula": metal,
                "chemical_composition": metal,
                "facet": facet,
                "surface_shift": "",
                "site": site,
                "domain": "benchmark",
                "barrier_eV": barrier,
                "reaction_energy_eV": "",
                "path_max_minus_initial_eV": "",
                "raw_initial_energy_eV": "",
                "raw_final_energy_eV": "",
                "raw_ts_energy_eV": "",
                "barrierless": barrier < 0,
                "converged": True,
                "label_kind": "benchmark_dissociative_chemisorption_barrier",
                "label_quality": "high",
                "quality_flags": flags,
                "has_structure": False,
                "structure_ref": "",
                "publication": "Tchakoua et al., JCTC 2023, SBH17",
                "method": "SRP-DFT benchmark" if functional != "experiment" else "semiempirical experiment",
                "functional": "" if functional == "experiment" else functional,
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "source_url": SBH17_SOURCE_URL,
            }
        )
    return rows


GAME_INTERMEDIATE_NAME = re.compile(
    r"^(?P<metal>[a-z]+)-(?P<code>\d{4})(?:[a-z].*)?$"
)
GAME_TS_NAME = re.compile(
    r"^(?P<metal>[a-z]+)-"
    r"(?P<initial>\d{4}(?:\+\d{4})*)-"
    r"(?P<final>\d{4}(?:\+\d{4})*)"
    r"(?:-(?P<variant>[a-z][a-z0-9]*))?$"
)


def _game_code_formula(code: str) -> str:
    return "".join(
        element + (str(int(count)) if int(count) > 1 else "")
        for element, count in zip("CHO", code[:3])
        if int(count)
    )


def _game_facet(value: str) -> str:
    facet = _text(value)
    match = re.fullmatch(r"[a-z]+\(([^()]*)\)", facet.lower())
    return (match.group(1) if match else facet).replace("m", "-")


def _game_state_energy(
    *,
    codes: str,
    reaction_species: Sequence[str],
    metal: str,
    facet: str,
    exact_index: Mapping[tuple[str, str, str], Sequence[object]],
    formula_index: Mapping[tuple[str, str, str], Sequence[object]],
) -> tuple[float, list[int], list[str], list[str]]:
    remaining = Counter(reaction_species)
    energy = 0.0
    row_ids = []
    actual_species = list(reaction_species)
    flags = []
    for code in codes.split("+"):
        if code == "0000":
            continue
        formula = _game_code_formula(code)
        if remaining[formula] > 0:
            remaining[formula] -= 1
        else:
            actual_species.append(formula)
            flags.append("coadsorbate_recovered_from_path_code")
        candidates = exact_index.get((metal, facet, code), ())
        if not candidates:
            candidates = formula_index.get((metal, facet, formula), ())
            flags.append("intermediate_code_missing_formula_fallback")
        if not candidates:
            raise KeyError((metal, facet, code, formula))
        best = min(candidates, key=lambda row: float(row.get("scaled_energy")))
        energy += float(best.get("scaled_energy"))
        row_ids.append(int(best.id))

    for formula in reaction_species:
        if remaining[formula] <= 0:
            continue
        remaining[formula] -= 1
        candidates = formula_index.get((metal, facet, formula), ())
        if not candidates:
            raise KeyError((metal, facet, formula))
        best = min(candidates, key=lambda row: float(row.get("scaled_energy")))
        energy += float(best.get("scaled_energy"))
        row_ids.append(int(best.id))
        flags.append("implicit_fragment_recovered_from_reaction_string")
    return energy, row_ids, actual_species, flags


def load_game_net_uq_records(path: Path) -> list[dict]:
    """Derive directional barriers from GAME-Net-UQ TS and intermediate rows.

    The public database identifies molecular graphs but not a unique adsorption
    site for every endpoint.  We therefore use the lowest-energy intermediate
    carrying the matching graph code and explicitly classify the result as a
    derived (medium-confidence) label.  Formula fallback is retained at low
    confidence to maximize coverage without hiding the weaker match.
    """

    from ase.db import connect

    database = connect(str(path))
    all_rows = list(database.select())
    exact_index = defaultdict(list)
    formula_index = defaultdict(list)
    for row in all_rows:
        if row.get("calc_type") != "int":
            continue
        match = GAME_INTERMEDIATE_NAME.fullmatch(
            Path(_text(row.get("path"))).name.lower()
        )
        if match is None:
            continue
        metal = _text(row.get("metal"))
        facet = _text(row.get("facet"))
        code = match.group("code")
        exact_index[(metal, facet, code)].append(row)
        formula_index[(metal, facet, _game_code_formula(code))].append(row)

    rows = []
    database_name = Path(path).name
    for transition in all_rows:
        if transition.get("calc_type") != "ts":
            continue
        match = GAME_TS_NAME.fullmatch(
            Path(_text(transition.get("path"))).name.lower()
        )
        reaction = _text(transition.get("rxn_string"))
        if match is None or not reaction or reaction == "N/A" or " -> " not in reaction:
            continue
        initial_text, final_text = reaction.split(" -> ", 1)
        initial_species = [part.strip() for part in initial_text.split(" + ")]
        final_species = [part.strip() for part in final_text.split(" + ")]
        metal = _text(transition.get("metal"))
        raw_facet = _text(transition.get("facet"))
        try:
            initial_energy, initial_ids, initial_actual, initial_flags = (
                _game_state_energy(
                    codes=match.group("initial"),
                    reaction_species=initial_species,
                    metal=metal,
                    facet=raw_facet,
                    exact_index=exact_index,
                    formula_index=formula_index,
                )
            )
            final_energy, final_ids, final_actual, final_flags = _game_state_energy(
                codes=match.group("final"),
                reaction_species=final_species,
                metal=metal,
                facet=raw_facet,
                exact_index=exact_index,
                formula_index=formula_index,
            )
        except KeyError:
            continue
        transition_energy = _float(transition.get("scaled_energy"))
        if transition_energy is None:
            continue
        forward_barrier = round(transition_energy - initial_energy, 12)
        reaction_energy = round(final_energy - initial_energy, 12)
        reverse_barrier = round(transition_energy - final_energy, 12)
        shared_flags = [
            "lowest_energy_intermediate_site_inferred",
            *initial_flags,
            *final_flags,
        ]
        note = _text(transition.get("note"))
        if not note.startswith("1 img_freqs"):
            shared_flags.append("not_exactly_one_imaginary_frequency")
        fallback = "intermediate_code_missing_formula_fallback" in shared_flags
        converged = _text(transition.get("converged")).lower() != "no"
        if not converged:
            shared_flags.append("transition_state_not_converged")
        structure_ref = (
            f"{database_name}#ts={transition.id};"
            f"initial={','.join(map(str, initial_ids))};"
            f"final={','.join(map(str, final_ids))}"
        )
        common = {
            "source": "game_net_uq",
            "source_record_id": str(transition.id),
            "reaction_class": "surface_bond_breaking",
            "material_id": metal,
            "material_formula": metal,
            "chemical_composition": metal,
            "facet": _game_facet(raw_facet),
            "surface_shift": "",
            "site": "lowest-energy matching endpoint",
            "domain": "GAME-Net-UQ training domain",
            "raw_initial_energy_eV": initial_energy,
            "raw_final_energy_eV": final_energy,
            "raw_ts_energy_eV": transition_energy,
            "converged": converged,
            "label_kind": "derived_dft_ts_minus_lowest_matching_intermediate",
            "has_structure": True,
            "structure_ref": structure_ref,
            "publication": "Morandi et al., Nature Chemical Engineering (2026)",
            "method": "DFT improved dimer transition-state search",
            "functional": "PBE-D3",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source_url": GAME_NET_UQ_SOURCE_URL,
        }

        def state_text(species: Sequence[str]) -> str:
            return " + ".join(f"{formula}*" for formula in species)

        for direction, start, end, barrier, delta, path_barrier in (
            (
                "forward",
                initial_actual,
                final_actual,
                forward_barrier,
                reaction_energy,
                forward_barrier,
            ),
            (
                "reverse",
                final_actual,
                initial_actual,
                reverse_barrier,
                -reaction_energy,
                reverse_barrier,
            ),
        ):
            flags = list(dict.fromkeys(shared_flags))
            quality = "low" if fallback else "medium"
            if barrier < 0:
                flags.append("negative_derived_barrier")
                quality = "invalid"
            elif barrier > 10:
                flags.append("barrier_above_10_eV")
                quality = "invalid"
            elif not converged:
                quality = "invalid"
            equation = f"{state_text(start)} -> {state_text(end)}"
            rows.append(
                {
                    **common,
                    "record_id": f"game_net_uq:{transition.id}:{direction}",
                    "reaction_equation": equation,
                    "equation_canonical": canonicalize_equation(equation),
                    "barrier_eV": barrier,
                    "reaction_energy_eV": round(delta, 12),
                    "path_max_minus_initial_eV": path_barrier,
                    "barrierless": barrier <= 0,
                    "label_quality": quality,
                    "quality_flags": ";".join(flags),
                }
            )
    return rows


def curated_layers(rows: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    positive = []
    high_confidence = []
    for row in rows:
        barrier = _float(row.get("barrier_eV"))
        if barrier is None or barrier <= 0:
            continue
        positive.append(row)
        if row.get("label_quality") == "high" and barrier <= 10:
            high_confidence.append(row)
    return positive, high_confidence


def training_candidate_layers(
    rows: Sequence[dict],
) -> tuple[list[dict], list[dict]]:
    """Select usable labels, with a stricter subset carrying facet identity."""

    candidates = []
    identity_complete = []
    for row in rows:
        barrier = _float(row.get("barrier_eV"))
        if barrier is None or barrier <= 0:
            continue
        if row.get("label_quality") not in {"high", "medium"}:
            continue
        if not _text(row.get("reaction_equation")) or not _text(
            row.get("material_formula")
        ):
            continue
        candidates.append(row)
        if _text(row.get("facet")):
            identity_complete.append(row)
    return candidates, identity_complete


def structure_training_candidates(rows: Sequence[dict]) -> list[dict]:
    """Return quality-gated training labels that reference atomic structures."""

    candidates, _ = training_candidate_layers(rows)
    return [row for row in candidates if bool(row.get("has_structure"))]


def _fingerprint(row: Mapping) -> str:
    barrier = _float(row.get("barrier_eV"))
    equation = canonicalize_equation(_text(row.get("reaction_equation")))
    material = re.sub(r"\s+", "", _text(row.get("material_formula")).lower())
    facet = re.sub(r"[(),\s]", "", _text(row.get("facet")).lower())
    if not equation or not material or not facet or barrier is None:
        return ""
    reaction_energy = _float(row.get("reaction_energy_eV"))
    parts = [
        equation,
        material,
        facet,
        f"{barrier:.6f}",
        "" if reaction_energy is None else f"{reaction_energy:.6f}",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def annotate_duplicates(rows: Sequence[dict]) -> None:
    groups = defaultdict(list)
    for row in rows:
        fingerprint = _fingerprint(row)
        row["duplicate_fingerprint"] = fingerprint
        if fingerprint:
            groups[fingerprint].append(row)
    for members in groups.values():
        sources = ";".join(sorted({str(row["source"]) for row in members}))
        for row in members:
            row["duplicate_count"] = len(members)
            row["duplicate_sources"] = sources
    for row in rows:
        row.setdefault("duplicate_count", 1)
        row.setdefault("duplicate_sources", _text(row.get("source")))


def deduplicate_records(rows: Sequence[dict]) -> list[dict]:
    quality_rank = {"high": 3, "medium": 2, "low": 1, "invalid": 0}
    selected = {}
    ungrouped = []
    for row in rows:
        fingerprint = _text(row.get("duplicate_fingerprint"))
        if not fingerprint:
            ungrouped.append(row)
            continue
        previous = selected.get(fingerprint)
        if previous is None or quality_rank.get(row.get("label_quality"), -1) > quality_rank.get(
            previous.get("label_quality"), -1
        ):
            selected[fingerprint] = row
    return ungrouped + list(selected.values())


def _iter_catalysis_hub_nodes(directory: Path) -> Iterable[dict]:
    seen_ids = {}
    for page in sorted(Path(directory).glob("page-*.json.gz")):
        with gzip.open(page, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        connection = payload.get("data", {}).get("reactions", {})
        for edge in connection.get("edges", []):
            node = edge.get("node", edge)
            source_id = _text(node.get("id"))
            if source_id:
                previous = seen_ids.get(source_id)
                if previous is not None:
                    if previous != node:
                        raise ValueError(
                            f"conflicting Catalysis-Hub payloads for id {source_id}"
                        )
                    continue
                seen_ids[source_id] = node
            yield node


def _read_catapp(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_pickle(path: Path):
    # Inputs are pinned files from the official FAIR-Chem repository. Pickle
    # must never be accepted here from an untrusted arbitrary URL.
    with Path(path).open("rb") as handle:
        return pickle.load(handle)


def _read_json_documents(path: Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        value = json.loads(text)
        if not isinstance(value, list):
            raise ValueError(f"expected a JSON array: {path}")
        return value
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def load_oc20neb_records(
    *,
    mapping_directory: Path,
    reaction_database_directory: Path,
    bulks_path: Path,
    trajectory_archive: Path,
) -> list[dict]:
    import pandas as pd

    mappings = {
        "desorption": pd.read_pickle(mapping_directory / "desorption_mapping.pkl"),
        "dissociation": pd.read_pickle(
            mapping_directory / "dissociation_mapping.pkl"
        ),
        "transfer": pd.read_pickle(mapping_directory / "transfer_mapping.pkl"),
    }
    reaction_databases = {
        "desorption": _read_pickle(
            reaction_database_directory / "desorptions_9Aug23.pkl"
        ),
        "dissociation": _read_pickle(
            reaction_database_directory / "dissociation_reactions_22May24.pkl"
        ),
        "transfer": _read_pickle(
            reaction_database_directory / "transfers_5Sept23.pkl"
        ),
    }
    bulks = _read_pickle(bulks_path)
    with tarfile.open(trajectory_archive, "r:gz") as archive:
        archive_names = {
            Path(member.name).name
            for member in archive.getmembers()
            if member.isfile() and member.name.endswith(".traj")
        }
    return build_oc20neb_records(
        mappings,
        reaction_databases=reaction_databases,
        bulks=bulks,
        archive_names=archive_names,
    )


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _write_csv_gz(path: Path, rows: Sequence[Mapping]) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            with io.TextIOWrapper(zipped, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: _csv_value(row.get(key, "")) for key in FIELDNAMES})
    return {
        "path": path.name,
        "rows": len(rows),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def export_barrier_files(
    *,
    output_directory: Path,
    catalysis_hub_reactions: Path,
    catapp_csv: Path,
    oc20neb_mapping_directory: Path,
    oc20neb_reaction_database_directory: Path,
    oc20neb_bulks: Path,
    oc20neb_trajectory_archive: Path,
    meo_methane_activation_csv: Path,
    ckinetics_pmutt_json: Path,
    uar_xlsx: Path,
    mo2c_fts_gibbs_table: Path,
    game_net_uq_ase_database: Path,
) -> Path:
    cathub = [
        build_catalysis_hub_record(node)
        for node in _iter_catalysis_hub_nodes(catalysis_hub_reactions)
        if _float(node.get("activationEnergy")) is not None
    ]
    catapp = [
        build_catapp_record(row, row_number=index)
        for index, row in enumerate(_read_catapp(catapp_csv), start=1)
        if _float(row.get("activation_energy")) is not None
    ]
    oc20neb = load_oc20neb_records(
        mapping_directory=oc20neb_mapping_directory,
        reaction_database_directory=oc20neb_reaction_database_directory,
        bulks_path=oc20neb_bulks,
        trajectory_archive=oc20neb_trajectory_archive,
    )
    meo_methane = [
        build_meo_methane_record(row)
        for row in _read_catapp(meo_methane_activation_csv)
    ]
    ckinetics = build_ckineticsdb_records(
        _read_json_documents(ckinetics_pmutt_json)
    )
    import pandas as pd

    uar_frame = pd.read_excel(uar_xlsx, header=1)
    uar = [build_uar_record(row) for row in uar_frame.to_dict("records")]
    mo2c_fts = load_mo2c_fts_records(mo2c_fts_gibbs_table)
    sbh17 = build_sbh17_records()
    game_net_uq = load_game_net_uq_records(game_net_uq_ase_database)
    rows = (
        cathub
        + catapp
        + oc20neb
        + meo_methane
        + ckinetics
        + uar
        + mo2c_fts
        + sbh17
        + game_net_uq
    )
    annotate_duplicates(rows)
    positive, high_confidence = curated_layers(rows)
    training_candidates, training_candidates_identity_complete = (
        training_candidate_layers(rows)
    )
    deduplicated = deduplicate_records(rows)
    positive_deduplicated = deduplicate_records(positive)
    high_confidence_deduplicated = deduplicate_records(high_confidence)
    training_candidates_deduplicated = deduplicate_records(training_candidates)
    training_candidates_identity_complete_deduplicated = deduplicate_records(
        training_candidates_identity_complete
    )
    structure_training = structure_training_candidates(rows)
    structure_training_deduplicated = deduplicate_records(structure_training)
    structure_linked = [row for row in rows if bool(row.get("has_structure"))]
    structure_linked_numeric = [
        row
        for row in structure_linked
        if _float(row.get("barrier_eV")) is not None
        and _float(row.get("barrier_eV")) > 0
    ]
    identity_complete_positive = [
        row
        for row in positive
        if _text(row.get("reaction_equation"))
        and _text(row.get("material_formula"))
        and _text(row.get("facet"))
    ]
    identity_complete_positive_deduplicated = deduplicate_records(
        identity_complete_positive
    )

    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    files = []
    for name, layer in (
        ("catalysis_hub_barriers.csv.gz", cathub),
        ("catapp_barriers.csv.gz", catapp),
        ("oc20neb_barriers.csv.gz", oc20neb),
        ("meo_methane_barriers.csv.gz", meo_methane),
        ("ckineticsdb_barriers.csv.gz", ckinetics),
        ("uar_labels_identity_withheld.csv.gz", uar),
        ("mo2c_fts_barriers.csv.gz", mo2c_fts),
        ("sbh17_barriers.csv.gz", sbh17),
        ("game_net_uq_derived_barriers.csv.gz", game_net_uq),
        ("barriers_all_raw.csv.gz", rows),
        ("barriers_positive.csv.gz", positive),
        ("barriers_high_confidence.csv.gz", high_confidence),
        ("barriers_training_candidates.csv.gz", training_candidates),
        (
            "barriers_training_candidates_deduplicated.csv.gz",
            training_candidates_deduplicated,
        ),
        (
            "barriers_training_candidates_identity_complete.csv.gz",
            training_candidates_identity_complete,
        ),
        (
            "barriers_training_candidates_identity_complete_deduplicated.csv.gz",
            training_candidates_identity_complete_deduplicated,
        ),
        ("barriers_structure_training_candidates.csv.gz", structure_training),
        (
            "barriers_structure_training_candidates_deduplicated.csv.gz",
            structure_training_deduplicated,
        ),
        ("barriers_deduplicated.csv.gz", deduplicated),
        ("barriers_positive_deduplicated.csv.gz", positive_deduplicated),
        (
            "barriers_high_confidence_deduplicated.csv.gz",
            high_confidence_deduplicated,
        ),
        ("barriers_structure_linked.csv.gz", structure_linked),
        ("barriers_structure_linked_numeric.csv.gz", structure_linked_numeric),
        ("barriers_identity_complete_positive.csv.gz", identity_complete_positive),
        (
            "barriers_identity_complete_positive_deduplicated.csv.gz",
            identity_complete_positive_deduplicated,
        ),
    ):
        files.append(_write_csv_gz(output_directory / name, layer))

    manifest = {
        "format": "independent-surface-barrier-export-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_ingestion": False,
        "sources": dict(Counter(row["source"] for row in rows)),
        "label_kinds": dict(Counter(row["label_kind"] for row in rows)),
        "label_quality": dict(Counter(row["label_quality"] for row in rows)),
        "counts": {
            "all_raw": len(rows),
            "positive": len(positive),
            "high_confidence": len(high_confidence),
            "deduplicated": len(deduplicated),
            "positive_deduplicated": len(positive_deduplicated),
            "high_confidence_deduplicated": len(high_confidence_deduplicated),
            "training_candidates": len(training_candidates),
            "training_candidates_deduplicated": len(
                training_candidates_deduplicated
            ),
            "training_candidates_identity_complete": len(
                training_candidates_identity_complete
            ),
            "training_candidates_identity_complete_deduplicated": len(
                training_candidates_identity_complete_deduplicated
            ),
            "structure_training_candidates": len(structure_training),
            "structure_training_candidates_deduplicated": len(
                structure_training_deduplicated
            ),
            "with_structure": sum(bool(row.get("has_structure")) for row in rows),
            "with_structure_and_numeric_barrier": len(structure_linked_numeric),
            "identity_complete_positive": len(identity_complete_positive),
            "identity_complete_positive_deduplicated": len(
                identity_complete_positive_deduplicated
            ),
        },
        "files": files,
    }
    manifest_path = output_directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def _default_paths() -> dict[str, Path]:
    root = default_data_root()
    raw = root / "raw" / "acquired"
    return {
        "catalysis_hub_reactions": raw / "catalysis-hub" / "reactions",
        "catapp_csv": raw / "catalysis-hub" / "static-catapp" / "catappdata.csv",
        "oc20neb_mapping_directory": raw / "oc20neb" / "mapping_files",
        "oc20neb_reaction_database_directory": raw
        / "oc20neb"
        / "reaction_databases",
        "oc20neb_bulks": raw / "oc20neb" / "bulks.pkl",
        "oc20neb_trajectory_archive": raw
        / "oc20neb"
        / "oc20neb_dft_trajectories_04_23_24.tar.gz",
        "meo_methane_activation_csv": raw
        / "catalysis-barriers"
        / "meo-methane-2026"
        / "activation.csv",
        "ckinetics_pmutt_json": raw
        / "ckineticsdb"
        / "ckineticsdb-pmutt.json",
        "uar_xlsx": raw
        / "catalysis-barriers"
        / "uar-2023"
        / "ci3c00740_si_002.xlsx",
        "mo2c_fts_gibbs_table": raw
        / "catalysis-barriers"
        / "mo2c-fts-2024"
        / "gibbs-energies-35-reactions.dat",
        "game_net_uq_ase_database": raw
        / "catalysis-barriers"
        / "game-net-uq-2026"
        / "all.db",
        "output_directory": root
        / "derived"
        / "catalysis-barriers"
        / f"unified-{date.today().isoformat()}",
    }


def main(argv: Sequence[str] | None = None) -> int:
    defaults = _default_paths()
    parser = ArgumentParser(description=__doc__)
    for name, default in defaults.items():
        parser.add_argument(
            f"--{name.replace('_', '-')}", type=Path, default=default
        )
    args = parser.parse_args(argv)
    manifest = export_barrier_files(
        output_directory=args.output_directory,
        catalysis_hub_reactions=args.catalysis_hub_reactions,
        catapp_csv=args.catapp_csv,
        oc20neb_mapping_directory=args.oc20neb_mapping_directory,
        oc20neb_reaction_database_directory=args.oc20neb_reaction_database_directory,
        oc20neb_bulks=args.oc20neb_bulks,
        oc20neb_trajectory_archive=args.oc20neb_trajectory_archive,
        meo_methane_activation_csv=args.meo_methane_activation_csv,
        ckinetics_pmutt_json=args.ckinetics_pmutt_json,
        uar_xlsx=args.uar_xlsx,
        mo2c_fts_gibbs_table=args.mo2c_fts_gibbs_table,
        game_net_uq_ase_database=args.game_net_uq_ase_database,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
