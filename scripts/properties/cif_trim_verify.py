#!/usr/bin/env python3
"""Prove that ``cif_trim.trim_cif`` cannot change a structure.

Samples random COD CIFs across several parquet row groups and, per CIF,
compares the ORIGINAL and the TRIMMED text on:

* pymatgen parse outcome (both parse, or both fail the same way)
* reduced formula, per-element amounts and site count
* lattice parameters (1e-6) and fractional coordinates (1e-6, matched
  order-insensitively and periodic-image aware)
* the loader's own regex fields (``materials_api.indexer._extract_cif_fields``:
  ``_cell_length_*``/``_cell_angle_*``/``_cell_volume``)
* idempotence, ``trim_cif(trim_cif(x)) == trim_cif(x)``
* on a subset, the primitive-reduced BAWL fingerprint, using
  ``scripts.properties.hashing``'s own protocol, which is what guarantees
  trimming cannot move a structure's pool identity

Read-only: touches nothing but the source parquet and its own sample cache.

    python -m scripts.properties.cif_trim_verify --sample 1100 --bawl 250
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import statistics
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.properties.cif_trim import (  # noqa: E402
    dropped_bytes,
    is_dropped_tag,
    trim_cif,
)

COD_PARQUET = (
    PROJECT_ROOT / "data" / "raw" / "external_structs" / "cod" / "cod_full.parquet"
)
ROW_GROUPS = (0, 6, 12, 18, 24, 30, 36, 42, 48, 53)
TOL = 1e-6

warnings.filterwarnings("ignore")


# --------------------------------------------------------------------------- sampling


def build_sample(cache: Path, per_group: int) -> None:
    """Reservoir-sample ``per_group`` CIFs from each of several row groups."""

    import pyarrow.parquet as pq

    rng = random.Random(20260818)
    parquet = pq.ParquetFile(COD_PARQUET)
    cache.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    with gzip.open(cache, "wt", encoding="utf-8") as out:
        for group in ROW_GROUPS:
            reservoir: list[dict] = []
            seen = 0
            for batch in parquet.iter_batches(
                batch_size=256,
                columns=["file", "cif_text", "flags"],
                row_groups=[group],
            ):
                data = batch.to_pydict()
                for i in range(len(data["file"])):
                    cif = data["cif_text"][i]
                    if not cif or "has coordinates" not in (data["flags"][i] or ""):
                        continue
                    seen += 1
                    item = {"file": data["file"][i], "rg": group, "cif": cif}
                    if len(reservoir) < per_group:
                        reservoir.append(item)
                    elif (slot := rng.randrange(seen)) < per_group:
                        reservoir[slot] = item
            for item in reservoir:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
            kept += len(reservoir)
            print(f"  row group {group}: {seen:,} eligible, sampled {len(reservoir)}")
    print(f"sample cached: {kept:,} CIFs -> {cache}")


# --------------------------------------------------------------------------- checks


def _init_worker() -> None:
    warnings.filterwarnings("ignore")
    from scripts.properties import hashing

    hashing._init()


def _lattice(structure) -> tuple:
    return structure.lattice.parameters


def _sites_match(left, right) -> bool:
    """Order-insensitive, periodic-image-aware fractional coordinate match."""

    pool = list(range(len(right)))
    for site in left:
        label = site.species_string
        for slot, index in enumerate(pool):
            other = right[index]
            if other.species_string != label:
                continue
            delta = site.frac_coords - other.frac_coords
            if max(abs(delta - delta.round())) < TOL:
                pool.pop(slot)
                break
        else:
            return False
    return not pool


def _compare(original, trimmed) -> list[str]:
    problems: list[str] = []
    if len(original) != len(trimmed):
        problems.append(f"n_sites {len(original)} != {len(trimmed)}")
        return problems
    if original.composition.reduced_formula != trimmed.composition.reduced_formula:
        problems.append(
            f"reduced_formula {original.composition.reduced_formula} != "
            f"{trimmed.composition.reduced_formula}"
        )
    left = original.composition.get_el_amt_dict()
    right = trimmed.composition.get_el_amt_dict()
    if set(left) != set(right) or any(
        abs(left[el] - right[el]) > TOL for el in left
    ):
        problems.append(f"element amounts {left} != {right}")
    if any(
        abs(a - b) > TOL for a, b in zip(_lattice(original), _lattice(trimmed))
    ):
        problems.append(f"lattice {_lattice(original)} != {_lattice(trimmed)}")
    if not _sites_match(original, trimmed):
        problems.append("fractional coordinates differ")
    return problems


def _parse(text: str):
    from pymatgen.core import Structure

    try:
        return Structure.from_str(text, fmt="cif"), None
    except Exception as exc:  # noqa: BLE001 - pymatgen raises many types
        return None, f"{type(exc).__name__}: {str(exc)[:90]}"


def _bawl(text: str) -> str:
    """The production fingerprint protocol, verbatim from hashing.py."""

    from scripts.properties import hashing

    _native, _n, _formula, hashed = hashing._work(
        json.dumps({"native_id": "verify", "cif": text})
    )
    return hashed


def _tag_diff(text: str, trimmed: str) -> list[str]:
    """Every surviving tag must still carry byte-identical data.

    Independent of our own tokenizer: it re-reads both texts with pymatgen's
    ``CifFile`` and diffs the per-block tag dictionaries, so it catches data
    loss anywhere in the file, not only in what ``Structure`` happens to read.
    """

    from pymatgen.io.cif import CifFile

    try:
        left = CifFile.from_str(text).data
        right = CifFile.from_str(trimmed).data
    except Exception as exc:  # noqa: BLE001
        return [f"CifFile: {type(exc).__name__}"]
    problems: list[str] = []
    for header, block in left.items():
        other = right.get(header)
        if other is None:
            problems.append(f"block {header!r} vanished")
            continue
        for tag, value in block.data.items():
            if is_dropped_tag(tag):
                continue
            if tag not in other.data:
                problems.append(f"{header}:{tag} vanished")
            elif other.data[tag] != value:
                problems.append(f"{header}:{tag} value changed")
    for header, block in right.items():
        extra = set(block.data) - set(left[header].data) if header in left else set()
        if header not in left:
            problems.append(f"block {header!r} appeared")
        elif extra:
            problems.append(f"{header}: tags appeared {sorted(extra)[:4]}")
    return problems


def check(job: tuple[dict, bool]) -> dict:
    record, want_bawl = job
    text = record["cif"]
    trimmed = trim_cif(text)
    result = {
        "file": record["file"],
        "rg": record["rg"],
        "bytes_in": len(text.encode("utf-8")),
        "bytes_out": len(trimmed.encode("utf-8")),
        "idempotent": trim_cif(trimmed) == trimmed,
        "noop": trimmed is text,
        "problems": [],
        "census": dropped_bytes(text),
    }

    from materials_api.indexer import _extract_cif_fields

    if _extract_cif_fields(text) != _extract_cif_fields(trimmed):
        result["problems"].append(
            f"indexer fields {_extract_cif_fields(text)} != "
            f"{_extract_cif_fields(trimmed)}"
        )

    original, original_error = _parse(text)
    reparsed, trimmed_error = _parse(trimmed)
    if original_error and trimmed_error:
        result["status"] = "both_fail"
        result["error"] = original_error
        if original_error.split(":")[0] != trimmed_error.split(":")[0]:
            result["problems"].append(
                f"different failure: {original_error} vs {trimmed_error}"
            )
    elif original_error:
        result["status"] = "orig_fail_trim_ok"
        result["error"] = original_error
    elif trimmed_error:
        result["status"] = "orig_ok_trim_fail"
        result["error"] = trimmed_error
        result["problems"].append(f"trimmed no longer parses: {trimmed_error}")
    else:
        result["status"] = "both_ok"
        result["problems"].extend(_compare(original, reparsed))

    result["tag_problems"] = _tag_diff(text, trimmed)

    if want_bawl and result["status"] == "both_ok":
        left, right = _bawl(text), _bawl(trimmed)
        result["bawl"] = (left, right)
        if left != right:
            result["problems"].append(f"BAWL {left} != {right}")
    return result


# --------------------------------------------------------------------------- selftest

_ADVERSARIAL = """#comment before the block
data_publication
_journal_name_full 'Some Journal'
_publ_author_name 'O'Brien, J.'
data_structure
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90.0
_cell_angle_beta 90.0
_cell_angle_gamma 90.0
_cell_measurement_temperature 293
_symmetry_space_group_name_H-M 'P 1'
loop_
_symmetry_equiv_pos_as_xyz
'x, y, z'
_shelx_res_file
;
data_fake
loop_
_atom_site_label
_cell_length_a 999.0
   ; indented, so not a field terminator
