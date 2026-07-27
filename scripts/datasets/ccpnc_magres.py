#!/usr/bin/env python3
"""Download the latest static CCP-NC Magres structure/property records by licence."""

from __future__ import annotations

import gzip
import json
import shutil
import time
import zipfile
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root, ensure_capacity, write_receipt


BASE_URL = "https://www.ccpnc.ac.uk/database"
SEARCH_URL = BASE_URL + "/search"
DOWNLOAD_URL = BASE_URL + "/download_selection_zip"
LICENCES = ("pddl", "cc-by", "odc-by")


def latest_file_items(rows: list[dict]) -> list[dict]:
    """Build the site's bulk-download payload with one latest version per record."""
    items: list[dict] = []
    for row in rows:
        version_count = int(row.get("version_count", 1))
        file_id = row.get("last_version", {}).get("magresFilesID")
        immutable_id = str(row.get("immutable_id", ""))
        if not file_id or not immutable_id:
            raise RuntimeError("CCP-NC record is missing immutable_id or latest Magres file id")
        items.append(
            {
                "fileID": file_id,
                "filename": "MRD" + immutable_id,
                "jsonData": row,
                "version": version_count - 1,
            }
        )
    return items


def _post_json(url: str, payload: dict, *, timeout: int = 600, attempts: int = 5):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "CMU-dataset-acquisition/1.0",
                },
            )
            return urlopen(request, timeout=timeout)
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(30, 2**attempt))
    assert last_error is not None
    raise last_error


def search_records(licence: str) -> list[dict]:
    if licence not in LICENCES:
        raise ValueError(f"unsupported CCP-NC licence: {licence}")
    payload = {
        "search_spec": [
            {
                "type": "license",
                "args": {"license": licence},
                "negate_query": False,
            }
        ]
    }
    with _post_json(SEARCH_URL, payload) as response:
        result = json.load(response)
    if not isinstance(result, list):
        raise RuntimeError(f"CCP-NC search returned an invalid {licence} result")
    return result


def _write_metadata(path: Path, rows: list[dict]) -> Path:
    building = path.with_name(path.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(path)
    return path


def _write_manifest(output_dir: Path, payload: dict) -> Path:
    target = output_dir / "manifest.json"
    building = target.with_name(target.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(target)
    return target


def _download_chunk(
    *, target: Path, items: list[dict], data_root: Path, request_delay: float
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with zipfile.ZipFile(target) as archive:
            if archive.testzip() is None:
                return target
        raise RuntimeError(f"invalid existing CCP-NC ZIP: {target}")
    ensure_capacity(available_bytes=shutil.disk_usage(data_root).free, expected_bytes=0)
    if request_delay:
        time.sleep(request_delay)
    part = target.with_name(target.name + ".part")
    with _post_json(DOWNLOAD_URL, {"files": items}, timeout=1800) as response:
        if response.headers.get_content_type() != "application/zip":
            raise RuntimeError("CCP-NC bulk endpoint did not return a ZIP archive")
        with part.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=8 * 1024 * 1024)
    with zipfile.ZipFile(part) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"corrupt CCP-NC ZIP member: {bad_member}")
    part.replace(target)
    write_receipt(target, data_root=data_root, source_id="ccpnc-magres", url=DOWNLOAD_URL)
    return target


def export_all(
    *,
    data_root: Path,
    output_dir: Path,
    chunk_size: int = 250,
    request_delay: float = 0.2,
) -> Path:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    completed_chunks: dict[str, list[str]] = {}

    for licence in LICENCES:
        metadata_path = output_dir / f"metadata-{licence}.json.gz"
        if metadata_path.exists():
            with gzip.open(metadata_path, "rt", encoding="utf-8") as handle:
                rows = json.load(handle)
        else:
            rows = search_records(licence)
            _write_metadata(metadata_path, rows)
        items = latest_file_items(rows)
        counts[licence] = len(items)
        completed_chunks[licence] = []
        for chunk_number, start in enumerate(range(0, len(items), chunk_size)):
            target = output_dir / licence / f"latest-{chunk_number:05d}.zip"
            _download_chunk(
                target=target,
                items=items[start : start + chunk_size],
                data_root=data_root,
                request_delay=request_delay,
            )
            completed_chunks[licence].append(str(target.relative_to(output_dir)))
            _write_manifest(
                output_dir,
                {
                    "source": "CCP-NC Magres Database",
                    "scope": "latest static Magres file per immutable crystal record",
                    "licence_counts": counts,
                    "completed_chunks": completed_chunks,
                    "total_documents": sum(counts.values()),
                    "complete": False,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    return _write_manifest(
        output_dir,
        {
            "source": "CCP-NC Magres Database",
            "scope": "latest static Magres file per immutable crystal record",
            "licence_counts": counts,
            "completed_chunks": completed_chunks,
            "total_documents": sum(counts.values()),
            "complete": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-size", type=int, default=250)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data_root = default_data_root()
    output = args.output or data_root / "raw" / "acquired" / "ccpnc-magres"
    manifest = export_all(
        data_root=data_root,
        output_dir=output,
        chunk_size=args.chunk_size,
        request_delay=args.request_delay,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
