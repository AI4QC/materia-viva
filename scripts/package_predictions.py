#!/usr/bin/env python3
"""Package the completion run's published predictions for the two HF releases.

Input is a local mirror of the cluster's published prediction sets
(``<runs>/<task>/seed-*/predictions/{PREDICTIONS.json,part-*.parquet}``) and the
queue audit that says which of the run's tasks are done, running or held.

Two things happen on the way out:

* **Duplicates are dropped, first occurrence kept.** Every inference that was
  resumed before the 2026-10-12 fix re-emitted the structures it had withheld,
  so 21 of the published sets carry repeated ``material_pk``. Keeping the first
  copy is what ``~/dedup_published.py`` on the cluster does and what restores the
  ascending-pk invariant; the two copies differ only by float32 reduction order
  (the gap is reported per task). The cluster's files are not touched.
* **Absolute cluster paths are dropped** from the metadata that ships.

Outputs:

* ``<full>/predictions/<task>.parquet`` -- ``material_pk`` + value(s), joins to
  ``materials.pk`` in the full index;
* ``<open>/predictions/<task>.parquet`` -- ``material_id`` + value(s), only the
  structures admitted to the open release (``data/open-release/provenance.npz``);
* ``<task>.json`` beside each (the task's PREDICTIONS.json plus dedup counts) and
  one ``MANIFEST.json`` per release listing every task of the run with its state.

    python scripts/package_predictions.py \\
        --runs data/completion-preds/runs --audit data/completion-preds/audit-20261020.json \\
        --full data/hf-upload --open data/open-release/hf
"""

from __future__ import annotations

import argparse
import glob
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from export_open_structures import (  # noqa: E402
    DEFAULT_WORK, INDEX_DB, _load_provenance, class_mask, load_licences,
)

#: PREDICTIONS.json keys that only make sense on the cluster.
LOCAL_ONLY = ("checkpoint",)
#: Queue states as a reader of the release understands them.
STATE = {"done": "done", "running": "training", "pending": "queued"}


def open_keep() -> np.ndarray:
    p, bits = _load_provenance(DEFAULT_WORK)
    table = load_licences(bits)
    open_m = class_mask(bits, table, {"open"})
    return p["present"] & ((p["holds"] & open_m) != np.uint64(0))


def material_ids() -> np.ndarray:
    db = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
    n = db.execute("SELECT MAX(pk) FROM materials").fetchone()[0] + 1
    ids = np.empty(n, dtype=object)
    for pk, mid in db.execute("SELECT pk, material_id FROM materials"):
        ids[pk] = mid
    return ids


def load_task(pred_dir: Path) -> tuple[pa.Table, dict]:
    shards = sorted(pred_dir.glob("part-*.parquet"))
    table = pa.concat_tables([pq.read_table(s) for s in shards])
    pk = table.column("material_pk").to_numpy()
    _, first = np.unique(pk, return_index=True)       # first occurrence, ascending pk
    stats = {"shards": len(shards), "rows_published": table.num_rows,
             "rows": int(first.size), "duplicates_dropped": int(table.num_rows - first.size)}
    if stats["duplicates_dropped"]:
        # How far apart the two copies of a duplicated pk are, per value column.
        order = np.argsort(pk, kind="stable")
        dup = pk[order][1:] == pk[order][:-1]
        gaps = {}
        for name in table.column_names:
            if name == "material_pk":
                continue
            v = table.column(name).to_numpy(zero_copy_only=False).astype(np.float64)[order]
            gaps[name] = float(np.nanmax(np.abs(v[1:][dup] - v[:-1][dup])))
        stats["max_abs_gap_between_duplicates"] = gaps
    return table.take(pa.array(first)), stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--audit", type=Path, required=True)
    ap.add_argument("--full", type=Path, required=True)
    ap.add_argument("--open", type=Path, required=True)
    args = ap.parse_args()
    t0 = time.time()

    audit = json.loads(args.audit.read_text())
    keep = open_keep()
    ids = material_ids()
    print(f"open structures: {int(keep.sum()):,} ({time.time() - t0:.0f}s)", flush=True)

    out_full = args.full / "predictions"
    out_open = args.open / "predictions"
    for d in (out_full, out_open):
        d.mkdir(parents=True, exist_ok=True)

    manifest_full, manifest_open = {}, {}
    for rec in sorted(audit, key=lambda r: r["task"]):
        task = rec["task"]
        entry = {"state": STATE[rec["status"]], "declared_domain": rec.get("domain")}
        if rec["status"] != "done":
            manifest_full[task] = manifest_open[task] = entry
            continue
        found = sorted(glob.glob(str(args.runs / task / "seed-*" / "predictions" / "PREDICTIONS.json")))
        if len(found) != 1:
            raise SystemExit(f"{task}: expected one published set, found {len(found)}")
        pred_dir = Path(found[0]).parent
        meta = json.loads(Path(found[0]).read_text())
        if meta.get("n_predicted") is not None:
            published = sum(pq.ParquetFile(s).metadata.num_rows for s in pred_dir.glob("part-*.parquet"))
            if published != meta["n_predicted"]:
                raise SystemExit(f"{task}: mirror has {published:,} rows, PREDICTIONS.json says "
                                 f"{meta['n_predicted']:,} -- incomplete copy?")
        table, stats = load_task(pred_dir)
        for k in LOCAL_ONLY:
            meta.pop(k, None)
        meta["packaging"] = stats

        pq.write_table(table, out_full / f"{task}.parquet", compression="zstd",
                       compression_level=9, row_group_size=1_000_000)
        (out_full / f"{task}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))

        pk = table.column("material_pk").to_numpy()
        sel = keep[pk]
        open_tbl = table.filter(pa.array(sel))
        open_tbl = open_tbl.drop_columns(["material_pk"]).add_column(
            0, "material_id", pa.array(ids[pk[sel]], type=pa.string()))
        pq.write_table(open_tbl, out_open / f"{task}.parquet", compression="zstd",
                       compression_level=9, row_group_size=1_000_000)
        open_meta = dict(meta, n_rows_in_open_release=int(sel.sum()))
        (out_open / f"{task}.json").write_text(json.dumps(open_meta, indent=1, ensure_ascii=False))

        manifest_full[task] = dict(entry, rows=stats["rows"],
                                   duplicates_dropped=stats["duplicates_dropped"])
        manifest_open[task] = dict(entry, rows=int(sel.sum()))
        print(f"  {task}: {stats['rows']:,} rows (-{stats['duplicates_dropped']:,} dup),"
              f" open {int(sel.sum()):,} ({time.time() - t0:.0f}s)", flush=True)

    for d, m in ((out_full, manifest_full), (out_open, manifest_open)):
        states: dict[str, int] = {}
        for e in m.values():
            states[e["state"]] = states.get(e["state"], 0) + 1
        (d / "MANIFEST.json").write_text(json.dumps(
            {"packaged_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "audit": args.audit.name,
             "tasks_by_state": states,
             "rows_total": sum(e.get("rows", 0) for e in m.values()),
             "tasks": m}, indent=1))
    print(f"done ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
