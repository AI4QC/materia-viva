#!/usr/bin/env python3
"""Stage 2: compute BAWL hashes (= LeMat entalpic_fingerprint) for ELEMENTA endpoints.

Same shape as data/lemat_merge_work/hash_local_cifs.py, but the input is the
endpoint extxyz produced by elementa_endpoints.py instead of a CIF CSV.

PROTOCOL (from external_structs/pipeline_stage1.py): primitive-reduce before
hashing. BAWL is not cell-representation invariant and the existing 6.12M pool is
stored in primitive-like cells, so a conventional cell would hash to a different
fingerprint and defeat the cross-dataset overlap check.

Output TSV per archive: material, structure, spin, energy, n_sites, bawl_hash
(hash 'FAIL:<err>' on failure).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Iterator

warnings.filterwarnings("ignore")

_hasher = None

MAX_SITES = 500
MAX_PRIMITIVE_SITES = 300


def _init() -> None:
    global _hasher
    import warnings as w

    w.filterwarnings("ignore")
    from material_hasher.hasher.bawl import BAWLHasher

    _hasher = BAWLHasher()
    # silence noisy pymatgen warnings inside workers
    sys.stderr = open(os.devnull, "w")


def _work(item):
    key, lattice, species, positions, energy, n_sites = item
    try:
        from pymatgen.core import Lattice, Structure

        structure = Structure(
            Lattice(lattice), species, positions, coords_are_cartesian=True
        )
        if len(structure) > MAX_SITES:
            return key, energy, n_sites, "FAIL:TOO_LARGE"
        structure = structure.get_primitive_structure()
        if len(structure) > MAX_PRIMITIVE_SITES:
            return key, energy, n_sites, "FAIL:TOO_LARGE_PRIM"
        return key, energy, n_sites, _hasher.get_material_hash(structure)
    except Exception as exc:  # noqa: BLE001 - recorded per row, never fatal
        return key, energy, n_sites, "FAIL:" + repr(exc)[:120]


def _scalar(comment: str, key: str) -> str:
    start = comment.find(" " + key)
    if start < 0:
        return ""
    start += len(key) + 1
    end = comment.find(" ", start)
    return comment[start:] if end < 0 else comment[start:end]


def _lattice(comment: str) -> list[float]:
    start = comment.find('Lattice="')
    end = comment.find('"', start + 9)
    return [float(value) for value in comment[start + 9 : end].split()]


def frames(path: Path) -> Iterator[tuple]:
    """Yield one work item per endpoint frame."""

    with path.open(encoding="utf-8") as handle:
        for count_line in handle:
            if not count_line.strip():
                continue
            n_atoms = int(count_line)
            comment = next(handle)
            species: list[str] = []
            positions: list[tuple[float, float, float]] = []
            for _ in range(n_atoms):
                parts = next(handle).split()
                species.append(parts[0])
                positions.append((float(parts[1]), float(parts[2]), float(parts[3])))
            flat = _lattice(comment)
            lattice = [flat[0:3], flat[3:6], flat[6:9]]
            key = (
                _scalar(comment, "material="),
                _scalar(comment, "structure="),
                _scalar(comment, "spin="),
            )
            yield (
                key,
                lattice,
                species,
                positions,
                _scalar(comment, "energy="),
                n_atoms,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoints", type=Path, help="endpoints_<tag>.extxyz")
    parser.add_argument("--out", type=Path, required=True, help="destination TSV")
    parser.add_argument("--nproc", type=int, default=28)
    parser.add_argument("--chunk", type=int, default=64)
    args = parser.parse_args()

    from multiprocessing import Pool

    done = 0
    failed = 0
    started = time.time()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with Pool(args.nproc, initializer=_init) as pool, \
            args.out.open("w", encoding="utf-8") as out:
        out.write("material\tstructure\tspin\tenergy\tn_sites\tbawl_hash\n")
        for key, energy, n_sites, hsh in pool.imap_unordered(
            _work, frames(args.endpoints), chunksize=args.chunk
        ):
            material, structure, spin = key
            out.write(
                f"{material}\t{structure}\t{spin}\t{energy}\t{n_sites}\t{hsh}\n"
            )
            done += 1
            failed += hsh.startswith("FAIL:")
            if done % 20000 == 0:
                elapsed = time.time() - started
                print(
                    f"{done:,} done, {failed:,} failed, "
                    f"{done / elapsed:,.0f}/s, {elapsed / 60:.1f} min",
                    flush=True,
                )
    print(
        f"FINISHED {done:,} endpoints ({failed:,} failed) "
        f"in {(time.time() - started) / 60:.1f} min -> {args.out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
