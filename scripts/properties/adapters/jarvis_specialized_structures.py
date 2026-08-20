"""JARVIS specialized structure sets: superconductors, 2D update, polymers.

Five of the acquired zips are ingested — supercon_3d and supercon_2d
(electron-phonon-coupling Tc from McMillan-Allen-Dynes), dft_2d-2022 (the
JARVIS-DFT 2D update, same field vocabulary as the 3D dump), polymer_genome
(Huan et al. Sci Data 2016: 1,073 bulk polymer crystals with HSE06/GGA gaps
and dielectric constants; ``atom_en`` is their *atomization* energy per atom,
-7.5..-4.4 eV/atom, not a raw DFT total energy, so it is NOT staged as
``total_energy_per_atom``) and mxene275 (functionalized MXene monolayers;
``formation_energy`` is per atom by magnitude and cell-size scaling,
-3.0..+1.0 eV over 3-11 atom cells). The catalysis / surface / interface /
vacancy zips are non-bulk or adsorbate systems out of scope and are skipped
entirely.

native_id is "<subset>:<jid|id>"; structures are JARVIS Atoms dicts.
dft_2d-2022 references bare mp-#### ids (monolayer suffixes like mp-####-1L
are NOT the MP entry and are skipped). always_hash: every structure is a
JARVIS (or upstream-source) relaxation.

The two supercon sets publish the pair the McMillan-Allen-Dynes Tc is built
from, ``lamb`` (the dimensionless electron-phonon coupling constant) and
``wlog`` (the logarithmic average phonon frequency). Both are staged, and the
unit of ``wlog`` is verified rather than assumed: reading it as kelvin
reproduces every one of the 1,219 published Tc values to the last digit
through Tc = (wlog/1.2)*exp(-1.04(1+lamb)/(lamb - mu*(1 + 0.62 lamb))) with
mu* = 0.085 (RMSE 0.0 K over both sets), which also pins the Coulomb
pseudopotential the dataset used. ``press`` is "0 GPa" on every record and is
carried in the method string of both.

dft_2d-2022 shares the JARVIS-DFT field vocabulary exactly, so it reuses the
3D adapter's ``scalar_properties`` instead of a hand-copied subset; that
widens it from 8 mapped fields to the full set (total energy, TBmBJ and DFPT
dielectrics, effective masses, EFG, Γ-phonon scalars, elastic moduli,
BoltzTraP thermopower, HSE gap, piezo modulus) with identical names, units
and method strings.

Held back deliberately: ``stability`` ("stable"/"unstable" on the supercon
sets, with nothing in the dump saying whether it means dynamical or
thermodynamic stability), ``a2F``/``a2F_original_*``/``dos_info`` (spectra),
``cfid``/``desc`` (ML descriptors), ``src``/``label``/``method`` on
polymer_genome (bibliography/provenance), ``vol`` (structure-derived) and, as
in the 3D adapter, ``ncond``/``pcond``/``nkappa``/``pkappa``.
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from typing import Iterator

from scripts.properties.adapters._util import (
    jarvis_atoms_to_structure,
    safe_float,
    safe_text,
)
from scripts.properties.adapters.jarvis_dft import scalar_properties
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
)

#: native field -> plausible window, for the fields this adapter guards itself
#: (the dft_2d-2022 fields are guarded inside jarvis_dft.scalar_properties)
_RANGES: dict[str, tuple[float, float]] = {
    # dimensionless electron-phonon coupling; the sets span -0.047 .. 18.3 and
    # the one negative value is unphysical
    "lamb": (1e-6, 20.0),
    # logarithmic average phonon frequency in K; the sets span 0 .. 912 and a
    # zero means the a2F integral never resolved
    "wlog": (1e-6, 5000.0),
    "formation_energy_peratom": (-20.0, 20.0),
}

# polymer genome scalars (Huan et al. Sci Data 3:160012)
_POLYMER_GENOME_MAP: tuple[tuple[str, str, str | None, str], ...] = (
    ("hse_gap", "band_gap", "eV", "HSE06"),
    ("gga_gap", "band_gap", "eV", "GGA"),
    ("diel_tot", "dielectric_constant_total", None, "DFT (polymer genome)"),
    ("diel_ion", "dielectric_constant_ionic", None, "DFT (polymer genome)"),
    ("diel_elec", "dielectric_constant_electronic", None, "DFT (polymer genome)"),
)

# subset -> zip filename (member is namelist()[0] in each)
_SUBSETS: tuple[tuple[str, str], ...] = (
    ("supercon_3d", "supercon_3d.json.zip"),
    ("supercon_2d", "supercon_2d.json.zip"),
    ("dft_2d-2022", "dft_2d-2022.json.zip"),
    ("polymer_genome", "polymer_genome.json.zip"),
    ("mxene275", "mxene275.json.zip"),
)


class JarvisSpecializedStructuresAdapter(SourceAdapter):
    source_key = "jarvis-specialized-structures"
    always_hash = True

    def __init__(self, root=None) -> None:
        super().__init__(root)
        self.drops: Counter[str] = Counter()

    def _guard(self, value: float | None, key: str) -> float | None:
        """Drop (and count) values outside the window declared for `key`."""

        window = _RANGES.get(key)
        if value is None or window is None:
            return value
        if not (window[0] <= value <= window[1]):
            self.drops[key] += 1
            return None
        return value

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        try:
            for subset, filename in _SUBSETS:
                archive = self.root / filename
                with zipfile.ZipFile(archive) as bundle:
                    with bundle.open(bundle.namelist()[0]) as handle:
                        rows = json.load(handle)
                for index, row in enumerate(rows):
                    if limit is not None and count >= limit:
                        return
                    native = row.get("jid") or row.get("id") or f"{subset}-{index}"
                    if subset.startswith("supercon"):
                        properties = self._supercon_properties(row)
                    elif subset == "polymer_genome":
                        properties = self._polymer_genome_properties(row)
                    elif subset == "mxene275":
                        properties = self._mxene_properties(row)
                    else:
                        properties = self._dft_2d_properties(row)
                    # No id matching anywhere: dft_2d 'reference' mp ids point
                    # at the 3D bulk parent, not this monolayer, so an id match
                    # would attach 2D properties to the wrong pool material.
                    match_ids: list[tuple[str, str]] = []
                    try:
                        structure = jarvis_atoms_to_structure(row["atoms"])
                    except Exception:  # noqa: BLE001 - keep property-only record
                        structure = None
                    yield SourceRecord(
                        native_id=f"{subset}:{native}",
                        properties=properties,
                        structure=structure,
                        match_ids=match_ids,
                    )
                    count += 1
        finally:
            print(
                "[jarvis-specialized-structures] value drops: "
                + (str(dict(self.drops)) if self.drops else "none"),
                flush=True,
            )

    def _supercon_properties(self, row: dict) -> list[PropertyValue]:
        properties = []
        tc = safe_float(row.get("Tc"))
        if tc is not None:
            properties.append(
                PropertyValue(
                    "tc_superconducting", tc, "K", "McMillan-Allen-Dynes EPC"
                )
            )
        # every record says "0 GPa"; carrying it keeps the pair readable if a
        # later dump ever adds the pressure series the field exists for
        pressure = safe_text(row.get("press")) or "unstated pressure"
        method = f"Eliashberg α²F ({pressure})"
        for key, name, unit in (
            ("lamb", "electron_phonon_coupling", None),
            ("wlog", "phonon_log_average_frequency", "K"),
        ):
            value = self._guard(safe_float(row.get(key)), key)
            if value is not None:
                properties.append(PropertyValue(name, value, unit, method))
        # supercon_2d alone carries it; same field name and provenance as the
        # JARVIS-DFT entry the jid points at
        formation = self._guard(
            safe_float(row.get("formation_energy_peratom")), "formation_energy_peratom"
        )
        if formation is not None:
            properties.append(
                PropertyValue(
                    "formation_energy_per_atom", formation, "eV/atom", "OptB88vdW"
                )
            )
        return properties

    def _dft_2d_properties(self, row: dict) -> list[PropertyValue]:
        # identical field vocabulary to the 3D dump, so the mapping lives in
        # one place; spacegroup_number is left to the structure pipeline and
        # the dimensionality label is fixed rather than read from the record
        # ('na' on every 2D row)
        properties = scalar_properties(row, self.drops)
        properties.append(PropertyValue("dimensionality", "2D", None, "OptB88vdW"))
        return properties

    @staticmethod
    def _polymer_genome_properties(row: dict) -> list[PropertyValue]:
        # atom_en (atomization energy per atom) is deliberately not staged,
        # see module docstring
        properties = []
        for key, name, unit, method in _POLYMER_GENOME_MAP:
            value = safe_float(row.get(key))
            if value is not None:
                properties.append(PropertyValue(name, value, unit, method))
        return properties

    @staticmethod
    def _mxene_properties(row: dict) -> list[PropertyValue]:
        properties = []
        value = safe_float(row.get("formation_energy"))
        if value is not None:
            properties.append(
                PropertyValue(
                    "formation_energy_per_atom", value, "eV/atom",
                    "DFT (MXene275)",
                )
            )
        properties.append(
            PropertyValue("dimensionality", "2D", None, "DFT (MXene275)")
        )
        return properties

