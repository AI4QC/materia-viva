#!/usr/bin/env python3
"""Stage the MateriaViva index, slice and docs for upload to Hugging Face.

Builds ``data/hf-upload/`` mirroring the layout the dataset repo should have,
using HARD LINKS for the multi-gigabyte payloads: the index is ~47 GB and the
volume has less than that free, so copying is not an option, and hard links
inside one filesystem cost nothing.

Two things this does that are easy to get wrong by hand:

* **WAL checkpoint first.** The index runs in WAL mode, so recent commits live
  in ``materials.sqlite-wal`` until they are folded back. Uploading the
  ``.sqlite`` file without checkpointing publishes a database that is silently
  missing its most recent writes -- and the ``-wal`` file is not something a
  downloader would think to fetch.
* **Refuse to run while anything is writing.** A hard link tracks the live
  file, so staging mid-load would hand the uploader a moving target.

    python scripts/prepare_hf_upload.py
    hf upload-large-folder AI4QC/MateriaViva data/hf-upload --repo-type=dataset
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "data" / "index"
SLICE_DIR = PROJECT_ROOT / "data" / "slice"
STAGE = PROJECT_ROOT / "data" / "hf-upload"

PAYLOAD = ("materials.sqlite", "structures.blob", "curves.blob")

#: Anything here holding the index open means the staged links would move.
BUSY_PATTERNS = (
    "finalize_all.sh", "repair_and_verify.sh", "load_new_extractors.sh",
    "fix_framework_hash_refs.sh", "hmof_chain.sh", "core_mof_chain.sh",
    "properties/load.py", "properties/curves.py", "hmof_composite_admit.py",
)


def _writers_running() -> list[str]:
    busy = []
    for pattern in BUSY_PATTERNS:
        result = subprocess.run(
            ["pgrep", "-af", pattern], capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if "pgrep" not in line:
                busy.append(line.strip())
    return busy


def checkpoint(path: Path) -> None:
    """Fold the WAL back into the database file so it stands alone."""

    db = sqlite3.connect(path, timeout=600)
    db.execute("PRAGMA busy_timeout = 600000")
    mode, pages, moved = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    db.close()
    if mode != 0:
        raise SystemExit(
            f"wal_checkpoint returned busy on {path.name}; something still holds "
            "a write lock. Stop it and re-run."
        )
    print(f"  checkpointed {path.name}: {pages} pages, {moved} moved", flush=True)


def link_into(src_dir: Path, dest_dir: Path, names: tuple[str, ...]) -> dict[str, int]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for name in names:
        src = src_dir / name
        if not src.is_file():
            raise SystemExit(f"missing {src}")
        target = dest_dir / name
        if target.exists():
            target.unlink()
        try:
            target.hardlink_to(src)
        except OSError:
            shutil.copy2(src, target)
        sizes[name] = src.stat().st_size
    return sizes


def index_facts() -> dict:
    db = sqlite3.connect(f"file:{INDEX_DIR / 'materials.sqlite'}?mode=ro", uri=True)
    facts = {
        "materials": db.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
        "sources": db.execute("SELECT COUNT(*) FROM source_defs").fetchone()[0],
        "properties": db.execute("SELECT COUNT(*) FROM property_defs").fetchone()[0],
        "curves": db.execute("SELECT COUNT(*) FROM material_curves").fetchone()[0],
        "source_refs": db.execute("SELECT COUNT(*) FROM material_source_refs").fetchone()[0],
    }
    meta = dict(db.execute(
        "SELECT key, value FROM metadata WHERE key IN "
        "('property_row_count', 'experimental_count', 'candidate_count')"
    ))
    facts["property_rows"] = int(meta.get("property_row_count", 0))
    facts["experimental"] = int(meta.get("experimental_count", 0))
    facts["candidate"] = int(meta.get("candidate_count", 0))
    facts["licenses"] = sorted({
        row[0] for row in db.execute(
            "SELECT DISTINCT license FROM source_defs WHERE license IS NOT NULL"
        )
    })
    facts["source_table"] = db.execute(
        "SELECT s.key, s.name, s.license,"
        " (SELECT COUNT(*) FROM material_properties p WHERE p.source_id = s.id),"
        " (SELECT COUNT(DISTINCT r.material_pk) FROM material_source_refs r"
        "   WHERE r.source_id = s.id)"
        " FROM source_defs s ORDER BY 4 DESC"
    ).fetchall()
    db.close()
    return facts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-full", action="store_true",
                        help="stage only the slice and docs")
    parser.add_argument("--force", action="store_true",
                        help="stage even while a writer is running (unsafe)")
    args = parser.parse_args()

    busy = _writers_running()
    if busy and not args.force:
        print("refusing to stage: these are still writing to the index", file=sys.stderr)
        for line in busy:
            print(f"  {line}", file=sys.stderr)
        return 1

    started = time.time()
    STAGE.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"staged_at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if not args.skip_full:
        print("checkpointing the full index...", flush=True)
        checkpoint(INDEX_DIR / "materials.sqlite")
        print("linking the full index...", flush=True)
        manifest["index"] = link_into(INDEX_DIR, STAGE / "index", PAYLOAD)

    if SLICE_DIR.is_dir():
        print("checkpointing and linking the slice...", flush=True)
        checkpoint(SLICE_DIR / "materials.sqlite")
        manifest["slice"] = link_into(SLICE_DIR, STAGE / "slice", PAYLOAD)
        slice_manifest = SLICE_DIR / "slice-manifest.json"
        if slice_manifest.is_file():
            shutil.copy2(slice_manifest, STAGE / "slice" / slice_manifest.name)

    docs_out = STAGE / "docs"
    docs_out.mkdir(parents=True, exist_ok=True)
    for doc in ("property-integration.md", "property-integration.zh-CN.md",
                "dataset-acquisition.md", "dataset-acquisition.zh-CN.md"):
        src = PROJECT_ROOT / "docs" / doc
        if src.is_file():
            shutil.copy2(src, docs_out / doc)

    facts = index_facts()
    manifest["facts"] = {k: v for k, v in facts.items() if k != "source_table"}
    (STAGE / "upload-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    (PROJECT_ROOT / "data" / "index-facts.json").write_text(
        json.dumps(
            {**{k: v for k, v in facts.items() if k != "source_table"},
             "source_table": [list(r) for r in facts["source_table"]]},
            indent=2, sort_keys=True,
        ),
        encoding="utf-8",
    )

    total = sum(sum(v.values()) for k, v in manifest.items()
                if k in {"index", "slice"} and isinstance(v, dict))
    print(f"\nstaged {STAGE} ({total / (1 << 30):.2f} GiB via hard links, "
          f"{time.time() - started:.0f}s)")
    print("next: write README.md into the staging dir, then")
    print(f"  hf upload-large-folder AI4QC/MateriaViva {STAGE} --repo-type=dataset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
