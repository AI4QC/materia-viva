#!/usr/bin/env python3
"""Turn the CIF blob into graph-ready structure arrays.

Two CIF populations live in ``structures.blob`` and they need different
treatment -- this is the whole reason the script is not three lines of
``CifParser``:

* **candidate** (13.19M, ~97% of the pool) are pymatgen-written, P1, fully
  ordered, one fixed column layout.  A hand-rolled parser reads them ~100x
  faster than ``CifParser`` and is exact for this layout.
* **experimental** (357K) are the *original* upstream CIFs: real symmetry
  operations that must be expanded, ASE-written ``data_image0`` files, and
  -- in roughly one in eight -- **partial site occupancies**.  A disordered
  site has no single atomic number, so it cannot be encoded as a graph node
  without a choice.  Those go through ``CifParser`` and are then handled per
  ``--disorder``.

Output: sharded ``.npz``, one shard per ``--shard-size`` structures, holding
ragged arrays concatenated with an offset index (``atom_ptr``), which is how
every GNN dataloader wants them anyway.

    lattice        (S, 3, 3)   float32, row vectors, Angstrom
    atom_ptr       (S + 1,)    int64, site slice bounds into the arrays below
    frac_coords    (A, 3)      float32
    atomic_numbers (A,)        int8 -> stored int16, Z <= 118
    material_pk    (S,)        int64  join key back to targets/*.parquet

Usage
-----
    # everything, 30 workers
    python scripts/ml/export_structures.py --out data/ml/export/structures \
        --workers 30

    # only the materials that carry a given property
    python scripts/ml/export_structures.py --out /scratch/bg \
        --pks-from data/ml/export/targets/band_gap.parquet --workers 16
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sqlite3
import sys
import time
import zlib
from pathlib import Path

import numpy as np

_ELEMENT_Z: dict[str, int] = {}


def _load_element_table() -> None:
    from pymatgen.core.periodic_table import Element

    for el in Element:
        _ELEMENT_Z[el.symbol] = el.Z


class FastCifError(ValueError):
    """Raised when the fixed pymatgen layout does not apply; caller falls back."""


def cif_float(token: str) -> float:
    """``"100.6621(23)"`` -> 100.6621.  Upstream CIFs carry standard
    uncertainties in parentheses; pymatgen-written ones never do."""

    return float(token.split("(")[0])


def parse_pymatgen_p1(cif: str):
    """Parse a pymatgen-written P1 CIF without pymatgen.

    Returns (lattice 3x3 float64, frac Nx3 float64, Z list[int]).
    Raises FastCifError on anything that is not the expected layout, so the
    caller can retry with the real parser rather than emit a wrong structure.

    Verified against ``CifParser`` over a random sample: identical lattices and
    interatomic distances to ~1e-8 A.  The one systematic difference is that
    ``CifParser`` snaps coordinates written as repeating decimals (0.6667133)
    back to the exact fraction (2/3); this parser keeps the literal file value.
    The gap is <1e-4 in fractional units and does not favour either result.
    """

    a = b = c = alpha = beta = gamma = None
    header: list[str] = []
    sites: list[list[str]] = []
    n_symops = 0
    # Which loop are we inside: None, "symop" or "atom".  Counting the symmetry
    # operations is the point of the state machine -- a CIF that lists four
    # operations also contains 'x, y, z', so testing for that string alone
    # would silently accept an asymmetric unit as if it were the full cell and
    # emit a structure with a quarter of its atoms.
    loop: str | None = None
    for line in cif.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("loop_"):
            loop = None
            continue
        if stripped.startswith("_"):
            tag = stripped.split()[0]
            if tag in ("_symmetry_equiv_pos_as_xyz", "_space_group_symop_operation_xyz"):
                loop = "symop"
            elif tag.startswith("_atom_site_"):
                if loop != "atom":
                    loop = "atom"
                header.append(tag)
            elif tag.startswith(("_symmetry_equiv_pos", "_space_group_symop")):
                loop = "symop"
            else:
                if loop is not None and not tag.startswith("_atom_site_"):
                    loop = None
                parts = stripped.split()
                if len(parts) >= 2:
                    if tag == "_cell_length_a":
                        a = cif_float(parts[1])
                    elif tag == "_cell_length_b":
                        b = cif_float(parts[1])
                    elif tag == "_cell_length_c":
                        c = cif_float(parts[1])
                    elif tag == "_cell_angle_alpha":
                        alpha = cif_float(parts[1])
                    elif tag == "_cell_angle_beta":
                        beta = cif_float(parts[1])
                    elif tag == "_cell_angle_gamma":
                        gamma = cif_float(parts[1])
            continue
        if loop == "symop":
            n_symops += 1
        elif loop == "atom":
            parts = stripped.split()
            if len(parts) < len(header):
                raise FastCifError("short atom row")
            sites.append(parts)

    if None in (a, b, c, alpha, beta, gamma) or not sites or not header:
        raise FastCifError("missing cell or sites")
    if n_symops > 1:
        raise FastCifError(f"{n_symops} symmetry operations; needs expansion")
    try:
        i_sym = header.index("_atom_site_type_symbol")
        i_x = header.index("_atom_site_fract_x")
        i_y = header.index("_atom_site_fract_y")
        i_z = header.index("_atom_site_fract_z")
    except ValueError as exc:
        raise FastCifError("unexpected atom_site columns") from exc
    i_occ = header.index("_atom_site_occupancy") if "_atom_site_occupancy" in header else None

    numbers: list[int] = []
    coords: list[tuple[float, float, float]] = []
    seen_labels: set[str] = set()
    i_label = header.index("_atom_site_label") if "_atom_site_label" in header else None
    for parts in sites:
        if i_occ is not None and abs(cif_float(parts[i_occ]) - 1.0) > 1e-6:
            raise FastCifError("partial occupancy")
        if i_label is not None:
            label = parts[i_label]
            if label in seen_labels:
                raise FastCifError("repeated site label; not a plain P1 listing")
            seen_labels.add(label)
        symbol = "".join(ch for ch in parts[i_sym] if ch.isalpha())
        z = _ELEMENT_Z.get(symbol)
        if z is None:
            raise FastCifError(f"unknown element {symbol!r}")
        numbers.append(z)
        coords.append((cif_float(parts[i_x]), cif_float(parts[i_y]), cif_float(parts[i_z])))

    alpha_r, beta_r, gamma_r = np.radians([alpha, beta, gamma])
    cos_a, cos_b, cos_g = np.cos([alpha_r, beta_r, gamma_r])
    sin_g = np.sin(gamma_r)
    cx = c * cos_b
    cy = c * (cos_a - cos_b * cos_g) / sin_g
    cz_sq = c * c - cx * cx - cy * cy
    if cz_sq <= 0:
        raise FastCifError("degenerate cell")
    lattice = np.array(
        [[a, 0.0, 0.0], [b * cos_g, b * sin_g, 0.0], [cx, cy, np.sqrt(cz_sq)]],
        dtype=np.float64,
    )
    return lattice, np.asarray(coords, dtype=np.float64), numbers


def parse_with_pymatgen(cif: str, disorder: str):
    from pymatgen.io.cif import CifParser

    parser = CifParser.from_str(cif)
    structures = parser.parse_structures(primitive=False)
    if not structures:
        raise ValueError("no structure parsed")
    structure = structures[0]
    if not structure.is_ordered:
        if disorder == "skip":
            raise ValueError("disordered")
        # 'majority': keep the highest-occupancy species per site.  This is a
        # lossy choice and is recorded in the shard's `disordered` mask so a
        # consumer can drop those rows instead of trusting them.
        structure = structure.copy()
        species = []
        for site in structure:
            species.append(max(site.species.items(), key=lambda kv: kv[1])[0])
        structure = type(structure)(
            structure.lattice, species, structure.frac_coords, coords_are_cartesian=False
        )
    return (
        np.asarray(structure.lattice.matrix, dtype=np.float64),
        np.asarray(structure.frac_coords, dtype=np.float64),
        [int(sp.Z) for sp in structure.species],
        not structures[0].is_ordered,
    )


def worker(task) -> dict:
    (blob_path, rows, out_path, disorder, max_atoms) = task
    if not _ELEMENT_Z:
        _load_element_table()

    lattices, ptr, coords, numbers, pks, disordered = [], [0], [], [], [], []
    failures: list[tuple[int, str]] = []
    n_fast = n_slow = 0
    with open(blob_path, "rb") as handle:
        for pk, offset, length in rows:
            try:
                handle.seek(offset)
                cif = zlib.decompress(handle.read(length)).decode("utf-8")
            except Exception as exc:  # corrupt slice -- record, never abort the shard
                failures.append((pk, f"blob: {exc}"))
                continue
            is_dis = False
            try:
                lat, frac, zs = parse_pymatgen_p1(cif)
                n_fast += 1
            except Exception:
                # Every fast-path miss -- unexpected layout, real symmetry,
                # partial occupancy, a malformed token -- falls through to the
                # reference parser.  A structure is only ever dropped when
                # pymatgen itself cannot read it.
                try:
                    lat, frac, zs, is_dis = parse_with_pymatgen(cif, disorder)
                    n_slow += 1
                except Exception as exc:
                    failures.append((pk, f"parse: {exc}"))
                    continue
            if max_atoms and len(zs) > max_atoms:
                failures.append((pk, f"too many atoms: {len(zs)}"))
                continue
            lattices.append(lat)
            coords.append(frac)
            numbers.extend(zs)
            ptr.append(ptr[-1] + len(zs))
            pks.append(pk)
            disordered.append(is_dis)

    if pks:
        np.savez_compressed(
            out_path,
            lattice=np.asarray(lattices, dtype=np.float32),
            atom_ptr=np.asarray(ptr, dtype=np.int64),
            frac_coords=(
                np.concatenate(coords).astype(np.float32)
                if coords
                else np.zeros((0, 3), np.float32)
            ),
            atomic_numbers=np.asarray(numbers, dtype=np.int16),
            material_pk=np.asarray(pks, dtype=np.int64),
            disordered=np.asarray(disordered, dtype=bool),
        )
    return {
        "shard": Path(out_path).name,
        "n_structures": len(pks),
        "n_fast": n_fast,
        "n_pymatgen": n_slow,
        "n_failed": len(failures),
        "failures": failures[:50],
    }


def load_pks(path: Path) -> set[int]:
    import pyarrow.parquet as pq

    if path.suffix == ".parquet":
        table = pq.read_table(path, columns=["material_pk"])
        return set(table.column("material_pk").to_pylist())
    return {int(line) for line in path.read_text().split() if line.strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=Path("data/index/materials.sqlite"))
    ap.add_argument("--blob", type=Path, default=Path("data/index/structures.blob"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pks-from", type=Path, action="append",
                    help="可重复。每次调用都要扫全部 13.5M 行 materials，"
                         "所以多个任务合并成一次调用，而不是循环调用")
    ap.add_argument("--dataset", choices=["experimental", "candidate"])
    ap.add_argument("--shard-size", type=int, default=100_000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-atoms", type=int, default=0, help="0 = no cap")
    ap.add_argument(
        "--disorder",
        choices=["skip", "majority"],
        default="skip",
        help="partial-occupancy sites: drop the structure, or keep the "
        "highest-occupancy species (recorded in the shard's `disordered` mask)",
    )
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    sql = "SELECT pk, blob_offset, blob_length FROM materials"
    params: list = []
    if args.dataset:
        sql += " WHERE dataset = ?"
        params.append(args.dataset)
    sql += " ORDER BY blob_offset"  # sequential blob reads, not random seeks
    rows = con.execute(sql, params).fetchall()

    if args.pks_from:
        keep: set[int] = set()
        for source in args.pks_from:
            keep |= load_pks(source)
        rows = [r for r in rows if r[0] in keep]
    print(f"{len(rows):,} structures to export", file=sys.stderr)

    shards = [
        (
            str(args.blob),
            rows[i : i + args.shard_size],
            str(args.out / f"shard-{i // args.shard_size:05d}.npz"),
            args.disorder,
            args.max_atoms,
        )
        for i in range(0, len(rows), args.shard_size)
    ]
    t0 = time.time()
    reports = []
    with mp.Pool(args.workers) as pool:
        for i, report in enumerate(pool.imap_unordered(worker, shards), 1):
            reports.append(report)
            done = sum(r["n_structures"] for r in reports)
            print(
                f"  {i}/{len(shards)} shards, {done:,} structures, "
                f"{time.time() - t0:.0f}s",
                end="\r",
                file=sys.stderr,
                flush=True,
            )
    print(file=sys.stderr)

    summary = {
        "n_requested": len(rows),
        "n_structures": sum(r["n_structures"] for r in reports),
        "n_fast_path": sum(r["n_fast"] for r in reports),
        "n_pymatgen_path": sum(r["n_pymatgen"] for r in reports),
        "n_failed": sum(r["n_failed"] for r in reports),
        "disorder_policy": args.disorder,
        "seconds": round(time.time() - t0, 1),
        "shards": sorted(reports, key=lambda r: r["shard"]),
    }
    (args.out / "STRUCTURES_MANIFEST.json").write_text(json.dumps(summary, indent=1))
    print(
        f"{summary['n_structures']:,} exported, {summary['n_failed']:,} failed "
        f"-> {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
