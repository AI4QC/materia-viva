#!/usr/bin/env python3
"""Turn exported long-format targets into model-ready train/val/test tables.

Four things stand between ``targets/<property>.parquet`` and a trainable set,
and each of them silently ruins a benchmark if skipped:

1. **Theory level.**  A property row's value depends on the functional that
   produced it.  Pooling PBE, HSE06, mBJ and experiment into one ``band_gap``
   column gives a target with ~1 eV of method-induced spread that no GNN can
   predict from the structure, so the model learns "which database is this"
   instead.  Rows are grouped by ``theory_level`` and by default only the
   largest comparable family is kept (``--theory-policy majority``).

2. **Multi-source disagreement.**  1.19M pool structures are claimed by two or
   more databases and their values genuinely differ.  ``--resolve`` picks the
   policy: ``median`` (robust, the default), ``priority`` (a fixed source
   ranking), or ``drop-conflicts`` (discard any structure whose sources
   disagree by more than ``--conflict-tol``, which produces a smaller but much
   cleaner set).  The per-material spread is always written out as
   ``value_spread`` so a training run can down-weight noisy labels.

3. **Outliers.**  Unit slips and failed relaxations sit in the tails.  Hard
   physical bounds are applied where physics gives them (a band gap is not
   negative, a Poisson ratio is in [-1, 0.5]); everything else is clipped at
   configurable quantiles.

4. **Split leakage.**  A random split puts the same compound -- often the
   literal same structure under two ids -- in both train and test, which
   inflates every reported metric.  ``--split chemsys`` (default) holds out
   whole chemical systems; ``--split formula`` holds out reduced formulas;
   ``--split random`` is offered only for reproducing a leaky baseline.

Usage
-----
    python scripts/ml/make_training_sets.py --export data/ml/export \\
        --out data/ml/datasets --min-materials 500

    # one property, keeping every theory level as its own task
    python scripts/ml/make_training_sets.py --export data/ml/export \\
        --out data/ml/datasets --property band_gap --theory-policy split
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from applicability import declared_domain, profile, verdict  # noqa: E402
from method_groups import (  # noqa: E402
    CONDITION_SPLIT_PROPERTIES,
    condition_key,
)

# Bounds physics actually gives us.  Anything outside is a data error, not a
# rare material, so these are applied before the quantile clip.
#
# Two of these were wrong on the first pass and the drop counts caught it, so
# they are annotated: a bound that discards a large share of a corpus is much
# more likely to be a misremembered textbook limit than a broken database.
HARD_BOUNDS: dict[str, tuple[float, float]] = {
    "band_gap": (0.0, 20.0),
    "band_gap_direct": (0.0, 20.0),
    "bulk_modulus_vrh": (0.0, 1000.0),
    "bulk_modulus_voigt": (0.0, 1000.0),
    "bulk_modulus_reuss": (0.0, 1000.0),
    "shear_modulus_vrh": (0.0, 800.0),
    "shear_modulus_voigt": (0.0, 800.0),
    "shear_modulus_reuss": (0.0, 800.0),
    "youngs_modulus": (0.0, 1500.0),
    # NOT (-1, 0.5): that is the ISOTROPIC thermodynamic limit.  11.2% of the
    # rows here are directional components (deem-zeolites stores nu_xy ... nu_zy
    # separately) and an anisotropic crystal may legitimately exceed 0.5.  This
    # is a sanity bound only; the quantile clip handles the real tails.
    "poisson_ratio": (-10.0, 10.0),
    "density": (0.0, 30.0),
    # Slightly negative values are real: a source computing the hull against
    # its own reference set puts a few entries below it.
    "energy_above_hull": (-1.0, 10.0),
    # Symmetric, not (0, inf): 25.9% of values are negative, which is the
    # spin-convention sign (majority spin down), not an error.  A trainer that
    # wants magnitude should take abs() explicitly rather than have a quarter
    # of the corpus silently discarded here.
    "total_magnetization": (-1000.0, 1000.0),
    "debye_temperature": (0.0, 3000.0),
    "dielectric_constant_total": (1.0, 1e4),
    "dielectric_constant_electronic": (1.0, 1e3),
    "refractive_index": (1.0, 100.0),
    "void_fraction": (0.0, 1.0),
    "tc_superconducting": (0.0, 300.0),
    "curie_temperature": (0.0, 1500.0),
    "neel_temperature": (0.0, 1500.0),
    "thermal_conductivity": (0.0, 1e4),
    "lattice_thermal_conductivity": (0.0, 1e4),
    "surface_area_gravimetric": (0.0, 1e5),
    "measurement_temperature": (0.0, 1e4),
}

# Used by --resolve priority.  Ranked by how tightly the upstream workflow is
# controlled, not by size: a curated experimental measurement outranks a
# high-throughput screen.
#: Theory levels that are not a first-principles calculation.  When one of
#: these is the LARGEST group for a property, `--theory-policy majority` would
#: hand the whole property to it and discard the DFT labels underneath -- which
#: is how elastic moduli ended up with only the GULP force-field zeolite set
#: (121,704 rows) as their single task, burying 42,019 OptB88vdW and 31,517 PBE
#: values that are the ones anyone would actually want pool-wide.
NON_FIRST_PRINCIPLES = {
    "forcefield", "gcmc", "geometric", "transport-postproc", "ml-predicted",
    "other", "unspecified",
}


SOURCE_PRIORITY = [
    "materials-project", "jarvis-dft", "alexandria", "oqmd", "aflow",
    "mc3d", "c2db", "mc2d", "qmof", "matbench-discovery", "gnome", "elementa",
]


def split_key(*_a, **_k):  # retired: see SPLIT_CASCADE
    raise NotImplementedError


def slugify(text: str) -> str:
    """Filesystem-safe task suffix; condition keys carry spaces and slashes."""

    out = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(text))
    return out.strip("_")[:70] or "group"


def hash_frac(key: str, seed: int) -> float:
    """Deterministic key -> [0, 1). The same key always lands in the same fold,
    so re-running on an updated export does not reshuffle the test set."""

    digest = hashlib.blake2b(f"{seed}:{key}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(1 << 64)


def assign_splits(keys: np.ndarray, val_frac: float, test_frac: float,
                  seed: int) -> np.ndarray:
    """Group-wise split, ordered by hash but cut by MATERIAL count.

    Hashing each key into a fold directly is the simplest scheme and is what
    this did first, but it splits by number of groups, not by number of
    materials.  That is fine when groups are many and similar in size (the
    ~10^5 chemical systems in a DFT corpus) and badly wrong when they are few
    and lopsided: the Deem zeolites reduce to a handful of distinct formulas,
    and hashing them landed 29% of the materials in val against a 10% target.

    Walking the keys in hash order and cutting when the cumulative material
    count crosses each target keeps both properties that matter -- a key's
    whole group stays in one fold, and the order is a deterministic function of
    the key, so re-running on an updated export does not reshuffle anything
    except near the two boundaries.
    """

    uniq, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    frac = np.fromiter((hash_frac(str(k), seed) for k in uniq),
                       dtype=np.float64, count=len(uniq))
    order = np.argsort(frac, kind="stable")
    cum = np.cumsum(counts[order]) / counts.sum()

    if len(uniq) < 3:
        # Fewer than three groups cannot fill three folds without putting a
        # whole fold's worth of one group somewhere arbitrary.  Return an
        # all-train assignment: the caller sees the empty val/test folds and
        # cascades to a finer key, which is the honest outcome.
        return np.full(len(keys), "train", dtype=object)

    fold_by_key = np.empty(len(uniq), dtype=object)
    # cum is the share of materials at or before each group in hash order
    placed = np.empty(len(uniq), dtype=object)
    placed[:] = "train"
    placed[cum <= test_frac + val_frac] = "val"
    placed[cum <= test_frac] = "test"
    fold_by_key[order] = placed
    return fold_by_key[inverse]


#: Split keys from coarsest to finest.  A grouped split is only meaningful when
#: the group actually varies: an enumerated framework library (the 136K Deem
#: zeolites are all SiO2, SACADA is all carbon) has ONE chemical system, so
#: holding out whole systems puts every material in train and leaves the test
#: fold empty.  Falling back one level at a time keeps the strongest split that
#: still produces all three folds, and records which one was used.
SPLIT_CASCADE = {
    "chemsys": ["chemsys", "formula", "random"],
    "formula": ["formula", "random"],
    "random": ["random"],
}


def load_materials(export: Path) -> dict:
    table = pq.read_table(
        export / "materials.parquet",
        columns=["pk", "formula", "chemical_system", "is_experimental",
                 "n_atoms", "material_family", "density", "blob_offset",
                 "blob_length"],
    )
    pk = np.asarray(table.column("pk"))
    # finalise() maps pk -> row with searchsorted, which silently returns wrong
    # rows on unsorted input.  pk is the sqlite rowid so the export is sorted;
    # assert it rather than trust it.
    if not np.all(np.diff(pk) > 0):
        raise SystemExit("materials.parquet is not sorted by pk; re-run export_targets.py")
    return {
        "pk": pk,
        "formula": np.asarray(table.column("formula")),
        "chemsys": np.asarray(table.column("chemical_system")),
        "is_exp": np.asarray(table.column("is_experimental")),
        "n_atoms": np.asarray(table.column("n_atoms")),
        "family": np.asarray(table.column("material_family").to_pylist(), dtype=object),
        "density": np.asarray(table.column("density")),
        "offset": np.asarray(table.column("blob_offset")),
        "length": np.asarray(table.column("blob_length")),
    }


def build_one(name: str, path: Path, mats: dict, args) -> dict | None:
    table = pq.read_table(path)
    n_rows = table.num_rows
    values = np.asarray(table.column("value_num"), dtype=np.float64)
    finite = np.isfinite(values)
    if finite.sum() == 0:
        return {"property": name, "skipped": "no numeric values", "n_rows": n_rows}

    pks = np.asarray(table.column("material_pk"))[finite]
    values = values[finite]
    levels = np.asarray(table.column("theory_level").to_pylist())[finite]
    sources = np.asarray(table.column("source").to_pylist())[finite]

    # A condition-split property is not one target: co2_uptake holds four GCMC
    # (P, T) conditions per MOF, decomposition_energy four reference hulls.
    # Grouping on the theory level would merge them into a meaningless average,
    # so those properties key on the condition instead.
    task_key = args.task_key
    if task_key == "auto":
        task_key = "condition" if name in CONDITION_SPLIT_PROPERTIES else "theory"
    if task_key == "condition":
        raw_methods = table.column("method").to_pylist()
        keys = np.array([condition_key(raw_methods[i])
                         for i in np.flatnonzero(finite)])
    else:
        keys = levels

    report: dict = {
        "property": name,
        "n_rows_total": int(n_rows),
        "n_rows_numeric": int(finite.sum()),
        "task_key": task_key,
        "theory_levels": {},
        "groups": {},
    }
    unique_levels, level_counts = np.unique(levels, return_counts=True)
    for level, count in zip(unique_levels.tolist(), level_counts.tolist()):
        report["theory_levels"][level] = count

    unique_keys, key_counts = np.unique(keys, return_counts=True)
    for key, count in zip(unique_keys.tolist(), key_counts.tolist()):
        report["groups"][key] = count

    if task_key == "condition" or args.theory_policy == "split":
        keep = unique_keys.tolist()
    elif args.theory_policy == "majority":
        winner = unique_keys[int(np.argmax(key_counts))]
        keep = [winner]
        # A force-field or geometric corpus can outnumber the DFT one and still
        # not be the target anyone wants pool-wide.  When the majority group is
        # not a first-principles calculation, keep the DFT levels alongside it
        # rather than letting size alone decide.
        if str(winner) in NON_FIRST_PRINCIPLES and args.keep_dft_levels:
            keep += [
                key for key, count in zip(unique_keys.tolist(), key_counts.tolist())
                if key != winner and key not in NON_FIRST_PRINCIPLES
                and count >= args.keep_dft_levels
            ]
    else:  # 'pool' -- explicitly asked for, and recorded as such
        keep = [None]

    tasks = []
    for level in keep:
        mask = np.ones(len(values), bool) if level is None else (keys == level)
        if mask.sum() < args.min_materials:
            continue
        task = finalise(name, level, pks[mask], values[mask], sources[mask],
                        mats, args)
        if task:
            tasks.append(task)
    report["tasks"] = tasks
    return report


def finalise(name, level, pks, values, sources, mats, args) -> dict | None:
    """Collapse to one row per material, clip, split, and write the table."""

    lo, hi = HARD_BOUNDS.get(name, (-np.inf, np.inf))
    keep = (values >= lo) & (values <= hi)
    n_out_of_bounds = int((~keep).sum())
    pks, values, sources = pks[keep], values[keep], sources[keep]
    if len(values) < args.min_materials:
        return None

    order = np.argsort(pks, kind="stable")
    pks, values, sources = pks[order], values[order], sources[order]
    bounds = np.flatnonzero(np.r_[True, pks[1:] != pks[:-1], True])

    uniq_pk = pks[bounds[:-1]]
    resolved = np.empty(len(uniq_pk))
    spread = np.zeros(len(uniq_pk))
    n_obs = np.diff(bounds).astype(np.int32)
    for i, (start, stop) in enumerate(zip(bounds[:-1], bounds[1:])):
        chunk = values[start:stop]
        if len(chunk) == 1:
            resolved[i] = chunk[0]
            continue
        spread[i] = float(chunk.max() - chunk.min())
        if args.resolve == "priority":
            ranks = [
                SOURCE_PRIORITY.index(s) if s in SOURCE_PRIORITY else len(SOURCE_PRIORITY)
                for s in sources[start:stop]
            ]
            resolved[i] = chunk[int(np.argmin(ranks))]
        else:
            resolved[i] = float(np.median(chunk))

    conflicted = spread > args.conflict_tol * max(np.std(resolved), 1e-9)
    if args.resolve == "drop-conflicts":
        keep2 = ~conflicted
        uniq_pk, resolved, spread, n_obs = (
            uniq_pk[keep2], resolved[keep2], spread[keep2], n_obs[keep2])

    if args.clip_quantile > 0:
        q_lo, q_hi = np.quantile(resolved, [args.clip_quantile, 1 - args.clip_quantile])
        inside = (resolved >= q_lo) & (resolved <= q_hi)
        uniq_pk, resolved, spread, n_obs = (
            uniq_pk[inside], resolved[inside], spread[inside], n_obs[inside])

    if len(uniq_pk) < args.min_materials:
        return None

    # pk is the sqlite rowid, so materials.parquet is already sorted by it:
    # searchsorted beats a 13.5M-entry dict lookup per material
    rows = np.searchsorted(mats["pk"], uniq_pk)
    formulas = mats["formula"][rows]
    chemsys = mats["chemsys"][rows]

    split_used, splits, fallback_from = args.split, None, None
    for mode in SPLIT_CASCADE[args.split]:
        if mode == "random":
            keys = uniq_pk.astype(str)
        elif mode == "formula":
            keys = formulas.astype(str)
        else:
            keys = chemsys.astype(str)
        candidate = assign_splits(keys, args.val_frac, args.test_frac, args.seed)
        if (candidate == "val").any() and (candidate == "test").any():
            split_used, splits = mode, candidate
            break
        fallback_from = fallback_from or mode
    if splits is None:  # every level degenerate -- should be unreachable
        split_used = "random"
        splits = assign_splits(uniq_pk.astype(str), args.val_frac,
                               args.test_frac, args.seed)

    # Applicability: what this model may legitimately be applied to.  Without
    # it, "fill in every missing property" produces a co2_uptake number for
    # every dense intermetallic in the pool.
    empirical = profile(mats["family"][rows], chemsys,
                        mats["density"][rows], mats["n_atoms"][rows])
    declared = declared_domain(name)

    import pyarrow as pa

    slug = name if level in (None, "") else f"{name}__{slugify(level)}"
    out_path = args.out / f"{slug}.parquet"
    pq.write_table(
        pa.table({
            "material_pk": pa.array(uniq_pk.tolist(), pa.int64()),
            "target": pa.array(resolved.tolist(), pa.float64()),
            "n_observations": pa.array(n_obs.tolist(), pa.int32()),
            "value_spread": pa.array(spread.tolist(), pa.float32()),
            "split": pa.array(splits.tolist(), pa.string()),
            "formula": pa.array([str(f) for f in formulas], pa.string()),
            "chemical_system": pa.array([str(c) for c in chemsys], pa.string()),
            "is_experimental": pa.array(mats["is_exp"][rows].tolist(), pa.int8()),
            "n_atoms": pa.array(mats["n_atoms"][rows].tolist(), pa.int16()),
            "blob_offset": pa.array(mats["offset"][rows].tolist(), pa.int64()),
            "blob_length": pa.array(mats["length"][rows].tolist(), pa.int32()),
        }),
        out_path,
        compression="zstd",
    )
    return {
        "file": out_path.name,
        "group": level,
        "n_materials": int(len(uniq_pk)),
        "n_train": int((splits == "train").sum()),
        "n_val": int((splits == "val").sum()),
        "n_test": int((splits == "test").sum()),
        "n_experimental": int(mats["is_exp"][rows].sum()),
        "n_multi_source": int((n_obs > 1).sum()),
        "n_conflicted": int(conflicted.sum()),
        "n_out_of_bounds_dropped": n_out_of_bounds,
        "target_mean": float(resolved.mean()),
        "target_std": float(resolved.std()),
        "target_min": float(resolved.min()),
        "target_max": float(resolved.max()),
        "declared_domain": declared,
        "applicability": empirical,
        "applicability_note": verdict(declared, empirical),
        "split_mode": split_used,
        "split_requested": args.split,
        "split_fallback": (
            None if split_used == args.split
            else f"'{args.split}' left an empty val/test fold "
                 f"(the task spans too few {args.split} groups); fell back"
        ),
        "resolve": args.resolve,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--export", type=Path, default=Path("data/ml/export"))
    ap.add_argument("--out", type=Path, default=Path("data/ml/datasets"))
    ap.add_argument("--property", action="append", help="repeatable; default all")
    ap.add_argument("--min-materials", type=int, default=300)
    ap.add_argument("--task-key", choices=["auto", "theory", "condition"],
                    default="auto",
                    help="what defines a separate task. 'auto' keys the "
                         "condition-split properties on their measurement "
                         "condition and everything else on theory level")
    ap.add_argument("--keep-dft-levels", type=int, default=10_000,
                    help="主导层级不是第一性原理时，额外保留达到这个规模的 DFT "
                         "层级；0 = 只留主导层级")
    ap.add_argument("--theory-policy", choices=["majority", "split", "pool"],
                    default="majority",
                    help="with --task-key theory: keep only the largest level, "
                         "one task per level, or pool them (not recommended)")
    ap.add_argument("--resolve", choices=["median", "priority", "drop-conflicts"],
                    default="median")
    ap.add_argument("--conflict-tol", type=float, default=0.25,
                    help="a material is 'conflicted' when its source spread "
                         "exceeds this many target standard deviations")
    ap.add_argument("--clip-quantile", type=float, default=0.0005)
    ap.add_argument("--split", choices=["chemsys", "formula", "random"],
                    default="chemsys")
    ap.add_argument("--val-frac", type=float, default=0.1)
    ap.add_argument("--test-frac", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    print("loading materials index...", file=sys.stderr)
    mats = load_materials(args.export)

    files = sorted((args.export / "targets").glob("*.parquet"))
    if args.property:
        wanted = set(args.property)
        files = [f for f in files if f.stem in wanted]

    reports = []
    for path in files:
        report = build_one(path.stem, path, mats, args)
        if report is None:
            continue
        reports.append(report)
        tasks = report.get("tasks", [])
        if tasks:
            for task in tasks:
                note = "" if task["split_fallback"] is None else \
                    f"  [split: {args.split} -> {task['split_mode']}]"
                if task["declared_domain"] != "pool-wide":
                    note += f"  [域: {task['declared_domain']}]"
                elif task["applicability"]["family_share"] > 0.9 and \
                        task["applicability"]["family_top"] != "(none)":
                    note += f"  [标签偏置: {task['applicability']['family_top']}]"
                print(f"  {task['file']:<58} {task['n_materials']:>9,} materials "
                      f"(train {task['n_train']:,} / val {task['n_val']:,} / "
                      f"test {task['n_test']:,}){note}", flush=True)
        else:
            print(f"  {path.stem:<58} skipped", file=sys.stderr)

    (args.out / "DATASETS.json").write_text(json.dumps(reports, indent=1))
    n_tasks = sum(len(r.get("tasks", [])) for r in reports)
    print(f"\n{n_tasks} trainable tasks written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
