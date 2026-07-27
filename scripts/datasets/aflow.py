#!/usr/bin/env python3
"""Resumable AFLUX exporter for the complete AFLOW structure/property collection."""

from __future__ import annotations

import gzip
import json
import math
import re
import shutil
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root, ensure_capacity


ENDPOINT = "https://aflow.org/API/aflux/"
FIELDS = (
    "auid",
    "aurl",
    "compound",
    "species",
    "geometry",
    "positions_fractional",
    "natoms",
    "nspecies",
    "spacegroup_relax",
    "Pearson_symbol_relax",
    "prototype",
    "energy_atom",
    "enthalpy_formation_atom",
    "Egap",
    "density",
    "volume_atom",
)


def build_url(*, page: int, page_size: int) -> str:
    if page < 1 or page_size < 1:
        raise ValueError("page and page_size must be positive")
    return f"{ENDPOINT}?paging({page},{page_size})," + ",".join(FIELDS)


def parse_total(payload: dict) -> int:
    pattern = re.compile(r"\bof\s+(\d+)$")
    for label in payload:
        match = pattern.search(label)
        if match:
            return int(match.group(1))
    raise RuntimeError("AFLUX response did not contain a total entry count")


def _fetch_json(url: str, *, attempts: int = 5) -> dict:
    last_error: Exception | None = None
    request = Request(url, headers={"User-Agent": "MateriaViva-dataset-acquisition/1.0"})
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=300) as response:
                return json.load(response)
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(30, 2**attempt))
    assert last_error is not None
    raise last_error


def _page_path(output_dir: Path, page: int) -> Path:
    return output_dir / f"page-{page:09d}.json.gz"


def _write_page(output_dir: Path, *, page: int, payload: dict) -> Path:
    target = _page_path(output_dir, page)
    building = target.with_name(target.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(target)
    return target


def _read_page(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _write_manifest(output_dir: Path, payload: dict) -> Path:
    target = output_dir / "manifest.json"
    building = target.with_name(target.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(target)
    return target


def export_all(
    *,
    output_dir: Path,
    page_size: int = 1000,
    fetch_json: Callable[[str], dict] | None = None,
    request_delay: float = 0.2,
    enforce_ssd_reserve: bool = False,
) -> Path:
    if page_size < 1:
        raise ValueError("page_size must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch_json or _fetch_json

    first_path = _page_path(output_dir, 1)
    if first_path.exists():
        first = _read_page(first_path)
    else:
        first = fetch(build_url(page=1, page_size=page_size))
        _write_page(output_dir, page=1, payload=first)
    total = parse_total(first)
    page_count = math.ceil(total / page_size)
    downloaded = 0
    pages: list[int] = []

    for page in range(1, page_count + 1):
        path = _page_path(output_dir, page)
        if page == 1:
            payload = first
        elif path.exists():
            payload = _read_page(path)
        else:
            if enforce_ssd_reserve:
                ensure_capacity(
                    available_bytes=shutil.disk_usage(output_dir).free,
                    expected_bytes=0,
                )
            if request_delay:
                time.sleep(request_delay)
            payload = fetch(build_url(page=page, page_size=page_size))
            _write_page(output_dir, page=page, payload=payload)
        downloaded += len(payload)
        pages.append(page)
        _write_manifest(
            output_dir,
            {
                "source": "AFLOW AFLUX API",
                "endpoint": ENDPOINT,
                "fields": list(FIELDS),
                "page_size": page_size,
                "total_documents": total,
                "downloaded_documents": downloaded,
                "pages": pages,
                "complete": downloaded == total,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    if downloaded != total:
        raise RuntimeError(f"downloaded {downloaded} AFLOW entries, expected {total}")
    return output_dir / "manifest.json"


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    snapshot = datetime.now(timezone.utc).date().isoformat()
    output = args.output or (
        default_data_root() / "raw" / "acquired" / "aflow" / f"aflux-{snapshot}"
    )
    manifest = export_all(
        output_dir=output,
        page_size=args.page_size,
        request_delay=args.request_delay,
        enforce_ssd_reserve=True,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
