"""CMR (Computational Materials Repository) static ASE databases.

One adapter over twelve curated sub-databases downloaded from
cmr.fysik.dtu.dk; every other .db file in the directory is out of scope.
native_id is ``<dbname>:<row.id>`` plus the row's ``uid``/``name`` key when
present.

Sub-database notes (verified against the raw key_value_pairs):

* ``mp_gllbsc``: GLLB-SC gaps + derivative discontinuity for MP/ICSD
  structures; legacy numeric ``mpid`` and ``icsd_id`` are id matches, the
  relaxed structure is still fingerprinted (always_hash).  Twenty rows also
  carry the paper's GW benchmark ladder (lda/gllbsc/hse06/g0w0/gw0/gw gaps),
  each staged under its own method string.
* ``lowdim``: dimensionality scoring of COD/ICSD entries.  Structures are
  ICSD-derived and must NOT be redistributed: records are properties-only
  (structure=None) and match purely via ('cod'|'icsd', dbid).  Every row
  carries source in {COD, ICSD}; anything else is skipped.
* ``cubic_perovskites``: Castelli screening.  ``heat_of_formation_all`` is
  the heat of formation relative to the pool of competing reference phases
  (hull-like, quantized ~0.02 eV steps; SrTiO3 = -0.24 with the published
  screening threshold of 0.21 eV/atom), so it is staged as the new
  ``heat_of_formation`` in eV/atom, NOT as formation_energy_per_atom.
  CB_*/VB_* absolute band-edge positions are skipped.
* ``abs3``/``abse3``: perovskite sulfides/selenides; GLLB-SC + PBEsol gaps
  (abs3) and PBE heat of formation (abse3, eV/atom by magnitude:
  median -0.33, range -1.9..1.4).  abs3 m_e/m_h are skipped (sparse, mixed
  sign convention).  abs3 holds two disjoint row groups: 1,621 ABS3
  candidates keyed by GLLB_ind/GLLB_dir/PBEsol_gap and 2,458 competing
  reference phases (``isreference=1``) whose only property is ``gap_PBE``;
  the latter used to fall out of the "no mapped key" filter entirely and are
  now staged as PBE band gaps, with their ``icsd`` value (when it is a real
  ICSD code and not a Strukturbericht symbol) used as an id match.
  ``E_hull`` is NOT staged: it is constant across every prototype of one
  ABS3 composition, i.e. the hull distance of that composition's most stable
  prototype rather than of the row's own structure.
* ``oqmd12``/``oqmd123``: OQMD reference sets; ``oqmd_delta_e``/``hform``
  are elemental formation energies (eV/atom, ~99% negative),
  ``oqmd_stability`` is OQMD's hull distance (may be negative for
  hull-defining entries), ``oqmd_energy_pa`` is the OQMD total energy per
  atom (VASP GGA reference, ~-10..-1 eV/atom).  ``emag`` is skipped: the key
  is undocumented and its magnitudes (1e-5..0.2) fit neither a moment nor a
  per-atom energy unambiguously.
* ``pv_pec_oqmd``: PBE + GLLB-SC gaps, derivative discontinuity and
  effective masses; numeric ``icsd`` is an id match.
* ``a2bcx4``: quaternary chalcogenide screening.  GLLB-SC gaps; ``mbeef_en``
  is the mBEEF total energy of the cell in eV (verified numerically:
  ``E_relative_per_atom`` equals ``(mbeef_en/natoms - min within name)*1e3``
  exactly), staged per atom as ``total_energy_per_atom``.
* ``abx2``: ABX2 photovoltaic absorbers.  GLLB-SC + TB09 gaps and
  derivative discontinuity; ``E_hull`` is the mBEEF hull distance in
  eV/atom (magnitude-verified, may be negative for hull-defining rows,
  like ``oqmd_stability``).  ``m_e``/``m_h`` are effective masses in m_e
  whose sign encodes band curvature (the 21 binary III-V reference rows
  flip the convention of the 94 ternary rows), so absolute values are
  staged.  ``KS_gap``/``total_en`` are skipped.
* ``low_symmetry_perovskites``/``absorption_perovskites``: GLLB-SC gaps and
  derivative discontinuity.  The absorption ``eff``/``eff_max`` scalars are
  skipped: the CMR docs label them "eV" while plotting them as absorbed
  photon percentages, so the unit is not trustworthy.

``prototype`` (abs3, abse3, a2bcx4) is the screening template each row was
built from and is staged as ``structure_prototype``.  Symmetry symbols
(``space_group``) and the CB_*/VB_* absolute band edges stay out; so do
``standard_energy`` (cubic_perovskites' reference-state energy, a property of
the references and not of the row) and the ``lowdim`` geometry scores.

Rows in property-bearing dbs that lack every mapped key are skipped
entirely (no bare benchmark structures are staged).
"""

