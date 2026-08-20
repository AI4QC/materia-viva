#!/usr/bin/env python3
"""Recompute PhononDB (NIMS MDR) phonons from the archived phonopy datasets.

Why this exists
---------------
``scripts/properties/adapters/phonondb.py`` stages structures, the DFPT
dielectric tensor, Born charges and the space group, but deliberately stops
there: the archives ship NO ``force_constants`` block, so frequencies, DOS and
thermal properties are not readable out of the yaml.  They ARE recoverable,
because the yaml carries the complete ``displacements`` block (per-atom
displacement + forces for every displaced supercell), which is exactly the
input phonopy needs to build force constants.  This CLI re-runs phonopy per
record and writes the recovered phonon payload next to the adapter's staging
files, leaving the adapter untouched.

Method
------
Per record (``archives/<uuid>.zip``):

1. ``phonopy_params.yaml.xz`` is extracted to a private temp dir and loaded
   with ``phonopy.load(phonopy_yaml=..., produce_fc=True)``.  Force constants
   are built from the embedded dataset by phonopy's traditional (finite
   displacement + symmetry) fc calculator.  ``primitive_matrix`` defaults to
   ``"auto"`` but the yaml's own value wins when the record carries one (~38%
   do), and where it does not, the unit cell was already primitive: VERIFIED
   over 464 recomputed records that phonopy 4.4's primitive cell has exactly
   the atom count of the archive's own ``primitive_cell`` block, 464/464.  That
   matters because every extensive quantity below (DOS height, Cv, S, F) is
   per primitive cell, so a cell phonopy reduced further than NIMS did would
   silently rescale all of them.
2. NAC: ``phonopy.load(is_nac=True)`` picks ``nac_params`` straight out of the
   same yaml whenever it holds both ``born_effective_charge`` and
   ``dielectric_constant`` (~50% of records), giving a ``DynamicalMatrixGL``
   (Gonze-Lee) and therefore correct LO-TO splitting.  ``nac_used`` records
   which branch each row took.  The worker chdirs into the temp dir first, so
   phonopy's fallback scan for ``BORN``/``FORCE_SETS``/``FORCE_CONSTANTS`` in
   the current directory can never pick up a stray file from the repo.
3. Mesh: phonopy's own length-based sampling, ``run_mesh(mesh=100.0)``, i.e.
   the VASP convention ``N_i = max(1, int(100 A * |a_i*| + 0.5))`` symmetrised
   over the point group.  A ~5 A primitive cell lands on [20, 20, 20] and the
   mesh scales *down* automatically as the cell grows, which keeps the
   sampling density -- not the q-point count -- constant across a corpus whose
   primitive cells span 1 to ~100 atoms.  This is also phonopy's documented
   default, which matters here: the archived plots were produced by the same
   defaults, so the recomputation reproduces them (see "Validated against the
   archived plots" below).  ``--mesh-length`` overrides it.  For ~6% of records phonopy
   4.4 emits ``MeshGRGridFallbackWarning`` and rebuilds the requested grid as a
   generalized regular grid to keep the full point group; the sampling density
   is unchanged but the stored ``mesh`` is then the requested triple rather
   than the GR grid actually used.  NIMS ran phonopy 2.17.1, which had no such
   fallback, so those records sample a slightly different (still
   symmetry-complete, comparable-density) grid than the archived plots.
4. Total DOS: tetrahedron method on that mesh (phonopy default), ~201 points
   spanning the full frequency range including the imaginary tail, plotted as
   negative frequencies exactly as phonopy does.
5. Thermal properties at 300 K only: ``heat_capacity`` (J/K/mol),
   ``entropy`` (J/K/mol), ``free_energy`` (kJ/mol) -- all per mole of
   PRIMITIVE cells, phonopy's native normalisation.  ``n_atoms_prim``,
   ``formula`` and ``z_formula`` are stored alongside so a consumer can
   renormalise per atom or per formula unit without reopening the archive.
   Records with imaginary modes still get numbers (phonopy drops modes below
   ``cutoff_frequency=0``); ``has_imaginary`` is the flag to filter on.

Validated against the archived plots
------------------------------------
Six records (the manifest quartiles 0 / 2508 / 5017 / 7525 / 10033 plus one
NAC-free control) were recomputed and their DOS / thermal plots re-rendered
with phonopy's own plotting for a side-by-side read of the archived PNGs.

* ``total_dos.png`` reproduces EXACTLY -- every peak position and peak height,
  including the tetrahedron-method spikes that are the most mesh-sensitive
  feature there (e.g. 184.16 vs the plotted 184 states/THz at 2.9 THz for
  a 10-layer CdI2 polytype, 54.4 vs 55 at 65.4 THz for H8Si8S12).  The
  archived plots are labelled "States/THz-primitive cell", the same
  normalisation phonopy returns.  That the sharp peak heights land on top of
  each other is the evidence that the mesh matches: phonopy's default
  length-100 sampling is what NIMS used, no tuning was needed.
* ``band_structure.png`` brackets ``max_freq_thz`` / ``min_freq_thz`` in every
  case, including the soft branch at Y2 in record 552622e1 (plot dips to
  ~-1 THz, recomputed min -0.889 THz) and the -3.7 THz imaginary tail of the
  NAC-free record 0a0b1580 (recomputed min -3.663 THz).
* Digitising the archived thermal curves (self-calibrated on the plotted
  curves: T spans 0-1000 K, Cv(0) = S(0) = 0 fixes the zero row, y tick
  spacing fixes the scale) puts Cv(300 K) per formula unit at 132.2 / 70.0 /
  278.9 / 116.7 / 136.4 / 124.2 J/K/mol for the six records, against
  recomputed 132.9 / 73.1 / 276.7 / 117.9 / 133.9 / 125.3 -- inside the
  1-2 px reading error of the rasters in every case.
* ``thermal_properties.png`` has the identical CURVE SHAPE but is uniformly
  smaller by an integer factor: 2x for K2Ca2Si2H2O8 and Pr6U2Cl6O12, 3x for
  Ta6O15 and B3O15Ge3Pr3, 4x for H8Si8S12, 10x for Cd10I20.  That factor is Z,
  the number of formula units in the primitive cell, to three significant
  figures in all six cases (e.g. Cd10I20: recomputed Cv(1000 K) 740.4 / 10 =
  74.0 against a plotted ~75 J/K/mol).  So NIMS plots thermal properties PER
  FORMULA UNIT while plotting the DOS per primitive cell.  The values written
  here stay in phonopy's native per-primitive-cell units -- the unambiguous,
  exactly reproducible number -- and ``z_formula`` carries the divisor that
  reproduces the archived plots.

Thresholds
----------
``has_imaginary`` is ``min_freq_thz < -0.1``.  The acoustic branches are only
zero at Gamma up to the numerical error of the force constants (no acoustic
sum rule is imposed beyond phonopy's symmetrisation), so a mesh that includes
Gamma routinely returns -0.01..-0.05 THz for a perfectly stable material.
-0.1 THz (~-3.3 cm^-1) sits above that noise floor and well below any real
soft mode.

Output
------
``data/props_work/phonondb/phonons.jsonl.gz``, one JSON object per line::

    {"native_id": "phonondb-<uuid>",          # matches the adapter's ids
     "max_freq_thz", "min_freq_thz", "has_imaginary",
     "cv_300k", "entropy_300k", "free_energy_300k",   # per primitive cell
     "dos_x": [THz], "dos_y": [states/THz/primitive cell],
     "n_atoms_prim", "formula", "z_formula",
     "mesh": [n1,n2,n3], "nac_used": bool,
     "error": "..."}                          # only on failure

Written incrementally as gzip members (the file is a concatenation of gzip
streams, which every gzip reader handles transparently), so a killed run keeps
everything already flushed.  Re-running skips every ``native_id`` already in
the file, so this is resumable and safe to restart.

Feeding the pipeline
--------------------
Nothing here writes to the index.  The scalars map onto the canonical names in
``scripts/properties/registry.py`` as::

    max_freq_thz     -> phonon_max_frequency   [THz]
    min_freq_thz     -> phonon_min_frequency   [THz]
    has_imaginary    -> has_imaginary_phonon   [bool]
    cv_300k          -> heat_capacity          [J/mol.K]

with method ``"phonopy PBEsol (PhononDB)"`` (append ``" 300K, Cv per mole of
formula units"`` on heat_capacity, following the normalisation-in-the-method
convention ``aflow_ael_attach.py`` already uses -- and divide by
``z_formula`` if you take the per-formula-unit route, which is the one the
NIMS plots publish).  ``entropy_300k`` / ``free_energy_300k`` have no canonical
name yet and are carried for completeness.

``dos_x`` / ``dos_y`` are the curve payload; ``curve_sources/phonondb.py``
turns them into ``phonon_dos`` CurveRecords in fmt ``xy`` and reads this file
directly.

Usage
-----
    python -m scripts.properties.phonondb_phonons --limit 20
    python -m scripts.properties.phonondb_phonons --nproc 8
    python -m scripts.properties.phonondb_phonons --uuid <uuid> --stdout
"""

