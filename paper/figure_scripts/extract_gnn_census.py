"""Flatten the property census and the gated prediction sets for Figure 4.

Both inputs are produced by scripts/ml (property_census.py and
prediction_sets.py) and are read here without recomputation, so the figure and
the census report cannot drift apart.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "paper" / "data"
POOL = 13_543_277

census = json.loads((ROOT / "data" / "ml" / "census" / "task_census.json").read_text())
predict = json.loads(
    (ROOT / "data" / "ml" / "predict" / "PREDICTION_SETS.strict.json").read_text())

# --------------------------------------------------- one row per census task
# A task is a (property, theory level) pair: the same property name computed at
# a different level of theory is a different quantity, not more data.
rows = []
for rec in census:
    for grp in rec["groups"]:
        rows.append((rec["p"], grp["g"], grp["n"], rec["k"], rec["u"] or "",
                     rec["ns"], rec["mat"]))
rows.sort(key=lambda r: -r[2])
with (DATA / "gnn_tasks.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["property", "theory_level", "n_materials", "kind", "unit",
                "n_sources", "property_total_materials"])
    w.writerows(rows)

# ------------------------------------- theory-level split of the biggest jobs
with (DATA / "gnn_theory_levels.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["property", "theory_level", "n_materials", "n_levels"])
    for rec in sorted(census, key=lambda r: -r["mat"])[:14]:
        for grp in rec["groups"]:
            w.writerow([rec["p"], grp["g"], grp["n"], len(rec["groups"])])

# ------------------------------------------- gated prediction sets, per task
with (DATA / "gnn_prediction_sets.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["task", "declared_domain", "n_labelled", "n_predictable",
                "n_deferred", "share_of_pool"])
    for rec in sorted(predict, key=lambda r: -r["n_predictable"]):
        w.writerow([rec["task"], rec["declared_domain"], rec["n_labelled"],
                    rec["n_predictable"], rec["n_deferred"], rec["share_of_pool"]])

# -------------------------------------------------------------- the summary
TIERS = [(1_000_000, "T1"), (100_000, "T2"), (10_000, "T3"),
         (2_000, "T4"), (300, "T5")]
tier_counts = {}
for thr, name in TIERS:
    reg = [r for r in rows if r[2] >= thr and r[3] == "num"]
    cls = [r for r in rows if r[2] >= thr and r[3] != "num"]
    tier_counts[name] = {
        "threshold": thr,
        "regression_tasks": len(reg),
        "regression_properties": len({r[0] for r in reg}),
        "classification_tasks": len(cls),
        "classification_properties": len({r[0] for r in cls}),
    }

domains = Counter(r["declared_domain"] for r in predict)
share_bands = Counter()
for r in predict:
    s = r["share_of_pool"]
    band = ("<1%" if s < 0.01 else "1-10%" if s < 0.10 else
            "10-50%" if s < 0.50 else "50-90%" if s < 0.90 else ">=90%")
    share_bands[band] += 1

summary = {
    "n_census_tasks": len(rows),
    "n_properties_with_data": len(census),
    "tiers": tier_counts,
    "n_training_sets": len(predict),
    "n_labels_total": sum(r["n_labelled"] for r in predict),
    "n_predictable_gated": sum(r["n_predictable"] for r in predict),
    "n_predictable_ungated": len(predict) * POOL,
    "gating_ratio": len(predict) * POOL / sum(r["n_predictable"] for r in predict),
    "declared_domains": dict(domains.most_common()),
    "share_of_pool_bands": dict(share_bands),
    "tasks_below_half_pool": sum(1 for r in predict if r["share_of_pool"] < 0.50),
    "max_theory_levels": max(len(r["groups"]) for r in census),
    "max_theory_levels_property": max(census, key=lambda r: len(r["groups"]))["p"],
}
(DATA / "gnn_census.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
for k, v in summary.items():
    if k not in ("tiers", "declared_domains", "share_of_pool_bands"):
        print(f"{k}: {v}")
print("tiers:", {k: v["regression_tasks"] for k, v in tier_counts.items()})
print("domains:", dict(domains.most_common(6)))
print("share bands:", dict(share_bands))
