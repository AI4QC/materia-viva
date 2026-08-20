"""Deem PCOD hypothetical zeolites -> simulated powder XRD stick patterns.

Every ``<id>.cif`` in the three archives under
data/raw/acquired/deem-zeolites/ is shipped next to an ``<id>.txt`` carrying
the framework's simulated diffraction pattern, so the whole 331,172-framework
enumeration comes with a pattern for free.  Layout (blank lines ignored)::

    8078731                                     numeric id
    PCOD8078731                                 PCOD label
    Si O2                                       formula (always silica here)
      22.754  13.470 ...  35.815  90.000        a b c alpha beta gamma
    C 2/M                                       space-group symbol
    13                                          space-group number
    54                                          number of peak lines
     11.7800    90.    0    0   -1              d(A)  intensity  h k l
     ...
         3.015                                  ZEFSAII/GULP energy (kJ/mol Si)
    Michael W. Deem and Ramdas Pophale (2010).  citation

Peak lines are the only 5-column rows, so we parse until a row stops matching
and the two trailing lines fall out naturally; the declared count is then
checked against the rows found, which is what catches a header that has lost
a line (see ``_parse``).  The energy on the second-to-last line is a scalar
for the property adapter, not a curve, so it is ignored here.

**d-spacing vs 2-theta.**  The file gives d, but every XRD curve already in
the store is an ascending 2-theta axis in degrees: rruff.py emits ``x_label
"2θ" / x_unit "deg"``, amcsd.py does the same for its ``peaks`` patterns, and
backend/materials_api/xrd.py simulates Cu Ka with pymatgen and returns 2-theta
degrees.  The detail view (frontend SpectraPanel's XrdPanel) draws the stored
curve and that computed pattern on one hard-coded ``2θ (deg)`` axis, so a
d-spacing axis would silently overlay two incompatible quantities.  We
therefore convert with Bragg's law at Cu Ka, name the wavelength in the method
string, and keep the untouched d list in the payload for anyone who wants it.

Intensities are rescaled from the file's 0-999 convention (every file peaks at
exactly 999) to the 0-100 relative scale pymatgen returns, so an overlay of
stored and computed patterns is directly comparable.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import tarfile
from pathlib import Path

try:
    from scripts.properties.curves import PROJECT_ROOT, CurveRecord
except ImportError:  # pragma: no cover - standalone / dry-run fallback
    from dataclasses import dataclass

    PROJECT_ROOT = Path(__file__).resolve().parents[3]

    @dataclass
    class CurveRecord:  # mirrors scripts.properties.curves.CurveRecord
        material_id: str
        curve_type: str
        fmt: str
        payload: str | bytes
        native_id: str | None = None
        method: str | None = None
        label: str | None = None

SOURCE = "deem-zeolites"
DEEM_DIR = PROJECT_ROOT / "data" / "raw" / "acquired" / SOURCE
ARCHIVES = (
    "database_2.1_slc_good_1_of_3.tgz",
    "database_2.1_slc_good_2_of_3.tgz",
    "database_2.1_slc_good_3_of_3.tgz",
)

#: Cu Ka.  This MUST be the wavelength pymatgen actually diffracts at, because
#: the detail view plots this curve on one shared axis with the pattern
#: backend/materials_api/xrd.py computes via XRDCalculator(wavelength="CuKa").
#: That is the Ka1/Ka2 weighted average 1.54184 A, *not* the "CuKa 1.5406 Å"
#: string that file reports (a stale label: 1.5406 is rounded Ka1 = 1.54056).
#: Converting at 1.5406 slides every stored stick systematically low against
#: the computed one, by a gap that grows with angle: 0.008 deg at 2-theta 10,
#: 0.025 at 30, 0.092 at 90, 0.110 at 100.  That is exactly the silent axis
#: mismatch the conversion exists to prevent.
CU_KA = 1.54184

#: curves.py caps a series at 2000 points.  All 331,172 shipped files hold
#: 2-99 peaks (mean 88.8), so the cap never bites; it is kept as a guard
#: rather than assumed away, and truncation keeps the strongest peaks because
#: dropping arbitrary sticks from a stick pattern would misrepresent it.  99
#: peaks is ~5 KB of JSON and even a capped series stays far under the ~1.5 MB
#: payload ceiling the other curve sources enforce by hand.
MAX_POINTS = 2000

#: "d intensity h k l"; intensities are written as "90." / "999.".  The two
#: float fields spell out digit placement rather than using [0-9.]+ so that a
#: corrupt token ("." or "21.36.4") fails the match instead of reaching
#: float() and raising ValueError out of the whole load.
_NUM = r"(?:\d+\.?\d*|\.\d+)"
_PEAK_RE = re.compile(
    rf"^\s*({_NUM})\s+({_NUM})\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*$"
)


def _parse(text: str) -> tuple[str, str] | None:
    """Return (payload JSON, PCOD label) for one .txt, or None if unusable."""

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 8:
        return None
    label = lines[1].strip()
    if not label.startswith("PCOD"):
        return None
    # The header is a fixed 7 lines, so peaks start at index 7.  Line 6
    # declares how many peak rows follow, and checking it is the only cheap
    # way to notice a header that has lost or gained a line: parsing would
    # otherwise start one row off, silently drop the strongest reflection and
    # renormalise the rest against it -- a plausible-looking but wrong pattern.
    # It equally catches a mid-table corruption that ends the scan early.
    # Verified to agree in all 331,172 shipped files, so this rejects nothing
    # today; it is here to keep a future bad file out of the store.
    if not lines[6].strip().isdigit():
        return None
    declared = int(lines[6])

    rows = 0
    peaks: list[tuple[float, float, int, int, int]] = []
    for line in lines[7:]:
        match = _PEAK_RE.match(line)
        if match is None:
            if rows:
                break  # trailing energy + citation lines
            continue
        rows += 1
        d_raw, intensity, h, k, l = match.groups()
        d_spacing = float(d_raw)
        if d_spacing <= 0.0:
            continue
        # Below the Bragg limit lambda/2d > 1 there is no diffraction angle at
        # this wavelength, so asin would be undefined; such peaks (d < 0.7709 A
        # for Cu Ka) simply cannot be plotted on a 2-theta axis and are
        # dropped.  None occur in the shipped files, whose smallest d is 1.0 A.
        ratio = CU_KA / (2.0 * d_spacing)
        if ratio > 1.0:
            continue
        two_theta = 2.0 * math.degrees(math.asin(ratio))
        peaks.append((two_theta, float(intensity), int(h), int(k), int(l)))
    # Count the rows the file claimed, not the peaks kept: dropping a peak for
    # being unplottable is a deliberate physical filter, not a parse failure.
    if rows != declared or not peaks:
        return None

    if len(peaks) > MAX_POINTS:
        peaks = sorted(peaks, key=lambda peak: peak[1], reverse=True)[:MAX_POINTS]
    peaks.sort(key=lambda peak: peak[0])  # ascending 2-theta for the plot

    # Files use 0-999; rescale to the 0-100 relative scale pymatgen returns.
    strongest = max(peak[1] for peak in peaks) or 1.0
    payload = json.dumps(
        {
            "x": [round(peak[0], 4) for peak in peaks],
            "y": [round(peak[1] * 100.0 / strongest, 4) for peak in peaks],
            "hkl": [[peak[2], peak[3], peak[4]] for peak in peaks],
            "d": [round(CU_KA / (2.0 * math.sin(math.radians(peak[0] / 2.0))), 5)
                  for peak in peaks],
            "x_label": "2θ",
            "y_label": "Intensity",
            "x_unit": "deg",
        },
        separators=(",", ":"),
    )
    return payload, label


def _refs_from_index(resolver) -> dict[str, list[str]]:
    """native_id -> material_ids from the index's own source refs.

    Preferred over matched.tsv.gz: the pipeline's BAWL fingerprint cannot tell
    idealized silica nets apart (see scripts/properties/deem_zeolite_admit.py),
    so matched.tsv.gz collapses 126,578 frameworks onto 281 pool materials --
    one material there collects 27,007 different frameworks.  Attaching a
    pattern per pair would bury a material under tens of thousands of curves
    for structures that are not it.  material_source_refs holds the composite-
    key admission instead: 144,270 native ids, each resolving to exactly one
    material.  Returns {} when the resolver has no index handle (stub /
    dry-run), letting the caller fall back.
    """

    db = getattr(resolver, "db", None)
    if db is None:
        return {}
    try:
        # match_via = 'origin' only: those are the composite-key admissions,
        # exactly one material per framework. A 'hash' ref for this source is
        # the fingerprint collapse this function exists to avoid (see
        # load.FINGERPRINT_UNRELIABLE); reading them back in would re-create
        # the 27,007-patterns-on-one-material pathology from the index side
        # even after the loader stopped writing them.
        rows = db.execute(
            "SELECT r.native_id, m.material_id FROM material_source_refs r "
            "JOIN materials m ON m.pk = r.material_pk "
            "WHERE r.source_id = (SELECT id FROM source_defs WHERE key = ?) "
            "AND r.match_via = 'origin'",
            (SOURCE,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    linked: dict[str, list[str]] = {}
    for native_id, material_id in rows:
        linked.setdefault(native_id, []).append(material_id)
    return linked


def _linked_materials(resolver) -> dict[str, list[str]]:
    """Build the native_id -> material_ids map once, before touching a tar."""

    linked = _refs_from_index(resolver)
    if linked:
        return linked
    for native_id, material_id in resolver.matched_pairs(SOURCE):
        linked.setdefault(native_id, []).append(material_id)
    return linked


def iter_curves(resolver, limit=None):
    linked = _linked_materials(resolver)
    if not linked:
        return

    yielded = 0
    for archive in ARCHIVES:
        path = DEEM_DIR / archive
        if not path.exists():
            continue
        # "r|gz" streams the ~200 MB member sequence in one pass; the map above
        # means no archive is ever reopened to look an id up.
        with tarfile.open(path, "r|gz") as tar:
            for member in tar:
                if not member.name.endswith(".txt"):
                    continue
                native_id = f"pcod-{Path(member.name).stem}"
                material_ids = linked.get(native_id)
                if not material_ids:
                    continue
                handle = tar.extractfile(member)
                if handle is None:
                    continue
                parsed = _parse(handle.read().decode("utf-8", errors="replace"))
                if parsed is None:
                    continue
                payload, label = parsed
                for material_id in material_ids:
                    yield CurveRecord(
                        material_id=material_id,
                        curve_type="xrd",
                        fmt="peaks",
                        payload=payload,
                        native_id=native_id,
                        # Fingerprint-colliding frameworks share a pool
                        # material (up to 41 of them), so the framework id goes
                        # in the method as well as the label: without it those
                        # curves would be indistinguishable on
                        # (material, curve_type, method).
                        method=(
                            f"simulated (ZEFSAII/GULP), Cu Kα {CU_KA} Å, {label}"
                        ),
                        label=label,
                    )
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
