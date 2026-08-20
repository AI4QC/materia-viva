"""Materials Cloud Archive static OPTIMADE dumps: four curated datasets.

Each dataset directory holds OPTIMADE ``page-*.json.gz`` files whose
``attributes`` carry the structure (lattice_vectors + cartesian sites) plus
``_mcloudarchive_*`` scalars:

* ``mca-electrides-2023``: candidate electrides — ELF maximum, formation
  energy and convex-hull distance.  ``_mcloudarchive_convex_hull_distance``
  is only filled for entries above the hull; the signed variant covers every
  entry and is used as a fallback, under its own method string so the two
  conventions never merge.
* ``mca-nonlinear-optical-2025``: ABINIT DFPT second-harmonic-generation
  screening — d_KP (Kurtz-Perry powder-averaged SHG coefficient; the source
  reports it in pm/V, magnitudes 0.02..40+ are consistent with that unit),
  average refractive index, birefringence, LDA and HSE06 fundamental and
  direct gaps, plus the HSE06 optical trio (d_KP, n, birefringence) where
  the hybrid run exists, and the ABINIT space-group number.  Tensor fields
  (d_ijk, eps_ij), the Neumann-symmetrised d_KP duplicates and the
  ``src_*`` columns copied from the parent MP/Alexandria entry are skipped.
* ``mca-optical-2026``: averaged refractive index for MP/Alexandria entries
  plus the source database's band gap. Per-axis indices are skipped.
* ``mca-topological-2025``: TQC topological classification (mat_type =
  TrI/TI/TCI, tqc_type = symmetry-indicator class).

The records are relaxations tied to (but not necessarily identical with)
their MP / Alexandria / ICSD parents, so always_hash=True.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_MP_RE = re.compile(r"^mp-\d+$")
_AGM_RE = re.compile(r"^agm\d+$")


def optimade_structure(attributes: dict):
    """Build a pymatgen Structure from OPTIMADE structure attributes."""

    from pymatgen.core import Lattice, Structure

    return Structure(
        Lattice(attributes["lattice_vectors"]),
        attributes["species_at_sites"],
        attributes["cartesian_site_positions"],
        coords_are_cartesian=True,
    )


def _pool_pair(value) -> tuple[str, str] | None:
    """Map an mp-*/agm* id string onto its pool database."""

    text = safe_text(value)
    if not text:
        return None
    if _MP_RE.match(text):
        return normalize_match_id("materials-project", text)
    if _AGM_RE.match(text):
        return normalize_match_id("alexandria", text)
    return None


class MaterialsCloudArchiveStaticAdapter(SourceAdapter):
    source_key = "materials-cloud-archive-static"
    always_hash = True

    _DATASETS = (
        "mca-electrides-2023-2026-07-26",
        "mca-nonlinear-optical-2025-2026-07-26",
        "mca-optical-2026-2026-07-26",
        "mca-topological-2025-2026-07-26",
    )

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        for dataset in self._DATASETS:
            directory = self.root / dataset
            if not directory.is_dir():
                continue
            # short label without the acquisition date suffix
            label = re.sub(r"-2026-07-26$", "", dataset)
            for page in sorted(directory.glob("page-*.json.gz")):
                with gzip.open(page, "rt", encoding="utf-8") as handle:
                    docs = json.load(handle)["data"]
                for doc in docs:
                    if limit is not None and count >= limit:
                        return
                    record = self._build(label, doc)
                    if record is None:
                        continue
                    count += 1
                    yield record

    def _build(self, dataset: str, doc: dict) -> SourceRecord | None:
        rec_id = str(doc.get("id") or "").strip()
        attributes = doc.get("attributes") or {}
        if not rec_id:
            return None

        properties: list[PropertyValue] = []
        match_ids: list[tuple[str, str]] = []

        if dataset == "mca-electrides-2023":
            elf = safe_float(attributes.get("_mcloudarchive_elf_max"))
            if elf is not None:
                properties.append(PropertyValue("elf_max", elf, None, "PBE"))
            formation = safe_float(
                attributes.get("_mcloudarchive_formation_energy_per_atom")
            )
            if formation is not None:
                properties.append(
                    PropertyValue(
                        "formation_energy_per_atom", formation, "eV/atom",
                        "PBE (MC-electrides)",
                    )
                )
            hull = safe_float(
                attributes.get("_mcloudarchive_convex_hull_distance")
            )
            if hull is not None:
                properties.append(
                    PropertyValue(
                        "energy_above_hull", hull, "eV/atom",
                        "PBE (MC-electrides)",
                    )
                )
            else:
                signed = safe_float(
                    attributes.get("_mcloudarchive_signed_convex_hull_distance")
                )
                if signed is not None and -10.0 < signed < 10.0:
                    properties.append(
                        PropertyValue(
                            "energy_above_hull", signed, "eV/atom",
                            "PBE (MC-electrides, signed hull distance)",
                        )
                    )

        elif dataset == "mca-nonlinear-optical-2025":
            pair = _pool_pair(attributes.get("_mcloudarchive_src_id"))
            if pair:
                match_ids.append(pair)
            shg = safe_float(attributes.get("_mcloudarchive_d_kp"))
            if shg is not None:
                properties.append(
                    PropertyValue("shg_coefficient", shg, "pm/V", "LDA")
                )
            index = safe_float(attributes.get("_mcloudarchive_n"))
            if index is not None:
                properties.append(
                    PropertyValue("refractive_index", index, None, "LDA")
                )
            biref = safe_float(attributes.get("_mcloudarchive_biref"))
            if biref is not None:
                properties.append(
                    PropertyValue("birefringence", biref, None, "LDA")
                )
            hse_shg = safe_float(attributes.get("_mcloudarchive_hse_d_kp"))
            if hse_shg is not None:
                properties.append(
                    PropertyValue("shg_coefficient", hse_shg, "pm/V", "HSE06")
                )
            hse_index = safe_float(attributes.get("_mcloudarchive_hse_n"))
            if hse_index is not None and 1.0 <= hse_index <= 20.0:
                properties.append(
                    PropertyValue("refractive_index", hse_index, None, "HSE06")
                )
            hse_biref = safe_float(attributes.get("_mcloudarchive_hse_biref"))
            if hse_biref is not None:
                properties.append(
                    PropertyValue("birefringence", hse_biref, None, "HSE06")
                )
            for key, name, method in (
                ("_mcloudarchive_lda_bandgap_fund", "band_gap", "LDA"),
                ("_mcloudarchive_hse_bandgap_fund", "band_gap", "HSE06"),
                ("_mcloudarchive_lda_bandgap_dir", "band_gap_direct", "LDA"),
                ("_mcloudarchive_hse_bandgap_dir", "band_gap_direct", "HSE06"),
            ):
                gap = safe_float(attributes.get(key))
                if gap is not None:
                    properties.append(
                        PropertyValue(name, gap, "eV", method)
                    )
            spacegroup = safe_float(
                attributes.get("_mcloudarchive_abi_spg_number")
            )
            if spacegroup is not None and 1 <= spacegroup <= 230:
                properties.append(
                    PropertyValue(
                        "spacegroup_number", int(spacegroup), None,
                        "ABINIT symmetry analysis",
                    )
                )

        elif dataset == "mca-optical-2026":
            pair = _pool_pair(rec_id)
            if pair:
                match_ids.append(pair)
            index = safe_float(
                attributes.get("_mcloudarchive_refractive_index")
            )
            if index is not None:
                properties.append(
                    PropertyValue(
                        "refractive_index", index, None, "PBE (MC-optical)"
                    )
                )
            biref = safe_float(attributes.get("_mcloudarchive_biref"))
            if biref is not None:
                properties.append(
                    PropertyValue(
                        "birefringence", biref, None, "PBE (MC-optical)"
                    )
                )
            gap = safe_float(attributes.get("_mcloudarchive_src_bandgap"))
            if gap is not None:
                properties.append(
                    PropertyValue("band_gap", gap, "eV", "source DB")
                )

        elif dataset == "mca-topological-2025":
            mp = safe_text(attributes.get("_mcloudarchive_mp_id"))
            if mp:
                pair = normalize_match_id("materials-project", mp)
                if pair:
                    match_ids.append(pair)
            icsd = safe_text(attributes.get("_mcloudarchive_icsd_id"))
            if icsd:
                # ids arrive as float strings like '71581.0'
                icsd = icsd.removesuffix(".0")
                pair = normalize_match_id("icsd", icsd)
                if pair:
                    match_ids.append(pair)
            mat_type = safe_text(attributes.get("_mcloudarchive_mat_type"))
            if mat_type:
                properties.append(
                    PropertyValue(
                        "topology_class", mat_type, None, "PBE+SOC TQC"
                    )
                )
            tqc = safe_text(attributes.get("_mcloudarchive_tqc_type"))
            if tqc:
                properties.append(
                    PropertyValue("topology_invariant", tqc, None, "TQC")
                )

        try:
            structure = optimade_structure(attributes)
        except Exception:  # noqa: BLE001 - keep the property-only record
            structure = None
        return SourceRecord(
            native_id=f"{dataset}:{rec_id}",
            properties=properties,
            structure=structure,
            match_ids=match_ids,
        )
