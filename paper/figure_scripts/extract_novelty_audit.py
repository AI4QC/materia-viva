#!/usr/bin/env python3
"""Assemble the novelty audit into one record for Figure 5.

Inputs (produced by scripts/novelty/audit_generated.py and novelty_ladder.py):
  paper/data/_novelty_baselines.json   the six released baseline sample sets
  paper/data/_novelty_local.json       MatterGen: paper CIFs and local generation
  paper/data/_novelty_ladder_gnome.json  GNoME, audited inside the corpus

Output: paper/data/novelty_audit.json
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "paper" / "data"
DB = f"file:{ROOT}/data/index/materials.sqlite?mode=ro"

# the reference a novelty claim is made against, from the usual one to all 55
TIERS = [
    ("MP", ["materials-project"]),
    ("+ OQMD,\nAlexandria", ["materials-project", "oqmd", "alexandria"]),
    ("+ all general\nDFT", None),                 # filled from source families
    ("all 55\nsources", None),                    # every source
]

db = sqlite3.connect(DB, uri=True)
SRC = {i: k for i, k in db.execute("select id,key from source_defs")}
GN = next(i for i, k in SRC.items() if k == "gnome")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from style import SOURCE_GROUP  # noqa: E402

GENERAL = sorted(k for k, g in SOURCE_GROUP.items() if g == "general")
EXPERIMENTAL = sorted(k for k, g in SOURCE_GROUP.items() if g == "experimental")
TIERS[2] = (TIERS[2][0], GENERAL)
TIERS[3] = (TIERS[3][0], sorted(SRC.values()))

baselines = json.loads((DATA / "_novelty_baselines.json").read_text())
local = json.loads((DATA / "_novelty_local.json").read_text())
sets = {**baselines, **local}

# ------------------------------------------------------------------ GNoME
gn_pks = {pk for (pk,) in db.execute(
    "select material_pk from material_source_refs where source_id=?", (GN,))}
holders_gnome: dict[int, set[str]] = {}
for pk, sid in db.execute("select material_pk, source_id from material_source_refs"):
    if sid != GN and pk in gn_pks:
        holders_gnome.setdefault(pk, set()).add(SRC[sid])
gnome_ladder = json.loads((DATA / "_novelty_ladder_gnome.json").read_text())

out = {"sets": {}, "reference_tiers": [t[0] for t in TIERS],
       "general_sources": GENERAL, "experimental_sources": EXPERIMENTAL}


def tier_novelty(holders: dict, n: int) -> list[float]:
    """Fraction still reported as new, per reference tier, exact-structure test."""
    row = []
    for _, keys in TIERS:
        keyset = set(keys)
        known = sum(1 for h in holders.values() if keyset & set(h))
        row.append((n - known) / n * 100)
    return row


for name, rec in sets.items():
    L = rec["ladder"]["all"]
    n = L["n"]
    holders = rec.get("exact_match_holders", {})
    out["sets"][name] = {
        "n": n,
        "ladder": {k: L[k] for k in ("exact", "comp_sg", "comp", "proto_sg", "none")},
        "ladder_no_gnome": {k: rec["ladder"]["no_gnome"][k]
                            for k in ("exact", "comp_sg", "comp", "proto_sg", "none")},
        "tier_novelty": tier_novelty(holders, n),
        "sources_of_exact_matches": rec["sources_of_exact_matches"],
        "experimental_matches": sum(
            1 for h in holders.values() if set(EXPERIMENTAL) & set(h)),
    }

gl = gnome_ladder
out["sets"]["GNoME"] = {
    "n": gl["total"],
    "ladder": {"exact": gl["exact_structure"],
               "comp_sg": gl["composition_and_spacegroup"],
               "comp": gl["composition_only"],
               "proto_sg": gl["prototype_only"],
               "none": gl["not_found"]},
    "ladder_no_gnome": None,
    "tier_novelty": tier_novelty(holders_gnome, gl["total"]),
    "sources_of_exact_matches": dict(Counter(
        s for h in holders_gnome.values() for s in h).most_common()),
    "experimental_matches": sum(
        1 for h in holders_gnome.values() if set(EXPERIMENTAL) & set(h)),
}

(DATA / "novelty_audit.json").write_text(json.dumps(out, indent=1))
for k, v in out["sets"].items():
    L = v["ladder"]
    print(f"{k:26s} n={v['n']:7d}  new@exact {(v['n']-L['exact'])/v['n']*100:5.1f}%"
          f"  new@any {L['none']/v['n']*100:5.1f}%"
          f"  tiers {' '.join(f'{x:.0f}' for x in v['tier_novelty'])}"
          f"  exp {v['experimental_matches']}")
