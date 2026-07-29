#!/usr/bin/env python3
"""Stage 1: reduce ELEMENTA relaxation trajectories to one endpoint frame each.

ELEMENTA ships as a single flat extxyz stream per archive. Every frame carries
``material=<formula>_<structure>[_spin_<n>]`` and ``ionic_step=<n>``; the frames of
one relaxation are contiguous and ionic_step increases within a run. Per the
acquisition policy (docs/dataset-acquisition.md section 7, rule 3) intermediate
trajectory frames are not ingested, so this pass keeps only the highest ionic_step
frame of each trajectory and records the convergence diagnostics needed to decide
whether that endpoint is a relaxed structure.

Outputs, per archive, into the work directory:
  endpoints_<tag>.extxyz   one frame per trajectory, original extxyz text
  endpoints_<tag>.tsv      material, formula, structure, spin, ionic_step, n_sites,
                           energy, magmom, max_force, max_abs_stress
  endpoints_<tag>.json     pass statistics (frames, trajectories, split runs)

The stream is never materialised on disk; the archive is decompressed through a
pipe. Run one archive per invocation.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator, TextIO


# extxyz comment-line keys this stage reads.
_MATERIAL = "material="
_IONIC_STEP = "ionic_step="
_ENERGY = "energy="
_MAGMOM = "magmom="
_FORMULA = "formula="
_STRUCTURE = "structure="
_SPIN = "spin="
_STRESS = 'stress="'


def _scalar(comment: str, key: str) -> str:
    """Read an unquoted ``key=value`` token out of an extxyz comment line.

    Keys are matched on a leading space so that ``energy=`` cannot be satisfied by
    a longer key such as ``free_energy=``.
    """

    start = comment.find(" " + key)
    if start < 0:
        return ""
    start += len(key) + 1
    end = comment.find(" ", start)
    return comment[start:] if end < 0 else comment[start:end]


def _stress_max(comment: str) -> float:
    """Largest absolute component of the quoted 3x3 stress tensor."""

    start = comment.find(" " + _STRESS)
    if start < 0:
        return math.nan
    start += len(_STRESS) + 1
    end = comment.find('"', start)
    if end < 0:
        return math.nan
    try:
        return max(abs(float(value)) for value in comment[start:end].split())
    except ValueError:
        return math.nan


def _max_force(atom_lines: list[str]) -> float:
    """Largest force magnitude over the frame, in the archive's own units."""

    largest = 0.0
    for line in atom_lines:
        parts = line.split()
        if len(parts) < 7:
            return math.nan
        try:
            fx, fy, fz = float(parts[4]), float(parts[5]), float(parts[6])
        except ValueError:
            return math.nan
        largest = max(largest, math.sqrt(fx * fx + fy * fy + fz * fz))
    return largest


class Frame:
    """One extxyz frame held verbatim so the endpoint can be re-emitted losslessly.

    The two ELEMENTA archives label trajectories differently. The core release and
    the head of the spin release fold the magnetic state into ``material``
    (``Cl2V_01_spin_00``) and carry a separate ``spin`` field; the rest of the spin
    release reuses one ``material`` per composition (``Al12Mn4Y4_01``) and
    distinguishes runs only through ``structure`` (``Al12Mn4Y4_01_mag24``), with no
    ``spin`` field at all. Keying on all three covers both layouts.
    """

    __slots__ = ("count_line", "comment", "atom_lines", "material", "key", "ionic_step")

    def __init__(self, count_line: str, comment: str, atom_lines: list[str]) -> None:
        self.count_line = count_line
        self.comment = comment
        self.atom_lines = atom_lines
        self.material = _scalar(comment, _MATERIAL)
        self.key = (
            self.material,
            _scalar(comment, _STRUCTURE),
            _scalar(comment, _SPIN),
        )
        step = _scalar(comment, _IONIC_STEP)
        try:
            self.ionic_step = int(step)
        except ValueError:
            self.ionic_step = -1

    def write(self, handle: TextIO) -> None:
        handle.write(self.count_line)
        handle.write(self.comment)
        handle.writelines(self.atom_lines)

    def summary(self) -> str:
        comment = self.comment
        return "\t".join(
            (
                self.material,
                _scalar(comment, _FORMULA),
                _scalar(comment, _STRUCTURE),
                _scalar(comment, _SPIN),
                str(self.ionic_step),
                str(len(self.atom_lines)),
                _scalar(comment, _ENERGY),
                _scalar(comment, _MAGMOM),
                f"{_max_force(self.atom_lines):.6f}",
                f"{_stress_max(comment):.8f}",
            )
        )