from __future__ import annotations

from typing import Any, Iterator

from scripts.properties.adapters._util import fast_cif, safe_float, safe_text
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

# fixed ingestion order
DB_ORDER = (
    "mp_gllbsc",
    "lowdim",
    "cubic_perovskites",
    "abs3",
    "abse3",
    "oqmd12",
    "oqmd123",
    "pv_pec_oqmd",
    "a2bcx4",
    "abx2",
    "low_symmetry_perovskites",
    "absorption_perovskites",
)


def _gap(kvp: dict, key: str, method: str) -> PropertyValue | None:
    value = safe_float(kvp.get(key))
    if value is None or value < 0:  # a few GLLB_ind entries are negative
        return None
    return PropertyValue("band_gap", value, "eV", method)


def _prototype(kvp: dict, method: str) -> PropertyValue | None:
    label = safe_text(kvp.get("prototype"))
    if not label:
        return None
    return PropertyValue("structure_prototype", label, None, method)


def _energy_per_atom(
    value: float | None, natoms: float | None, method: str
) -> PropertyValue | None:
    """Cell energy in eV -> eV/atom, rejecting absurd magnitudes."""

    if value is None or not natoms:
        return None
    per_atom = value / natoms
    if not -1e4 < per_atom < 1e4:
        return None
    return PropertyValue("total_energy_per_atom", per_atom, "eV/atom", method)


