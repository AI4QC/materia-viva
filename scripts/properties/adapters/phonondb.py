"""PhononDB (NIMS MDR): PBEsol DFPT harmonic phonon calculations.

10,034 records, one zip archive each under ``archives/<uuid>.zip``; the record
set is enumerated from ``manifest.json`` (``dataset_ids``) so runs are
reproducible, falling back to ``sorted(archives.glob('*.zip'))``.

Matching: MP ids from the MDR crosswalk, plus the fingerprint
-------------------------------------------------------------
The *acquisition* carries zero cross-database identifiers -- VERIFIED: the zip
names are bare MDR dataset UUIDs, ``phonopy_params.yaml`` holds no mp/icsd/
cod/oqmd field, and ``manifest.json`` records only UUIDs, byte counts and
checksums. The MDR *record metadata* does, though: every dataset is titled
``Ab-initio phonon calculation for KCaSiHO4 / P2_1 (4) / materials id 995190``
and its description states that the input geometry was "obtained from the
Materials Project using pymatgen MPRester".
``scripts/datasets/phonondb_mdr_metadata.py`` harvests that metadata over the
repository's OAI-PMH endpoint and writes ``uuid_to_mpid.json`` next to the
archives; this adapter loads it when present and is unchanged when it is
absent (no crosswalk -> no ``match_ids``, fingerprint-only, exactly as before).

``always_hash`` is True whenever the crosswalk is loaded, and deliberately so.
The MP id names the *parent* entry the structure came from, not this record's
geometry: PhononDB re-relaxes each cell with PBEsol before the DFPT run, while
the MP entry is a PBE (or PBE+U) relaxation, so lattice constants typically
differ by a fraction of a percent and the two are not the same structure. The
id is the right provenance link -- it says which MP entry this phonon
calculation is *about* -- but the record still has to be fingerprinted so its
own PBEsol cell can join the pool as a distinct candidate rather than being
silently folded into the PBE parent.

Parsing
-------
Only ``phonopy_params.yaml.xz`` is read, and only its header. The file is
~370 kB uncompressed, ~87% of which is the ``displacements:`` force-set block,
so it is stream-decompressed in 64 kB chunks and cut at the first
``\\ndisplacements:`` (~30 kB of header survives; ~500 records/1.3 s on one
core). ``yaml.safe_load`` on the whole document would be ~50x slower for no
extra information. Top-level sections are split by regex and indexed by key
rather than by position: ``primitive_matrix`` is present in only ~38% of
records and ``born_effective_charge``/``dielectric_constant`` in ~50%.

The staged structure is the ``unit_cell`` section only -- never ``supercell``
(the displaced 1x2x1-style cell) and never ``primitive_cell`` (which would
duplicate the same material under a different setting).

No phonon spectra
-----------------
VERIFIED absent: the archive ships band_structure/total_dos/projected_dos/
thermal_properties as matplotlib PNG rasters plus the raw displacement force
sets, and no ``force_constants`` block. Frequencies, DOS and thermal
properties are therefore NOT recoverable without re-running phonopy, so do not
retry ``phonon_max_frequency`` / ``has_imaginary_phonon`` / ``heat_capacity``
here.

Properties
----------
* ``spacegroup_number`` -- phonopy's spglib symmetrisation of the unit cell.
* ``dielectric_constant_electronic`` -- trace/3 of the DFPT high-frequency
  tensor (eps-infinity). CLAMPED to (0, 100]: the survey found a divergent
  tail from small-gap/metallic DFPT (median 4.99, p95 17.5, p99 83.3, max 395)
  where the electronic response is an artefact of a vanishing gap rather than a
  physical permittivity; those rows are dropped rather than staged.
* ``born_effective_charge_max`` -- the maximum |component| over all Born
  tensors, in units of e. Deliberately the max component and not the isotropic
  trace/3: the off-diagonal terms are what flag strong dynamical charge
  anisotropy (ferroelectric candidates), and a single scalar per record has to
  be comparable across sources. NOTE: phonopy writes 3N Born rows for the
  PRIMITIVE cell (verified: the vector count is always 3 x len(primitive_cell
  points), which differs from the unit cell whenever a primitive_matrix is
  set), so these charges are not per-site-aligned with the staged unit cell --
  which is fine for a max-over-atoms reduction, but rules out staging them
  per site later without redoing the mapping.
"""

from __future__ import annotations

import json
import lzma
import re
import zipfile
from pathlib import Path
from typing import Iterator

from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_STOP = b"\ndisplacements:"
_CHUNK = 65536

_SECTION = re.compile(r"^(\w[\w_]*):", re.M)
_VECTOR = re.compile(r"\[\s*([-\d.eE+]+),\s*([-\d.eE+]+),\s*([-\d.eE+]+)\s*\]")
_SYMBOL = re.compile(r"symbol:\s*(\w+)")
_SPACE_GROUP = re.compile(
    r'^space_group:\n  type: "([^"]+)"\n  number: (\d+)', re.M
)
_SPACE_GROUP_NUMBER = re.compile(r"^\s*number:\s*(\d+)", re.M)

DFPT_METHOD = "PBEsol DFPT (PhononDB)"
SYMMETRY_METHOD = "PBEsol (PhononDB)"

#: eps-infinity above this is a small-gap/metallic DFPT failure, not a material
MAX_EPSILON = 100.0

#: {uuid: {"mp_id": ..., "formula": ...}}, written by
#: scripts/datasets/phonondb_mdr_metadata.py; optional
CROSSWALK_FILE = "uuid_to_mpid.json"


