#!/usr/bin/env python3
"""Build the redistributable (open-licence) structure release of MateriaViva.

The rule, as the user set it: a structure goes in if at least one database whose
licence permits redistribution holds it. A structure held by both an open and a
restricted database stays. Only the structure's sources decide admission.

Every property value and curve the index holds for an admitted structure goes in
too, whatever database it came from (user decision 2026-10-23, after the first
release shipped structures only). Those rows are not all openly licensed, so each
one carries its source database and that database's licence and licence class;
filtering on ``licence_class == "open"`` gives the openly licensed part.

What "holds" means is the part that is easy to get wrong. ``material_source_refs``
records three kinds of link and they are not equivalent:

* ``origin`` -- the database supplied the stored structure;
* ``hash`` -- the database has its own entry with the same BAWL fingerprint;
* ``id:<db>`` -- the database's entry was resolved through an identifier. When
  ``<db>`` is the database itself (``alexandria`` reading LeMat's ``agm`` ids,
  ``oqmd`` reading ``oqmd-`` ids) the entry IS that database's structure. When it
  names another database it is a citation: Materials Project saying "this is
  ICSD 1234" means MP has a relaxed calculation of that compound, not that the
  ICSD coordinates we store are in MP.

So a database counts as holding a structure through ``origin``, ``hash`` or an
id link on its own identifiers. Cross-database id citations are recorded in a
second mask so their effect can be reported, but they never admit a structure.

The pool also has two origins that are not rows in ``source_defs``:

* LeMat-Bulk (4.27M candidates): Materials Project, OQMD and Alexandria entries
  redistributed by Entalpic. The immutable id says which upstream it was.
* the legacy local pool (1.85M candidates, ``local_meta_*.tsv``): merged before
  provenance was tracked. It has no origin; a structure from it is admitted only
  if an open database independently holds it.

Stages (each reads the previous stage's output under --work):

    python scripts/export_open_structures.py provenance   # ~5 min, one pass over refs
    python scripts/export_open_structures.py classify     # counts per licence class
    python scripts/export_open_structures.py export       # Parquet shards + manifest (~10 min)
    python scripts/export_open_structures.py properties   # one Parquet file per property
    python scripts/export_open_structures.py curves       # spectra, DOS, band structures
    python scripts/export_open_structures.py card         # stage <work>/hf for upload
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DB = PROJECT_ROOT / "data" / "index" / "materials.sqlite"
STRUCTURES_BLOB = PROJECT_ROOT / "data" / "index" / "structures.blob"
CURVES_BLOB = PROJECT_ROOT / "data" / "index" / "curves.blob"
SOURCES = PROJECT_ROOT / "data" / "sources"
LICENCES = PROJECT_ROOT / "scripts" / "source_licences.json"
DEFAULT_WORK = PROJECT_ROOT / "data" / "open-release"

#: Bits past the 55 ``source_defs`` rows. source_defs ids run 1..55 and take
#: bits 0..54, so these start at 55; a uint64 mask has room to spare.
EXTRA = {"lemat-bulk": 55, "legacy-local": 56, "camd": 57, "wren": 58}
LEMAT_UPSTREAM = {"agm": "alexandria", "mp-": "materials-project", "oqm": "oqmd"}
#: The meta TSVs predate one rename in source_defs.
META_ALIAS = {"omdb": "omdb-organic"}
#: ODBX is an OPTIMADE mirror that states no licence of its own, but most of
#: what we took from it is other groups' data whose own releases are licensed:
#: CAMD (figshare 19601956, CC BY 4.0) and Wren (Zenodo 6345276, MIT). The
#: native id names the upstream, so those entries count as the upstream's.
SUBSOURCE = {"odbx": (("camd-", "camd"), ("wren-scn-", "wren"))}


def effective_key(key: str, native_id: str) -> str:
    for prefix, sub in SUBSOURCE.get(key, ()):
        if native_id.startswith(prefix):
            return sub
    return key

csv.field_size_limit(10 ** 9)


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True, timeout=600)
    db.execute("PRAGMA busy_timeout = 600000")
    return db


def source_bits(db: sqlite3.Connection) -> dict[str, int]:
    bits = {key: sid - 1 for sid, key in db.execute("SELECT id, key FROM source_defs")}
    assert max(bits.values()) < min(EXTRA.values()), "source_defs outgrew the bit layout"
    bits.update(EXTRA)
    return bits


def _read_meta(path: Path, has_header: bool = True):
    with path.open() as fh:
        reader = csv.reader(fh, delimiter="\t")
        if has_header:
            next(reader)
        yield from reader


# ---------------------------------------------------------------- provenance
def stage_provenance(work: Path) -> None:
    t0 = time.time()
    db = connect()
    bits = source_bits(db)
    key_of = {sid: key for sid, key in db.execute("SELECT id, key FROM source_defs")}
    n = db.execute("SELECT MAX(pk) FROM materials").fetchone()[0] + 1

    # Origin of the stored structure, keyed by (dataset, source_index).
    exp_origin: dict[int, str] = {}
    for row in _read_meta(SOURCES / "experimental" / "synth_meta.tsv"):
        exp_origin[int(row[0])] = META_ALIAS.get(row[1], row[1])
    cand_origin: dict[int, str] = {}
    cand_upstream: dict[int, str] = {}
    for split in ("train", "val"):
        for row in _read_meta(SOURCES / "candidate" / f"local_meta_{split}.tsv", has_header=False):
            cand_origin[int(row[0])] = "legacy-local"
    for row in _read_meta(SOURCES / "candidate" / "lemat_meta.tsv"):
        idx = int(row[0])
        cand_origin[idx] = "lemat-bulk"
        cand_upstream[idx] = LEMAT_UPSTREAM[row[1][:3]]
    for row in _read_meta(SOURCES / "candidate" / "elementa_meta.tsv"):
        cand_origin[int(row[0])] = "elementa"
    for row in _read_meta(SOURCES / "candidate" / "added_meta.tsv"):
        cand_origin[int(row[0])] = effective_key(META_ALIAS.get(row[1], row[1]), row[2])
    print(f"meta read: {len(exp_origin):,} experimental, {len(cand_origin):,} candidate"
          f" ({time.time() - t0:.0f}s)", flush=True)

    origin = np.full(n, -1, dtype=np.int16)
    upstream = np.full(n, -1, dtype=np.int16)
    is_exp = np.zeros(n, dtype=bool)
    present = np.zeros(n, dtype=bool)
    unmapped = 0
    for pk, dataset, sidx in db.execute("SELECT pk, dataset, source_index FROM materials"):
        idx = int(sidx)
        present[pk] = True
        if dataset == "experimental":
            is_exp[pk] = True
            key = exp_origin.get(idx)
        else:
            key = cand_origin.get(idx)
            up = cand_upstream.get(idx)
            if up is not None:
                upstream[pk] = bits[up]
        if key is None:
            unmapped += 1
            continue
        origin[pk] = bits[key]
    print(f"materials: {int(present.sum()):,} ({unmapped:,} without an origin row)"
          f" ({time.time() - t0:.0f}s)", flush=True)

    # One ordered pass over the refs table (WITHOUT ROWID, so it streams in
    # material_pk order). Classify each (source, match_via) pair once rather
    # than per row: there are ~140 distinct pairs and 21.5M rows.
    holds = np.zeros(n, dtype=np.uint64)     # origin / hash / own-id
    cites = np.zeros(n, dtype=np.uint64)     # cross-database id citation only
    kind_cache: dict[tuple[int, str, str], tuple[bool, np.uint64]] = {}
    split_sids = {sid for sid, key in key_of.items() if key in SUBSOURCE}
    seen = 0
    cur = db.execute(
        "SELECT material_pk, source_id, match_via, native_id FROM material_source_refs")
    while True:
        chunk = cur.fetchmany(500_000)
        if not chunk:
            break
        for pk, sid, via, nid in chunk:
            key = effective_key(key_of[sid], nid) if sid in split_sids else key_of[sid]
            k = kind_cache.get((sid, via, key))
            if k is None:
                own = via in ("origin", "hash") or via == f"id:{key_of[sid]}"
                k = kind_cache[(sid, via, key)] = (own, np.uint64(1) << np.uint64(bits[key]))
            if k[0]:
                holds[pk] |= k[1]
            else:
                cites[pk] |= k[1]
        seen += len(chunk)
        if seen % 5_000_000 < 500_000:
            print(f"  refs {seen:,} ({time.time() - t0:.0f}s)", flush=True)

    # The origin and the LeMat upstream hold the structure by construction.
    one = np.uint64(1)
    has_o = origin >= 0
    holds[has_o] |= one << origin[has_o].astype(np.uint64)
    has_u = upstream >= 0
    holds[has_u] |= one << upstream[has_u].astype(np.uint64)

    work.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        work / "provenance.npz", present=present, is_exp=is_exp, origin=origin,
        upstream=upstream, holds=holds, cites=cites,
    )
    (work / "bits.json").write_text(json.dumps(bits, indent=1, sort_keys=True))
    print(f"wrote {work / 'provenance.npz'} ({time.time() - t0:.0f}s)")


# ------------------------------------------------------------------ licences
#: Licence families, most permissive first. A structure held by several open
#: databases is offered under the most permissive of their licences.
LICENCE_RANK = {"public-domain": 0, "attribution": 1, "share-alike": 2}


def load_licences(bits: dict[str, int]) -> dict[str, dict]:
    table = json.loads(LICENCES.read_text())["sources"]
    missing = sorted(set(bits) - set(table))
    if missing:
        raise SystemExit(f"{LICENCES.name} has no entry for: {', '.join(missing)}")
    for key, entry in table.items():
        if entry["class"] not in ("open", "noncommercial", "restricted", "unclear", "unknown"):
            raise SystemExit(f"{key}: unknown class {entry['class']!r}")
        if entry["class"] == "open" and entry.get("family") not in LICENCE_RANK:
            raise SystemExit(f"{key}: an open source needs a family in {sorted(LICENCE_RANK)}")
    return table


def class_mask(bits: dict[str, int], table: dict[str, dict], classes: set[str]) -> np.uint64:
    mask = 0
    for key, bit in bits.items():
        if table[key]["class"] in classes:
            mask |= 1 << bit
    return np.uint64(mask)


def _load_provenance(work: Path):
    p = np.load(work / "provenance.npz")
    bits = json.loads((work / "bits.json").read_text())
    return {k: p[k] for k in p.files}, bits


def _popcount_by_bit(masks: np.ndarray, bits: dict[str, int]) -> dict[str, int]:
    return {key: int(((masks >> np.uint64(bit)) & np.uint64(1)).sum()) for key, bit in bits.items()}


# ------------------------------------------------------------------- classify
def stage_classify(work: Path) -> dict:
    p, bits = _load_provenance(work)
    table = load_licences(bits)
    key_at = {bit: key for key, bit in bits.items()}
    present, is_exp, holds, cites, origin = p["present"], p["is_exp"], p["holds"], p["cites"], p["origin"]
    zero = np.uint64(0)

    open_m = class_mask(bits, table, {"open"})
    nc_m = class_mask(bits, table, {"noncommercial"})
    keep = present & ((holds & open_m) != zero)
    keep_nc = present & ((holds & (open_m | nc_m)) != zero)
    keep_cite = present & (((holds | cites) & open_m) != zero)

    origin_open = np.zeros_like(present)
    ok = origin >= 0
    origin_open[ok] = ((np.uint64(1) << origin[ok].astype(np.uint64)) & open_m) != zero

    def by_origin(sel: np.ndarray) -> dict[str, int]:
        codes, counts = np.unique(origin[sel], return_counts=True)
        return {key_at.get(int(c), "unmapped"): int(n) for c, n in
                sorted(zip(codes, counts), key=lambda t: -t[1])}

    report = {
        "rule": "admitted iff an open-licence database holds the structure"
                " (origin, BAWL fingerprint, or its own identifier)",
        "materials": int(present.sum()),
        "admitted": int(keep.sum()),
        "admitted_experimental": int((keep & is_exp).sum()),
        "admitted_candidate": int((keep & ~is_exp).sum()),
        "excluded": int((present & ~keep).sum()),
        "admitted_with_restricted_origin": int((keep & ~origin_open).sum()),
        "admitted_with_restricted_origin_by_origin": by_origin(keep & ~origin_open),
        "excluded_by_origin": by_origin(present & ~keep),
        "admitted_by_origin": by_origin(keep),
        "if_noncommercial_admitted": int(keep_nc.sum()),
        "if_cross_citations_admitted": int(keep_cite.sum()),
        # Structures that ONLY this source holds, among all sources. Read as
        # "what is lost from the full pool if this source is withheld".
        "sole_holder": {},
        "holders": _popcount_by_bit(holds[present], bits),
    }
    single = holds[present]
    single = single[(single & (single - np.uint64(1))) == zero]
    codes, counts = np.unique(single, return_counts=True)
    for code, cnt in zip(codes, counts):
        if code == zero:
            report["sole_holder"]["(no holder)"] = int(cnt)
        else:
            report["sole_holder"][key_at[int(code).bit_length() - 1]] = int(cnt)
    report["sole_holder"] = dict(sorted(report["sole_holder"].items(), key=lambda t: -t[1]))
    # Excluded structures, by the least-restricted class among their holders:
    # tells apart "would need a licence purchase" from "licence never stated".
    for cls in ("noncommercial", "unclear", "restricted", "unknown"):
        m = class_mask(bits, table, {cls})
        report[f"excluded_held_by_{cls}"] = int((present & ~keep & ((holds & m) != zero)).sum())
    # Per source: what it holds, what only it holds, and -- for a source that
    # is not open -- how much of its holding the release keeps anyway because
    # an open database also has the structure.
    per = {}
    hp, kp = holds[present], keep[present]
    for key, bit in bits.items():
        b = np.uint64(1) << np.uint64(bit)
        held = (hp & b) != zero
        per[key] = {"holds": int(held.sum()), "sole": int((hp == b).sum()),
                    "held_admitted": int((held & kp).sum()),
                    "held_excluded": int((held & ~kp).sum())}
    report["per_source"] = per
    out = work / "classify.json"
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, dict)}, indent=1))
    print(f"wrote {out}")
    return report


# --------------------------------------------------------------------- export
#: Columns copied from ``materials``. All are read off the structure itself
#: (cell, composition, BAWL space group); the property columns of that table
#: (gap, formation energy, moduli, ...) are licensed values and stay out.
STRUCT_COLUMNS = (
    "material_id", "formula", "chemical_system", "dataset", "material_family",
    "n_elements", "n_atoms", "spacegroup_number", "spacegroup_symbol", "crystal_system",
    "lattice_a", "lattice_b", "lattice_c", "lattice_alpha", "lattice_beta", "lattice_gamma",
    "volume", "density",
)
#: Text that would mean a restricted database's own CIF header survived into a
#: stored structure. Counted, not silently dropped, so the manifest says so.
FOREIGN_MARKERS = ("icsd", "fiz karlsruhe", "ccdc", "copyright", "(c) ")


def _schema():
    import pyarrow as pa
    s, i, f, ls = pa.string(), pa.int32(), pa.float64(), pa.list_(pa.string())
    return pa.schema([
        ("material_id", s), ("formula", s), ("chemical_system", s), ("elements", ls),
        ("dataset", s), ("material_family", s), ("n_elements", i), ("n_sites", i),
        ("spacegroup_number", i), ("spacegroup_symbol", s), ("crystal_system", s),
        ("lattice_a", f), ("lattice_b", f), ("lattice_c", f),
        ("lattice_alpha", f), ("lattice_beta", f), ("lattice_gamma", f),
        ("volume", f), ("density", f),
        ("licence", s), ("licence_from", s),
        ("open_sources", ls), ("open_source_ids", ls), ("other_sources", ls),
        ("origin_source", s), ("origin_open", pa.bool_()),
        ("cif", s),
    ])


def stage_export(work: Path, shard_rows: int) -> None:
    import zlib

    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.time()
    p, bits = _load_provenance(work)
    table = load_licences(bits)
    key_at = {bit: key for key, bit in bits.items()}
    open_m = class_mask(bits, table, {"open"})
    zero, one = np.uint64(0), np.uint64(1)
    present, holds, origin = p["present"], p["holds"], p["origin"]
    keep = present & ((holds & open_m) != zero)
    print(f"admitting {int(keep.sum()):,} of {int(present.sum()):,}", flush=True)

    # Bit masks become source-key lists once per distinct mask, not per row:
    # 10M rows share a few thousand distinct holder sets.
    split_cache: dict[int, tuple[list[str], list[str], str, str]] = {}

    def split(mask: int):
        hit = split_cache.get(mask)
        if hit is None:
            keys = [key_at[b] for b in range(64) if mask >> b & 1]
            opn = [k for k in keys if table[k]["class"] == "open"]
            other = [k for k in keys if table[k]["class"] != "open"]
            best = min(opn, key=lambda k: (LICENCE_RANK[table[k]["family"]], k))
            hit = split_cache[mask] = (opn, other, table[best]["licence"], best)
        return hit

    lemat_ids: dict[int, str] = {}
    for row in _read_meta(SOURCES / "candidate" / "lemat_meta.tsv"):
        lemat_ids[int(row[0])] = row[1]

    db = connect()
    key_of = {sid: key for sid, key in db.execute("SELECT id, key FROM source_defs")}
    refs = db.execute(
        "SELECT material_pk, source_id, native_id, match_via FROM material_source_refs"
        " ORDER BY material_pk")
    pending_ref = None

    def refs_for(pk: int) -> list[tuple[int, str, str]]:
        """Merge-join: refs stream in material_pk order, as do materials."""
        nonlocal pending_ref
        out = []
        while True:
            if pending_ref is None:
                pending_ref = refs.fetchone()
                if pending_ref is None:
                    return out
            if pending_ref[0] > pk:
                return out
            if pending_ref[0] == pk:
                out.append(pending_ref[1:])
            pending_ref = None

    out_dir = work / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.parquet"):
        old.unlink()
    schema = _schema()
    cols: dict[str, list] = {name: [] for name in schema.names}
    shard = 0
    written = 0
    foreign: dict[str, int] = {}
    per_licence: dict[str, int] = {}
    blob = STRUCTURES_BLOB.open("rb")

    def flush():
        nonlocal shard, cols
        if not cols["material_id"]:
            return
        tbl = pa.Table.from_pydict(cols, schema=schema)
        pq.write_table(tbl, out_dir / f"structures-{shard:05d}.parquet",
                       compression="zstd", compression_level=6, row_group_size=50_000)
        shard += 1
        cols = {name: [] for name in schema.names}

    sql = ("SELECT pk, " + ", ".join(STRUCT_COLUMNS) + ", source_index, blob_offset, blob_length"
           " FROM materials ORDER BY pk")
    for row in db.execute(sql):
        pk = row[0]
        own_refs = refs_for(pk)
        if not keep[pk]:
            continue
        rec = dict(zip(STRUCT_COLUMNS, row[1:1 + len(STRUCT_COLUMNS)]))
        source_index, off, length = row[-3:]
        opn, other, lic, lic_from = split(int(holds[pk]))
        ids = set()
        for sid, nid, via in own_refs:
            key = key_of[sid]
            if via in ("origin", "hash") or via == f"id:{key}":
                ekey = effective_key(key, nid)
                if table[ekey]["class"] == "open":
                    ids.add(f"{ekey}:{nid}")
        ids = sorted(ids)
        o = int(origin[pk])
        okey = key_at.get(o, "unmapped") if o >= 0 else "unmapped"
        if okey == "lemat-bulk":
            ids.insert(0, f"lemat-bulk:{lemat_ids[int(source_index)]}")
        blob.seek(off)
        cif = zlib.decompress(blob.read(length)).decode()
        low = cif.lower()
        for marker in FOREIGN_MARKERS:
            if marker in low:
                foreign[f"{okey}:{marker}"] = foreign.get(f"{okey}:{marker}", 0) + 1
        rec["elements"] = rec["chemical_system"].split("-")
        rec["n_sites"] = int(round(rec.pop("n_atoms")))
        rec.update(licence=lic, licence_from=lic_from, open_sources=opn, open_source_ids=ids,
                   other_sources=other, origin_source=okey,
                   origin_open=okey in table and table[okey]["class"] == "open", cif=cif)
        for name in schema.names:
            cols[name].append(rec[name])
        per_licence[lic] = per_licence.get(lic, 0) + 1
        written += 1
        if len(cols["material_id"]) >= shard_rows:
            flush()
            print(f"  {written:,} rows, {shard} shards ({time.time() - t0:.0f}s)", flush=True)
    flush()
    manifest = {
        "rows": written,
        "shards": shard,
        "per_row_licence": dict(sorted(per_licence.items(), key=lambda t: -t[1])),
        "foreign_cif_markers": foreign,
        "built_from": str(INDEX_DB),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seconds": round(time.time() - t0),
    }
    (work / "export-manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))


# --------------------------------------------------------- properties, curves
#: Property rows held in memory, over all properties, before they are written.
PROPERTY_FLUSH_ROWS = 4_000_000
#: Decompressed curve payload per Parquet row group, and per shard file.
CURVE_GROUP_BYTES = 128 << 20
CURVE_SHARD_BYTES = 4 << 30


def _release_rows(work: Path):
    """What the property and curve stages share: who is admitted, and row labels.

    Returns the connection, the admission mask and pk -> material_id (both indexed
    by material pk), and ``label(source_id, native_id)`` -> (source, licence,
    licence class). ODBX rows resolve to CAMD / Wren by native id, as in export.
    """
    p, bits = _load_provenance(work)
    table = load_licences(bits)
    open_m = class_mask(bits, table, {"open"})
    keep = p["present"] & ((p["holds"] & open_m) != np.uint64(0))
    db = connect()
    n = max(len(keep), db.execute("SELECT MAX(pk) FROM materials").fetchone()[0] + 1)
    keep = np.concatenate([keep, np.zeros(n - len(keep), dtype=bool)])
    ids = np.empty(n, dtype=object)
    for pk, mid in db.execute("SELECT pk, material_id FROM materials"):
        ids[pk] = mid
    key_of = {sid: key for sid, key in db.execute("SELECT id, key FROM source_defs")}
    cache: dict[int, tuple[str, str, str]] = {}

    def label(sid: int, native_id: str | None) -> tuple[str, str, str]:
        key = key_of[sid]
        if key in SUBSOURCE:
            key = effective_key(key, native_id or "")
        elif sid in cache:
            return cache[sid]
        out = (key, table[key]["licence"], table[key]["class"])
        if key_of[sid] not in SUBSOURCE:
            cache[sid] = out
        return out

    return db, keep, ids, label


def _fresh_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for old in path.glob("*.parquet"):
        old.unlink()
    return path


def stage_properties(work: Path, limit: int | None = None) -> None:
    """``<work>/properties/<property>.parquet``: every value held for an admitted structure.

    One table scan; rows go to per-property writers. ``bool`` properties keep the
    index's 0/1 numbers, ``text`` ones are strings.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.time()
    db, keep, ids, label = _release_rows(work)
    defs = {pid: (name, unit, kind) for pid, name, unit, kind in
            db.execute("SELECT id, name, unit, kind FROM property_defs")}
    out_dir = _fresh_dir(work / "properties")
    s = pa.string()

    def schema(kind: str) -> pa.Schema:
        return pa.schema([("material_id", s), ("value", s if kind == "text" else pa.float64()),
                          ("method", s), ("source", s), ("source_native_id", s),
                          ("licence", s), ("licence_class", s)])

    writers: dict[int, pq.ParquetWriter] = {}
    bufs: dict[int, list] = {pid: [] for pid in defs}
    pks: dict[int, list] = {pid: [] for pid in defs}
    by_source: dict[int, dict[str, int]] = {pid: {} for pid in defs}
    by_class: dict[str, int] = {}
    mismatched: dict[str, int] = {}
    buffered = scanned = 0

    def flush():
        nonlocal buffered
        for pid, rows in bufs.items():
            if not rows:
                continue
            name, _, kind = defs[pid]
            sch = schema(kind)
            if pid not in writers:
                writers[pid] = pq.ParquetWriter(out_dir / f"{name}.parquet", sch,
                                                compression="zstd", compression_level=6)
            cols = list(zip(*rows))
            writers[pid].write_table(pa.Table.from_arrays(
                [pa.array(c, type=f.type) for c, f in zip(cols[1:], sch)], schema=sch))
            pks[pid].append(np.asarray(cols[0], dtype=np.int64))
            rows.clear()
        buffered = 0

    sql = ("SELECT material_pk, property_id, source_id, native_id, value_num, value_text, method"
           " FROM material_properties" + (f" LIMIT {int(limit)}" if limit else ""))
    cur = db.execute(sql)
    for chunk in iter(lambda: cur.fetchmany(200_000), []):
        scanned += len(chunk)
        for pk, pid, sid, nid, vnum, vtext, method in chunk:
            if not keep[pk]:
                continue
            kind = defs[pid][2]
            value = vtext if kind == "text" else vnum
            if value is None and (vnum if kind == "text" else vtext) is not None:
                mismatched[defs[pid][0]] = mismatched.get(defs[pid][0], 0) + 1
            src, lic, cls = label(sid, nid)
            bufs[pid].append((pk, ids[pk], value, method, src, nid, lic, cls))
            by_source[pid][src] = by_source[pid].get(src, 0) + 1
            by_class[cls] = by_class.get(cls, 0) + 1
            buffered += 1
        if buffered >= PROPERTY_FLUSH_ROWS:
            flush()
            print(f"  scanned {scanned:,} rows ({time.time() - t0:.0f}s)", flush=True)
    flush()
    for w in writers.values():
        w.close()
    pid_of = {name: pid for pid, (name, _, _) in defs.items()}
    for name in mismatched:
        _rewrite_as_text(db, keep, ids, label, out_dir, pid_of[name], name)
        defs[pid_of[name]] = (name, defs[pid_of[name]][1], "text")

    props = {}
    for pid, (name, unit, kind) in sorted(defs.items(), key=lambda t: t[1][0]):
        if pid not in writers:
            continue
        mats = np.unique(np.concatenate(pks[pid]))
        props[name] = {"unit": unit, "kind": kind, "rows": sum(by_source[pid].values()),
                       "structures": int(mats.size),
                       "sources": dict(sorted(by_source[pid].items(), key=lambda t: -t[1]))}
    manifest = {
        "rows": sum(e["rows"] for e in props.values()),
        "rows_scanned": scanned,
        "properties": len(props),
        "rows_by_licence_class": dict(sorted(by_class.items(), key=lambda t: -t[1])),
        # Values stored in the column the property's kind does not read. Each such
        # property was rewritten with a text ``value`` (so nothing is lost), and is
        # listed with kind "text" below.
        "values_in_unexpected_column": mismatched,
        "per_property": props,
        "built_from": str(INDEX_DB),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seconds": round(time.time() - t0),
    }
    (work / "properties-manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps({k: v for k, v in manifest.items() if k != "per_property"}, indent=1))


def _rewrite_as_text(db, keep, ids, label, out_dir: Path, pid: int, name: str) -> None:
    """Rewrite one property's file with a string ``value``.

    For a property declared numeric whose values are text -- NOVOMAG's ``easy_axis``
    holds '<111>' and 'a' -- the numeric file would hold only nulls. Text wins where
    both columns are set; a numeric value becomes its repr.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    s = pa.string()
    sch = pa.schema([(c, s) for c in ("material_id", "value", "method", "source",
                                      "source_native_id", "licence", "licence_class")])
    rows = []
    for pk, sid, nid, vnum, vtext, method in db.execute(
            "SELECT material_pk, source_id, native_id, value_num, value_text, method"
            " FROM material_properties WHERE property_id = ?", (pid,)):
        if keep[pk]:
            value = vtext if vtext is not None else None if vnum is None else repr(vnum)
            src, lic, cls = label(sid, nid)
            rows.append((ids[pk], value, method, src, nid, lic, cls))
    cols = list(zip(*rows)) if rows else [[] for _ in sch]
    pq.write_table(pa.Table.from_arrays([pa.array(c, type=s) for c in cols], schema=sch),
                   out_dir / f"{name}.parquet", compression="zstd", compression_level=6)


def stage_curves(work: Path, limit: int | None = None) -> None:
    """``<work>/curves/<type>-<fmt>-NNNNN.parquet``: every curve of an admitted structure.

    ``data`` is the payload exactly as the index serves it, decompressed: JSON
    (``{"x": [...], "y": [...]}``, or peak lists for ``xrd``/``peaks``) or SVG text.
    The blob is read in offset order, so the pass is one sequential read.
    """
    import zlib

    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.time()
    db, keep, ids, label = _release_rows(work)
    out_dir = _fresh_dir(work / "curves")
    s = pa.string()
    schema = pa.schema([("material_id", s), ("curve_type", s), ("fmt", s), ("label", s),
                        ("method", s), ("source", s), ("source_native_id", s),
                        ("licence", s), ("licence_class", s), ("data", s)])
    sql = ("SELECT material_pk, curve_type, fmt, source_id, native_id, method, label,"
           " blob_offset, blob_length FROM material_curves ORDER BY blob_offset"
           + (f" LIMIT {int(limit)}" if limit else ""))
    rows = [r for r in db.execute(sql) if keep[r[0]]]
    print(f"{len(rows):,} curves to write ({time.time() - t0:.0f}s)", flush=True)

    class Out:
        def __init__(self, stem: str):
            self.stem, self.shard, self.writer = stem, 0, None
            self.buf: list = []
            self.buf_bytes = self.shard_bytes = 0

        def flush(self, final: bool = False):
            if self.buf:
                if self.writer is None:
                    self.writer = pq.ParquetWriter(
                        out_dir / f"{self.stem}-{self.shard:05d}.parquet", schema,
                        compression="zstd", compression_level=6)
                cols = list(zip(*self.buf))
                self.writer.write_table(pa.Table.from_arrays(
                    [pa.array(c, type=s) for c in cols], schema=schema))
                self.shard_bytes += self.buf_bytes
                self.buf, self.buf_bytes = [], 0
            if self.writer is not None and (final or self.shard_bytes >= CURVE_SHARD_BYTES):
                self.writer.close()
                self.writer, self.shard, self.shard_bytes = None, self.shard + 1, 0

    outs: dict[str, Out] = {}
    stats: dict[str, dict] = {}
    by_class: dict[str, int] = {}
    blob = CURVES_BLOB.open("rb")
    for i, (pk, ctype, fmt, sid, nid, method, lab, off, length) in enumerate(rows, 1):
        blob.seek(off)
        data = zlib.decompress(blob.read(length)).decode()
        src, lic, cls = label(sid, nid)
        stem = f"{ctype}-{fmt}"
        out = outs.get(stem) or outs.setdefault(stem, Out(stem))
        out.buf.append((ids[pk], ctype, fmt, lab, method, src, nid, lic, cls, data))
        out.buf_bytes += len(data)
        st = stats.setdefault(stem, {"curves": 0, "payload_bytes": 0, "sources": {}})
        st["curves"] += 1
        st["payload_bytes"] += len(data)
        st["sources"][src] = st["sources"].get(src, 0) + 1
        by_class[cls] = by_class.get(cls, 0) + 1
        if out.buf_bytes >= CURVE_GROUP_BYTES:
            out.flush()
        if i % 100_000 == 0:
            print(f"  {i:,} curves ({time.time() - t0:.0f}s)", flush=True)
    for out in outs.values():
        out.flush(final=True)
    for stem, st in stats.items():
        st["shards"] = outs[stem].shard
    manifest = {
        "curves": len(rows),
        "rows_by_licence_class": dict(sorted(by_class.items(), key=lambda t: -t[1])),
        "per_type": dict(sorted(stats.items())),
        "built_from": str(INDEX_DB),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seconds": round(time.time() - t0),
    }
    (work / "curves-manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps({k: v for k, v in manifest.items() if k != "per_type"}, indent=1))


# ----------------------------------------------------------------------- card
def stage_card(work: Path) -> None:
    """Stage ``<work>/hf``: dataset card, licence table, hard-linked shards.

    Every number in the card is read from classify.json / export-manifest.json,
    so regenerating after a rebuild cannot leave stale figures behind.
    """
    rep = json.loads((work / "classify.json").read_text())
    man = json.loads((work / "export-manifest.json").read_text())
    # Written by scripts/package_predictions.py when the completion run's
    # predictions are packaged; absent, the release is structures only.
    pred_manifest = work / "hf" / "predictions" / "MANIFEST.json"
    preds = json.loads(pred_manifest.read_text()) if pred_manifest.is_file() else None
    table = json.loads(LICENCES.read_text())["sources"]
    per = rep["per_source"]
    if man["rows"] != rep["admitted"]:
        raise SystemExit(f"export wrote {man['rows']:,} rows but classify admitted {rep['admitted']:,}")
    stage = work / "hf"
    (stage / "data").mkdir(parents=True, exist_ok=True)
    for old in (stage / "data").glob("*.parquet"):
        old.unlink()
    for shard in sorted((work / "data").glob("*.parquet")):
        (stage / "data" / shard.name).hardlink_to(shard)
    (stage / "licences.json").write_text(json.dumps(
        {k: v for k, v in table.items() if k != "legacy-local"}, indent=1, ensure_ascii=False))
    # properties/ and curves/, when those stages have run.
    extra: dict[str, dict] = {}
    for part in ("properties", "curves"):
        part_manifest = work / f"{part}-manifest.json"
        if not part_manifest.is_file():
            continue
        dst = _fresh_dir(stage / part)
        for f in sorted((work / part).glob("*.parquet")):
            (dst / f.name).hardlink_to(f)
        m = json.loads(part_manifest.read_text())
        m.pop("built_from", None)                    # a local path
        (dst / "MANIFEST.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
        extra[part] = m
    props, curves = extra.get("properties"), extra.get("curves")

    lines: list[str] = []
    add = lines.append
    add("---")
    add("license: other")
    add("license_name: per-row-licences")
    add("license_link: https://huggingface.co/datasets/AI4QC/MateriaViva-Open/blob/main/licences.json")  # the Hub rejects a relative link
    add("pretty_name: MateriaViva Open")
    add("size_categories:\n- 10M<n<100M")
    add("tags:\n- materials-science\n- crystal-structures\n- cif\n- chemistry")
    add("configs:\n- config_name: default\n  data_files: data/*.parquet")
    add("---")
    add("")
    add("# MateriaViva Open")
    add("")
    add(f"{man['rows']:,} deduplicated crystal structures, each held by at least one database "
        "whose licence permits redistribution and commercial use. This is the "
        f"redistributable part of the {rep['materials']:,}-structure MateriaViva pool, which "
        "merges 55 materials databases by BAWL structure fingerprint: structures that only "
        "restricted, non-commercial or unlicensed databases hold are left out, and their "
        "properties with them.")
    add("")
    held = []
    if props:
        held.append(f"{props['rows']:,} property values over {props['properties']} properties "
                    "(`properties/`)")
    if curves:
        held.append(f"{curves['curves']:,} curves — spectra, densities of states, band "
                    "structures (`curves/`)")
    if preds:
        held.append("model predictions for properties nobody has computed (`predictions/`)")
    if held:
        add("For every structure that is included, the release carries what the full index "
            "holds for it: " + "; ".join(held) + ".")
        add("")
    add("## Inclusion rule")
    add("")
    add("A structure is included when an open-licence database holds it: the database supplied "
        "the stored structure, has its own entry with the same BAWL fingerprint, or lists it under "
        "its own identifier. A structure that a restricted database also holds is still included. "
        "A database citing another database's identifier (e.g. an entry saying \"this is ICSD 1234\") "
        "does not count as holding the structure.")
    add("")
    add("| | Structures |")
    add("|---|---:|")
    add(f"| Full pool | {rep['materials']:,} |")
    add(f"| Included | {rep['admitted']:,} |")
    add(f"| of which experimental | {rep['admitted_experimental']:,} |")
    add(f"| of which computed / hypothetical | {rep['admitted_candidate']:,} |")
    add(f"| Excluded | {rep['excluded']:,} |")
    add("")
    add("## Licence of each row")
    add("")
    add("Each row carries `licence`: the most permissive licence among the open databases that hold "
        "it (public domain, then attribution, then share-alike), and `licence_from`, the database "
        "that licence comes from. Attribution licences require crediting that database; "
        "CC BY-SA rows must stay CC BY-SA in derived datasets.")
    add("")
    add("| `licence` | Rows |")
    add("|---|---:|")
    for lic, n in man["per_row_licence"].items():
        add(f"| {lic} | {n:,} |")
    add("")
    add("## Where the stored coordinates come from")
    add("")
    add(f"For {rep['admitted_with_restricted_origin']:,} rows (`origin_open == false`) the stored "
        "CIF was not supplied by an open database, although an open database holds the same "
        "structure (same fingerprint). These are mostly the legacy deduplicated pool, whose "
        "origin was not recorded, and AFLOW entries that Alexandria, OQMD, NOMAD or others also "
        "hold. Filter on `origin_open` if you need coordinates that come from an open database.")
    add("")
    add("| `origin_source` | Included rows with a non-open origin |")
    add("|---|---:|")
    for key, n in rep["admitted_with_restricted_origin_by_origin"].items():
        add(f"| {key} | {n:,} |")
    add("")
    if props:
        add("## Property values")
        add("")
        add("`properties/<property>.parquet` has one row per value: `material_id`, `value`, "
            "`method`, `source`, `source_native_id`, `licence`, `licence_class`. A structure often "
            "has several values for one property, from different databases or levels of theory "
            "(`method`); they are kept side by side, not averaged. `bool` properties are 0/1 "
            "numbers. `properties/MANIFEST.json` lists each property's unit and rows per source.")
        add("")
        add("| Property | Unit | Values | Structures | Sources |")
        add("|---|---|---:|---:|---|")
        for name, e in sorted(props["per_property"].items(), key=lambda t: -t[1]["rows"]):
            srcs = list(e["sources"])
            add(f"| `{name}` | {e['unit'] or '—'} | {e['rows']:,} | {e['structures']:,} | "
                f"{', '.join(srcs[:4])}{' …' if len(srcs) > 4 else ''} |")
        add("")
    if curves:
        add("## Curves")
        add("")
        add("`curves/<type>-<format>-NNNNN.parquet`: `material_id`, `curve_type`, `fmt`, `label`, "
            "`method`, `source`, `source_native_id`, `licence`, `licence_class`, `data`. `data` is "
            "the payload as the MateriaViva site serves it: JSON `{\"x\": [...], \"y\": [...]}` for "
            "`xy`, a peak list for `peaks`, SVG text for `svg` (rendered band structures).")
        add("")
        add("| Type | Format | Curves | Sources |")
        add("|---|---|---:|---|")
        for stem, e in sorted(curves["per_type"].items(), key=lambda t: -t[1]["curves"]):
            ctype, fmt = stem.rsplit("-", 1)
            add(f"| {ctype} | {fmt} | {e['curves']:,} | {', '.join(e['sources'])} |")
        add("")
    if preds:
        tasks = preds["tasks"]
        done = {t: e for t, e in tasks.items() if e["state"] == "done"}
        add("## Predicted properties")
        add("")
        add(f"`predictions/<task>.parquet` holds `material_id` and the predicted value for "
            f"one property. **These are model predictions, not measurements**: a CGTNet "
            f"model per property, trained on values collected from the source databases and "
            f"applied to the structures inside that property's applicability gate. "
            f"{len(done)} of {len(tasks)} properties are complete "
            f"({preds['rows_total']:,} values on the structures in this release); the rest "
            f"are still training or queued. `<task>.json` records how the model was "
            f"selected, the gate, and any warning that goes with the numbers.")
        add("")
        add("| Property (task) | Domain | Predicted structures |")
        add("|---|---|---:|")
        for task, e in sorted(done.items(), key=lambda t: -t[1]["rows"]):
            add(f"| `{task}` | {e.get('declared_domain') or '—'} | {e['rows']:,} |")
        add("")
    add("## Structure columns (`data/`)")
    add("")
    for name, desc in (
        ("material_id", "MateriaViva id; joins to the full MateriaViva index"),
        ("formula, chemical_system, elements", "composition"),
        ("dataset", "`experimental` or `candidate` (computed or hypothetical)"),
        ("material_family", "e.g. `mof`, `zeolite`, `2d`, where known"),
        ("n_elements, n_sites", "element count; sites as indexed. For some sources (e.g. the "
         "Deem hypothetical zeolites) `n_sites` and `formula` describe the primitive cell while "
         "`cif` holds a larger conventional cell"),
        ("spacegroup_number, spacegroup_symbol, crystal_system", "symmetry"),
        ("lattice_a … lattice_gamma, volume, density", "cell (Å, degrees, Å³, g/cm³)"),
        ("licence, licence_from", "per-row licence, see above"),
        ("open_sources", "open databases holding the structure"),
        ("open_source_ids", "`database:native_id` for each, for attribution and lookup"),
        ("other_sources", "non-open databases that also hold it (provenance only)"),
        ("origin_source, origin_open", "database that supplied the stored CIF; whether it is open"),
        ("cif", "structure as CIF text"),
    ):
        add(f"- `{name}`: {desc}")
    add("")
    add("## Source databases")
    add("")
    add("Structures per open database (a structure held by several databases is counted for each).")
    add("")
    add("| Database | Licence | Structures | Link |")
    add("|---|---|---:|---|")
    opens = [(k, v) for k, v in table.items() if v["class"] == "open" and per.get(k, {}).get("holds")]
    for key, v in sorted(opens, key=lambda t: -per[t[0]]["holds"]):
        add(f"| {v['name']} (`{key}`) | {v['licence']} | {per[key]['holds']:,} | {v['url']} |")
    add("")
    add("Their structures are excluded, unless an open database holds them too, because their "
        "terms do not permit redistribution, permit it only non-commercially, or state no "
        "licence at all: " + ", ".join(
            f"{v['name']} ({v['licence']})" for k, v in table.items()
            if v["class"] in ("noncommercial", "restricted", "unclear")
            and per.get(k, {}).get("holds")) + ".")
    add("")
    add("## Caveats")
    add("")
    add("- Licences were read from each provider's pages on 2026-10-19 (`licences.json` has the "
        "evidence URL and quote for each). They describe the providers' published terms, not "
        "legal advice.")
    add("- NOMAD's terms fix CC BY 4.0 for all published uploads, but the export used here did "
        "not record the licence per entry.")
    add("- Several open databases publish structures derived from ICSD or the CSD under their own "
        "licence (relaxed geometries in MP, OQMD, MC3D, SNUMAT; curated CSD entries in FAIR-MOFs). "
        "`licences.json` notes each case.")
    add("")
    (stage / "README.md").write_text("\n".join(lines))
    print(f"staged {stage} ({man['shards']} shards, {man['rows']:,} rows)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stage", choices=["provenance", "classify", "export", "properties", "curves",
                                      "card"])
    ap.add_argument("--work", type=Path, default=DEFAULT_WORK)
    ap.add_argument("--shard-rows", type=int, default=250_000)
    ap.add_argument("--limit", type=int, help="properties/curves: read only this many index rows "
                    "(a smoke test; the output is incomplete)")
    args = ap.parse_args()
    if args.stage == "export":
        stage_export(args.work, args.shard_rows)
    elif args.stage == "properties":
        stage_properties(args.work, args.limit)
    elif args.stage == "curves":
        stage_curves(args.work, args.limit)
    else:
        {"provenance": stage_provenance, "classify": stage_classify,
         "card": stage_card}[args.stage](args.work)
    return 0


if __name__ == "__main__":
    sys.exit(main())
