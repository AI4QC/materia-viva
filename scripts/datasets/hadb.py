#!/usr/bin/env python3
"""Collect one final structure per static HADB entry while excluding AIMD frames."""

from __future__ import annotations

import gzip
import hashlib
import html as html_module
import json
import re
import shutil
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root, ensure_capacity


BASE_URL = "https://hadb.funmat-ii.se/"
INDEX_URL = BASE_URL + "search_page?q="


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []
        self._row: dict | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._row = {"cells": [], "hrefs": []}
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []
        elif tag.lower() == "a" and self._row is not None:
            href = dict(attrs).get("href")
            if href:
                self._row["hrefs"].append(href)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row["cells"].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag.lower() == "tr" and self._row is not None:
            if self._row["cells"]:
                self.rows.append(self._row)
            self._row = None
            self._cell = None


def _parse_tables(html: str) -> list[dict]:
    parser = _TableParser()
    parser.feed(html)
    return parser.rows


def select_static_materials(html: str) -> list[dict]:
    """Return material rows whose method denotes a static DFT/MLIP endpoint."""
    selected: list[dict] = []
    for row in _parse_tables(html):
        if len(row["cells"]) < 4:
            continue
        method = row["cells"][3].strip().upper()
        if method not in {"DFT", "MLIP"}:
            continue
        material_id: int | None = None
        for href in row["hrefs"]:
            values = parse_qs(urlparse(href).query).get("material_id", [])
            if values and values[0].isdigit():
                material_id = int(values[0])
                break
        if material_id is None:
            continue
        selected.append(
            {
                "material_id": material_id,
                "formula": row["cells"][1],
                "temperature": row["cells"][2],
                "method": method,
                "index_cells": row["cells"],
            }
        )
    return sorted(selected, key=lambda item: item["material_id"])


def extract_embedded_cif(html: str) -> str:
    """Decode the exact final CIF supplied to HADB's browser structure viewer."""
    match = re.search(
        r'vewer\.addModel\(\s*("(?:\\.|[^"\\])*")\s*,\s*"cif"\s*\)'.replace(
            "vewer", "viewer"
        ),
        html,
    )
    if not match:
        raise RuntimeError("HADB material page did not contain an embedded final CIF")
    return html_module.unescape(json.loads(match.group(1)))


def _fetch_text(url: str, *, attempts: int = 5) -> str:
    request = Request(url, headers={"User-Agent": "MateriaViva-dataset-acquisition/1.0"})
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=300) as response:
                return response.read().decode("utf-8")
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(30, 2**attempt))
    assert last_error is not None
    raise last_error


def _record_path(output_dir: Path, material_id: int) -> Path:
    return output_dir / "records" / f"material-{material_id:06d}.json.gz"


def _write_gzip_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(path)
    return path


def _write_manifest(output_dir: Path, payload: dict) -> Path:
    target = output_dir / "manifest.json"
    building = target.with_name(target.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(target)
    return target


def export_static(
    *,
    output_dir: Path,
    fetch_text=_fetch_text,
    request_delay: float = 0.2,
    enforce_ssd_reserve: bool = False,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_html = fetch_text(INDEX_URL)
    materials = select_static_materials(index_html)
    if not materials:
        raise RuntimeError("HADB index did not yield any static materials")
    index_target = output_dir / "source-index.html.gz"
    if not index_target.exists():
        building = index_target.with_name(index_target.name + ".building")
        with gzip.open(building, "wt", encoding="utf-8") as handle:
            handle.write(index_html)
        building.replace(index_target)

    completed: list[int] = []
    for material in materials:
        material_id = material["material_id"]
        target = _record_path(output_dir, material_id)
        if not target.exists():
            if enforce_ssd_reserve:
                ensure_capacity(available_bytes=shutil.disk_usage(output_dir).free, expected_bytes=0)
            if request_delay:
                time.sleep(request_delay)
            source_url = f"{BASE_URL}search_page?material_id={material_id}&q="
            page = fetch_text(source_url)
            _write_gzip_json(
                target,
                {
                    **material,
                    "source_url": source_url,
                    "source_html_sha256": hashlib.sha256(page.encode("utf-8")).hexdigest(),
                    "cif": extract_embedded_cif(page),
                    "table_rows": [row["cells"] for row in _parse_tables(page)],
                },
            )
        completed.append(material_id)
        if len(completed) % 10 == 0 or len(completed) == len(materials):
            _write_manifest(
                output_dir,
                {
                    "source": "Hard-coating Alloys Database",
                    "index_url": INDEX_URL,
                    "scope": "one final CIF per DFT or MLIP material entry",
                    "excluded_methods": ["AIMD"],
                    "total_static_documents": len(materials),
                    "downloaded_documents": len(completed),
                    "material_ids": completed,
                    "complete": len(completed) == len(materials),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    return output_dir / "manifest.json"


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or default_data_root() / "raw" / "acquired" / "hadb"
    manifest = export_static(
        output_dir=output,
        request_delay=args.request_delay,
        enforce_ssd_reserve=True,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
