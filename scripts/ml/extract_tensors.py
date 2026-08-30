#!/usr/bin/env python3
"""Extract MATRIX (tensor) properties, which the index does not carry.

Why a separate script
---------------------
``material_properties`` is a scalar store by construction: ``value_num`` is one
float.  Every adapter therefore reduced tensors on the way in -- a 6x6 elastic
stiffness became ``bulk_modulus_vrh``, a 3x3 dielectric tensor became its
trace/3, a full set of Born effective charges became one maximum component.
The tensors themselves were never written to the index, so training a tensor
model means going back to the raw archives under ``data/raw/acquired/``.

What is recoverable from data already on disk
---------------------------------------------
``jarvis``    elastic stiffness 6x6 (~34.5K), diagonal dielectric from
              epsx/epsy/epsz (OptB88vdW ~60K, mBJ ~19.8K), per-site electric
              field gradient tensors (~13.8K), Gamma-point phonon modes (~13.9K)
``phonondb``  high-frequency dielectric tensor 3x3 and per-atom Born effective
              charge tensors, PBEsol DFPT (~4.9K each)

What needs an API re-pull (``plan`` prints the exact queries)
-------------------------------------------------------------
The Materials Project and AFLOW harvests requested scalar field lists only, so
their tensors are not in ``data/raw/`` at all.  They are small pulls.

Output: one Parquet per tensor family, tensors flattened row-major with the
shape recorded in the file metadata, joined to ``material_pk`` through
``material_source_refs`` so they line up with ``targets/*.parquet``.

Usage
-----
    python scripts/ml/extract_tensors.py jarvis   --out data/ml/export/tensors
    python scripts/ml/extract_tensors.py phonondb --out data/ml/export/tensors --workers 16
    python scripts/ml/extract_tensors.py plan
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACQUIRED = PROJECT_ROOT / "data" / "raw" / "acquired"


def source_ref_map(db: Path, source_key: str) -> dict[str, list[int]]:
    """native_id -> [material_pk].  One native id can match several pool
    entries (the same JVASP id appearing as both a bulk and a 2D record), so
    the value is a list and the caller decides whether to fan out or drop."""

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        """
        SELECT r.native_id, r.material_pk
        FROM material_source_refs r JOIN source_defs s ON s.id = r.source_id
        WHERE s.key = ?
        """,
        (source_key,),
    )
    out: dict[str, list[int]] = {}
    for native, pk in rows:
        out.setdefault(native, []).append(int(pk))
    con.close()
    return out


def write_tensor_parquet(
    path: Path,
    records: list[dict],
    shape: tuple[int, ...],
    *,
    method: str,
    source: str,
    per_site: bool = False,
    labels: bool = False,
) -> int:
    """Flatten tensors row-major into one float32 list column.

    ``shape`` is stored in the Parquet key-value metadata rather than baked
    into the column type, so a per-site tensor (variable first axis) and a
    fixed 6x6 use the same reader.
    """

    if not records:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = {
        "material_pk": pa.array([r["material_pk"] for r in records], pa.int64()),
        "native_id": pa.array([r["native_id"] for r in records], pa.string()),
        "n_units": pa.array([r.get("n_units", 1) for r in records], pa.int32()),
        "tensor": pa.array(
            [np.asarray(r["tensor"], dtype=np.float32).ravel().tolist() for r in records],
            pa.list_(pa.float32()),
        ),
    }
    if labels:
        # which site each per-site tensor belongs to; without it a Wyckoff-site
        # tensor list cannot be mapped back onto the structure's atoms
        columns["labels"] = pa.array(
            [r.get("labels", []) for r in records], pa.list_(pa.string())
        )
    table = pa.table(
        columns,
        metadata={
            b"tensor_shape": json.dumps(list(shape)).encode(),
            b"per_site": b"1" if per_site else b"0",
            b"method": method.encode(),
            b"source": source.encode(),
        },
    )
    pq.write_table(table, path, compression="zstd")
    return len(records)


# --------------------------------------------------------------------------
# JARVIS-DFT
# --------------------------------------------------------------------------


def is_na(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in ("na", ""))


def cmd_jarvis(args) -> int:
    zip_path = next(iter(sorted((ACQUIRED / "jarvis-dft").glob("jdft_3d-*.json.zip"))), None)
    if zip_path is None:
        print("jarvis-dft archive not found", file=sys.stderr)
        return 1
    refs = source_ref_map(args.db, "jarvis-dft")
    print(f"{len(refs):,} jarvis-dft native ids in the index", file=sys.stderr)

    with zipfile.ZipFile(zip_path) as bundle:
        with bundle.open(bundle.namelist()[0]) as handle:
            records = json.load(handle)
    print(f"{len(records):,} JARVIS records", file=sys.stderr)

    elastic, eps_opt, eps_mbj, efg, modes = [], [], [], [], []
    unmatched = 0
    for rec in records:
        jid = rec.get("jid")
        pks = refs.get(jid)
        if not pks:
            unmatched += 1
            continue
        pk = pks[0]  # the pool entry the id resolved to; extras are duplicates

        tensor = rec.get("elastic_tensor")
        if isinstance(tensor, list) and len(tensor) == 6 and isinstance(tensor[0], list):
            elastic.append({"material_pk": pk, "native_id": jid, "tensor": tensor})

        # JARVIS publishes only the diagonal of the dielectric tensor; the
        # off-diagonal terms are not in dft_3d, so this is a diag(3) target,
        # not a full 3x3.  Kept separate from a true 3x3 for that reason.
        for key_set, sink in ((("epsx", "epsy", "epsz"), eps_opt),
                              (("mepsx", "mepsy", "mepsz"), eps_mbj)):
            values = [rec.get(k) for k in key_set]
            if not any(is_na(v) for v in values):
                sink.append({"material_pk": pk, "native_id": jid,
                             "tensor": [float(v) for v in values]})

        sites = rec.get("efg")
        if isinstance(sites, list) and sites:
            # JARVIS rows are [element, wyckoff_letter, xx, xy, xz, yx, ..., zz]:
            # one full 3x3 EFG tensor per SYMMETRY-DISTINCT site, not per atom.
            # The element/Wyckoff pair is kept so the tensors can be mapped back
            # onto the structure; dropping it would make the block unusable.
            values, site_labels = [], []
            for row in sites:
                if not (isinstance(row, list) and len(row) >= 11):
                    values = []
                    break
                try:
                    values.extend(float(v) for v in row[2:11])
                except (TypeError, ValueError):
                    values = []
                    break
                site_labels.append(f"{row[0]}:{row[1]}")
            if values:
                efg.append({"material_pk": pk, "native_id": jid, "tensor": values,
                            "n_units": len(sites), "labels": site_labels})

        freqs = rec.get("modes")
        if isinstance(freqs, list) and freqs:
            modes.append({"material_pk": pk, "native_id": jid, "tensor": freqs,
                          "n_units": len(freqs)})

    out = args.out
    counts = {
        "elastic_tensor_6x6": write_tensor_parquet(
            out / "jarvis_elastic_tensor.parquet", elastic, (6, 6),
            method="OptB88vdW finite-difference", source="jarvis-dft"),
        "dielectric_diag_optb88vdw": write_tensor_parquet(
            out / "jarvis_dielectric_diag_optb88vdw.parquet", eps_opt, (3,),
            method="OptB88vdW", source="jarvis-dft"),
        "dielectric_diag_mbj": write_tensor_parquet(
            out / "jarvis_dielectric_diag_mbj.parquet", eps_mbj, (3,),
            method="TBmBJ", source="jarvis-dft"),
        "efg_per_wyckoff_site_3x3": write_tensor_parquet(
            out / "jarvis_efg.parquet", efg, (-1, 3, 3),
            method="OptB88vdW", source="jarvis-dft", per_site=True, labels=True),
        "gamma_phonon_modes": write_tensor_parquet(
            out / "jarvis_phonon_modes.parquet", modes, (-1,),
            method="DFPT Gamma-point", source="jarvis-dft", per_site=True),
    }
    counts["unmatched_records"] = unmatched
    (out / "jarvis_tensors_report.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))
    return 0


# --------------------------------------------------------------------------
# PhononDB (NIMS MDR) -- dielectric tensor + Born effective charges
# --------------------------------------------------------------------------


def _phonondb_worker(path_str: str):
    # the adapter imports `scripts.properties.base`, so the project root -- not
    # the adapters directory -- has to be on the path
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.properties.adapters.phonondb import (  # type: ignore
        _VECTOR,
        _read_header,
        _sections,
    )

    path = Path(path_str)
    try:
        text = _read_header(path)
    except Exception:
        return None
    if not text:
        return None
    sections = _sections(text)

    result = {"native_id": f"phonondb-{path.stem}"}
    dielectric = sections.get("dielectric_constant")
    if dielectric:
        rows = _VECTOR.findall(dielectric)[:3]
        if len(rows) == 3:
            try:
                result["dielectric"] = [[float(v) for v in row] for row in rows]
            except ValueError:
                pass
    born = sections.get("born_effective_charge")
    if born:
        rows = _VECTOR.findall(born)
        if rows and len(rows) % 3 == 0:
            try:
                values = [[float(v) for v in row] for row in rows]
            except ValueError:
                values = None
            if values:
                result["born"] = values
                result["n_atoms"] = len(values) // 3
    return result if len(result) > 1 else None


def cmd_phonondb(args) -> int:
    archives = sorted((ACQUIRED / "phonondb" / "archives").glob("*.zip"))
    if not archives:
        print("phonondb archives not found", file=sys.stderr)
        return 1
    refs = source_ref_map(args.db, "phonondb")
    print(f"{len(archives):,} archives, {len(refs):,} indexed refs", file=sys.stderr)

    dielectric, born = [], []
    t0 = time.time()
    with mp.Pool(args.workers) as pool:
        for i, result in enumerate(
            pool.imap_unordered(_phonondb_worker, [str(p) for p in archives], chunksize=32), 1
        ):
            if i % 500 == 0:
                print(f"  {i}/{len(archives)} {time.time() - t0:.0f}s",
                      end="\r", file=sys.stderr, flush=True)
            if not result:
                continue
            pks = refs.get(result["native_id"])
            if not pks:
                continue
            pk = pks[0]
            if "dielectric" in result:
                dielectric.append({"material_pk": pk, "native_id": result["native_id"],
                                   "tensor": result["dielectric"]})
            if "born" in result:
                born.append({"material_pk": pk, "native_id": result["native_id"],
                             "tensor": result["born"], "n_units": result["n_atoms"]})
    print(file=sys.stderr)

    counts = {
        "dielectric_tensor_3x3": write_tensor_parquet(
            args.out / "phonondb_dielectric_tensor.parquet", dielectric, (3, 3),
            method="PBEsol DFPT (PhononDB)", source="phonondb"),
        "born_effective_charges_Nx3x3": write_tensor_parquet(
            args.out / "phonondb_born_charges.parquet", born, (-1, 3, 3),
            method="PBEsol DFPT (PhononDB)", source="phonondb", per_site=True),
        "seconds": round(time.time() - t0, 1),
    }
    (args.out / "phonondb_tensors_report.json").write_text(json.dumps(counts, indent=1))
    print(json.dumps(counts, indent=1))
    return 0


# --------------------------------------------------------------------------
# What still has to be re-pulled
# --------------------------------------------------------------------------

REFETCH_PLAN = {
    "materials-project/elasticity": {
        "why": "the 2026-08-19 harvest requested scalar moduli only; "
               "elastic_tensor / compliance_tensor were never downloaded",
        "docs": 13283,
        "endpoint": "https://api.materialsproject.org/materials/elasticity/",
        "add_fields": ["elastic_tensor", "compliance_tensor",
                       "elastic_tensor_original", "structure"],
        "tensor": "6x6 stiffness, GPa",
        "estimate": "~15 min, <1 GB",
    },
    "materials-project/dielectric": {
        "why": "no dielectric harvest exists under data/raw/acquired/materials-project/",
        "docs": "~7500",
        "endpoint": "https://api.materialsproject.org/materials/dielectric/",
        "add_fields": ["material_id", "total", "ionic", "electronic", "e_total",
                       "e_ionic", "e_electronic", "n"],
        "tensor": "3x3 total / ionic / electronic",
        "estimate": "~10 min",
    },
    "materials-project/piezoelectric": {
        "why": "harvest requested e_ij_max and max_direction only",
        "docs": 3322,
        "endpoint": "https://api.materialsproject.org/materials/piezoelectric/",
        "add_fields": ["total", "ionic", "electronic", "strain_for_max"],
        "tensor": "3x6 piezoelectric, C/m^2",
        "estimate": "~5 min",
    },
    "materials-project/phonon": {
        "why": "phonon manifest has no field list; Born charges and the DFPT "
               "dielectric tensor are not in the local pages",
        "endpoint": "https://api.materialsproject.org/materials/phonon/",
        "add_fields": ["ph_bs", "ph_dos"],
        "tensor": "phonon band structure / DOS",
        "estimate": "large; fetch only if phonon curves are wanted beyond the "
                    "27.6K already in material_curves",
    },
    "aflow/ael": {
        "why": "the AFLUX AEL/AGL pull requested VRH scalars only",
        "docs": "5664 resolved auids, ~10^5 available",
        "endpoint": "AFLUX: ael_stiffness_tensor,ael_compliance_tensor",
        "tensor": "6x6 stiffness, GPa",
        "estimate": "AFLUX paging is slow; budget hours",
    },
}


def cmd_plan(args) -> int:
    print(json.dumps(REFETCH_PLAN, indent=1, ensure_ascii=False))
    return 0


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=Path("data/index/materials.sqlite"))
    common.add_argument("--out", type=Path, default=Path("data/ml/export/tensors"))
    common.add_argument("--workers", type=int, default=8)

    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0], parents=[common]
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    # options are repeated on every subparser so they may be written on either
    # side of the subcommand
    sub.add_parser("jarvis", parents=[common]).set_defaults(func=cmd_jarvis)
    sub.add_parser("phonondb", parents=[common]).set_defaults(func=cmd_phonondb)
    sub.add_parser("plan", parents=[common]).set_defaults(func=cmd_plan)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
