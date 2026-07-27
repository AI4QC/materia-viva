#!/usr/bin/env python3
"""Resumable OPTIMADE structure exporter for bounded public providers."""

from __future__ import annotations

import gzip
import json
import math
import shutil
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root, ensure_capacity


COMMON_STRUCTURE_FIELDS = (
    "id",
    "immutable_id",
    "last_modified",
    "elements",
    "nelements",
    "chemical_formula_descriptive",
    "chemical_formula_reduced",
    "chemical_formula_hill",
    "chemical_formula_anonymous",
    "dimension_types",
    "nperiodic_dimensions",
    "lattice_vectors",
    "cartesian_site_positions",
    "nsites",
    "species",
    "species_at_sites",
    "structure_features",
)

PROVIDERS = {
    "odbx": {
        "source_id": "odbx",
        "endpoint": "https://optimade.odbx.science/v1/structures",
        "fields": COMMON_STRUCTURE_FIELDS,
    },
    "odbx-misc": {
        "source_id": "odbx",
        "endpoint": "https://optimade-misc.odbx.science/v1/structures",
        "fields": COMMON_STRUCTURE_FIELDS
        + ("_odbx_hull_distance", "_odbx_formation_energy"),
    },
    "mc-2dtopo": {
        "source_id": "materials-cloud-specialized",
        "endpoint": "https://optimade.materialscloud.org/main/2dtopo/v1/structures",
        "fields": (),
    },
    "mc-pyrene-mofs": {
        "source_id": "materials-cloud-specialized",
        "endpoint": "https://optimade.materialscloud.org/main/pyrene-mofs/v1/structures",
        "fields": (),
    },
    "mc-stoceriaitf": {
        "source_id": "materials-cloud-specialized",
        "endpoint": "https://optimade.materialscloud.org/main/stoceriaitf/v1/structures",
        "fields": (),
    },
    "mc-autowannier": {
        "source_id": "materials-cloud-specialized",
        "endpoint": "https://optimade.materialscloud.org/main/autowannier/v1/structures",
        "fields": (),
    },
    "mc-tin-antimony-sulfoiodide": {
        "source_id": "materials-cloud-specialized",
        "endpoint": "https://optimade.materialscloud.org/main/tin-antimony-sulfoiodide/v1/structures",
        "fields": (),
    },
    "mca-optical-2026": {
        "source_id": "materials-cloud-archive-static",
        "endpoint": "https://optimade.materialscloud.org/archive/ed-g2/v1/structures",
        "fields": (),
    },
    "mca-nonlinear-optical-2025": {
        "source_id": "materials-cloud-archive-static",
        "endpoint": "https://optimade.materialscloud.org/archive/1z-pd/v1/structures",
        "fields": (),
    },
    "mca-topological-2025": {
        "source_id": "materials-cloud-archive-static",
        "endpoint": "https://optimade.materialscloud.org/archive/m0-zg/v1/structures",
        "fields": (),
    },
    "mca-electrides-2023": {
        "source_id": "materials-cloud-archive-static",
        "endpoint": "https://optimade.materialscloud.org/archive/zt-z4/v1/structures",
        "fields": (),
    },
}


def build_url(
    *, endpoint: str, offset: int, page_size: int, fields: Sequence[str]
) -> str:
    if offset < 0:
        raise ValueError("offset must not be negative")
    if not 1 <= page_size <= 500:
        raise ValueError("page_size must be between 1 and 500")
    parameters = {"page_limit": page_size, "page_offset": offset}
    if fields:
        parameters["response_fields"] = ",".join(fields)
    query = urlencode(parameters, safe=",_")
    return f"{endpoint.rstrip('/')}?{query}"


def _page_path(output_dir: Path, offset: int) -> Path:
    return output_dir / f"page-{offset:09d}.json.gz"


def _write_page(output_dir: Path, *, offset: int, payload: dict) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = _page_path(output_dir, offset)
    building = target.with_name(target.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(target)
    return target


def _read_page(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _fetch_json(url: str, *, attempts: int = 5) -> dict:
    request = Request(url, headers={"User-Agent": "CMU-dataset-acquisition/1.0"})
    last_error: Exception | None = None
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


def _write_manifest(output_dir: Path, payload: dict) -> Path:
    target = output_dir / "manifest.json"
    building = target.with_name(target.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(target)
    return target


def export_all(
    *,
    output_dir: Path,
    endpoint: str,
    fields: Sequence[str] = COMMON_STRUCTURE_FIELDS,
    page_size: int = 500,
    fetch_json: Callable[[str], dict] | None = None,
    request_delay: float = 0.2,
    enforce_ssd_reserve: bool = False,
) -> Path:
    """Export one provider without mixing provider-specific schemas."""
    if not 1 <= page_size <= 500:
        raise ValueError("page_size must be between 1 and 500")
    output_dir.mkdir(parents=True, exist_ok=True)
    fetch = fetch_json or _fetch_json

    first_path = _page_path(output_dir, 0)
    if first_path.exists():
        first = _read_page(first_path)
    else:
        first = fetch(build_url(endpoint=endpoint, offset=0, page_size=page_size, fields=fields))
        _write_page(output_dir, offset=0, payload=first)

    total = int(first.get("meta", {}).get("data_available", -1))
    if total < 0:
        raise RuntimeError("OPTIMADE response did not provide meta.data_available")
    page_count = math.ceil(total / page_size) if total else 0
    downloaded = 0
    offsets: list[int] = []

    for page_index in range(page_count):
        offset = page_index * page_size
        path = _page_path(output_dir, offset)
        if offset == 0:
            payload = first
        elif path.exists():
            payload = _read_page(path)
        else:
            if enforce_ssd_reserve:
                ensure_capacity(available_bytes=shutil.disk_usage(output_dir).free, expected_bytes=0)
            if request_delay:
                time.sleep(request_delay)
            payload = fetch(
                build_url(endpoint=endpoint, offset=offset, page_size=page_size, fields=fields)
            )
            _write_page(output_dir, offset=offset, payload=payload)
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise RuntimeError(f"invalid OPTIMADE data payload at offset {offset}")
        downloaded += len(rows)
        offsets.append(offset)
        _write_manifest(
            output_dir,
            {
                "source": "OPTIMADE structures API",
                "endpoint": endpoint,
                "fields": list(fields) if fields else "provider-default-all-fields",
                "page_size": page_size,
                "total_documents": total,
                "downloaded_documents": downloaded,
                "page_offsets": offsets,
                "complete": downloaded == total,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    if total == 0:
        return _write_manifest(
            output_dir,
            {
                "source": "OPTIMADE structures API",
                "endpoint": endpoint,
                "fields": list(fields) if fields else "provider-default-all-fields",
                "page_size": page_size,
                "total_documents": 0,
                "downloaded_documents": 0,
                "page_offsets": [],
                "complete": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    if downloaded != total:
        raise RuntimeError(f"downloaded {downloaded} OPTIMADE entries, expected {total}")
    return output_dir / "manifest.json"


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]
    snapshot = datetime.now(timezone.utc).date().isoformat()
    output = args.output or (
        default_data_root()
        / "raw"
        / "acquired"
        / provider["source_id"]
        / f"{args.provider}-{snapshot}"
    )
    manifest = export_all(
        output_dir=output,
        endpoint=provider["endpoint"],
        fields=provider["fields"],
        page_size=args.page_size,
        request_delay=args.request_delay,
        enforce_ssd_reserve=True,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
