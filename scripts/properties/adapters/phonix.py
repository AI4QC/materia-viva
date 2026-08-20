"""PHONIX: phono3py lattice thermal conductivity for MP structures.

One HuggingFace parquet (28,211 rows). ``unique_id`` distinguishes suffixed
reruns (mp-19-2) of the same parent ``mp_id``; every row keeps its own record.
Structures are ase-style dicts with *fractional* positions (verified: every
coordinate lies in [0, 1)). Large per-mode arrays (phfreq/phdos/mfp/kspec...)
are never loaded.

``modulus[GPa]`` is undocumented in the summary receipt; the value
distribution (median ~106 GPa) matches an EOS bulk modulus but a handful of
rows carry wildly unphysical fit failures (|B| > 1e6 GPa), so it is staged
under the source-specific name ``eos_bulk_modulus`` and clamped to
(0, 2000) GPa.

``kp[W/mK]`` and ``kc[W/mK]`` are the two halves of the Wigner transport
equation that phono3py solves: verified on all 7,444 rows carrying the three
columns, ``kp + kc == klat`` to a relative 4e-5 (median 5e-8). ``kp`` is the
particle-like (Peierls / populations) term, ``kc`` the coherence term from
wave-like tunnelling between overlapping branches — both are *phonon*
conductivities in W/m·K, not an electronic contribution, so they are staged as
``lattice_thermal_conductivity_particle`` / ``..._coherence`` beside the
existing ``lattice_thermal_conductivity`` row.

Reruns: 604 mp_ids carry more than one converged calculation, and 153 of those
groups are not told apart by ``volume_relaxation`` or ``qmesh`` alone (they are
independent force-constant fits), so the run tag from ``unique_id`` also goes
into the method whenever it differs from the parent ``mp_id``.
"""

from __future__ import annotations

import json
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

CM1_TO_THZ = 0.0299792458

#: outer sanity bound on a lattice thermal conductivity; 15 rows carry
#: fit failures up to 1e8 W/m·K (diamond, the record holder, is ~2200)
K_MAX = 1.0e5

_COLUMNS = [
    "mp_id",
    "unique_id",
    "spg_number",
    "structure",
    "modulus[GPa]",
    "klat[W/mK]",
    "kp[W/mK]",
    "kc[W/mK]",
    "qmesh",
    "volume_relaxation",
    "min_phfreq[cm^-1]",
    "max_phfreq[cm^-1]",
]

_WIGNER = (
    ("kp[W/mK]", "lattice_thermal_conductivity_particle", "particle-like"),
    ("kc[W/mK]", "lattice_thermal_conductivity_coherence", "coherence"),
)


def _run_method(row: dict, component: str) -> str:
    """Self-describing, per-run-unique method for one Wigner component.

    Same crystal, several converged runs: the volume treatment and the q-mesh
    are the physical variants, and the ``unique_id`` suffix separates repeat
    fits that share both.
    """

    parts = [
        "relaxed volume" if row.get("volume_relaxation") else "fixed volume"
    ]
    qmesh = row.get("qmesh")
    if qmesh:
        parts.append(f"q-mesh {qmesh}")
    unique_id = str(row.get("unique_id") or "")
    if unique_id and unique_id != str(row.get("mp_id") or ""):
        parts.append(f"run {unique_id}")
    return f"phono3py PBE Wigner {component} ({', '.join(parts)})"


def _to_structure(payload: str):
    from pymatgen.core import Lattice, Structure

    atoms = json.loads(payload)
    return Structure(
        Lattice(atoms["cell"]),
        atoms["symbols"],
        atoms["positions"],  # fractional (verified against cell dimensions)
        coords_are_cartesian=False,
    )


class PhonixAdapter(SourceAdapter):
    source_key = "phonix"
    always_hash = False

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        import pyarrow.parquet as pq

        files = sorted(self.root.glob("*.parquet"))
        count = 0
        for path in files:
            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(batch_size=512, columns=_COLUMNS):
                for row in batch.to_pylist():
                    if limit is not None and count >= limit:
                        return
                    count += 1
                    properties = []
                    klat = safe_float(row.get("klat[W/mK]"))
                    if klat is not None:
                        properties.append(
                            PropertyValue(
                                "lattice_thermal_conductivity",
                                klat,
                                "W/m·K",
                                "phono3py PBE",
                            )
                        )
                    for key, name, component in _WIGNER:
                        value = safe_float(row.get(key))
                        if value is None:
                            continue
                        if not 0.0 <= value < K_MAX:
                            continue
                        properties.append(
                            PropertyValue(
                                name,
                                value,
                                "W/m·K",
                                _run_method(row, component),
                            )
                        )
                    modulus = safe_float(row.get("modulus[GPa]"))
                    if modulus is not None and 0.0 < modulus < 2000.0:
                        properties.append(
                            PropertyValue(
                                "eos_bulk_modulus", modulus, "GPa", "phonopy EOS"
                            )
                        )
                    max_freq = safe_float(row.get("max_phfreq[cm^-1]"))
                    if max_freq is not None:
                        properties.append(
                            PropertyValue(
                                "phonon_max_frequency",
                                max_freq * CM1_TO_THZ,
                                "THz",
                                "phono3py PBE",
                            )
                        )
                    min_freq = safe_float(row.get("min_phfreq[cm^-1]"))
                    if min_freq is not None:
                        properties.append(
                            PropertyValue(
                                "phonon_min_frequency",
                                min_freq * CM1_TO_THZ,
                                "THz",
                                "phono3py PBE",
                            )
                        )
                        properties.append(
                            PropertyValue(
                                "has_imaginary_phonon",
                                min_freq < -1e-6,
                                None,
                                "phono3py PBE",
                            )
                        )
                    spacegroup = safe_float(row.get("spg_number"))
                    if spacegroup:
                        properties.append(
                            PropertyValue(
                                "spacegroup_number", int(spacegroup), None,
                                "phono3py PBE",
                            )
                        )
                    match_ids = []
                    mp = normalize_match_id("materials-project", row.get("mp_id"))
                    if mp:
                        match_ids.append(mp)
                    try:
                        structure = _to_structure(row["structure"])
                    except Exception:  # noqa: BLE001 - keep properties anyway
                        structure = None
                    yield SourceRecord(
                        native_id=str(row["unique_id"]),
                        properties=properties,
                        structure=structure,
                        match_ids=match_ids,
                    )