def iter_frames(stream: Iterator[str]) -> Iterator[Frame]:
    """Yield frames from an extxyz stream without buffering more than one frame."""

    for count_line in stream:
        if not count_line.strip():
            continue
        try:
            n_atoms = int(count_line)
        except ValueError as exc:
            raise ValueError(f"expected an atom count, got {count_line!r}") from exc
        comment = next(stream)
        atom_lines = [next(stream) for _ in range(n_atoms)]
        yield Frame(count_line, comment, atom_lines)


def reduce_stream(
    stream: Iterator[str],
    frames_out: TextIO,
    summary_out: TextIO,
    *,
    progress_every: int,
    started: float,
) -> dict[str, int]:
    """Emit the highest-ionic_step frame of every contiguous trajectory run."""

    n_frames = 0
    n_trajectories = 0
    n_split_runs = 0
    n_restarts = 0
    seen: set[tuple[str, str, str]] = set()
    held: Frame | None = None

    def flush(frame: Frame) -> None:
        nonlocal n_trajectories, n_split_runs
        if frame.key in seen:
            n_split_runs += 1
        else:
            seen.add(frame.key)
        frame.write(frames_out)
        summary_out.write(frame.summary() + "\n")
        n_trajectories += 1

    for frame in iter_frames(stream):
        n_frames += 1
        if held is None:
            held = frame
        elif frame.key != held.key:
            flush(held)
            held = frame
        elif frame.ionic_step < held.ionic_step:
            # Same key but the counter restarted: a second run is concatenated
            # behind the first, so close the run that just ended.
            n_restarts += 1
            flush(held)
            held = frame
        else:
            held = frame
        if progress_every and n_frames % progress_every == 0:
            elapsed = time.time() - started
            print(
                f"frames={n_frames:,} trajectories={n_trajectories:,} "
                f"{n_frames / max(elapsed, 1e-9):,.0f} frames/s "
                f"{elapsed / 60:.1f} min",
                flush=True,
            )
    if held is not None:
        flush(held)

    return {
        "frames": n_frames,
        "trajectories": n_trajectories,
        "split_runs": n_split_runs,
        "restarted_runs": n_restarts,
    }


def open_archive(archive: Path) -> subprocess.Popen[str]:
    """Decompress a .tar.zst holding one extxyz member straight to a pipe."""

    return subprocess.Popen(
        ["tar", "--use-compress-program=unzstd", "-xOf", str(archive)],
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1 << 20,
    )


SUMMARY_COLUMNS = (
    "material",
    "formula",
    "structure",
    "spin",
    "ionic_step",
    "n_sites",
    "energy",
    "magmom",
    "max_force",
    "max_abs_stress",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="ELEMENTA *.extxyz.tar.zst archive")
    parser.add_argument("--tag", required=True, help="output basename, e.g. open or spin")
    parser.add_argument("--work", type=Path, required=True, help="output directory")
    parser.add_argument("--progress-every", type=int, default=2_000_000)
    args = parser.parse_args()

    if not args.archive.is_file():
        parser.error(f"missing archive: {args.archive}")
    args.work.mkdir(parents=True, exist_ok=True)

    frames_path = args.work / f"endpoints_{args.tag}.extxyz"
    summary_path = args.work / f"endpoints_{args.tag}.tsv"
    stats_path = args.work / f"endpoints_{args.tag}.json"
    started = time.time()

    process = open_archive(args.archive)
    assert process.stdout is not None
    try:
        with frames_path.open("w", encoding="utf-8") as frames_out, \
                summary_path.open("w", encoding="utf-8") as summary_out:
            summary_out.write("\t".join(SUMMARY_COLUMNS) + "\n")
            stats = reduce_stream(
                process.stdout,
                frames_out,
                summary_out,
                progress_every=args.progress_every,
                started=started,
            )
    finally:
        process.stdout.close()
        returncode = process.wait()
    if returncode != 0:
        raise SystemExit(f"decompression failed for {args.archive} (exit {returncode})")

    stats.update(
        archive=str(args.archive),
        tag=args.tag,
        elapsed_seconds=round(time.time() - started, 1),
    )
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
