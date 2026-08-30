#!/usr/bin/env python3
"""Which pool structures each trained model is allowed to score.

``make_training_sets.py`` records what a task's training set covered.  This
script turns that into the operational answer: the set of ``material_pk`` a
model may be applied to when filling in missing values, and -- just as
important -- how much of the pool it must NOT touch.

Two gate strengths, because the honest answer differs:

``strict`` (default)
    Admits a structure only on evidence already in the index: it belongs to a
    ``material_family`` the declared domain allows, it contains every element
    that appeared in *every* training structure, and it is not larger than the
    training set's 99th percentile.  High precision, and it will under-admit
    -- a porous framework that came from Materials Project carries no family
    label and is refused.

``wide``
    Additionally admits unlabelled structures whose density falls inside the
    training band.  This is a PROXY and it is wrong in identifiable ways:
    lithium metal is 0.53 g/cm3 and would pass a porosity density gate while
    having no pore at all.  Use it to build a *candidate* screening list, not
    to publish numbers.

The rigorous porosity gate is a zeo++ pass (pore-limiting diameter against the
sorbate kinetic diameter -- 3.3 A for CO2, 2.9 A for H2).  That is not run
here; ``--gate wide`` exists so the screening list can be produced before it,
and every output records which gate produced it.

Usage
-----
    python scripts/ml/prediction_sets.py --export data/ml/export \\
        --datasets data/ml/datasets --out data/ml/predict

    # materialise the actual pk list for one task
    python scripts/ml/prediction_sets.py --export data/ml/export \\
        --datasets data/ml/datasets --out data/ml/predict \\
        --materialize co2_uptake__GCMC_0.15bar_298K
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from applicability import GATE_HINT  # noqa: E402

#: Families a declared domain accepts under the strict gate.  ``None`` means
#: the domain has no family-level gate and falls back to the other tests.
DOMAIN_FAMILIES: dict[str, set[str] | None] = {
    "porous": {"mof", "cof", "zeolite", "zeotype"},
    "framework": {"mof", "cof", "zeolite", "zeotype"},
    "layered": {"2d-material"},
    "ion-conducting": None,      # gated by always_elements (the working ion)
    "magnetic": None,            # gated at predict time on total_magnetization
    "gapped": None,              # gated at predict time on a predicted gap
    "surface-derived": None,
    "synthesized-only": None,
    "pool-wide": None,
    "pool-wide-biased-labels": None,
}

#: Ions a battery / migration model can be about.  Used to gate the
#: ion-conducting domain when the task's own always_elements is empty.
WORKING_IONS = ("Li", "Na", "K", "Mg", "Ca", "Zn", "Al", "Y", "Cs", "Rb")

#: Domains with no structural gate at all.  ``gapped`` and ``magnetic`` are NOT
#: here: the index carries ``pbes_gap`` and ``total_magnetization`` for part of
#: the pool, so those are gated where the value is known and only deferred
#: where it is not -- see :func:`gate_for`.
DEFERRED_GATES = {
    "surface-derived": "目标是表面/界面量，池里存的是体相胞；只能作为面平均量解释",
    "synthesized-only": "标签缺失通常是'没人测过'而不是'不适用'；无结构门控",
}


def load_pool(export: Path) -> dict:
    table = pq.read_table(
        export / "materials.parquet",
        columns=["pk", "material_family", "chemical_system", "density", "n_atoms",
                 "pbes_gap", "total_magnetization"],
    )
    return {
        "pk": np.asarray(table.column("pk")),
        "family": np.asarray(table.column("material_family").to_pylist(), dtype=object),
        "chemsys": np.asarray(table.column("chemical_system").to_pylist(), dtype=object),
        "density": np.asarray(table.column("density")),
        "n_atoms": np.asarray(table.column("n_atoms")),
        "gap": np.asarray(table.column("pbes_gap")),
        "magmom": np.asarray(table.column("total_magnetization")),
    }


def any_element_mask(chemsys: np.ndarray, elements) -> np.ndarray:
    wanted = set(elements)
    return np.fromiter(
        (bool(wanted & set(str(cs).split("-"))) for cs in chemsys), bool, len(chemsys)
    )


def element_mask(chemsys: np.ndarray, elements: list[str]) -> np.ndarray:
    """True where the chemical system contains every one of ``elements``."""

    mask = np.ones(len(chemsys), bool)
    for element in elements:
        # chemical_system is a '-'-joined sorted element list, so a plain
        # substring test would match 'C' inside 'Ca'; split instead
        mask &= np.fromiter(
            (element in str(cs).split("-") for cs in chemsys), bool, len(chemsys)
        )
    return mask


def gate_for(task: dict, pool: dict, labelled: np.ndarray, mode: str) -> tuple[np.ndarray, list[str]]:
    """Boolean mask over the pool, plus the reasons that shaped it."""

    domain = task["declared_domain"]
    app = task["applicability"]
    reasons: list[str] = []

    mask = ~labelled
    reasons.append(f"排除已有标签 {int(labelled.sum()):,}")

    families = DOMAIN_FAMILIES.get(domain)
    if families is None and mode == "strict" and app["family_share"] > 0.9 \
            and app["family_top"] != "(none)":
        # The property has no domain limit, but every label came from one
        # family -- bulk_modulus_vrh__forcefield is 100% zeolite over two
        # chemical systems.  Scoring the other 98.7% of the pool with it is
        # pure extrapolation, so `strict` holds the model to the family it
        # actually saw and `wide` is where you opt into the extrapolation.
        families = {app["family_top"]}
        reasons.append(f"标签偏置：训练集 {app['family_share']:.0%} 为 "
                       f"{app['family_top']}，strict 门控限制在该族内")
    if families:
        fam_mask = np.fromiter(
            ((f or "") in families for f in pool["family"]), bool, len(pool["family"])
        )
        if mode == "wide" and app["density_p99"]:
            # unlabelled structures inside the training density band, admitted
            # as CANDIDATES only -- see the module docstring
            band = np.isfinite(pool["density"]) & (pool["density"] <= app["density_p99"])
            unlabelled_family = np.fromiter(
                ((f or "") == "" for f in pool["family"]), bool, len(pool["family"])
            )
            fam_mask |= band & unlabelled_family
            reasons.append(f"wide: 加入密度 ≤ {app['density_p99']} 的无族标结构（代理，未验证）")
        else:
            reasons.append(f"material_family ∈ {sorted(families)}")
        mask &= fam_mask

    if app["always_elements"]:
        mask &= element_mask(pool["chemsys"], app["always_elements"])
        reasons.append(f"必须含 {'+'.join(app['always_elements'])}"
                       f"（训练集每个结构都含）")

    # Gates the index CAN evaluate, on the part of the pool where the value is
    # known.  Where it is NULL the structure is neither admitted nor refused --
    # it is counted separately as deferred, because deciding it needs the
    # prediction this pipeline has not made yet.
    deferred = 0
    if domain == "gapped":
        known = np.isfinite(pool["gap"])
        mask &= ~(known & (pool["gap"] <= 0))
        deferred = int((mask & ~known).sum())
        reasons.append(f"band_gap > 0（已知带隙的部分）；带隙未知的 "
                       f"{deferred:,} 个待定 — 先预测带隙再筛")
    elif domain == "magnetic":
        known = np.isfinite(pool["magmom"])
        mask &= ~(known & (np.abs(pool["magmom"]) < 1e-3))
        deferred = int((mask & ~known).sum())
        reasons.append(f"|total_magnetization| > 0（已知磁矩的部分）；未知的 "
                       f"{deferred:,} 个待定")
    elif domain == "ion-conducting" and not app["always_elements"]:
        # BVSE computes the barrier for a HYPOTHETICAL inserted ion, so the
        # host need not contain it and always_elements comes back empty.  Fall
        # back to "contains some plausible working ion" rather than admitting
        # the whole pool.
        mask &= any_element_mask(pool["chemsys"], WORKING_IONS)
        reasons.append(f"含至少一种工作离子 {'/'.join(WORKING_IONS[:6])}…"
                       f"（训练集无统一必含元素，退回此门控）")

    if app["n_atoms_p99"]:
        cap = int(app["n_atoms_p99"])
        mask &= pool["n_atoms"] <= cap
        reasons.append(f"n_atoms ≤ {cap}（训练集 p99）")

    if domain in DEFERRED_GATES:
        reasons.append(f"待定门控 — {DEFERRED_GATES[domain]}")

    return mask, reasons, deferred


def gate_warning(task: dict, n_predictable: int, n_pool: int) -> str | None:
    """Flag a gate that stayed wide open despite a restricted declared domain.

    ``migration_barrier__*_Na`` is the case this catches: BVSE computes the
    barrier for a *hypothetical* inserted ion, so Na-free hosts are legitimate
    training rows, ``always_elements`` comes back empty, and nothing narrows
    the set.  The domain really is restricted -- to frameworks with a migration
    path -- but no column in the index expresses that.
    """

    domain = task["declared_domain"]
    if domain in ("pool-wide", "pool-wide-biased-labels"):
        return None
    if n_predictable / n_pool <= 0.5:
        return None
    return (f"declared_domain 是 {domain}，但索引里没有能收窄它的列，"
            f"门控放行了 {n_predictable / n_pool:.0%} 的池 —— "
            f"这个数字是上界，不是可信的预测范围")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--export", type=Path, default=Path("data/ml/export"))
    ap.add_argument("--datasets", type=Path, default=Path("data/ml/datasets"))
    ap.add_argument("--out", type=Path, default=Path("data/ml/predict"))
    ap.add_argument("--gate", choices=["strict", "wide"], default="strict")
    ap.add_argument("--materialize", action="append",
                    help="repeatable: write the actual pk list for this task")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    print("loading pool...", file=sys.stderr)
    pool = load_pool(args.export)
    n_pool = len(pool["pk"])

    reports = json.loads((args.datasets / "DATASETS.json").read_text())
    tasks = [t for r in reports for t in r.get("tasks", [])]
    wanted = set(args.materialize or [])

    out = []
    for task in tasks:
        stem = task["file"].replace(".parquet", "")
        labelled_pk = np.asarray(
            pq.read_table(args.datasets / task["file"], columns=["material_pk"])
            .column("material_pk")
        )
        labelled = np.zeros(n_pool, bool)
        labelled[np.searchsorted(pool["pk"], labelled_pk)] = True

        mask, reasons, deferred = gate_for(task, pool, labelled, args.gate)
        n = int(mask.sum())
        warning = gate_warning(task, n, n_pool)
        out.append({
            "task": stem,
            "declared_domain": task["declared_domain"],
            "gate": args.gate,
            "gate_hint": GATE_HINT.get(task["declared_domain"], ""),
            "n_labelled": int(labelled.sum()),
            "n_predictable": n,
            "n_deferred": deferred,
            "share_of_pool": round(n / n_pool, 5),
            "reasons": reasons,
            "warning": warning,
            "note": task["applicability_note"],
        })
        if stem in wanted:
            path = args.out / f"{stem}.pk.parquet"
            pq.write_table(
                pa.table({"material_pk": pa.array(pool["pk"][mask].tolist(), pa.int64())}),
                path, compression="zstd")
            print(f"  wrote {path} ({n:,} rows)", file=sys.stderr)

    out.sort(key=lambda r: -r["n_predictable"])
    (args.out / f"PREDICTION_SETS.{args.gate}.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False))

    print(f"\n{'任务':<56}{'已有标签':>11}{'可预测':>12}{'占池':>8}  域")
    for r in out:
        flag = " ⚠" if r["warning"] else ""
        print(f"{r['task'][:54]:<56}{r['n_labelled']:>11,}{r['n_predictable']:>12,}"
              f"{r['share_of_pool']:>8.1%}  {r['declared_domain']}{flag}")
    restricted = [r for r in out if r["share_of_pool"] < 0.5]
    warned = [r for r in out if r["warning"]]
    print(f"\n{len(out)} 个任务，其中 {len(restricted)} 个的可预测范围不到池的一半")
    if warned:
        print(f"⚠ {len(warned)} 个任务的域受限但索引里没有可用的门控列：")
        for r in warned:
            print(f"   {r['task'][:60]:<62}{r['warning']}")
    print(f"写入 {args.out}/PREDICTION_SETS.{args.gate}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