class CmrStaticAdapter(SourceAdapter):
    source_key = "cmr-static"
    # id matches point at parent MP/ICSD/COD/OQMD entries while the row's own
    # relaxed structure may still be a distinct pool candidate.  lowdim rows
    # carry no structure at all, so they can never be admitted as new.
    always_hash = True

    # ------------------------------------------------------------------
    # per-database row handlers: kvp -> (properties, match_ids, structure?)

    def _mp_gllbsc(self, kvp: dict) -> tuple[list, list, bool]:
        properties = []
        for key, method in (
            ("gllbsc_ind_gap", "GLLB-SC indirect"),
            ("gllbsc_dir_gap", "GLLB-SC direct"),
        ):
            prop = _gap(kvp, key, method)
            if prop:
                properties.append(prop)
        disc = safe_float(kvp.get("gllbsc_disc"))
        if disc is not None:
            properties.append(
                PropertyValue(
                    "gllbsc_derivative_discontinuity", disc, "eV", "GLLB-SC"
                )
            )
        # the 20-row GW benchmark ladder of the same paper
        for key, method in (
            ("lda_gap", "LDA"),
            ("gllbsc_gap", "GLLB-SC (GW benchmark set)"),
            ("hse06_gap", "HSE06"),
            ("g0w0_gap", "G0W0"),
            ("gw0_gap", "GW0"),
            ("gw_gap", "GW"),
        ):
            prop = _gap(kvp, key, method)
            if prop:
                properties.append(prop)
        match_ids = []
        for source, key in (("materials-project", "mpid"), ("icsd", "icsd_id")):
            pair = normalize_match_id(source, kvp.get(key))
            if pair:
                match_ids.append(pair)
        return properties, match_ids, True

    def _lowdim(self, kvp: dict) -> tuple[list, list, bool]:
        source = safe_text(kvp.get("source"))
        if source not in {"COD", "ICSD"}:
            return [], [], False
        pair = normalize_match_id(source.lower(), kvp.get("dbid"))
        if pair is None:
            return [], [], False
        dimtype = safe_text(kvp.get("dimtype"))
        if dimtype is None:
            return [], [], False
        properties = [
            PropertyValue(
                "dimensionality", dimtype, None, "geometric scoring (lowdim)"
            )
        ]
        # ICSD-derived licence: never ship the structure
        return properties, [pair], False

    def _cubic_perovskites(self, kvp: dict) -> tuple[list, list, bool]:
        properties = []
        hof = safe_float(kvp.get("heat_of_formation_all"))
        if hof is not None:
            properties.append(
                PropertyValue(
                    "heat_of_formation", hof, "eV/atom",
                    "PBE/GLLB (CMR perovskites)",
                )
            )
        for key, method in (
            ("gllbsc_dir_gap", "GLLB-SC direct"),
            ("gllbsc_ind_gap", "GLLB-SC indirect"),
        ):
            prop = _gap(kvp, key, method)
            if prop:
                properties.append(prop)
        return properties, [], True

    def _abs3(self, kvp: dict) -> tuple[list, list, bool]:
        properties = []
        for key, method in (
            ("GLLB_dir", "GLLB-SC direct"),
            ("GLLB_ind", "GLLB-SC indirect"),
            ("PBEsol_gap", "PBEsol"),
        ):
            prop = _gap(kvp, key, method)
            if prop:
                properties.append(prop)
        # reference-phase rows carry gap_PBE instead of the GLLB trio
        prop = _gap(kvp, "gap_PBE", "PBE (CMR ABS3 reference phase)")
        if prop:
            properties.append(prop)
        prototype = _prototype(kvp, "CMR ABS3 screening template")
        if prototype:
            properties.append(prototype)
        match_ids = []
        # 'icsd' holds either an ICSD code or a Strukturbericht symbol
        # ('B_h'); normalize_match_id rejects the latter
        pair = normalize_match_id("icsd", kvp.get("icsd"))
        if pair:
            match_ids.append(pair)
        return properties, match_ids, True

    def _abse3(self, kvp: dict) -> tuple[list, list, bool]:
        properties = []
        hof = safe_float(kvp.get("pbe_hof"))
        if hof is not None:
            properties.append(
                PropertyValue("heat_of_formation", hof, "eV/atom", "PBE")
            )
        energy = _energy_per_atom(
            safe_float(kvp.get("pbe_tot_en")), safe_float(kvp.get("_natoms")), "PBE"
        )
        if energy:
            properties.append(energy)
        prototype = _prototype(kvp, "CMR ABSe3 screening template")
        if prototype:
            properties.append(prototype)
        return properties, [], True

    def _oqmd(self, kvp: dict) -> tuple[list, list, bool]:
        method = "GGA OQMD (CMR)"
        properties = []
        for key, name, unit in (
            ("oqmd_delta_e", "formation_energy_per_atom", "eV/atom"),
            ("hform", "formation_energy_per_atom", "eV/atom"),
            ("oqmd_stability", "energy_above_hull", "eV/atom"),
            ("oqmd_energy_pa", "total_energy_per_atom", "eV/atom"),
        ):
            value = safe_float(kvp.get(key))
            if value is not None:
                properties.append(PropertyValue(name, value, unit, method))
        gap = _gap(kvp, "oqmd_bandgap", method)
        if gap:
            properties.append(gap)
        match_ids = []
        pair = normalize_match_id("oqmd", kvp.get("oqmd_id"))
        if pair:
            match_ids.append(pair)
        return properties, match_ids, True

    def _pv_pec_oqmd(self, kvp: dict) -> tuple[list, list, bool]:
        properties = []
        for key, method in (
            ("PBE_gap", "PBE"),
            ("GLLB_dir", "GLLB-SC direct"),
            ("GLLB_ind", "GLLB-SC indirect"),
        ):
            prop = _gap(kvp, key, method)
            if prop:
                properties.append(prop)
        disc = safe_float(kvp.get("Dxc"))
        if disc is not None:
            properties.append(
                PropertyValue(
                    "gllbsc_derivative_discontinuity", disc, "eV", "GLLB-SC"
                )
            )
        for key, name in (
            ("m_e", "effective_mass_electron"),
            ("m_h", "effective_mass_hole"),
        ):
            value = safe_float(kvp.get(key))
            if value is not None and value > 0:
                properties.append(
                    PropertyValue(name, value, "m_e", "DFT (CMR PV-PEC)")
                )
        match_ids = []
        pair = normalize_match_id("icsd", kvp.get("icsd"))
        if pair:
            match_ids.append(pair)
        return properties, match_ids, True

    def _a2bcx4(self, kvp: dict) -> tuple[list, list, bool]:
        properties = []
        for key, method in (
            ("GLLB_dir", "GLLB-SC direct"),
            ("GLLB_ind", "GLLB-SC indirect"),
        ):
            prop = _gap(kvp, key, method)
            if prop:
                properties.append(prop)
        # mbeef_en is the mBEEF total energy of the whole cell in eV
        # (verified against E_relative_per_atom, see module docstring)
        energy = _energy_per_atom(
            safe_float(kvp.get("mbeef_en")), safe_float(kvp.get("_natoms")), "mBEEF"
        )
        if energy:
            properties.append(energy)
        prototype = _prototype(kvp, "CMR A2BCX4 screening template")
        if prototype:
            properties.append(prototype)
        return properties, [], True

    def _abx2(self, kvp: dict) -> tuple[list, list, bool]:
        properties = []
        for key, method in (
            ("GLLB_dir", "GLLB-SC direct"),
            ("GLLB_ind", "GLLB-SC indirect"),
            ("TB09_dir", "TB09 direct"),
            ("TB09_ind", "TB09 indirect"),
        ):
            prop = _gap(kvp, key, method)
            if prop:
                properties.append(prop)
        disc = safe_float(kvp.get("Dxc"))
        if disc is not None:
            properties.append(
                PropertyValue(
                    "gllbsc_derivative_discontinuity", disc, "eV", "GLLB-SC"
                )
            )
        hull = safe_float(kvp.get("E_hull"))
        if hull is not None:
            properties.append(
                PropertyValue("energy_above_hull", hull, "eV/atom", "mBEEF")
            )
        # sign encodes band curvature (mixed convention, docstring): the
        # physical mass is the magnitude
        for key, name in (
            ("m_e", "effective_mass_electron"),
            ("m_h", "effective_mass_hole"),
        ):
            value = safe_float(kvp.get(key))
            if value is not None and value != 0:
                properties.append(
                    PropertyValue(name, abs(value), "m_e", "DFT (CMR ABX2)")
                )
        return properties, [], True

    def _gllb_perovskites(self, kvp: dict) -> tuple[list, list, bool]:
        """low_symmetry_perovskites + absorption_perovskites share keys."""

        properties = []
        for key, method in (
            ("gllbsc_dir_gap", "GLLB-SC direct"),
            ("gllbsc_ind_gap", "GLLB-SC indirect"),
        ):
            prop = _gap(kvp, key, method)
            if prop:
                properties.append(prop)
        disc = safe_float(kvp.get("gllbsc_disc"))
        if disc is not None:
            properties.append(
                PropertyValue(
                    "gllbsc_derivative_discontinuity", disc, "eV", "GLLB-SC"
                )
            )
        return properties, [], True

    # ------------------------------------------------------------------

    def _handler(self, dbname: str):
        return {
            "mp_gllbsc": self._mp_gllbsc,
            "lowdim": self._lowdim,
            "cubic_perovskites": self._cubic_perovskites,
            "abs3": self._abs3,
            "abse3": self._abse3,
            "oqmd12": self._oqmd,
            "oqmd123": self._oqmd,
            "pv_pec_oqmd": self._pv_pec_oqmd,
            "a2bcx4": self._a2bcx4,
            "abx2": self._abx2,
            "low_symmetry_perovskites": self._gllb_perovskites,
            "absorption_perovskites": self._gllb_perovskites,
        }[dbname]

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        from ase.db import connect
        from pymatgen.io.ase import AseAtomsAdaptor

        count = 0
        for dbname in DB_ORDER:
            path = self.root / f"{dbname}.db"
            if not path.exists():
                continue
            handler = self._handler(dbname)
            wants_structure = dbname != "lowdim"
            db = connect(str(path))
            for row in db.select(include_data=wants_structure):
                if limit is not None and count >= limit:
                    return
                kvp: dict[str, Any] = dict(row.key_value_pairs)
                # row-level cell size for handlers staging per-atom energies;
                # existing handlers read fixed keys and never iterate kvp
                kvp["_natoms"] = row.natoms
                properties, match_ids, ship_structure = handler(kvp)
                if not properties:
                    continue  # never stage bare benchmark structures
                structure = None
                if ship_structure:
                    try:
                        structure = fast_cif(
                            AseAtomsAdaptor.get_structure(row.toatoms())
                        )
                    except Exception:  # noqa: BLE001 - keep the property record
                        structure = None
                native_id = f"{dbname}:{row.id}"
                label = safe_text(kvp.get("uid")) or safe_text(kvp.get("name"))
                if label:
                    native_id = f"{native_id}:{label}"
                count += 1
                yield SourceRecord(
                    native_id=native_id,
                    properties=properties,
                    structure=structure,
                    match_ids=match_ids,
                )
