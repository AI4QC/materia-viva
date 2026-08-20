"""Recomputed PhononDB (NIMS MDR) total phonon DOS.

The archives carry no numeric spectra at all -- the only phonon results NIMS
ships are matplotlib PNG rasters -- so these curves come from
``scripts/properties/phonondb_phonons.py``, which rebuilds force constants from
the ``displacements`` block of each ``phonopy_params.yaml.xz`` and re-runs
phonopy (length-100 q-point mesh, tetrahedron DOS, Gonze-Lee NAC wherever the
record carries Born charges + dielectric tensor).  That recomputation was
validated peak-for-peak against the archived ``total_dos.png``, so what is
loaded here is the same curve the NIMS plot shows.

Input: ``data/props_work/phonondb/phonons.jsonl.gz``, one row per uuid with
``native_id`` already in the adapter's ``phonondb-<uuid>`` notation.  Rows that
failed to recompute carry ``error`` and are skipped.

Axes: frequency in THz on a ~201-point grid that starts BELOW zero whenever the
record has imaginary modes (phonopy plots those as negative frequencies and so
do we -- clipping them would hide exactly the instability the DOS is evidence
for).  The DOS is phonopy's native normalisation, states/THz per primitive
cell, matching the "States/THz-primitive cell" axis label on the archived PNGs.
"""

from __future__ import annotations

import gzip
import json
import zlib

from scripts.properties.curves import PROJECT_ROOT, CurveRecord

PHONONS = PROJECT_ROOT / "data" / "props_work" / "phonondb" / "phonons.jsonl.gz"

METHOD = "phonopy PBEsol (PhononDB)"
LABEL = "Phonon DOS"
MAX_PAYLOAD = 1_500_000  # bytes, uncompressed


def _rows():
    """Rows of phonons.jsonl.gz, stopping cleanly at a torn final member.

    The recompute CLI appends gzip members and writes the last member's CRC
    trailer only on close, so the file reads short while a recompute is still
    running.  Loading the curves that already exist is legitimate; crashing on
    the tail is not.
    """

    try:
        with gzip.open(PHONONS, "rt", encoding="utf-8") as handle:
            while True:
                try:
                    line = handle.readline()
                except (EOFError, OSError, zlib.error):
                    return
                if not line:
                    return
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    return
    except (EOFError, OSError, zlib.error):
        return


def _payload(row: dict) -> str | None:
    x = row.get("dos_x") or []
    y = row.get("dos_y") or []
    if len(x) != len(y) or len(x) < 2:
        return None
    if any(a > b for a, b in zip(x, x[1:])):  # frequency grid must ascend
        return None
    if max(y) <= 0:  # an all-zero DOS carries no information
        return None
    text = json.dumps(
        {
            "x": x,
            "y": y,
            "x_label": "Frequency",
            "x_unit": "THz",
            "y_label": "Phonon DOS",
            "y_unit": "states/THz·cell",
        },
        separators=(",", ":"),
    )
    return text if len(text) <= MAX_PAYLOAD else None


def iter_curves(resolver, limit=None):
    targets: dict[str, list[str]] = {}
    for native_id, material_id in resolver.matched_pairs("phonondb"):
        targets.setdefault(native_id, []).append(material_id)

    seen: set[str] = set()  # one DOS per material, first matching uuid wins
    yielded = 0
    for row in _rows():
        if "error" in row:
            continue
        material_ids = targets.get(row.get("native_id", ""))
        if not material_ids:
            continue
        text = _payload(row)
        if text is None:
            continue
        for material_id in material_ids:
            if material_id in seen:
                continue
            seen.add(material_id)
            yield CurveRecord(
                material_id=material_id,
                curve_type="phonon_dos",
                fmt="xy",
                payload=text,
                native_id=row["native_id"],
                method=METHOD,
                label=LABEL,
            )
            yielded += 1
            if limit is not None and yielded >= limit:
                return