def _read_header(path: Path) -> str | None:
    """Decompress phonopy_params.yaml.xz only as far as the force sets."""

    with zipfile.ZipFile(path) as bundle:
        with bundle.open("phonopy_params.yaml.xz") as raw:
            decompressor = lzma.LZMADecompressor()
            buffer = b""
            while chunk := raw.read(_CHUNK):
                buffer += decompressor.decompress(chunk)
                if _STOP in buffer or decompressor.eof:
                    break
    if not buffer:
        return None
    return buffer.split(_STOP)[0].decode("utf-8", "replace")


def _sections(text: str) -> dict[str, str]:
    """Top-level yaml sections keyed by name; order is never assumed."""

    parts = _SECTION.split(text)
    sections: dict[str, str] = {}
    for index in range(1, len(parts) - 1, 2):
        sections.setdefault(parts[index], parts[index + 1])
    return sections


def _unit_cell_structure(section: str):
    """pymatgen Structure from the unit_cell section (lattice in angstrom)."""

    from pymatgen.core import Lattice, Structure

    head, _, points = section.partition("points:")
    if not points:
        return None
    lattice = [
        [float(value) for value in match] for match in _VECTOR.findall(head)
    ]
    if len(lattice) != 3:
        return None
    symbols = _SYMBOL.findall(points)
    coords = [
        [float(value) for value in match] for match in _VECTOR.findall(points)
    ]
    if not symbols or len(symbols) != len(coords):
        return None
    return Structure(Lattice(lattice), symbols, coords)


def _epsilon_electronic(section: str) -> float | None:
    """trace/3 of the 3x3 high-frequency dielectric tensor."""

    rows = _VECTOR.findall(section)
    if len(rows) < 3:
        return None
    try:
        trace = float(rows[0][0]) + float(rows[1][1]) + float(rows[2][2])
    except ValueError:
        return None
    return trace / 3.0


def _born_max(section: str) -> float | None:
    """Largest |component| over every Born effective-charge tensor, in e."""

    largest = None
    for row in _VECTOR.findall(section):
        for value in row:
            try:
                magnitude = abs(float(value))
            except ValueError:
                continue
            if largest is None or magnitude > largest:
                largest = magnitude
    return largest


def _spacegroup_number(text: str, sections: dict[str, str]) -> int | None:
    match = _SPACE_GROUP.search(text)
    if match:
        return int(match.group(2))
    fallback = _SPACE_GROUP_NUMBER.search(sections.get("space_group", ""))
    return int(fallback.group(1)) if fallback else None


def _load_crosswalk(path: Path) -> dict[str, str]:
    """{uuid: mp-id} from the MDR harvest; empty when the file is absent."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # a truncated harvest must not stop the run
        return {}
    crosswalk = {}
    for uuid, entry in (payload or {}).items():
        mp_id = entry.get("mp_id") if isinstance(entry, dict) else entry
        if mp_id:
            crosswalk[uuid] = str(mp_id)
    return crosswalk


class PhonondbAdapter(SourceAdapter):
    source_key = "phonondb"
    always_hash = False
    properties_only = False

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(root)
        self.crosswalk = _load_crosswalk(self.root / CROSSWALK_FILE)
        # the MP id names the PBE parent entry, not this PBEsol cell, so an id
        # hit must not skip fingerprinting (see the module docstring)
        self.always_hash = bool(self.crosswalk)

    def _match_ids(self, uuid: str) -> list[tuple[str, str]]:
        mp_id = self.crosswalk.get(uuid)
        if not mp_id:
            return []
        pair = normalize_match_id("materials-project", mp_id)
        return [pair] if pair else []

    def _archive_paths(self) -> list[Path]:
        archives = self.root / "archives"
        manifest = self.root / "manifest.json"
        if manifest.exists():
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            uuids = payload.get("dataset_ids") or []
            paths = [archives / f"{uuid}.zip" for uuid in uuids]
            paths = [path for path in paths if path.exists()]
            if paths:
                return paths
        return sorted(archives.glob("*.zip"))

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        for count, path in enumerate(self._archive_paths()):
            if limit is not None and count >= limit:
                return
            native_id = f"phonondb-{path.stem}"
            match_ids = self._match_ids(path.stem)
            try:
                text = _read_header(path)
            except Exception:  # noqa: BLE001 - a corrupt zip must not stop the run
                text = None
            if not text:
                yield SourceRecord(native_id=native_id, match_ids=match_ids)
                continue
            sections = _sections(text)
            properties: list[PropertyValue] = []

            spacegroup = _spacegroup_number(text, sections)
            if spacegroup:
                properties.append(
                    PropertyValue(
                        "spacegroup_number", spacegroup, None, SYMMETRY_METHOD
                    )
                )

            dielectric = sections.get("dielectric_constant")
            if dielectric:
                epsilon = _epsilon_electronic(dielectric)
                if epsilon is not None and 0.0 < epsilon <= MAX_EPSILON:
                    properties.append(
                        PropertyValue(
                            "dielectric_constant_electronic",
                            epsilon,
                            None,
                            DFPT_METHOD,
                        )
                    )

            born = sections.get("born_effective_charge")
            if born:
                largest = _born_max(born)
                if largest is not None:
                    properties.append(
                        PropertyValue(
                            "born_effective_charge_max", largest, "e", DFPT_METHOD
                        )
                    )

            try:
                structure = _unit_cell_structure(sections.get("unit_cell", ""))
            except Exception:  # noqa: BLE001 - keep the property-only record
                structure = None

            yield SourceRecord(
                native_id=native_id,
                properties=properties,
                structure=structure,
                match_ids=match_ids,
            )
