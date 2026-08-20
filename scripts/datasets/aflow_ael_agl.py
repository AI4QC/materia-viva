#!/usr/bin/env python3
"""AFLUX exporter for AFLOW AEL (elastic) and AGL (thermal) properties.

The 2026-07-26 AFLUX snapshot was fetched without the ael_*/agl_* columns and
the CFID mirror carries them all-null, so this one-off pulls just the entries
where either workflow ran:

    ?ael_bulk_modulus_vrh(*):agl_debye(*),<bare select fields>,$paging(p,n)

AFLUX syntax notes (verified against the live endpoint, 2026-08):

* ``field(*)``      match-any filter: only entries where the field exists
* ``:``             logical OR between two filter tokens
* bare ``field``    selects the column WITHOUT filtering (null when absent)
* ``$paging(p,n)``  page p (1-based) of size n; ``$paging(0)`` disables
                    paging and returns the full matching set (used for the
                    exact count before paging starts)
* responses are plain JSON arrays of records

Pages land in data/raw/acquired/aflow/aflux-ael-agl-<date>/page-*.json with a
manifest.json, mirroring the aflux-2026-07-26 layout (uncompressed: the whole
set is ~3 MB). Serial requests, page size <= 1000, retry with backoff.
"""

from __future__ import annotations

import json
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root

ENDPOINT = "https://aflow.org/API/aflux/"
#: filter: entries where the AEL or the AGL workflow produced results
FILTER = "ael_bulk_modulus_vrh(*):agl_debye(*)"
#: bare (non-filtering) column selections; the two filter fields are
#: selected by the filter tokens themselves, auid/compound/aurl by default
SELECT_FIELDS = (
    "auid",
    "ael_shear_modulus_vrh",
    "ael_poisson_ratio",
    "agl_thermal_conductivity_300K",
    "agl_heat_capacity_Cp_300K",
    "agl_thermal_expansion_300K",
)
MAX_PAGE_SIZE = 1000


def build_url(*, page: int, page_size: int) -> str:
    """AFLUX matchbook for one page; page 0 returns the full unpaged set."""
    if page < 0 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError("page must be >= 0 and 1 <= page_size <= 1000")
    paging = "$paging(0)" if page == 0 else f"$paging({page},{page_size})"
    return f"{ENDPOINT}?{FILTER}," + ",".join(SELECT_FIELDS) + f",{paging}"


def _fetch_json(url: str, *, attempts: int = 6) -> list:
    last_error: Exception | None = None
    request = Request(url, headers={"User-Agent": "MateriaViva-dataset-acquisition/1.0"})
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=300) as response:
                payload = json.load(response)
            if isinstance(payload, dict):  # legacy labelled-object format
                payload = list(payload.values())
            if not isinstance(payload, list):
                raise RuntimeError(f"unexpected AFLUX payload type {type(payload)}")
            return payload
        except Exception as error:  # noqa: BLE001 - retry then re-raise
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(60, 2 ** (attempt + 1)))
    assert last_error is not None
    raise last_error


def _write_json(path: Path, payload) -> Path:
    building = path.with_name(path.name + ".building")
    building.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if path.name.startswith("page-")
        else json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    building.replace(path)
    return path


def export_all(*, output_dir: Path, page_size: int = MAX_PAGE_SIZE,
               request_delay: float = 1.0) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)

    # exact count first: $paging(0) returns the complete matching set
    count_url = build_url(page=0, page_size=page_size)
    total = len(_fetch_json(count_url))
    print(f"AFLUX reports {total} AEL/AGL entries", flush=True)

    downloaded = 0
    pages: list[int] = []
    page = 0
    while downloaded < total:
        page += 1
        path = output_dir / f"page-{page:09d}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            time.sleep(request_delay)
            payload = _fetch_json(build_url(page=page, page_size=page_size))
            _write_json(path, payload)
        if not payload:
            break
        downloaded += len(payload)
        pages.append(page)
        _write_json(output_dir / "manifest.json", {
            "source": "AFLOW AFLUX API (AEL elastic + AGL thermal subset)",
            "endpoint": ENDPOINT,
            "query": build_url(page=1, page_size=page_size),
            "count_query": count_url,
            "filter": FILTER,
            "select_fields": list(SELECT_FIELDS),
            "page_size": page_size,
            "total_documents": total,
            "downloaded_documents": downloaded,
            "pages": pages,
            "complete": downloaded == total,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"page {page}: +{len(payload)} ({downloaded}/{total})", flush=True)

    if downloaded != total:
        raise RuntimeError(f"downloaded {downloaded} entries, expected {total}")
    return output_dir / "manifest.json"


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--page-size", type=int, default=MAX_PAGE_SIZE)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (
        default_data_root() / "raw" / "acquired" / "aflow"
        / "aflux-ael-agl-2026-08-18"
    )
    print(export_all(output_dir=output, page_size=args.page_size,
                     request_delay=args.request_delay))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
