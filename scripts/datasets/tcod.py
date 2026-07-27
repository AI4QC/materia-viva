#!/usr/bin/env python3
"""Discover and resumably download final TCOD crystal CIF records."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from scripts.datasets.acquire import (
    build_curl_command,
    default_data_root,
    ensure_capacity,
    write_receipt,
)


BASE_URL = "https://www.crystallography.net/tcod/cif/"
BASE_PATH = urlparse(BASE_URL).path


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def extract_tcod_links(base_url: str, html: str) -> tuple[list[str], list[str]]:
    """Extract same-origin numeric directories and numbered CIF records."""
    parser = _LinkParser()
    parser.feed(html)
    base = urlparse(base_url)
    directories: set[str] = set()
    cifs: set[str] = set()
    for href in parser.hrefs:
        parsed_href = urlparse(href)
        if parsed_href.query or parsed_href.fragment:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme != "https" or parsed.netloc != base.netloc:
            continue
        if not parsed.path.startswith(BASE_PATH):
            continue
        name = PurePosixPath(parsed.path.rstrip("/")).name
        if parsed.path.endswith("/") and re.fullmatch(r"\d+", name):
            directories.add(absolute)
        elif re.fullmatch(r"\d+\.cif", name):
            cifs.add(absolute)
    return sorted(directories), sorted(cifs)


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "CMU-dataset-acquisition/1.0"})
    with urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8")


def discover_cifs(*, fetch_text=_fetch_text) -> list[str]:
    pending = [BASE_URL]
    visited: set[str] = set()
    cifs: set[str] = set()
    while pending:
        url = pending.pop(0)
        if url in visited:
            continue
        visited.add(url)
        directories, found = extract_tcod_links(url, fetch_text(url))
        cifs.update(found)
        pending.extend(directory for directory in directories if directory not in visited)
    return sorted(cifs)


def _relative_cif_path(url: str) -> Path:
    path = urlparse(url).path
    if not path.startswith(BASE_PATH):
        raise ValueError(f"TCOD URL is outside the CIF tree: {url}")
    relative = PurePosixPath(path.removeprefix(BASE_PATH))
    if ".." in relative.parts or not re.fullmatch(r"\d+\.cif", relative.name):
        raise ValueError(f"unsafe TCOD CIF path: {url}")
    return Path(*relative.parts)


def _write_manifest(output_dir: Path, *, urls: list[str], downloaded: int) -> Path:
    target = output_dir / "manifest.json"
    building = target.with_name(target.name + ".building")
    building.write_text(
        json.dumps(
            {
                "source": "Theoretical Crystallography Open Database",
                "base_url": BASE_URL,
                "record_urls": urls,
                "total_documents": len(urls),
                "downloaded_documents": downloaded,
                "complete": downloaded == len(urls),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    building.replace(target)
    return target


def download_all(
    *, data_root: Path, output_dir: Path, request_delay: float = 0.05
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        urls = prior.get("record_urls") or discover_cifs()
    else:
        urls = discover_cifs()
    _write_manifest(output_dir, urls=urls, downloaded=0)

    downloaded = 0
    for url in urls:
        target = output_dir / _relative_cif_path(url)
        if not target.exists():
            ensure_capacity(available_bytes=shutil.disk_usage(data_root).free, expected_bytes=0)
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            subprocess.run(build_curl_command(url, part), check=True)
            part.replace(target)
            write_receipt(target, data_root=data_root, source_id="tcod", url=url)
            if request_delay:
                time.sleep(request_delay)
        downloaded += 1
        if downloaded % 25 == 0 or downloaded == len(urls):
            _write_manifest(output_dir, urls=urls, downloaded=downloaded)
    return _write_manifest(output_dir, urls=urls, downloaded=downloaded)


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--request-delay", type=float, default=0.05)
    parser.add_argument("--enumerate-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data_root = default_data_root()
    output = args.output or data_root / "raw" / "acquired" / "tcod"
    if args.enumerate_only:
        urls = discover_cifs()
        output.mkdir(parents=True, exist_ok=True)
        manifest = _write_manifest(output, urls=urls, downloaded=0)
    else:
        manifest = download_all(
            data_root=data_root, output_dir=output, request_delay=args.request_delay
        )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
