"""Materials Project spectra: electronic DOS, phonon DOS, XAS, optical absorption.

Acquired by ``scripts/datasets/mp_spectra.py`` into
``data/raw/acquired/materials-project/<family>-2026-08-19/``.  Two shapes of
input, because MP publishes these two different ways:

* ``dos`` and ``phonon`` are zstd parquet parts of the public
  ``materialsproject-parsed`` Delta tables ``core/electronic-structure/
  total-dos`` and ``phonon/electronic-structure/dos``.  Only the *total* DOS
  tables are used; the projected companions are 21.1 GB and 1.1 TB and carry
  no information a plot needs.
* ``xas`` and ``absorption`` are gzipped JSONL of the REST documents.

Each family directory carries a ``targets.tsv.gz`` (``join_key`` ->
``material_id``) written at acquisition time from the local MP summary
snapshot, because the parquet ``identifier`` column is a *calculation* id for
the electronic DOS (the summary doc names which calculation is blessed for a
material) while it is already the material id for the phonon DOS.

Downsampling and unit decisions, all applied here rather than at acquisition
so the raw parquet stays re-interpretable:

* **Electronic DOS** (``dos``) — x is ``energies - efermi`` in eV so the plot
  is Fermi-referenced like the SuperBand and Materiae DOS curves already in
  the store.  y is the spin sum (states/eV); spin-polarised calculations also
  get ``series`` for the up and down channels.  The native grid is 301-2001
  points over a median window of -46 eV to +18 eV around E_F, most of which
  is identically zero, so the payload is first trimmed to where the DOS
  exceeds 1e-6 of its peak (plus a 10-point margin) — lossless, ~32% smaller,
  and it lands every sampled curve under the 2000-point ceiling at MP's own
  resolution rather than halving it with a stride.  Anything still over
  ``MAX_POINTS`` after the trim is strided.  Points are rounded to 4 decimals
  on x and 5 on y — 0.1 meV and 1e-5 states/eV, far below any DFT DOS's own
  resolution, and it is what makes the payload compress ~3x.  Cross-checked
  against MP's own DOS-derived band gap over every material this source emits
  (62,042 of the summary's 62,972 blessed DOS tasks are present in the
  table): on the 24,006 gapped ones the gap read straight off the stored
  curve agrees to a median 0.056 eV, within 0.15 eV for 93.9% and 0.30 eV for
  97.1% — a few steps of the downsampled grid — and 37,963 of the 38,036
  materials whose DOS gap is zero come back below 0.3 eV.
* **Phonon DOS** (``phonon_dos``) — frequencies are already THz and are stored
  as published, negative (imaginary) branches included.  The densities are per
  unit cell: the trapezoid integral over the frequency grid comes to 3N for N
  sites (median ratio 1.000 over 600 sampled rows from both methods), which is
  why the unit is written ``states/THz·cell``, matching the recomputed
  PhononDB curves already in the store.  The native grid runs 593-4408 points,
  so anything over the cap is strided.  ``projected_densities`` is one entry
  per *site* (verified: 400/400 sampled rows have
  ``len(projected_densities) == len(structure.sites)``, versus 53/400 matching
  the distinct-element count), so per-site curves are summed by element and
  attached as ``series``.
* **XAS** (``xas``) — MP stores XANES (near edge, ~100 points), EXAFS
  (extended, ~400) and XAFS (the stitched full range, ~500) per absorbing
  element and edge.  XANES and XAFS are kept; EXAFS is dropped wherever a
  XAFS exists for the same group, because XAFS is the stitched union of the
  two and storing EXAFS as well repeats it at ~7.2 kB a spectrum — that alone
  drops a quarter of the fetched spectra.  Where a group has no XAFS the
  EXAFS is kept instead.  Nothing needs striding at
  these lengths.  The x axis is absolute photon energy in eV: over 79,503
  XANES curves spanning 19 element/edge combinations the first stored point
  sits within 0.5% of the tabulated edge energy for every combination but
  O K (2.6%, a -14 eV offset on a 543 eV soft-X-ray edge), which also
  confirms the element and edge named in the method string.
* **Absorption** (``absorption``) — a fixed 2001-point energy grid in eV
  against the coefficient in cm^-1; strided to 1001 points to sit under the
  2000-point ceiling with a round stride rather than a ragged one.  Sanity
  check on the axes: across all 919 gapped curves the photon energy at which
  α first exceeds the conventional 1e4 cm^-1 absorption-edge threshold sits a
  median +0.14 eV above the doc's own DFT gap, and above it for 86% of them.

* **Band structure** (``band_structure``) — only the bands that come within
  ``BAND_WINDOW_EV`` of E_F anywhere along the path are kept, at most
  ``MAX_BANDS`` of them, as one ``series`` each over a shared k-path distance
  axis in Å⁻¹.  MP stores hundreds of bands per calculation, nearly all of
  them semicore or high conduction states no band plot draws.  The budget is
  split evenly between valence and conduction bands ranked by closest
  approach to E_F, which in practice yields a window of about -2.7 to +4.9 eV
  (medians) on 40 bands over ~137 k-points.  The ``xy``
  payload has no channel for tick positions, so the high-symmetry point names
  are folded into ``x_label`` instead: the path is named even though its ticks
  cannot be placed.  The distance axis is non-decreasing rather than strictly
  ascending: where the path jumps (the ``…|U–X`` breaks) consecutive q-points
  coincide and the cumulative distance repeats, which is the honest reading of
  a broken path — 239 of 453 sampled curves do this, at most 10 times each,
  and none ever steps backwards.  Checked against the summary's own
  ``setyawan_curtarolo`` band gap on one part of the table: all 129 gapped
  materials reproduce the gap exactly (median |Δ| 0.000 eV) and all 128 metals
  keep a band that actually crosses E_F.

Band structures load only if ``mp_spectra.py --family bandstructure`` has been
run: the unprojected energies table is 75.25 GB, or 20.37 GB restricted to the
``setyawan_curtarolo`` path convention that 99.8% of MP's band-structure
materials carry, which is what the fetcher takes.  The projected companion is
1.1 TB and is never fetched.  Every family is skipped unless its
``manifest.json`` reports ``complete``.
"""

