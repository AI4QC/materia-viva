#!/usr/bin/env python3
"""Fetch the local-dataset supplement archives from the project's HF repo.

Downloads only the original `<source>/<source>.tar.gz` acquisition artifacts
(the repo also mirrors pre-extracted trees; extracting locally is cheaper),
verifies each against the repo's inventory.json SHA-256, and unpacks into
`data/raw/acquired/<source>/` following the repo README's layout.

Idempotent: an archive whose checksum already matches on disk is neither
re-downloaded nor re-extracted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACQUIRED = PROJECT_ROOT / "data" / "raw" / "acquired"
REPO_ID = "AI4QC/materia-viva-local-datasets"

#: amcsd is already acquired and loaded locally; skip unless --include-amcsd
DEFAULT_SKIP = {"amcsd"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-amcsd", action="store_true")
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()

    from huggingface_hub import hf_hub_download

    inventory_path = hf_hub_download(
        REPO_ID, "inventory.json", repo_type="dataset",
        local_dir=str(PROJECT_ROOT / "data" / "raw" / "_hf_supplements"),
    )
    inventory = json.loads(Path(inventory_path).read_text(encoding="utf-8"))

    report: dict[str, dict] = {}
    for entry in inventory:
        rel = entry["file"]
        source = rel.split("/")[3]
        if args.only and source not in args.only:
            continue
        if not args.include_amcsd and source in DEFAULT_SKIP:
            report[source] = {"state": "skipped-already-local"}
            continue

        target_dir = ACQUIRED / source
        target_dir.mkdir(parents=True, exist_ok=True)
        archive = target_dir / Path(rel).name

        started = time.time()
        if archive.is_file() and sha256(archive) == entry["sha256"]:
            state = "already-present"
        else:
            print(f"[{source}] downloading {entry['bytes'] / 1e6:.0f} MB",
                  flush=True)
            downloaded = hf_hub_download(
                REPO_ID, rel, repo_type="dataset",
                local_dir=str(PROJECT_ROOT / "data" / "raw" / "_hf_supplements"),
            )
            digest = sha256(Path(downloaded))
            if digest != entry["sha256"]:
                report[source] = {"state": "CHECKSUM-MISMATCH",
                                  "expected": entry["sha256"], "got": digest}
                print(f"[{source}] CHECKSUM MISMATCH", flush=True)
                continue
            Path(downloaded).replace(archive)
            state = "downloaded"

        # extract (README: --strip-components=1 drops the archive's own root)
        marker = target_dir / ".extracted"
        if not marker.is_file() or marker.read_text().strip() != entry["sha256"]:
            print(f"[{source}] extracting", flush=True)
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    parts = Path(member.name).parts
                    if len(parts) <= 1:
                        continue
                    member.name = str(Path(*parts[1:]))
                    if member.name.startswith(("/", "..")):
                        continue
                    tar.extract(member, target_dir, filter="data")
            marker.write_text(entry["sha256"], encoding="utf-8")
        report[source] = {
            "state": state,
            "bytes": entry["bytes"],
            "minutes": round((time.time() - started) / 60, 1),
        }
        print(f"[{source}] {report[source]}", flush=True)

    (PROJECT_ROOT / "data" / "raw" / "_hf_supplements" / "fetch_report.json"
     ).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