from __future__ import annotations

import os

# Must precede numpy/phonopy: each record is single-threaded and parallelism
# comes from the process pool, so a threaded BLAS would oversubscribe the box.
# RAYON_NUM_THREADS is the load-bearing one -- phonopy 4.x runs its force
# constants and its tetrahedron DOS through Rust (lang="Rust"), and rayon
# ignores OMP_NUM_THREADS entirely.  Left unpinned, one worker spreads over
# every core (measured: 1.5 s wall for 24 s of CPU on a 31-core box), so
# --nproc 8 would really mean ~130 threads.  Pinned, --nproc 8 means 8 cores.
# Explicitly exported values still win (setdefault).
for _var in (
    "RAYON_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
):
    os.environ.setdefault(_var, "1")

import argparse  # noqa: E402
import gzip  # noqa: E402
import json  # noqa: E402
import lzma  # noqa: E402
import multiprocessing as mp  # noqa: E402
import signal  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
import zipfile  # noqa: E402
from pathlib import Path  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SOURCE_ROOT = PROJECT_ROOT / "data" / "raw" / "acquired" / "phonondb"
ARCHIVE_DIR = SOURCE_ROOT / "archives"
MANIFEST = SOURCE_ROOT / "manifest.json"
OUT_PATH = PROJECT_ROOT / "data" / "props_work" / "phonondb" / "phonons.jsonl.gz"

