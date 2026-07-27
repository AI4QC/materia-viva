#!/usr/bin/env python3
"""Acquire SACADA's catalog and one endpoint archive per unique carbon allotrope."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from scripts.datasets.acquire import _download_item, default_data_root


METADATA_URL = "https://www.sacada.info/scd_ajax.php"
DOWNLOAD_URL = "https://www.sacada.info/download/{structure_id}.zip"
SOURCE = {
    "id": "sacada",
    "data_path": "raw/acquired/sacada",
}


def build_structure_downloads(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Convert SACADA metadata into a stable, unique list of structure archives."""
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("SACADA metadata must contain a data list")

    structure_ids: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("SACADA metadata rows must be objects")
        try:
            structure_id = int(row["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("SACADA metadata contains an invalid structure id") from exc
        if structure_id <= 0:
            raise ValueError("SACADA structure ids must be positive")
        if structure_id in structure_ids:
            raise ValueError(f"duplicate SACADA structure id: {structure_id}")
        structure_ids.add(structure_id)

    return [
        {
            "filename": f"structures/{structure_id:06d}.zip",
            "url": DOWNLOAD_URL.format(structure_id=structure_id),
        }
        for structure_id in sorted(structure_ids)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Polite delay in seconds between per-structure requests",
    )
    parser.add_argument("--limit", type=int, help="Optional smoke-test limit")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay cannot be negative")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    data_root = default_data_root()
    metadata_path = _download_item(
        data_root,
        SOURCE,
        {"filename": "sacada-metadata.json", "url": METADATA_URL},
    )
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    downloads = build_structure_downloads(payload)
    if args.limit is not None:
        downloads = downloads[: args.limit]

    failures: list[dict[str, Any]] = []
    for index, item in enumerate(downloads, start=1):
        try:
            target = _download_item(data_root, SOURCE, item, retries=0)
        except subprocess.CalledProcessError as exc:
            failures.append({"filename": item["filename"], "returncode": exc.returncode})
            print(f"[{index}/{len(downloads)}] unavailable: {item['url']}", flush=True)
        else:
            print(f"[{index}/{len(downloads)}] {target}", flush=True)
        if index != len(downloads):
            time.sleep(args.delay)

    manifest = {
        "source_id": "sacada",
        "metadata_url": METADATA_URL,
        "catalog_records": len(payload["data"]),
        "requested_archives": len(downloads),
        "downloaded_archives": len(downloads) - len(failures),
        "unavailable_archives": failures,
        "complete": args.limit is None and not failures,
    }
    manifest_path = Path(data_root) / SOURCE["data_path"] / "manifest.json"
    building = manifest_path.with_name(manifest_path.name + ".building")
    building.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