from __future__ import annotations

import gzip
import json
import math
from collections import defaultdict
from pathlib import Path

from scripts.properties.curves import PROJECT_ROOT, CurveRecord

ACQUIRED = PROJECT_ROOT / "data" / "raw" / "acquired" / "materials-project"
SNAPSHOT = "2026-08-19"
DB_VERSION = "MP2026.04.13"

MAX_POINTS = 2000        #: the curve store's per-series ceiling
SPIN_MAX_POINTS = 1000   #: curves that also carry spin-up/spin-down series
MAX_PAYLOAD = 1_500_000  # bytes, uncompressed

BAND_WINDOW_EV = 5.0     #: bands are kept only if they enter E_F ± this
MAX_BANDS = 40           #: hard ceiling on series per band-structure curve
BAND_BATCH = 64          #: rows materialised at a time from a 1 GB row group

#: MP ``run_type`` -> the functional a reader recognises.
RUN_TYPE_NAMES = {
    "GGA": "PBE",
    "GGA+U": "PBE+U",
    "PBE": "PBE",
    "PBEsol": "PBEsol",
    "r2SCAN": "r2SCAN",
    "HSE06": "HSE06",
    "SCAN": "SCAN",
    "unknown": "DFT",
}

#: XAS spectrum types worth storing; EXAFS is contained in the stitched XAFS.
XAS_TYPES = ("XANES", "XAFS")

