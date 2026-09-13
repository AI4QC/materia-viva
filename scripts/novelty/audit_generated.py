#!/usr/bin/env python3
"""How much of a generated structure set is already in the resolved record.

A claim of novelty is a claim about a reference and a criterion. This script
holds the reference fixed - all 55 sources - and varies the criterion, from the
strictest to the loosest:

  1 exact structure      the BAWL fingerprint of the primitive cell is a row
                         already in the pool (the same test the corpus itself
                         is deduplicated with)
  2 composition + space group
  3 composition          some structure of that reduced composition exists
  4 stoichiometry pattern + space group
                         a NECESSARY condition for "same prototype, different
                         decoration", so it bounds prototype redundancy from
                         above rather than measuring it

Sets are audited against the whole record and, separately, against the record
with GNoME removed, because GNoME is itself a generated set and counting it as
prior knowledge is a different claim.

Usage
  audit_generated.py <spec.json> <out.json>

where spec.json is {"sets": [{"name": ..., "cifs": <dir|zip>, "glob": "*.cif",
"exclude_source": "gnome"|null}, ...]}.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
import warnings
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[2]
INDEX = f"file:{ROOT}/data/index/materials.sqlite?mode=ro"
MATCHMAP = f"file:{ROOT}/data/props_work/match_map.sqlite?mode=ro"
MAX_SITES, MAX_PRIM = 500, 300

TOK = re.compile(r"([A-Z][a-z]?)(\d*\.?\d*)")
_cache: dict[str, tuple[int, int]] = {}


def keys(formula: str) -> tuple[int, int]:
    """(reduced-composition hash, stoichiometry-pattern hash)."""
    hit = _cache.get(formula)
    if hit is not None:
        return hit
    agg: dict[str, float] = {}
    for el, num in TOK.findall(formula):
        agg[el] = agg.get(el, 0.0) + (float(num) if num else 1.0)
    if not agg:
        out = (hash(formula), hash(formula))
        _cache[formula] = out
        return out
    if all(abs(n - round(n)) < 1e-6 for n in agg.values()):
        g = 0
        for n in agg.values():
            g = math.gcd(g, int(round(n)))
        red = {el: int(round(n)) // (g or 1) for el, n in agg.items()}
    else:
        red = agg
    comp = "".join(f"{el}{red[el]:g}" for el in sorted(red))
    proto = ",".join(f"{v:g}" for v in sorted(red.values(), reverse=True))
    out = (hash(comp), hash(proto))
    _cache[formula] = out
    return out


# ----------------------------------------------------------------- the record
def build_record(db: sqlite3.Connection, gnome_exclusive: set[int]) -> dict:
    n = db.execute("select count(*) from materials").fetchone()[0]
    comp = np.empty(n, dtype=np.int64)
    cspg = np.empty(n, dtype=np.int64)
    pspg = np.empty(n, dtype=np.int64)
    isg = np.zeros(n, dtype=bool)
    for i, (pk, formula, spg) in enumerate(
            db.execute("select pk, formula, spacegroup_number from materials")):
        c, p = keys(formula or "")
        s = spg or 0
        comp[i], cspg[i], pspg[i] = c, hash((c, s)), hash((p, s))
        isg[i] = pk in gnome_exclusive
        if i and i % 4_000_000 == 0:
            print(f"    record {i:,}/{n:,}", flush=True)
    out = {}
    for tag, sel in (("all", np.ones(n, dtype=bool)), ("no_gnome", ~isg)):
        out[tag] = {"comp": np.unique(comp[sel]), "cspg": np.unique(cspg[sel]),
                    "pspg": np.unique(pspg[sel])}
    return out


# ------------------------------------------------------------------ the sets
def read_cifs(spec: dict) -> list[dict]:
    src = Path(spec["cifs"])
    rows = []
    if src.suffix == ".zip":
        with zipfile.ZipFile(src) as z:
            for nm in sorted(z.namelist()):
                if nm.lower().endswith(".cif"):
                    rows.append({"native_id": nm, "cif": z.read(nm).decode("utf-8", "replace")})
    else:
        for p in sorted(src.glob(spec.get("glob", "*.cif"))):
            rows.append({"native_id": p.name, "cif": p.read_text(errors="replace")})
    return rows


_hasher = None


def _init():
    global _hasher
    import sys as s
    warnings.filterwarnings("ignore")
    from material_hasher.hasher.bawl import BAWLHasher
    _hasher = BAWLHasher()
    s.stderr = open(os.devnull, "w")


def _hash_one(row: dict) -> dict:
    from pymatgen.core import Structure
    try:
        st = Structure.from_str(row["cif"], fmt="cif")
        n = len(st)
        formula = st.composition.formula.replace(" ", "")
        if n > MAX_SITES:
            h = "FAIL:TOO_LARGE"
        elif not st.is_ordered:
            h = "FAIL:DISORDERED"
        else:
            st = st.get_primitive_structure()
            h = "FAIL:TOO_LARGE_PRIM" if len(st) > MAX_PRIM else _hasher.get_material_hash(st)
    except Exception as exc:                                   # noqa: BLE001
        n, formula, h = 0, "", "FAIL:" + repr(exc)[:90]
    return {"native_id": row["native_id"], "n_sites": n, "formula": formula, "hash": h}


def main() -> None:
    spec = json.loads(Path(sys.argv[1]).read_text())
    out_path = Path(sys.argv[2])
    db = sqlite3.connect(INDEX, uri=True)
    db.execute("pragma mmap_size=8000000000")
    mm = sqlite3.connect(MATCHMAP, uri=True)
    SRC = {i: k for i, k in db.execute("select id,key from source_defs")}
    GN = next(i for i, k in SRC.items() if k == "gnome")

    gn_pks = {pk for (pk,) in db.execute(
        "select material_pk from material_source_refs where source_id=?", (GN,))}
    shared = {pk for pk, sid in db.execute(
        "select material_pk, source_id from material_source_refs")
        if sid != GN and pk in gn_pks}
    gnome_exclusive = gn_pks - shared
    print(f"gnome: {len(gn_pks):,} in corpus, {len(shared):,} also elsewhere", flush=True)

    print("building the record...", flush=True)
    record = build_record(db, gnome_exclusive)
    print({k: {kk: len(vv) for kk, vv in v.items()} for k, v in record.items()}, flush=True)

    from multiprocessing import Pool
    results = {}
    for s in spec["sets"]:
        rows = read_cifs(s)
        with Pool(int(spec.get("nproc", 16)), initializer=_init) as pool:
            hashed = pool.map(_hash_one, rows, chunksize=8)
        ok = [r for r in hashed if not r["hash"].startswith("FAIL:")]
        # criterion 1
        srcs = Counter()
        exact = set()
        holders: dict[str, list[str]] = {}
        for r in ok:
            got = mm.execute("select material_id from hash_map where hash=?",
                             (r["hash"],)).fetchone()
            if not got:
                continue
            exact.add(r["native_id"])
            pk = db.execute("select pk from materials where material_id=?", (got[0],)).fetchone()
            if pk:
                # one vote per (matched crystal, database): AFLOW and others file
                # several native ids against the same crystal, and counting rows
                # would report more holders than there are matches.
                held = sorted({SRC[sid] for (sid,) in db.execute(
                    "select source_id from material_source_refs where material_pk=?", (pk[0],))})
                holders[r["native_id"]] = held
                for key in held:
                    srcs[key] += 1
        # criteria 2-4
        def _has(arr, v):
            i = int(np.searchsorted(arr, v))
            return i < arr.size and int(arr[i]) == v

        per = {}
        for tag in ("all", "no_gnome"):
            R = record[tag]
            n = len(ok)
            e = cs = co = pr = 0
            for r in ok:
                if r["native_id"] in exact:
                    e += 1
                    continue
                spg = int(r["hash"].split("_")[1]) if r["hash"].count("_") >= 2 else 0
                c, p_ = keys(r["formula"])
                if _has(R["cspg"], hash((c, spg))):
                    cs += 1
                elif _has(R["comp"], c):
                    co += 1
                elif _has(R["pspg"], hash((p_, spg))):
                    pr += 1
            per[tag] = {"n": n, "exact": e, "comp_sg": cs, "comp": co,
                        "proto_sg": pr, "none": n - e - cs - co - pr}
        results[s["name"]] = {
            "n_cifs": len(rows), "n_hashed": len(ok),
            "fail": Counter(r["hash"].split(":")[1] for r in hashed
                            if r["hash"].startswith("FAIL:")),
            "ladder": per, "sources_of_exact_matches": dict(srcs.most_common()),
            # kept so novelty can be recomputed against any subset of the record
            "exact_match_holders": holders,
        }
        p = per["all"]
        print(f"{s['name']:24s} n={p['n']:5d}  exact {p['exact']:5d} "
              f"({p['exact']/max(p['n'],1)*100:5.1f}%)  none {p['none']:5d} "
              f"({p['none']/max(p['n'],1)*100:5.1f}%)", flush=True)
    out_path.write_text(json.dumps(results, indent=1, default=int))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
