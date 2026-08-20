#!/usr/bin/env python3
"""Parallel BAWL fingerprints for staged source structures.

Protocol matches the original pool merge exactly (see elementa_hash.py):
parse, cap at 500 sites, primitive-reduce, cap at 300 sites, then
BAWLHasher.get_material_hash. Failures are recorded per row as FAIL:<reason>
and never abort the run.

Input:  staging_structs.jsonl.gz lines {"native_id": ..., "cif": ...}
Output: hashes.tsv.gz with native_id, n_sites, formula, bawl_hash
(formula is the full input cell's composition; the BAWL string itself carries
the space-group number as its middle token, which the loader reuses).
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

MAX_SITES = 500
MAX_PRIMITIVE_SITES = 300

_hasher = None


def _init() -> None:
    global _hasher
    import warnings as w

    w.filterwarnings("ignore")
    from material_hasher.hasher.bawl import BAWLHasher

    _hasher = BAWLHasher()
    sys.stderr = open(os.devnull, "w")


def _work(line: str) -> tuple[str, int, str, str]:
    try:
        payload = json.loads(line)
        native_id = payload["native_id"]
    except Exception as exc:  # noqa: BLE001
        return "?", 0, "", "FAIL:BAD_ROW:" + repr(exc)[:80]
    try:
        from pymatgen.core import Structure

        structure = Structure.from_str(payload["cif"], fmt="cif")
        n_sites = len(structure)
        formula = structure.composition.formula.replace(" ", "")
        if n_sites > MAX_SITES:
            return native_id, n_sites, formula, "FAIL:TOO_LARGE"
        if not structure.is_ordered:
            return native_id, n_sites, formula, "FAIL:DISORDERED"
        structure = structure.get_primitive_structure()
        if len(structure) > MAX_PRIMITIVE_SITES:
            return native_id, n_sites, formula, "FAIL:TOO_LARGE_PRIM"
        return native_id, n_sites, formula, _hasher.get_material_hash(structure)
    except Exception as exc:  # noqa: BLE001
        return native_id, 0, "", "FAIL:" + repr(exc)[:120]


def run(structs_path: Path, out_path: Path, nproc: int, chunk: int) -> dict:
    from multiprocessing import Pool

    done = failed = 0
    started = time.time()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
    with gzip.open(structs_path, "rt", encoding="utf-8") as source, \
            Pool(nproc, initializer=_init) as pool, \
            gzip.open(tmp_path, "wt", encoding="utf-8") as out:
        out.write("native_id\tn_sites\tformula\tbawl_hash\n")
        for native_id, n_sites, formula, hashed in pool.imap_unordered(
            _work, source, chunksize=chunk
        ):
            out.write(f"{native_id}\t{n_sites}\t{formula}\t{hashed}\n")
            done += 1
            failed += hashed.startswith("FAIL:")
            if done % 20_000 == 0:
                elapsed = time.time() - started
                print(
                    f"{done:,} hashed, {failed:,} failed, "
                    f"{done / elapsed:,.0f}/s, {elapsed / 60:.1f} min",
                    flush=True,
                )
    tmp_path.replace(out_path)
    elapsed = time.time() - started
    print(
        f"HASH DONE {done:,} rows ({failed:,} failed) in {elapsed / 60:.1f} min",
        flush=True,
    )
    return {"hashed": done, "hash_failed": failed, "hash_minutes": round(elapsed / 60, 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("structs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--nproc", type=int, default=28)
    parser.add_argument("--chunk", type=int, default=32)
    args = parser.parse_args()
    run(args.structs, args.out, args.nproc, args.chunk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
