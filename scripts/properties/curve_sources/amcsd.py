"""AMCSD calculated powder XRD patterns (peaks) from dif.zip.

Each ``*.dif`` member in ``data/raw/acquired/amcsd/dif.zip`` holds one
calculated powder pattern for a single AMCSD record.  Members are named
``<Mineral>__<7-digit code>.dif`` where the code equals the pipeline's
native id.  The body carries a header (including ``X-RAY WAVELENGTH:``)
followed by a ``2-THETA  INTENSITY  D-SPACING  H  K  L  Multiplicity``
table which we parse into a stick pattern.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from scripts.properties.curves import PROJECT_ROOT, CurveRecord

DIF_ZIP = PROJECT_ROOT / "data" / "raw" / "acquired" / "amcsd" / "dif.zip"

MAX_PAYLOAD = 1_500_000  # bytes, uncompressed

_WAVELENGTH_RE = re.compile(r"X-RAY WAVELENGTH:\s*([0-9.]+)")
_MEMBER_CODE_RE = re.compile(r"__(\d{7})\.dif$")
_PEAK_RE = re.compile(
    r"^\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+"
    r"(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+\d+\s*$"
)

# CuKa wavelengths (Angstrom) commonly used by AMCSD's calculated patterns.
_CUKA = {"1.541838", "1.5418", "1.54178", "1.5406", "1.54056", "1.540598"}


def _method(text: str) -> str:
    match = _WAVELENGTH_RE.search(text)
    if match is None:
        return "calculated from refinement (CuKa)"
    raw = match.group(1)
    if raw.rstrip("0").rstrip(".") in {
        w.rstrip("0").rstrip(".") for w in _CUKA
    } or raw in _CUKA:
        return "calculated from refinement (CuKa)"
    return f"calculated from refinement (wavelength {raw} A)"


def _parse(text: str) -> str | None:
    """Return the peaks-payload JSON for one .dif member, or None."""

    xs: list[float] = []
    ys: list[float] = []
    ds: list[float] = []
    hkls: list[str] = []
    in_table = False
    for line in text.splitlines():
        if not in_table:
            if "2-THETA" in line and "INTENSITY" in line:
                in_table = True
            continue
        match = _PEAK_RE.match(line)
        if match is None:
            if xs:
                break  # table ended
            continue
        two_theta, intensity, d_spacing, h, k, l = match.groups()
        xs.append(float(two_theta))
        ys.append(float(intensity))
        ds.append(float(d_spacing))
        hkls.append(f"({int(h)} {int(k)} {int(l)})")
    if not xs:
        return None
    if any(b < a for a, b in zip(xs, xs[1:])):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        xs = [xs[i] for i in order]
        ys = [ys[i] for i in order]
        ds = [ds[i] for i in order]
        hkls = [hkls[i] for i in order]
    payload = json.dumps(
        {
            "x": xs,
            "y": ys,
            "d": ds,
            "hkl": hkls,
            "x_label": "2θ",
            "x_unit": "deg",
            "y_label": "Intensity",
            "y_unit": "a.u.",
        },
        separators=(",", ":"),
    )
    if len(payload) > MAX_PAYLOAD:
        return None
    return payload


def iter_curves(resolver, limit=None):
    with zipfile.ZipFile(DIF_ZIP) as archive:
        members: dict[str, str] = {}
        for name in archive.namelist():
            match = _MEMBER_CODE_RE.search(name)
            if match:
                members[match.group(1)] = name

        # One .dif per native id, but a native id may match several
        # materials: parse each member once and reuse the payload.
        cache: dict[str, tuple[str, str] | None] = {}
        yielded = 0
        for native_id, material_id in resolver.matched_pairs("amcsd"):
            if limit is not None and yielded >= limit:
                return
            member = members.get(native_id)
            if member is None:
                continue
            if native_id not in cache:
                text = archive.read(member).decode("utf-8", errors="replace")
                payload = _parse(text)
                cache[native_id] = (
                    None if payload is None else (payload, _method(text))
                )
            entry = cache[native_id]
            if entry is None:
                continue
            payload, method = entry
            yield CurveRecord(
                material_id=material_id,
                curve_type="xrd",
                fmt="peaks",
                payload=payload,
                native_id=native_id,
                method=method,
                label="Powder XRD (calculated)",
            )
            yielded += 1
