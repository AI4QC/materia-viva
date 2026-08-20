"""SuperBand electronic DOS curves.

Source archive: data/raw/acquired/superband/0724.hdf5 — one HDF5 group per
material, group name = native id (integer as string).  Each group's
``sc_DOSs`` dataset is written by the upstream repo's write_superbands.py as
``dos0s.T`` where row 0 of ``dos0s`` is ``bs_dos.energies - bs_dos.efermi``
(eV) and the following rows are the orbital-projected DOS for
OrbitalType(0..n) (s, p, d, and f when present), spin-averaged.  So column 0
is a physically meaningful E - E_F axis; columns 1..n are orbital-resolved
DOS in states/eV.  We store the summed total as ``y`` plus the orbital
components as ``series``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from scripts.properties.curves import PROJECT_ROOT, CurveRecord

HDF5_PATH = (
    PROJECT_ROOT / "data" / "raw" / "acquired" / "superband" / "0724.hdf5"
)
ORBITAL_NAMES = ("s", "p", "d", "f", "g")
MAX_POINTS = 2000
MAX_PAYLOAD = 1_500_000  # bytes, uncompressed


def _round(values):
    return [round(float(v), 5) for v in values]


def _build_payload(dos) -> str | None:
    """Turn a (n_points, 1 + n_orbitals) sc_DOSs array into an xy payload."""

    if dos.ndim != 2 or dos.shape[0] < 2 or dos.shape[1] < 2:
        return None
    energy = dos[:, 0]
    # Axis must be ascending for the xy convention.
    if not all(energy[i] < energy[i + 1] for i in range(len(energy) - 1)):
        return None

    stride = max(1, math.ceil(dos.shape[0] / MAX_POINTS))
    dos = dos[::stride]

    n_orb = dos.shape[1] - 1
    total = dos[:, 1:].sum(axis=1)
    payload = {
        "x": _round(dos[:, 0]),
        "y": _round(total),
        "x_label": "E - E_F",
        "x_unit": "eV",
        "y_label": "DOS",
        "y_unit": "states/eV",
        "series": [
            {
                "name": ORBITAL_NAMES[i] if i < len(ORBITAL_NAMES) else f"l={i}",
                "y": _round(dos[:, i + 1]),
            }
            for i in range(n_orb)
        ],
    }
    text = json.dumps(payload, separators=(",", ":"))
    if len(text) > MAX_PAYLOAD:
        return None
    return text


def iter_curves(resolver, limit=None):
    import h5py

    emitted = 0
    with h5py.File(HDF5_PATH, "r") as h5:
        cached_native = None
        cached_payload = None
        for native_id, material_id in resolver.matched_pairs("superband"):
            if limit is not None and emitted >= limit:
                return
            if native_id != cached_native:
                cached_native = native_id
                cached_payload = None
                group = h5.get(native_id)
                if group is not None and "sc_DOSs" in group:
                    cached_payload = _build_payload(group["sc_DOSs"][...])
            if cached_payload is None:
                continue
            yield CurveRecord(
                material_id=material_id,
                curve_type="dos",
                fmt="xy",
                payload=cached_payload,
                native_id=native_id,
                method="DFT (SuperBand)",
                label="Electronic DOS",
            )
            emitted += 1
