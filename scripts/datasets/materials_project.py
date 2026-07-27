#!/usr/bin/env python3
"""Resumable Materials Project summary export."""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root


SUMMARY_ENDPOINT = "https://api.materialsproject.org/materials/summary/"


def build_request(*, skip: int, limit: int, api_key: str) -> Request:
    query = urlencode({"_skip": skip, "_limit": limit, "_all_fields": "true"})
    return Request(
        f"{SUMMARY_ENDPOINT}?{query}",
        headers={"X-API-KEY": api_key, "User-Agent": "MateriaViva-dataset-acquisition/1.0"},
    )


def write_page(directory: Path, *, offset: int, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"page-{offset:09d}.json.gz"
    building = target.with_name(target.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(target)
    return target


def completed_offsets(directory: Path) -> set[int]:
    pattern = re.compile(r"^page-(\d{9})\.json\.gz$")
    offsets: set[int] = set()
    if not directory.exists():
        return offsets
    for path in directory.iterdir():
        match = pattern.match(path.name)
        if match:
            offsets.add(int(match.group(1)))
    return offsets


def _read_page(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _fetch_json(request: Request, *, attempts: int = 5) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=300) as response:
                return json.load(response)
        except Exception as error:  # urllib exposes several transient exception types
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(30, 2**attempt))
    assert last_error is not None
    raise last_error


def _write_manifest(output_dir: Path, payload: dict) -> Path:
    target = output_dir / "manifest.json"
    building = target.with_name(target.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(target)
    return target


def export_all(
    *,
    output_dir: Path,
    api_key: str,
    page_size: int = 1000,
    fetch_json: Callable[[Request], dict] | None = None,
    request_delay: float = 0.2,
) -> Path:
    """Export all SummaryDoc records into independently resumable gzip pages."""
    if not api_key:
        raise ValueError("MP_API_KEY is required")
    if not 1 <= page_size <= 1000:
        raise ValueError("page_size must be between 1 and the API maximum of 1000")
    output_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch_json or _fetch_json
    offsets = completed_offsets(output_dir)

    first_path = output_dir / "page-000000000.json.gz"
    if 0 in offsets:
        first = _read_page(first_path)
    else:
        first = fetch(build_request(skip=0, limit=page_size, api_key=api_key))
        write_page(output_dir, offset=0, payload=first)
        offsets.add(0)

    meta = first.get("meta", {})
    total = int(meta.get("total_doc", 0))
    if total <= 0:
        raise RuntimeError("Materials Project response did not provide a positive meta.total_doc")

    downloaded = 0
    page_offsets: list[int] = []
    for offset in range(0, total, page_size):
        page_path = output_dir / f"page-{offset:09d}.json.gz"
        if offset == 0:
            payload = first
        elif offset in offsets:
            payload = _read_page(page_path)
        else:
            if request_delay:
                time.sleep(request_delay)
            payload = fetch(build_request(skip=offset, limit=page_size, api_key=api_key))
            write_page(output_dir, offset=offset, payload=payload)
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise RuntimeError(f"invalid data payload at offset {offset}")
        downloaded += len(rows)
        page_offsets.append(offset)
        _write_manifest(
            output_dir,
            {
                "source": "Materials Project summary API",
                "endpoint": SUMMARY_ENDPOINT,
                "api_version": meta.get("api_version"),
                "page_size": page_size,
                "total_documents": total,
                "downloaded_documents": downloaded,
                "page_offsets": page_offsets,
                "complete": downloaded == total,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    if downloaded != total:
        raise RuntimeError(f"downloaded {downloaded} documents, expected {total}")
    return output_dir / "manifest.json"


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    api_key = os.environ.get("MP_API_KEY") or os.environ.get("MAPI_KEY")
    if not api_key:
        parser.error("set MP_API_KEY (or legacy MAPI_KEY) in the environment")
    snapshot = datetime.now(timezone.utc).date().isoformat()
    output = args.output or (
        default_data_root() / "raw" / "acquired" / "materials-project" / f"summary-{snapshot}"
    )
    manifest = export_all(
        output_dir=output,
        api_key=api_key,
        page_size=args.page_size,
        request_delay=args.request_delay,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
