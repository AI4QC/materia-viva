#!/usr/bin/env python3
"""Stage 3: merge unique ELEMENTA endpoints into the candidate dataset.

Follows data/lemat_merge_work/merge_build.py:

 1. Load the reference BAWL hash set for the current 6.12M candidate pool, which is
    the union of local_hashes_{train,val}.tsv (the 1.84M local half) and the
    entalpic_fingerprint column of lemat_meta.tsv (the 4.27M LeMat half).
 2. Load the ELEMENTA endpoint hashes from elementa_hash.py. Both archives are
    merged in one pass. Within ELEMENTA, endpoints sharing a fingerprint collapse to
    the lowest-energy representative -- ELEMENTA Spin relaxes one geometry under many
    magnetic initialisations, so those runs are the same structure at different
    energies. Endpoints whose fingerprint is already in the reference set are dropped.
 3. For kept endpoints: re-stream the endpoint extxyz, Structure -> P1 CIF
    (multiprocessing), material_id from composition, sequential index continuing
    after the current dataset maximum.
 4. Append to train.csv / val.csv (deterministic 95/5 by row counter, every 20th to
    val), and write elementa_meta.tsv and elementa_stats.json alongside lemat_meta.tsv.

pbes_gap is written empty: ELEMENTA labels total energy, forces, stress and magnetic
moment, not a PBEsol band gap, and the data contract accepts a blank gap.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
csv.field_size_limit(10 ** 8)


def _init() -> None:
    import warnings as w

    w.filterwarnings("ignore")
    sys.stderr = open(os.devnull, "w")


def _to_cif(item):
    """(lattice, species, cartesian positions, key) -> (material_id, cif, key)."""

    lattice, species, positions, key = item
    try:
        from pymatgen.core import Lattice, Structure
        from pymatgen.io.cif import CifWriter

        structure = Structure(
            Lattice(lattice), species, positions, coords_are_cartesian=True
        )
        material_id = structure.composition.formula.replace(" ", "")
        return material_id, str(CifWriter(structure)), key
    except Exception:  # noqa: BLE001 - counted as a CIF failure
        return None


def _scalar(comment: str, key: str) -> str:
    start = comment.find(" " + key)
    if start < 0:
        return ""
    start += len(key) + 1
    end = comment.find(" ", start)
    return comment[start:] if end < 0 else comment[start:end]


def _lattice(comment: str) -> list[list[float]]:
    start = comment.find('Lattice="')
    end = comment.find('"', start + 9)
    flat = [float(value) for value in comment[start + 9 : end].split()]
    return [flat[0:3], flat[3:6], flat[6:9]]


def load_reference(work: Path, candidate: Path) -> tuple[set[str], int, int]:
    """Fingerprints and largest row index for the candidate pool as it stands.

    The pool is the union of the 1.84M local half and the 4.27M LeMat half, so its
    fingerprints and indices are read from local_hashes_{train,val}.tsv and
    lemat_meta.tsv. Both carry the index column, which is why the 6.8 GB CSVs never
    need to be parsed just to find where to continue numbering.
    """

    hashes: set[str] = set()
    n_fail = 0
    largest = 0
    for split in ("train", "val"):
        path = work / f"local_hashes_{split}.tsv"
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                index, _material_id, hsh = line.rstrip("\n").split("\t")
                try:
                    largest = max(largest, int(index))
                except ValueError:
                    pass
                if hsh.startswith("FAIL:"):
                    n_fail += 1
                else:
                    hashes.add(hsh)
    with (candidate / "lemat_meta.tsv").open(encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            fields = line.split("\t", 3)
            try:
                largest = max(largest, int(fields[0]))
            except ValueError:
                pass
            hashes.add(fields[2])
    return hashes, n_fail, largest


def select_winners(
    work: Path, tags: list[str]
) -> tuple[dict[tuple[str, str, str, str], str], dict]:
    """Lowest-energy endpoint per fingerprint, across both ELEMENTA archives.

    Keys carry the archive tag so that the two archives can never collide on a
    shared (material, structure, spin) triple; within one archive stage 1 already
    guarantees the triple is unique.
    """

    best: dict[str, tuple[float, tuple[str, str, str, str]]] = {}
    n_rows = 0
    n_hash_fail = 0
    for tag in tags:
        path = work / f"hashes_{tag}.tsv"
        with path.open(encoding="utf-8") as handle:
            next(handle)
            for line in handle:
                material, structure, spin, energy, _n_sites, hsh = (
                    line.rstrip("\n").split("\t")
                )
                n_rows += 1
                if hsh.startswith("FAIL:"):
                    n_hash_fail += 1
                    continue
                try:
                    value = float(energy)
                except ValueError:
                    value = float("inf")
                key = (tag, material, structure, spin)
                current = best.get(hsh)
                if current is None or value < current[0]:
                    best[hsh] = (value, key)
    winners = {key: hsh for hsh, (_energy, key) in best.items()}
    stats = {
        "n_elementa_endpoints": n_rows,
        "n_hash_fail": n_hash_fail,
        "n_unique_within_elementa": len(best),
        "n_dup_within_elementa": n_rows - n_hash_fail - len(best),
    }
    return winners, stats


def iter_selected(endpoints: Path, tag: str, keep: dict[tuple[str, str, str, str], str]):
    """Re-stream an endpoint file, yielding work items for the selected keys only."""

    with endpoints.open(encoding="utf-8") as handle:
        for count_line in handle:
            if not count_line.strip():
                continue
            n_atoms = int(count_line)
            comment = next(handle)
            key = (
                tag,
                _scalar(comment, "material="),
                _scalar(comment, "structure="),
                _scalar(comment, "spin="),
            )
            wanted = key in keep
            species: list[str] = []
            positions: list[tuple[float, float, float]] = []
            for _ in range(n_atoms):
                line = next(handle)
                if not wanted:
                    continue
                parts = line.split()
                species.append(parts[0])
                positions.append((float(parts[1]), float(parts[2]), float(parts[3])))
            if wanted:
                yield _lattice(comment), species, positions, key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--lemat-work",
        type=Path,
        required=True,
        help="directory holding local_hashes_{train,val}.tsv",
    )
    parser.add_argument("--tags", nargs="+", default=["open", "spin"])
    parser.add_argument("--nproc", type=int, default=28)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report overlap statistics without touching the released splits",
    )
    args = parser.parse_args()
    started = time.time()

    reference, n_local_fail, pool_max_index = load_reference(
        args.lemat_work, args.candidate
    )
    print(
        f"reference: {len(reference):,} hashes ({n_local_fail:,} failed), "
        f"max index {pool_max_index:,}, {time.time() - started:.0f}s",
        flush=True,
    )

    winners, stats = select_winners(args.work, args.tags)
    print(json.dumps(stats, indent=2), flush=True)

    keep: dict[tuple[str, str, str, str], str] = {}
    n_overlap = 0
    for key, hsh in winners.items():
        if hsh in reference:
            n_overlap += 1
        else:
            keep[key] = hsh
    stats["n_overlap_vs_pool"] = n_overlap
    stats["n_new"] = len(keep)
    stats["overlap_rate_vs_elementa_unique"] = round(
        n_overlap / max(stats["n_unique_within_elementa"], 1), 4
    )
    print(
        f"overlap with pool: {n_overlap:,}  new: {len(keep):,}  "
        f"({(time.time() - started) / 60:.1f} min)",
        flush=True,
    )
    if args.dry_run:
        print(json.dumps(stats, indent=2), flush=True)
        return 0

    next_index = pool_max_index + 1
    print(f"appending from index {next_index:,}", flush=True)

    from multiprocessing import Pool

    new_rows_path = args.work / "new_rows.csv"
    meta_path = args.candidate / "elementa_meta.tsv"
    n_cif_fail = 0
    n_written = 0

    with Pool(args.nproc, initializer=_init) as pool, \
            new_rows_path.open("w", newline="", encoding="utf-8") as new_file, \
            meta_path.open("w", encoding="utf-8") as meta_file:
        writer = csv.writer(new_file)
        writer.writerow(["index", "material_id", "cif", "pbes_gap"])
        meta_file.write("index\tarchive\tmaterial\tstructure\tspin\tbawl_hash\n")
        for tag in args.tags:
            endpoints = args.work / f"endpoints_{tag}.extxyz"
            for result in pool.imap(
                _to_cif, iter_selected(endpoints, tag, keep), chunksize=32
            ):
                if result is None:
                    n_cif_fail += 1
                    continue
                material_id, cif, key = result
                _tag, material, structure, spin = key
                writer.writerow([next_index, material_id, cif, ""])
                meta_file.write(
                    f"{next_index}\t{tag}\t{material}\t{structure}\t{spin}\t"
                    f"{keep[key]}\n"
                )
                next_index += 1
                n_written += 1
                if n_written % 100000 == 0:
                    print(
                        f"{n_written:,} rows staged "
                        f"({(time.time() - started) / 60:.1f} min)",
                        flush=True,
                    )
            print(f"{tag}: staged, total {n_written:,}", flush=True)

    stats["n_cif_fail"] = n_cif_fail
    stats["n_appended"] = n_written

    with new_rows_path.open(newline="", encoding="utf-8") as new_file, \
            (args.candidate / "train.csv").open("a", newline="", encoding="utf-8") as train, \
            (args.candidate / "val.csv").open("a", newline="", encoding="utf-8") as val:
        reader = csv.reader(new_file)
        next(reader)
        train_writer, val_writer = csv.writer(train), csv.writer(val)
        n_train = n_val = 0
        for counter, row in enumerate(reader):
            if counter % 20 == 19:
                val_writer.writerow(row)
                n_val += 1
            else:
                train_writer.writerow(row)
                n_train += 1
    stats["n_appended_train"] = n_train
    stats["n_appended_val"] = n_val
    stats["elapsed_minutes"] = round((time.time() - started) / 60, 1)

    (args.candidate / "elementa_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