#: MP writes high-symmetry labels in LaTeX; the axis label wants the letter.
GREEK = {
    "Gamma": "Γ", "Sigma": "Σ", "Delta": "Δ", "Lambda": "Λ",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _family_dir(family: str) -> Path:
    return ACQUIRED / f"{family}-{SNAPSHOT}"


def _family_complete(family: str) -> bool:
    """Only load a family whose acquisition manifest says it finished.

    A half-downloaded family would silently contribute a biased subset of
    curves, and a source's curves are replaced wholesale on re-run, so a
    partial load is worse than none.
    """

    manifest = _family_dir(family) / "manifest.json"
    if not manifest.exists():
        return False
    try:
        return bool(json.loads(manifest.read_text(encoding="utf-8")).get("complete"))
    except (OSError, ValueError):
        return False


def _keep(n: int, cap: int = MAX_POINTS) -> list[int]:
    """Indices to keep when thinning ``n`` points down to at most ``cap``.

    The index list is computed once and reused for x, y and every series, so
    the arrays cannot drift apart in length.  Selecting by *value* instead --
    "append the last point unless it is already there" -- silently drops the
    final sample of any series whose last two kept values happen to be equal,
    which for a DOS tail of zeros is most of them.
    """

    stride = max(1, math.ceil(n / cap))
    if stride <= 1:
        return list(range(n))
    indices = list(range(0, n, stride))
    if indices[-1] != n - 1:
        indices.append(n - 1)
    return indices


def _thin(values, keep: list[int]):
    return [values[i] for i in keep]


def _round(values, digits: int):
    return [round(float(v), digits) for v in values]


def _dump(payload: dict) -> str | None:
    text = json.dumps(payload, separators=(",", ":"))
    return text if len(text) <= MAX_PAYLOAD else None


def _targets(family: str) -> dict[str, str]:
    """``join_key`` -> MP material id, from the family's acquisition manifest."""

    path = _family_dir(family) / "targets.tsv.gz"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            key, material_id = line.rstrip("\n").split("\t")
            out[key] = material_id
    return out


def _run_type_of(path: Path) -> str:
    """Recover the Delta partition value baked into the local filename."""

    name = path.name
    for token in name.split("__"):
        if token.startswith("run_type-"):
            return token[len("run_type-"):].replace("%2B", "+")
        if token.startswith("phonon_method-"):
            return token[len("phonon_method-"):]
    return "unknown"


class _Emitter:
    """Applies the pool fan-out, the one-curve-per-(material, type, method)
    rule and the caller's ``limit``."""

    def __init__(self, pool: dict[str, list[str]], limit: int | None) -> None:
        self.pool = pool
        self.limit = limit
        self.count = 0
        self.seen: set[tuple[str, str, str]] = set()

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.count >= self.limit

    def emit(self, mp_id: str, *, curve_type: str, payload: str, method: str,
             label: str):
        for material_id in self.pool.get(mp_id, ()):
            key = (material_id, curve_type, method)
            if key in self.seen:
                continue
            self.seen.add(key)
            yield CurveRecord(
                material_id=material_id,
                curve_type=curve_type,
                fmt="xy",
                payload=payload,
                native_id=mp_id,
                method=method,
                label=label,
            )
            self.count += 1
            if self.exhausted:
                return


# ---------------------------------------------------------------------------
# electronic total DOS  (core/electronic-structure/total-dos parquet)
# ---------------------------------------------------------------------------


def _dos_payload(row: dict) -> str | None:
    energies = row.get("energies")
    up = row.get("spin_up_densities")
    down = row.get("spin_down_densities")
    efermi = row.get("efermi")
    if not energies or not up or efermi is None or len(up) != len(energies):
        return None
    if len(energies) < 2:
        return None
    if any(a > b for a, b in zip(energies, energies[1:])):  # x must ascend
        return None
    spin_polarised = bool(down) and len(down) == len(energies)
    total = [a + b for a, b in zip(up, down)] if spin_polarised else list(up)
    peak = max(total)
    if peak <= 0:  # an all-zero DOS carries no information
        return None

    # Trim the dead ends of MP's grid before touching resolution.  The stored
    # window runs a median of -46 eV to +18 eV around E_F but the DOS is
    # identically zero over most of the lower half, so cutting where it is
    # below 1e-6 of the peak (plus a 10-point margin) is lossless and takes a
    # median 601-point grid down to ~410 points -- which is what keeps every
    # curve under the store's 2000-point ceiling at MP's *native* resolution
    # instead of halving it with a stride.
    threshold = peak * 1e-6
    live = [i for i, value in enumerate(total) if value > threshold]
    lo = max(0, live[0] - 10)
    hi = min(len(energies) - 1, live[-1] + 10)
    energies = energies[lo:hi + 1]
    total = total[lo:hi + 1]
    up = up[lo:hi + 1]
    down = down[lo:hi + 1] if spin_polarised else down

    # A spin-polarised DOS ships three y-arrays (total, up, down), so it is
    # capped at a third of the store's per-series ceiling to keep the byte
    # budget of a curve roughly constant either way.  At MP's median trimmed
    # window that is ~55 meV per point, an order of magnitude finer than any
    # feature a DOS plot resolves.
    keep = _keep(len(energies), SPIN_MAX_POINTS if spin_polarised else MAX_POINTS)
    payload = {
        "x": _round(_thin([e - efermi for e in energies], keep), 4),
        "y": _round(_thin(total, keep), 5),
        "x_label": "E - E_F",
        "x_unit": "eV",
        "y_label": "DOS",
        "y_unit": "states/eV",
    }
    if spin_polarised:
        payload["series"] = [
            {"name": "spin up", "y": _round(_thin(up, keep), 5)},
            {"name": "spin down", "y": _round(_thin(down, keep), 5)},
        ]
    return _dump(payload)


def _iter_dos(emitter: _Emitter):
    import pyarrow.parquet as pq

    directory = _family_dir("dos")
    targets = _targets("dos")  # dos task_id -> mp material id
    if not targets:
        return
    columns = ["identifier", "energies", "spin_up_densities",
               "spin_down_densities", "efermi"]
    for path in sorted(directory.glob("*.parquet")):
        run_type = _run_type_of(path)
        method = f"{RUN_TYPE_NAMES.get(run_type, run_type)} {DB_VERSION}"
        parquet = pq.ParquetFile(path)
        for group in range(parquet.metadata.num_row_groups):
            # Pull the (tiny) identifier column first and materialise only the
            # rows we can actually attach: a full row group of 1024 DOS rows is
            # ~6 M doubles, and this source runs alongside other heavy jobs.
            identifiers = parquet.read_row_group(
                group, columns=["identifier"]).column("identifier").to_pylist()
            wanted = [
                index for index, identifier in enumerate(identifiers)
                if targets.get(identifier) in emitter.pool
            ]
            if not wanted:
                continue
            table = parquet.read_row_group(group, columns=columns).take(wanted)
            for row in table.to_pylist():
                mp_id = targets.get(row["identifier"])
                if mp_id is None or mp_id not in emitter.pool:
                    continue
                text = _dos_payload(row)
                if text is None:
                    continue
                yield from emitter.emit(
                    mp_id, curve_type="dos", payload=text, method=method,
                    label="Electronic DOS",
                )
                if emitter.exhausted:
                    return


# ---------------------------------------------------------------------------
# phonon DOS  (phonon/electronic-structure/dos parquet)
# ---------------------------------------------------------------------------


def _phonon_payload(dos: dict) -> str | None:
    frequencies = dos.get("frequencies")
    densities = dos.get("densities")
    if not frequencies or not densities or len(frequencies) != len(densities):
        return None
    if len(frequencies) < 2:
        return None
    if any(a > b for a, b in zip(frequencies, frequencies[1:])):
        return None
    if max(densities) <= 0:
        return None

    projected = dos.get("projected_densities")
    structure = dos.get("structure") or {}
    sites = structure.get("sites") or []
    per_element: dict[str, list[float]] = {}
    if projected and len(projected) == len(sites) > 1:
        for site, site_dos in zip(sites, projected):
            species = site.get("species") or []
            if not species or not site_dos or len(site_dos) != len(frequencies):
                per_element.clear()
                break
            element = species[0].get("element")
            bucket = per_element.setdefault(element, [0.0] * len(frequencies))
            for index, value in enumerate(site_dos):
                bucket[index] += value
    if len(per_element) < 2:
        per_element = {}

    # Same byte-budget rule as the electronic DOS: a curve that also ships
    # per-element series is capped lower so its total payload stays in the
    # same range as a bare curve's.
    keep = _keep(len(frequencies),
                 SPIN_MAX_POINTS if per_element else MAX_POINTS)
    payload = {
        "x": _round(_thin(frequencies, keep), 5),
        "y": _round(_thin(densities, keep), 6),
        "x_label": "Frequency",
        "x_unit": "THz",
        "y_label": "Phonon DOS",
        "y_unit": "states/THz·cell",
    }
    if per_element:
        payload["series"] = [
            {"name": element, "y": _round(_thin(values, keep), 6)}
            for element, values in sorted(per_element.items())
        ]
    return _dump(payload)


def _iter_phonon(emitter: _Emitter):
    import pyarrow.parquet as pq

    directory = _family_dir("phonon")
    # No summary gate here, unlike the electronic DOS: the parquet identifier
    # is already the material id and a row's existence *is* the evidence that
    # the material has a phonon DOS, so the pool membership is the only filter
    # that matters.  (It is the binding one anyway -- of the 26,401 pheasy
    # rows only 1,390 name a material that is in the pool's MP snapshot at
    # all; MP's pheasy phonon batch is largely materials the 2026-07-26
    # summary export does not contain.)
    for path in sorted(directory.glob("*.parquet")):
        phonon_method = _run_type_of(path)
        method = f"{'DFPT' if phonon_method == 'dfpt' else 'pheasy'} PBE {DB_VERSION}"
        parquet = pq.ParquetFile(path)
        for group in range(parquet.metadata.num_row_groups):
            identifiers = parquet.read_row_group(
                group, columns=["identifier"]).column("identifier").to_pylist()
            wanted = [
                index for index, identifier in enumerate(identifiers)
                if f"mp-{identifier}" in emitter.pool
            ]
            if not wanted:
                continue
            table = parquet.read_row_group(
                group, columns=["identifier", "dos"]).take(wanted)
            for row in table.to_pylist():
                mp_id = f"mp-{row['identifier']}"
                dos = row.get("dos")
                if not isinstance(dos, dict):
                    continue
                text = _phonon_payload(dos)
                if text is None:
                    continue
                yield from emitter.emit(
                    mp_id, curve_type="phonon_dos", payload=text, method=method,
                    label="Phonon DOS",
                )
                if emitter.exhausted:
                    return


# ---------------------------------------------------------------------------
# XAS  (REST JSONL)
# ---------------------------------------------------------------------------


def _xas_payload(spectrum: dict) -> str | None:
    x = spectrum.get("x")
    y = spectrum.get("y")
    if not x or not y or len(x) != len(y) or len(x) < 2:
        return None
    if any(a > b for a, b in zip(x, x[1:])):
        return None
    if max(y) <= 0:
        return None
    keep = _keep(len(x))
    return _dump({
        "x": _round(_thin(x, keep), 3),
        "y": _round(_thin(y, keep), 6),
        "x_label": "Energy",
        "x_unit": "eV",
        "y_label": "μ(E)",
        "y_unit": "a.u.",
    })


def _iter_xas(emitter: _Emitter):
    """One XANES plus one full-range curve per (material, element, edge).

    A shard holds every spectrum of the 40 materials it was fetched for, so the
    (material, element, edge) groups are complete within one file and can be
    resolved without buffering the whole family.  Over the 209,789 groups the
    421,184 fetched spectra form: 50.2% carry all three types, 46.9% are
    XANES-only, 2.6% EXAFS-only and 0.3% EXAFS+XANES.  Where all three exist,
    XAFS covers the EXAFS range in 94% of groups and the XANES range in 98%
    -- it is the stitched union, so EXAFS is redundant there and is dropped;
    where no XAFS exists the EXAFS is kept instead.  The policy keeps 315,185
    of the 421,184 spectra (74.8%).
    """

    directory = _family_dir("xas")
    for path in sorted(directory.glob("xas-*.jsonl.gz")):
        groups: dict[tuple, dict[str, dict]] = defaultdict(dict)
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue
                mp_id = f"mp-{doc.get('task_id')}"
                if mp_id not in emitter.pool:
                    continue
                if not isinstance(doc.get("spectrum"), dict):
                    continue
                key = (mp_id, doc.get("absorbing_element"), doc.get("edge"))
                groups[key][doc.get("spectrum_type")] = doc
        for (mp_id, element, edge), by_type in groups.items():
            chosen = [by_type[name] for name in XAS_TYPES if name in by_type]
            if "XAFS" not in by_type and "EXAFS" in by_type:
                chosen.append(by_type["EXAFS"])
            for doc in chosen:
                text = _xas_payload(doc["spectrum"])
                if text is None:
                    continue
                spectrum_type = doc.get("spectrum_type")
                method = f"{spectrum_type} {edge}-edge {element} FEFF {DB_VERSION}"
                yield from emitter.emit(
                    mp_id, curve_type="xas", payload=text, method=method,
                    label=f"{spectrum_type} {edge}-edge {element}",
                )
                if emitter.exhausted:
                    return


# ---------------------------------------------------------------------------
# optical absorption  (REST JSONL)
# ---------------------------------------------------------------------------


def _absorption_payload(doc: dict) -> str | None:
    energies = doc.get("energies")
    alpha = doc.get("absorption_coefficient")
    if not energies or not alpha or len(energies) != len(alpha) or len(energies) < 2:
        return None
    if any(a > b for a, b in zip(energies, energies[1:])):
        return None
    if max(alpha) <= 0:
        return None
    keep = _keep(len(energies))
    return _dump({
        "x": _round(_thin(energies, keep), 4),
        "y": _round(_thin(alpha, keep), 2),
        "x_label": "Photon energy",
        "x_unit": "eV",
        "y_label": "Absorption coefficient",
        "y_unit": "cm⁻¹",
    })


def _iter_absorption(emitter: _Emitter):
    directory = _family_dir("absorption")
    method = f"IPA dielectric function {DB_VERSION}"
    for path in sorted(directory.glob("absorption-*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue
                mp_id = doc.get("material_id")
                if mp_id not in emitter.pool:
                    continue
                text = _absorption_payload(doc)
                if text is None:
                    continue
                yield from emitter.emit(
                    mp_id, curve_type="absorption", payload=text, method=method,
                    label="Optical absorption",
                )
                if emitter.exhausted:
                    return


# ---------------------------------------------------------------------------
# electronic band structure  (core/electronic-structure/bandstructures parquet)
# ---------------------------------------------------------------------------


def _kpath_label(labels_dict, qpoints) -> str:
    """The high-symmetry path in the order the calculation actually walked it.

    ``labels_dict`` maps a label to fractional coordinates and carries no
    ordering, so the labels are matched back onto the q-point list and emitted
    in path order.  Arrow hands a parquet ``map`` column back as a list of
    pairs, so both shapes are accepted.
    """

    if isinstance(labels_dict, dict):
        items = list(labels_dict.items())
    elif isinstance(labels_dict, (list, tuple)):
        items = [tuple(entry) for entry in labels_dict if len(entry) == 2]
    else:
        return ""
    named = [(str(label), coords) for label, coords in items
             if coords and len(coords) == 3]
    if not named:
        return ""
    ordered: list[str] = []
    for qpoint in qpoints:
        for label, coords in named:
            if all(abs(a - b) < 1e-4 for a, b in zip(qpoint, coords)):
                pretty = GREEK.get(label.lstrip("\\"), label)
                if not ordered or ordered[-1] != pretty:
                    ordered.append(pretty)
                break
    return "–".join(ordered)


def _band_payload(row: dict) -> tuple[str, str] | None:
    """(payload, path label) for one line-mode band structure.

    x is the cumulative Cartesian distance along the k-path in Å⁻¹, y is the
    lowest band in the window, and every other band in the window becomes a
    ``series``.  Only bands that come within ``BAND_WINDOW_EV`` of E_F anywhere
    on the path are kept: MP's stored band count runs into the hundreds
    (semicore and high conduction states), none of which a band plot shows.

    The ``xy`` payload has no channel for tick positions, so the high-symmetry
    labels are folded into ``x_label`` — the reader learns which path was
    walked even though the ticks themselves cannot be drawn.
    """

    qpoints = row.get("qpoints")
    rec = row.get("reciprocal_lattice")
    efermi = row.get("efermi")
    up = row.get("spin_up_bands")
    if not qpoints or not rec or efermi is None or not up:
        return None
    down = row.get("spin_down_bands")
    nk = len(qpoints)
    if nk < 2:
        return None

    # cumulative |Δk| in Cartesian reciprocal space
    cart = [
        [sum(q[i] * rec[i][j] for i in range(3)) for j in range(3)]
        for q in qpoints
    ]
    distance = [0.0]
    for a, b in zip(cart, cart[1:]):
        step = math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
        distance.append(distance[-1] + step)
    if distance[-1] <= 0:
        return None

    # Rank by closest approach to E_F, but keep valence and conduction bands
    # in separate queues and spend half the budget on each: MP stores hundreds
    # of bands and a plain "nearest E_F" cut fills up with valence states in
    # any material that has a dense valence manifold, leaving a band plot with
    # nothing above the gap.
    valence: list[tuple[float, str, list[float]]] = []
    conduction: list[tuple[float, str, list[float]]] = []
    for spin, table in (("↑", up), ("↓", down)):
        if not table:
            continue
        for index, band in enumerate(table):
            if len(band) != nk:
                continue
            shifted = [e - efermi for e in band]
            if min(shifted) > BAND_WINDOW_EV or max(shifted) < -BAND_WINDOW_EV:
                continue
            name = f"band {index}" if not down else f"band {index} {spin}"
            nearest = min(shifted, key=abs)
            entry = (abs(nearest), name, shifted)
            (conduction if nearest > 0 else valence).append(entry)
    valence.sort(key=lambda item: item[0])
    conduction.sort(key=lambda item: item[0])
    half = MAX_BANDS // 2
    kept = valence[:half] + conduction[:half]
    spare = MAX_BANDS - len(kept)
    if spare:
        kept += valence[half:half + spare] + conduction[half:half + spare]
        kept = kept[:MAX_BANDS]
    if not kept:
        return None
    bands = [(name, values) for _distance, name, values in kept]
    bands.sort(key=lambda item: min(item[1]))

    keep = _keep(nk, max(200, MAX_POINTS // max(1, len(bands))))
    payload = {
        "x": _round(_thin(distance, keep), 4),
        "y": _round(_thin(bands[0][1], keep), 4),
        "x_label": "Wave vector",
        "x_unit": "Å⁻¹",
        "y_label": "E - E_F",
        "y_unit": "eV",
        "series": [
            {"name": name, "y": _round(_thin(values, keep), 4)}
            for name, values in bands[1:]
        ],
    }
    path = _kpath_label(row.get("labels_dict"), qpoints)
    if path:
        payload["x_label"] = f"Wave vector ({path})"
    text = _dump(payload)
    return (text, path) if text else None


def _iter_bandstructure(emitter: _Emitter):
    import pyarrow.parquet as pq

    directory = _family_dir("bandstructure")
    targets = _targets("bandstructure")  # bs task_id -> mp material id
    if not targets:
        return
    columns = ["identifier", "qpoints", "reciprocal_lattice", "labels_dict",
               "efermi", "spin_up_bands", "spin_down_bands"]
    for path in sorted(directory.glob("*.parquet")):
        run_type = _run_type_of(path)
        method = (f"{RUN_TYPE_NAMES.get(run_type, run_type)} "
                  f"setyawan-curtarolo {DB_VERSION}")
        parquet = pq.ParquetFile(path)
        for group in range(parquet.metadata.num_row_groups):
            identifiers = parquet.read_row_group(
                group, columns=["identifier"]).column("identifier").to_pylist()
            wanted = [
                index for index, identifier in enumerate(identifiers)
                if targets.get(identifier) in emitter.pool
            ]
            if not wanted:
                continue
            # These parts hold a single ~1 GB row group.  It is read once into
            # Arrow (columnar, cheap) and only ever converted to Python objects
            # a few rows at a time -- to_pylist() on the whole group would be
            # tens of GB of Python floats.
            group_table = parquet.read_row_group(group, columns=columns)
            for start in range(0, len(wanted), BAND_BATCH):
                batch = wanted[start:start + BAND_BATCH]
                for row in group_table.take(batch).to_pylist():
                    mp_id = targets.get(row["identifier"])
                    if mp_id is None or mp_id not in emitter.pool:
                        continue
                    built = _band_payload(row)
                    if built is None:
                        continue
                    text, _path = built
                    yield from emitter.emit(
                        mp_id, curve_type="band_structure", payload=text,
                        method=method, label="Band structure",
                    )
                    if emitter.exhausted:
                        return


# ---------------------------------------------------------------------------


#: Emitted in the order the families were prioritised for acquisition, so a
#: ``--limit`` run exercises the most valuable curves first.
FAMILIES = (
    ("dos", _iter_dos),
    ("phonon", _iter_phonon),
    ("xas", _iter_xas),
    ("bandstructure", _iter_bandstructure),
    ("absorption", _iter_absorption),
)


def iter_curves(resolver, limit=None):
    pool: dict[str, list[str]] = defaultdict(list)
    for native_id, material_id in resolver.matched_pairs("materials-project"):
        pool[native_id].append(material_id)

    emitter = _Emitter(pool, limit)
    for family, generator in FAMILIES:
        if not _family_complete(family):
            continue
        yield from generator(emitter)
        if emitter.exhausted:
            return
