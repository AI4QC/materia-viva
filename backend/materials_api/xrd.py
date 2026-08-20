"""On-demand simulated powder XRD for any pool structure.

Computed with pymatgen's XRDCalculator (Cu Kα) straight from the stored CIF,
so every material has a diffraction pattern even when no source database
ships one. Stored experimental / published patterns live in the curve store
and are overlaid client-side.
"""

from __future__ import annotations

from functools import lru_cache


class XrdComputeError(ValueError):
    """Raised when a CIF cannot be turned into a diffraction pattern."""


@lru_cache(maxsize=256)
def _cached(cif: str, two_theta_max: float) -> dict:
    from pymatgen.analysis.diffraction.xrd import XRDCalculator
    from pymatgen.core import Structure

    try:
        structure = Structure.from_str(cif, fmt="cif")
        pattern = XRDCalculator(wavelength="CuKa").get_pattern(
            structure, two_theta_range=(5.0, two_theta_max)
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a 422 upstream
        raise XrdComputeError(f"XRD simulation failed: {exc}") from exc
    hkls = [
        " ".join(
            "(" + "".join(str(index) for index in item["hkl"]) + ")"
            for item in entries[:3]
        )
        for entries in pattern.hkls
    ]
    return {
        # 1.54184 Å, not the 1.5406 Å this label used to claim: pymatgen's
        # "CuKa" is the Kα1/Kα2 weighted average, while 1.5406 is rounded Kα1.
        # The label is what a curve source reads to place its own d-spacings on
        # the same 2θ axis as this pattern, so a stale number here plots the two
        # on different scales (0.11° apart by 2θ = 100).
        "wavelength": "CuKa 1.54184 Å",
        "x_label": "2θ",
        "x_unit": "deg",
        "y_label": "Intensity",
        "y_unit": "a.u.",
        "x": [round(value, 4) for value in pattern.x.tolist()],
        "y": [round(value, 4) for value in pattern.y.tolist()],
        "hkl": hkls,
        "d": [round(value, 5) for value in pattern.d_hkls],
    }


def simulate_xrd(cif: str, *, two_theta_max: float = 90.0) -> dict:
    return _cached(cif, two_theta_max)
