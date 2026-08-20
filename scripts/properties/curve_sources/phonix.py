"""Phonon DOS and thermal-conductivity curves from the PhoniX parquet.

The parquet stores per-material JSON list strings: ``phfreq[cm^-1]`` is the
DOS frequency grid (same length as ``phdos[a.u.]``, ascending), and
``pdos[a.u.]`` is a per-element dict of same-length partial-DOS lists, which
we attach as extra series. Frequencies are converted from cm^-1 to THz.

Spectral thermal conductivity: ``kspec_freq[W/mK/cm^-1]`` holds the spectral
κ values on the *same* ``phfreq[cm^-1]`` grid — verified by (a) identical
lengths (51/51 in every one of 2,000+ inspected rows), (b) zero values at
the negative (imaginary-mode) frequencies where spectral κ must vanish, and
(c) the stored ``kcumu_norm_freq`` matching the normalized cumulative
trapezoid integral of kspec over phfreq (median max-deviation ~7%, explained
by the 51-point downsampling of a peaky integrand).  The trapezoid integral
of kspec ≈ 3·klat for smooth spectra (trace over Cartesian components vs the
isotropic mean); values are stored as-is, only cm^-1 → THz converted on both
axes (y divided by 0.0299792458 to become W/m·K/THz).

Cumulative κ vs mean free path: ``mfp[nm]`` is a log-spaced MFP grid
(uniform step in the companion ``log10[mfp[nm]]`` column) and
``kcumu_norm_mfp`` the same-length normalized cumulative κ — ascending x and
non-decreasing y ending at 1.0 in every inspected row.  Rows failing any of
these checks are skipped.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.properties.curves import PROJECT_ROOT, CurveRecord

DATA_DIR = PROJECT_ROOT / "data" / "raw" / "acquired" / "phonix"

CM1_TO_THZ = 0.0299792458
MAX_POINTS = 1500
MAX_PAYLOAD = 1_500_000  # bytes, uncompressed


def _downsample(values: list, stride: int) -> list:
    if stride <= 1:
        return values
    picked = values[::stride]
    if picked[-1] is not values[-1]:
        picked.append(values[-1])
    return picked


def _json_list(raw) -> list | None:
    if not raw:
        return None
    try:
        values = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return values if isinstance(values, list) and values else None


def _kappa_spectral_payload(freq_cm: list, raw_kspec) -> str | None:
    """Spectral κ on the phonon frequency grid, cm^-1 → THz on both axes."""

    kspec = _json_list(raw_kspec)
    if kspec is None or len(kspec) != len(freq_cm) or len(kspec) < 2:
        return None
    if any(a > b for a, b in zip(freq_cm, freq_cm[1:])):  # need ascending x
        return None
    try:
        if max(kspec) <= 0:
            return None  # empty spectrum carries no information
    except TypeError:
        return None
    stride = -(-len(freq_cm) // MAX_POINTS)
    x = [round(v * CM1_TO_THZ, 6) for v in _downsample(freq_cm, stride)]
    y = [round(v / CM1_TO_THZ, 6) for v in _downsample(kspec, stride)]
    payload = json.dumps(
        {
            "x": x,
            "y": y,
            "x_label": "Frequency",
            "x_unit": "THz",
            "y_label": "κ spectral",
            "y_unit": "W/m·K/THz",
        },
        separators=(",", ":"),
    )
    return payload if len(payload) <= MAX_PAYLOAD else None


def _kappa_cumulative_payload(raw_mfp, raw_kcumu) -> str | None:
    """Normalized cumulative κ vs mean free path (log-spaced nm grid)."""

    mfp = _json_list(raw_mfp)
    kcumu = _json_list(raw_kcumu)
    if mfp is None or kcumu is None or len(mfp) != len(kcumu) or len(mfp) < 2:
        return None
    try:
        if any(a > b for a, b in zip(mfp, mfp[1:])):  # ascending MFP grid
            return None
        if any(a > b + 1e-6 for a, b in zip(kcumu, kcumu[1:])):  # monotone y
            return None
        if not (-1e-6 <= kcumu[0] and kcumu[-1] <= 1.001):
            return None
    except TypeError:
        return None
    stride = -(-len(mfp) // MAX_POINTS)
    payload = json.dumps(
        {
            "x": [round(v, 5) for v in _downsample(mfp, stride)],
            "y": [round(v, 6) for v in _downsample(kcumu, stride)],
            "x_label": "Mean free path",
            "x_unit": "nm",
            "y_label": "Cumulative κ (norm.)",
            "y_unit": "",
        },
        separators=(",", ":"),
    )
    return payload if len(payload) <= MAX_PAYLOAD else None


def iter_curves(resolver, limit=None):
    import pyarrow.parquet as pq

    targets: dict[str, list[str]] = {}
    for native_id, material_id in resolver.matched_pairs("phonix"):
        targets.setdefault(native_id, []).append(material_id)

    columns = [
        "unique_id", "phfreq[cm^-1]", "phdos[a.u.]", "pdos[a.u.]",
        "kspec_freq[W/mK/cm^-1]", "mfp[nm]", "kcumu_norm_mfp",
    ]
    yielded = 0
    for path in sorted(DATA_DIR.glob("*.parquet")):
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=256, columns=columns):
            rows = batch.to_pydict()
            for i, native_id in enumerate(rows["unique_id"]):
                material_ids = targets.get(native_id)
                if not material_ids:
                    continue
                raw_freq = rows["phfreq[cm^-1]"][i]
                raw_dos = rows["phdos[a.u.]"][i]
                if not raw_freq or not raw_dos:
                    continue
                freq = json.loads(raw_freq)
                dos = json.loads(raw_dos)
                if len(freq) != len(dos) or len(freq) < 2:
                    continue

                stride = -(-len(freq) // MAX_POINTS)  # ceil division
                x = [round(v * CM1_TO_THZ, 6) for v in _downsample(freq, stride)]
                y = _downsample(dos, stride)

                payload = {
                    "x": x,
                    "y": y,
                    "x_label": "Frequency",
                    "x_unit": "THz",
                    "y_label": "Phonon DOS",
                    "y_unit": "a.u.",
                }

                raw_pdos = rows["pdos[a.u.]"][i]
                if raw_pdos:
                    try:
                        pdos = json.loads(raw_pdos)
                    except (ValueError, TypeError):
                        pdos = None
                    if isinstance(pdos, dict) and len(pdos) > 1:
                        series = [
                            {"name": elem, "y": _downsample(vals, stride)}
                            for elem, vals in pdos.items()
                            if isinstance(vals, list) and len(vals) == len(freq)
                        ]
                        if series:
                            payload["series"] = series

                text = json.dumps(payload)
                if len(text) > MAX_PAYLOAD:
                    continue

                row_records = [("phonon_dos", text, "Phonon DOS")]
                kspec_text = _kappa_spectral_payload(
                    freq, rows["kspec_freq[W/mK/cm^-1]"][i]
                )
                if kspec_text is not None:
                    row_records.append((
                        "kappa_spectral", kspec_text,
                        "Spectral thermal conductivity",
                    ))
                kcumu_text = _kappa_cumulative_payload(
                    rows["mfp[nm]"][i], rows["kcumu_norm_mfp"][i]
                )
                if kcumu_text is not None:
                    row_records.append((
                        "kappa_cumulative", kcumu_text, "Cumulative κ vs MFP",
                    ))

                for material_id in material_ids:
                    for curve_type, curve_text, label in row_records:
                        yield CurveRecord(
                            material_id=material_id,
                            curve_type=curve_type,
                            fmt="xy",
                            payload=curve_text,
                            native_id=native_id,
                            method="phono3py PBE",
                            label=label,
                        )
                        yielded += 1
                        if limit is not None and yielded >= limit:
                            return
