#!/usr/bin/env python3
"""Collect one published msCIF per B-IncStrDB entry."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root, ensure_capacity


BASE_URL = "https://cryst.ehu.es/bincstrdb/"
SEARCH_URL = BASE_URL + "search/?order=entry_date&page={page}"
CREATE_URL = BASE_URL + "create/?incid={entry_id}"
ENTRY_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []
        self.cif_chunks: list[str] = []
        self._in_cif_textarea = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.lower() == "a" and attributes.get("href"):
            self.hrefs.append(str(attributes["href"]))
        elif tag.lower() == "textarea" and attributes.get("id") == "cif-text":
            self._in_cif_textarea = True

    def handle_data(self, data: str) -> None:
        if self._in_cif_textarea:
            self.cif_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "textarea" and self._in_cif_textarea:
            self._in_cif_textarea = False


def _parse_page(html: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html)
    return parser


def extract_entry_ids(html: str) -> list[str]:
    """Return safe, unique B-IncStrDB IDs linked by an official result page."""
    ids: set[str] = set()
    for href in _parse_page(html).hrefs:
        absolute = urlparse(urljoin(BASE_URL, href))
        if absolute.scheme != "https" or absolute.netloc != "cryst.ehu.es":
            continue
        if absolute.path not in {
            "/bincstrdb/view/",
            "/bincstrdb/create/",
            "/bincstrdb/visualize/",
        }:
            continue
        values = parse_qs(absolute.query).get("incid", [])
        if len(values) == 1 and ENTRY_ID_PATTERN.fullmatch(values[0]):
            ids.add(values[0])
    return sorted(ids)


def extract_page_numbers(html: str) -> list[int]:
    pages = {1}
    for href in _parse_page(html).hrefs:
        absolute = urlparse(urljoin(BASE_URL, href))
        if absolute.netloc != "cryst.ehu.es" or absolute.path != "/bincstrdb/search/":
            continue
        values = parse_qs(absolute.query).get("page", [])
        if len(values) == 1 and values[0].isdigit() and int(values[0]) > 0:
            pages.add(int(values[0]))
    return sorted(pages)


def extract_cif_text(html: str) -> str:
    """Extract the exact msCIF payload offered by the site's download button."""
    chunks = _parse_page(html).cif_chunks
    if not chunks:
        raise RuntimeError("B-IncStrDB download page did not contain a CIF textarea")
    cif = "".join(chunks).replace("\r\n", "\n").replace("\r", "\n")
    if not cif.endswith("\n"):
        cif += "\n"
    if not re.search(r"(?m)^data_", cif):
        raise RuntimeError("B-IncStrDB textarea did not contain an msCIF data block")
    return cif


def _fetch_text(url: str, *, attempts: int = 5) -> str:
    request = Request(url, headers={"User-Agent": "CMU-dataset-acquisition/1.0"})
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=180) as response:
                return response.read().decode("utf-8")
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(30, 2**attempt))
    assert last_error is not None
    raise last_error


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".building")
    building.write_text(text, encoding="utf-8")
    building.replace(path)


def _write_gzip_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        handle.write(text)
    building.replace(path)


def _write_manifest(output_dir: Path, *, ids: list[str], complete: bool) -> Path:
    records = output_dir / "records"
    downloaded = sum((records / f"{entry_id}.cif").exists() for entry_id in ids)
    target = output_dir / "manifest.json"
    payload = {
        "source": "Bilbao Incommensurate Structures Database",
        "base_url": BASE_URL,
        "scope": "one published static msCIF per database entry; no trajectories",
        "entry_ids": ids,
        "total_documents": len(ids),
        "downloaded_documents": downloaded,
        "complete": complete and downloaded == len(ids),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_text_atomic(target, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target


def export_all(
    *,
    output_dir: Path,
    fetch_text=_fetch_text,
    request_delay: float = 0.2,
    enforce_ssd_reserve: bool = False,
) -> Path:
    """Discover every entry and resumably save its single published msCIF."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        ids = list(prior.get("entry_ids") or [])
    else:
        first = fetch_text(SEARCH_URL.format(page=1))
        page_numbers = extract_page_numbers(first)
        pages = {1: first}
        for page in range(2, max(page_numbers) + 1):
            if request_delay:
                time.sleep(request_delay)
            pages[page] = fetch_text(SEARCH_URL.format(page=page))
        ids = sorted({entry_id for html in pages.values() for entry_id in extract_entry_ids(html)})
        if not ids:
            raise RuntimeError("B-IncStrDB search pages did not yield any entry IDs")
        for page, html in pages.items():
            _write_gzip_atomic(output_dir / "source-pages" / f"page-{page:04d}.html.gz", html)
        _write_manifest(output_dir, ids=ids, complete=False)

    records = output_dir / "records"
    for index, entry_id in enumerate(ids, start=1):
        target = records / f"{entry_id}.cif"
        if not target.exists():
            if enforce_ssd_reserve:
                ensure_capacity(available_bytes=shutil.disk_usage(output_dir).free, expected_bytes=0)
            if request_delay:
                time.sleep(request_delay)
            page = fetch_text(CREATE_URL.format(entry_id=entry_id))
            cif = extract_cif_text(page)
            _write_text_atomic(target, cif)
            receipt = {
                "source_id": "b-incstrdb",
                "source_record_id": entry_id,
                "url": CREATE_URL.format(entry_id=entry_id),
                "sha256": hashlib.sha256(cif.encode("utf-8")).hexdigest(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
            _write_text_atomic(
                target.with_suffix(".receipt.json"),
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            )
        if index % 25 == 0:
            _write_manifest(output_dir, ids=ids, complete=False)
    return _write_manifest(output_dir, ids=ids, complete=True)


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--request-delay", type=float, default=0.2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or default_data_root() / "raw" / "acquired" / "b-incstrdb"
    manifest = export_all(
        output_dir=output,
        request_delay=args.request_delay,
        enforce_ssd_reserve=True,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