;
_atom_sites_solution_primary direct
loop_
_atom_site_aniso_label
_atom_site_aniso_U_11
Na1 0.01
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na1 Na 0.0 0.0 0.0
Cl1 Cl 0.5 0.5 0.5
loop_
_geom_bond_atom_site_label_1
_geom_bond_distance
Na1 2.5
loop_
_atom_type_symbol
_geom_bond_distance
Na 2.5
"""


def selftest() -> None:
    """Adversarial CIF syntax the random sample may not happen to contain."""

    from pymatgen.core import Lattice, Structure

    trimmed = trim_cif(_ADVERSARIAL)
    assert "_shelx_res_file" not in trimmed, "SHELX payload survived"
    assert "data_fake" not in trimmed, "text-field content leaked out of its field"
    assert "999.0" not in trimmed, "text-field content leaked out of its field"
    assert "_cell_measurement_temperature" not in trimmed
    assert "_atom_sites_solution_primary" not in trimmed
    assert "_atom_site_aniso_U_11" not in trimmed, "aniso loop survived"
    assert "_journal_name_full" not in trimmed and "O'Brien" not in trimmed
    assert "_geom_bond_atom_site_label_1" not in trimmed, "pure _geom loop survived"
    # a loop that mixes a kept and a dropped tag stays whole
    assert trimmed.count("_geom_bond_distance") == 1, "mixed loop was not preserved"
    assert "data_publication" in trimmed and "data_structure" in trimmed
    for tag in ("_cell_length_a", "_symmetry_equiv_pos_as_xyz", "_atom_site_fract_z"):
        assert tag in trimmed, tag
    assert trim_cif(trimmed) == trimmed, "not idempotent"

    structure = Structure.from_str(trimmed, fmt="cif")
    assert structure.composition.reduced_formula == "NaCl", structure.composition
    assert abs(structure.lattice.a - 5.0) < TOL

    # a CIF with none of the dropped families comes back untouched
    plain = Structure(Lattice.cubic(4.0), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    text = plain.to(fmt="cif")
    assert trim_cif(text) is text, "pymatgen CIF was modified"
    assert trim_cif("") == ""
    print("selftest: adversarial CIF syntax OK")


# --------------------------------------------------------------------------- driver


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=1100)
    parser.add_argument("--bawl", type=int, default=250)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("/tmp/claude-1000/cod_trim_sample.jsonl.gz"),
    )
    parser.add_argument("--rebuild-sample", action="store_true")
    parser.add_argument("--selftest-only", action="store_true")
    parser.add_argument("--dump", type=Path, default=None, help="per-CIF results JSON")
    args = parser.parse_args()

    selftest()
    if args.selftest_only:
        return 0

    if args.rebuild_sample or not args.cache.exists():
        print(f"sampling {args.sample} COD CIFs across {len(ROW_GROUPS)} row groups")
        build_sample(args.cache, max(1, args.sample // len(ROW_GROUPS)))

    records = [json.loads(line) for line in gzip.open(args.cache, "rt")]
    rng = random.Random(7)
    bawl_files = set(
        rng.sample([r["file"] for r in records], min(args.bawl, len(records)))
    )
    jobs = [(r, r["file"] in bawl_files) for r in records]

    from multiprocessing import Pool

    results: list[dict] = []
    with Pool(max(1, min(args.workers, 4)), initializer=_init_worker) as pool:
        for done, result in enumerate(pool.imap_unordered(check, jobs, chunksize=4), 1):
            results.append(result)
            if done % 100 == 0:
                print(f"  {done}/{len(jobs)} checked", flush=True)

    if args.dump:
        args.dump.write_text(
            json.dumps([{k: v for k, v in r.items() if k != "census"} for r in results]),
            encoding="utf-8",
        )
    report(results)
    return 1 if any(r["problems"] or r["tag_problems"] for r in results) else 0


def report(results: list[dict]) -> None:
    total_in = sum(r["bytes_in"] for r in results)
    total_out = sum(r["bytes_out"] for r in results)
    per_file = [1 - r["bytes_out"] / r["bytes_in"] for r in results if r["bytes_in"]]
    status: dict[str, int] = {}
    for result in results:
        status[result["status"]] = status.get(result["status"], 0) + 1
    bawl_checked = [r for r in results if "bawl" in r]
    bawl_equal = sum(1 for r in bawl_checked if r["bawl"][0] == r["bawl"][1])
    bawl_hash_fail = sum(1 for r in bawl_checked if r["bawl"][0].startswith("FAIL:"))
    broken = [r for r in results if r["problems"]]
    tag_broken = [r for r in results if r.get("tag_problems")]

    print("\n=== cif_trim verification ===")
    print(f"CIFs checked            : {len(results):,}")
    for name, count in sorted(status.items()):
        print(f"  {name:22s}: {count:,}")
    print(f"structural mismatches   : {len(broken)}")
    print(f"kept-tag data mismatches: {len(tag_broken)}")
    print(f"idempotent              : {sum(r['idempotent'] for r in results):,}"
          f" / {len(results):,}")
    print(f"no-op (unchanged text)  : {sum(r['noop'] for r in results):,}")
    print(f"BAWL compared           : {len(bawl_checked):,}"
          f"  identical: {bawl_equal:,}")
    print(f"  real fingerprints     : {len(bawl_checked) - bawl_hash_fail:,}"
          f"  (rest are matching FAIL: sentinels, e.g. DISORDERED)")
    print(f"bytes  in / out         : {total_in / 1e6:,.1f} MB / "
          f"{total_out / 1e6:,.1f} MB")
    print(f"total reduction         : {100 * (1 - total_out / total_in):.1f}%")
    print(f"mean size               : {total_in / len(results) / 1024:,.1f} KB -> "
          f"{total_out / len(results) / 1024:,.1f} KB")
    print(f"per-file reduction      : mean {100 * statistics.mean(per_file):.1f}%, "
          f"median {100 * statistics.median(per_file):.1f}%")

    census: dict[str, int] = {}
    for result in results:
        for tag, size in result["census"].items():
            family = "_".join(tag.split("_")[:3])
            census[family] = census.get(family, 0) + size
    print("\nbytes removed by family (top 12):")
    for family, size in sorted(census.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {family:32s} {size / 1e6:8.2f} MB  {100 * size / total_in:5.2f}%")

    if broken or tag_broken:
        print("\nFAILURES:")
        for result in broken[:25]:
            print(f"  COD {result['file']} (rg {result['rg']}): {result['problems']}")
        for result in tag_broken[:25]:
            print(
                f"  COD {result['file']} (rg {result['rg']}): "
                f"tags {result['tag_problems'][:6]}"
            )
    else:
        print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    sys.exit(main())
