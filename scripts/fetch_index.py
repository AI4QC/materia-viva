#!/usr/bin/env python3
"""Download a MateriaViva index from Hugging Face.

The code lives on GitHub; the data does not. The full index is ~47 GB across
three files, which is not something a git repository should carry, so it is
published as a Hugging Face dataset and fetched on demand.

Two variants:

``slice``  ~1k materials, tens of MB. Chosen by set cover so that every source,
           every property name, every curve type and every material family is
           represented at least once -- it exists so the UI can be developed
           without the full download, and a random sample would not do, because
           the rare properties are exactly the panels most likely to be broken.
``full``   the whole index, ~47 GB. What the public site serves.

Both land as a directory holding materials.sqlite, structures.blob and
curves.blob, which is precisely what ``scripts/serve.py --runtime`` expects:

    python scripts/fetch_index.py slice
    python scripts/serve.py --runtime data/slice

Resumable: huggingface_hub caches by content hash, so an interrupted 47 GB
download continues rather than restarting.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

REPO_ID = "AI4QC/MateriaViva"
REPO_TYPE = "dataset"

VARIANTS = {
    "slice": {"prefix": "slice", "default_dest": PROJECT_ROOT / "data" / "slice",
              "approx_bytes": 200 << 20},
    "full": {"prefix": "index", "default_dest": PROJECT_ROOT / "data" / "index",
             "approx_bytes": 47 << 30},
}

REQUIRED = ("materials.sqlite", "structures.blob", "curves.blob")


def fetch(variant: str, dest: Path, token: str | None) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:  # pragma: no cover - dependency hint
        raise SystemExit(
            "huggingface_hub is required: pip install huggingface_hub"
        ) from None

    spec = VARIANTS[variant]
    free = shutil.disk_usage(dest.parent if dest.parent.exists() else PROJECT_ROOT).free
    # The cache holds a second copy until the files are linked into place, so
    # the honest requirement is roughly twice the payload.
    needed = spec["approx_bytes"] * 2
    if free < needed:
        raise SystemExit(
            f"{variant} needs roughly {needed / (1 << 30):.0f} GiB free "
            f"(payload plus the hub cache); {free / (1 << 30):.0f} GiB available. "
            f"Point HF_HOME at a larger volume, or fetch the slice instead."
        )

    print(f"fetching {variant} from {REPO_ID} -> {dest}", flush=True)
    local = snapshot_download(
        repo_id=REPO_ID,
        repo_type=REPO_TYPE,
        allow_patterns=[f"{spec['prefix']}/*"],
        token=token,
    )
    source = Path(local) / spec["prefix"]
    dest.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED:
        src = source / name
        if not src.is_file():
            raise SystemExit(f"{name} missing from the downloaded {variant}")
        target = dest / name
        if target.exists():
            target.unlink()
        # Hard link when the cache shares a filesystem with dest, so the second
        # copy costs nothing; fall back to a real copy across devices.
        try:
            target.hardlink_to(src)
        except OSError:
            shutil.copy2(src, target)
    for extra in source.glob("*.json"):
        shutil.copy2(extra, dest / extra.name)

    total = sum((dest / name).stat().st_size for name in REQUIRED)
    print(f"ready: {dest} ({total / (1 << 30):.2f} GiB)")
    print(f"run it with:  python scripts/serve.py --runtime {dest}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=sorted(VARIANTS), default="slice", nargs="?")
    parser.add_argument("--dest", type=Path, default=None)
    parser.add_argument(
        "--token",
        default=None,
        help="Hugging Face token; omit to use the ambient login "
             "(hf auth login) or the HF_TOKEN environment variable",
    )
    args = parser.parse_args()
    dest = args.dest or VARIANTS[args.variant]["default_dest"]
    fetch(args.variant, dest, args.token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