#: phonopy's default length-based q-point sampling (Angstrom); see module doc
DEFAULT_MESH_LENGTH = 100.0
#: min_freq below this counts as a genuine imaginary mode, not fc noise
IMAGINARY_THRESHOLD_THZ = -0.1
#: DOS points written per record
MAX_DOS_POINTS = 600
#: per-record wall-clock guard (seconds); a blown-up cell must not stall a pool
RECORD_TIMEOUT = 1800


class _Timeout(Exception):
    pass


def _alarm(signum, frame):  # noqa: ARG001
    raise _Timeout("record exceeded the per-record time limit")


def archive_paths() -> list[Path]:
    """Same enumeration as the adapter: manifest order, then a glob fallback."""

    if MANIFEST.exists():
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        paths = [
            ARCHIVE_DIR / f"{uuid}.zip" for uuid in payload.get("dataset_ids") or []
        ]
        paths = [path for path in paths if path.exists()]
        if paths:
            return paths
    return sorted(ARCHIVE_DIR.glob("*.zip"))


def _downsample(values, limit: int = MAX_DOS_POINTS) -> list[float]:
    """Uniform stride down to <= limit points, always keeping both endpoints."""

    values = [float(v) for v in values]
    if len(values) <= limit:
        return values
    stride = -(-len(values) // limit)  # ceil division
    picked = values[::stride]
    if picked[-1] != values[-1]:
        picked.append(values[-1])
    return picked


def _formula_and_z(symbols) -> tuple[str, int]:
    """Reduced formula plus Z, the formula units in the cell.

    Z is the divisor that turns phonopy's per-primitive-cell thermal
    properties into the per-formula-unit numbers the archived
    ``thermal_properties.png`` plots (verified on six records).
    """

    from collections import Counter
    from math import gcd

    counts = Counter(str(symbol) for symbol in symbols)
    z = 0
    for value in counts.values():
        z = gcd(z, value)
    z = max(1, z)
    formula = "".join(
        f"{element}{counts[element] // z if counts[element] // z > 1 else ''}"
        for element in sorted(counts)
    )
    return formula, z


def compute(uuid: str, mesh_length: float = DEFAULT_MESH_LENGTH) -> dict:
    """Recompute one record. Never raises: failures come back as {'error': ...}."""

    import numpy as np
    import phonopy

    native_id = f"phonondb-{uuid}"
    path = ARCHIVE_DIR / f"{uuid}.zip"
    started = time.time()
    previous_cwd = os.getcwd()
    handler = None
    try:
        handler = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(RECORD_TIMEOUT)
    except ValueError:  # not the main thread of the worker; run unguarded
        handler = None

    try:
        with tempfile.TemporaryDirectory(prefix="phonondb-") as workdir:
            yaml_path = Path(workdir) / "phonopy_params.yaml"
            with zipfile.ZipFile(path) as bundle:
                compressed = bundle.read("phonopy_params.yaml.xz")
            yaml_path.write_bytes(lzma.decompress(compressed))

            # phonopy falls back to BORN / FORCE_SETS / FORCE_CONSTANTS in the
            # CURRENT directory; the temp dir holds only our yaml.
            os.chdir(workdir)
            phonon = phonopy.load(
                phonopy_yaml=str(yaml_path),
                produce_fc=True,
                is_nac=True,
                log_level=0,
            )
            if phonon.force_constants is None:
                raise RuntimeError("no force constants produced from the dataset")

            nac_used = phonon.nac_params is not None
            n_atoms_prim = len(phonon.primitive)
            formula, z_formula = _formula_and_z(phonon.primitive.symbols)

            phonon.run_mesh(mesh_length)
            mesh = [int(v) for v in phonon.mesh.mesh_numbers]
            frequencies = np.asarray(phonon.mesh.frequencies)
            max_freq = float(frequencies.max())
            min_freq = float(frequencies.min())

            phonon.run_total_dos()
            total_dos = phonon.total_dos
            dos_x = _downsample(np.asarray(total_dos.frequency_points))
            dos_y = _downsample(np.asarray(total_dos.dos))

            phonon.run_thermal_properties(t_min=300, t_max=300, t_step=1)
            thermal = phonon.thermal_properties

            record = {
                "native_id": native_id,
                "max_freq_thz": round(max_freq, 6),
                "min_freq_thz": round(min_freq, 6),
                "has_imaginary": bool(min_freq < IMAGINARY_THRESHOLD_THZ),
                "cv_300k": round(float(thermal.heat_capacity[0]), 6),
                "entropy_300k": round(float(thermal.entropy[0]), 6),
                "free_energy_300k": round(float(thermal.free_energy[0]), 6),
                "dos_x": [round(v, 6) for v in dos_x],
                "dos_y": [round(v, 6) for v in dos_y],
                "n_atoms_prim": n_atoms_prim,
                "formula": formula,
                "z_formula": z_formula,
                "mesh": mesh,
                "nac_used": nac_used,
                "seconds": round(time.time() - started, 2),
            }
            return record
    except _Timeout:
        return {
            "native_id": native_id,
            "error": f"timeout after {RECORD_TIMEOUT}s",
            "seconds": round(time.time() - started, 2),
        }
    except Exception as exc:  # noqa: BLE001 - one bad record must not stop the run
        return {
            "native_id": native_id,
            "error": f"{type(exc).__name__}: {exc}".strip()[:500],
            "traceback": traceback.format_exc(limit=3)[-800:],
            "seconds": round(time.time() - started, 2),
        }
    finally:
        try:
            signal.alarm(0)
            if handler is not None:
                signal.signal(signal.SIGALRM, handler)
        except ValueError:
            pass
        try:
            os.chdir(previous_cwd)
        except OSError:
            pass


_MESH_LENGTH = DEFAULT_MESH_LENGTH


def _init_worker(mesh_length: float) -> None:
    global _MESH_LENGTH
    _MESH_LENGTH = mesh_length
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # let the parent handle Ctrl-C


def _work(uuid: str) -> dict:
    return compute(uuid, _MESH_LENGTH)


def read_rows(path: Path):
    """Yield the rows of a phonons.jsonl.gz, tolerating a torn final member.

    The writer appends gzip members and only the final ``close()`` writes that
    member's CRC trailer, so the file raises ``EOFError`` at the tail whenever
    it is read while a run is in flight or after a run was killed.  Everything
    before the tear is intact, which is exactly what resume needs, so the tear
    ends the iteration instead of failing it.
    """

    if not path.exists():
        return
    import zlib

    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
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
                except ValueError:  # torn last line
                    return
    except (EOFError, OSError, zlib.error):
        return


def done_ids(out_path: Path) -> set[str]:
    """native_ids already written, so a restart resumes instead of redoing."""

    return {row["native_id"] for row in read_rows(out_path) if "native_id" in row}


def run(
    nproc: int,
    limit: int | None,
    out_path: Path,
    mesh_length: float,
    uuids: list[str] | None,
    to_stdout: bool,
    redo_errors: bool,
) -> int:
    if uuids:
        targets = list(uuids)
    else:
        targets = [path.stem for path in archive_paths()]

    if not to_stdout:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        skip = done_ids(out_path)
        if redo_errors:
            skip = {
                row["native_id"]
                for row in read_rows(out_path)
                if "error" not in row and "native_id" in row
            }
        before = len(targets)
        targets = [u for u in targets if f"phonondb-{u}" not in skip]
        print(
            f"[phonondb-phonons] {before:,} records, {len(skip):,} already done, "
            f"{len(targets):,} to do",
            file=sys.stderr,
            flush=True,
        )
    if limit is not None:
        targets = targets[:limit]
    if not targets:
        print("[phonondb-phonons] nothing to do", file=sys.stderr, flush=True)
        return 0

    started = time.time()
    written = failed = 0
    handle = (
        sys.stdout
        if to_stdout
        else gzip.open(out_path, "at", encoding="utf-8", compresslevel=6)
    )
    pool = None
    try:
        if nproc <= 1:
            _init_worker(mesh_length)
            results = (_work(uuid) for uuid in targets)
        else:
            pool = mp.Pool(
                processes=nproc, initializer=_init_worker, initargs=(mesh_length,)
            )
            results = pool.imap_unordered(_work, targets, chunksize=1)
        for record in results:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            written += 1
            failed += 1 if "error" in record else 0
            if written % 50 == 0:
                handle.flush()
            if written % 200 == 0:
                elapsed = time.time() - started
                rate = written / elapsed
                left = (len(targets) - written) / rate if rate else 0
                print(
                    f"[phonondb-phonons] {written:,}/{len(targets):,} "
                    f"({failed:,} errors) {rate:.2f} rec/s "
                    f"ETA {left / 3600:.2f} h",
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        if pool is not None:
            pool.terminate()
            pool.join()
        handle.flush()
        if handle is not sys.stdout:
            handle.close()

    elapsed = time.time() - started
    print(
        f"[phonondb-phonons] DONE {written:,} written ({failed:,} errors) in "
        f"{elapsed / 60:.1f} min -> {out_path}",
        file=sys.stderr,
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--nproc", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument(
        "--mesh-length",
        type=float,
        default=DEFAULT_MESH_LENGTH,
        help="length-based q-point sampling in Angstrom (default 100 = phonopy's)",
    )
    parser.add_argument(
        "--uuid", action="append", default=None, help="run only these uuids"
    )
    parser.add_argument(
        "--stdout", action="store_true", help="print JSONL instead of appending"
    )
    parser.add_argument(
        "--redo-errors",
        action="store_true",
        help="re-run rows previously written with an error",
    )
    args = parser.parse_args()
    return run(
        nproc=max(1, args.nproc),
        limit=args.limit,
        out_path=args.out,
        mesh_length=args.mesh_length,
        uuids=args.uuid,
        to_stdout=args.stdout,
        redo_errors=args.redo_errors,
    )


if __name__ == "__main__":
    sys.exit(main())
