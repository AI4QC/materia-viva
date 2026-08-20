"""Materiae pre-rendered band-structure SVGs (PBE and PBE+SOC).

Data layout::

    data/raw/acquired/materiae/bandplots/{soc,nsoc}/<mp-id>.svg
    data/raw/acquired/materiae/details/<MAT id>.json.gz   (mp_id field)

The summary file (summary/materials.json.gz) does not carry ``mp_id``, so the
MAT-id -> mp-id mapping is read lazily from the per-material detail files —
one small gzipped JSON per matched MAT id actually needed.

For every (MAT id, material_id) pair in matched.tsv.gz we emit the soc and/or
nsoc SVG when present on disk. A material matched by several MAT ids keeps
only the first curve per (material_id, method). SVGs over ~1.5 MB are skipped.

Numeric electronic DOS: the detail file's ``soc_dos`` field is a list of 500
``[energy, dos]`` pairs — the energy axis is embedded per point, nothing is
reconstructed. Axis reference: in a 4,000-file sample, 3,762 of the 3,765
detail files carrying ``soc_dos`` have ``soc_efermi == 0.0`` exactly, i.e.
the stored energies are already Fermi-level-referenced (E - E_F, eV); for
metals ``soc_fermi_dos`` matches the stored DOS at x = 0 and for insulators
the zero-DOS gap straddles x = 0.  The rare files with a nonzero
``soc_efermi`` are ambiguous (some match an absolute-energy reading, some a
shifted one), so those are skipped rather than guessed.  One DOS curve per
material (first MAT id with usable data wins).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from scripts.properties.curves import PROJECT_ROOT, CurveRecord

RAW = PROJECT_ROOT / "data" / "raw" / "acquired" / "materiae"
BANDPLOTS = RAW / "bandplots"
DETAILS = RAW / "details"

MAX_PAYLOAD = 1_500_000  # bytes, uncompressed

#: (variant dir, method tag, label)
VARIANTS = (
    ("soc", "PBE+SOC", "Band structure (PBE+SOC)"),
    ("nsoc", "PBE", "Band structure (PBE)"),
)


def _load_detail(native_id: str) -> dict | None:
    detail = DETAILS / f"{native_id}.json.gz"
    if not detail.exists():
        return None
    try:
        with gzip.open(detail, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _detail_cached(native_id: str, slot: dict) -> dict | None:
    """Parsed detail JSON with a one-slot (most recent native id) cache.

    matched.tsv.gz is partially grouped by native id, so a one-slot cache
    avoids most repeat reads without holding ~28k details in memory.
    """

    if slot.get("native") != native_id:
        slot.clear()
        slot["native"] = native_id
        slot["data"] = _load_detail(native_id)
    return slot.get("data")


def _mp_id(native_id: str, cache: dict, slot: dict) -> str | None:
    """MAT id -> mp-id via the detail file, cached (None if unavailable)."""

    if native_id in cache:
        return cache[native_id]
    data = _detail_cached(native_id, slot)
    mp_id = (data or {}).get("mp_id") or None
    cache[native_id] = mp_id
    return mp_id


def _dos_payload_from_detail(data: dict | None) -> str | None:
    """xy payload from ``soc_dos`` [[E - E_F, dos], ...] pairs, or None.

    Skipped when the axis is unusable: missing/malformed pairs, or a nonzero
    ``soc_efermi`` (the energy reference is ambiguous there, see module
    docstring — never fabricate an axis).
    """

    if not data:
        return None
    pairs = data.get("soc_dos")
    if not isinstance(pairs, list) or len(pairs) < 2:
        return None
    efermi = data.get("soc_efermi")
    if efermi is not None and abs(efermi) > 1e-9:
        return None
    try:
        xs = [float(p[0]) for p in pairs]
        ys = [float(p[1]) for p in pairs]
    except (TypeError, ValueError, IndexError):
        return None
    if any(a > b for a, b in zip(xs, xs[1:])):  # enforce ascending x
        order = sorted(range(len(xs)), key=xs.__getitem__)
        xs = [xs[i] for i in order]
        ys = [ys[i] for i in order]
    # ~3.5% of files carry a boundary artifact in the very first bin (an
    # accumulator of all states below the window, e.g. 89550 vs curve max
    # ~40) — only ever at index 0, never at the tail. Trim that one point;
    # genuine first bins sit well below the curve maximum (p90 ratio 0.6).
    if len(ys) > 10 and ys[0] > 20 * max(ys[1:]):
        xs, ys = xs[1:], ys[1:]
    payload = json.dumps(
        {
            "x": [round(x, 4) for x in xs],
            "y": [round(y, 4) for y in ys],
            "x_label": "E - E_F",
            "x_unit": "eV",
            "y_label": "DOS",
            "y_unit": "states/eV",
        },
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) > MAX_PAYLOAD:
        return None
    return payload


def _dos_payload(native_id: str, slot: dict) -> str | None:
    """DOS payload for one MAT id, built once per slot occupancy."""

    data = _detail_cached(native_id, slot)
    if "dos_payload" not in slot:
        slot["dos_payload"] = _dos_payload_from_detail(data)
    return slot.get("dos_payload")


def iter_curves(resolver, limit=None):
    mp_cache: dict[str, str | None] = {}
    detail_slot: dict = {}
    seen: set[tuple[str, str]] = set()
    seen_dos: set[str] = set()
    yielded = 0
    for native_id, material_id in resolver.matched_pairs("materiae"):
        if limit is not None and yielded >= limit:
            return
        mp_id = _mp_id(native_id, mp_cache, detail_slot)
        if mp_id:
            for variant, method, label in VARIANTS:
                key = (material_id, method)
                if key in seen:
                    continue
                svg_path = BANDPLOTS / variant / f"{mp_id}.svg"
                if not svg_path.exists():
                    continue
                if svg_path.stat().st_size > MAX_PAYLOAD:
                    continue  # another MAT id may still supply a smaller SVG
                try:
                    svg_text = svg_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                seen.add(key)
                yield CurveRecord(
                    material_id=material_id,
                    curve_type="band_structure",
                    fmt="svg",
                    payload=svg_text,
                    native_id=native_id,
                    method=method,
                    label=label,
                )
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
        if material_id in seen_dos:
            continue
        dos_payload = _dos_payload(native_id, detail_slot)
        if dos_payload is None:
            continue
        seen_dos.add(material_id)
        yield CurveRecord(
            material_id=material_id,
            curve_type="dos",
            fmt="xy",
            payload=dos_payload,
            native_id=native_id,
            method="PBE+SOC",
            label="Electronic DOS (SOC)",
        )
        yielded += 1
