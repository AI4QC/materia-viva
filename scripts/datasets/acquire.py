#!/usr/bin/env python3
"""Validate the source catalog and acquire source-native archives on the SSD."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESERVE_BYTES = 50 * 1024**3
ACCESS_MODES = {
    "open",
    "api-key",
    "free-registration",
    "licensed",
    "paid",
    "federated",
}
# Source lifecycle, see docs/self-evolving-loop.zh-CN.md section 2.1. `acquired`
# means the files are here; whether an adapter exists yet is answered by
# scripts/properties/adapters/, not by a second state.
SOURCE_STATES = {"registered", "acquired", "integrated", "rejected", "quarantined"}
TERMINAL_STATES = {"rejected", "quarantined"}
# section 2.2 — a terminal state must say why, in a code a script can group on
REASON_CODES = {
    "licence-unclear",
    "licence-restricted",
    "account-required",
    "no-bulk-interface",
    "scope-trajectory",
    "scope-unbounded",
    "join-key-missing",
    "integrity-failed",
}


class CapacityError(RuntimeError):
    """Raised before a download would consume the SSD safety reserve."""


def default_data_root(repo_root: Path | None = None) -> Path:
    """Return the configured data root, resolving the repository data link."""
    override = os.environ.get("MV_DATA_ROOT")
    repository = Path(repo_root).resolve() if repo_root is not None else REPOSITORY_ROOT
    root = Path(override).expanduser() if override else repository / "data"
    return root.resolve()


def load_catalog(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _validate_state(source_id: str, source: dict[str, Any]) -> None:
    """Check the optional lifecycle pair. Absent `state` reads as `registered`."""
    state = source.get("state")
    if state is None:
        if "reason" in source:
            raise ValueError(f"reason without state for {source_id}")
        return
    if state not in SOURCE_STATES:
        raise ValueError(f"unsupported state for {source_id}: {state}")
    reason = source.get("reason")
    if state in TERMINAL_STATES:
        if reason not in REASON_CODES:
            raise ValueError(f"{state} needs a known reason code for {source_id}: {reason}")
    elif reason is not None:
        raise ValueError(f"{state} must not carry a reason for {source_id}")


def validate_catalog(catalog: dict[str, Any]) -> None:
    # version 2 adds the optional `state` / `reason` pair; version 1 files load
    # unchanged because every entry without them reads as `registered`
    if catalog.get("schema_version") not in (1, 2):
        raise ValueError("catalog schema_version must be 1 or 2")
    sources = catalog.get("sources")
    if not isinstance(sources, list):
        raise ValueError("catalog sources must be a list")
    seen: set[str] = set()
    required = {"id", "name", "access", "official_url", "license", "data_path"}
    for source in sources:
        missing = required - source.keys()
        if missing:
            raise ValueError(f"source is missing fields: {sorted(missing)}")
        source_id = source["id"]
        if source_id in seen:
            raise ValueError(f"duplicate source id: {source_id}")
        seen.add(source_id)
        if source["access"] not in ACCESS_MODES:
            raise ValueError(f"unsupported access mode for {source_id}")
        if not str(source["official_url"]).startswith("https://"):
            raise ValueError(f"official_url must use HTTPS for {source_id}")
        if not _is_safe_relative_path(source["data_path"]):
            raise ValueError(f"data_path must be a safe relative path for {source_id}")
        _validate_state(source_id, source)
        for item in source.get("downloads", []):
            if not str(item.get("url", "")).startswith("https://"):
                raise ValueError(f"download URL must use HTTPS for {source_id}")
            if not _is_safe_relative_path(str(item.get("filename", ""))):
                raise ValueError(f"download filename must be a safe relative path for {source_id}")
            size = item.get("bytes")
            if size is not None and (not isinstance(size, int) or size < 0):
                raise ValueError(f"invalid byte size for {source_id}")
        for index in source.get("indexes", []):
            if not str(index.get("url", "")).startswith("https://"):
                raise ValueError(f"index URL must use HTTPS for {source_id}")
            if not _is_safe_relative_path(str(index.get("destination", ""))):
                raise ValueError(f"index destination must be a safe relative path for {source_id}")
            if not index.get("suffixes"):
                raise ValueError(f"index suffixes are required for {source_id}")


def ensure_capacity(
    *,
    available_bytes: int,
    expected_bytes: int,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
) -> None:
    if available_bytes - expected_bytes < reserve_bytes:
        raise CapacityError(
            "download would violate the 50 GiB reserve "
            f"(available={available_bytes}, expected={expected_bytes})"
        )


def build_curl_command(url: str, part_path: Path) -> list[str]:
    """Build one protected resume attempt without curl-internal retries.

    Curl reopens its output file during an internal retry and can truncate a
    partially downloaded file before ``--continue-at -`` is recalculated.  A
    single invocation therefore makes exactly one attempt; retries are handled
    by :func:`run_curl_resumable`, which starts a fresh process for each offset.
    """
    return [
        "curl",
        "--fail",
        "--location",
        "--retry",
        "0",
        "--continue-at",
        "-",
        "--output",
        str(part_path),
        url,
    ]


def run_curl_resumable(
    url: str,
    part_path: Path,
    *,
    retries: int = 5,
    run_command: Any = subprocess.run,
    sleep: Any = time.sleep,
) -> None:
    """Retry with fresh curl processes so every attempt resumes current bytes."""
    if retries < 0:
        raise ValueError("retries must be non-negative")
    for attempt in range(retries + 1):
        try:
            run_command(build_curl_command(url, part_path), check=True)
            return
        except subprocess.CalledProcessError:
            if attempt == retries:
                raise
            delay = min(30, 2**attempt)
            saved_bytes = part_path.stat().st_size if part_path.exists() else 0
            print(
                f"download interrupted; preserving {saved_bytes} bytes in "
                f"{part_path} and retrying in {delay}s",
                flush=True,
            )
            sleep(delay)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


def extract_index_downloads(
    base_url: str,
    html: str,
    *,
    suffixes: tuple[str, ...],
) -> list[dict[str, str]]:
    """Extract safe, matching file links from an Apache-style directory index."""
    parser = _LinkParser()
    parser.feed(html)
    items: list[dict[str, str]] = []
    for href in parser.hrefs:
        parsed = urlparse(href)
        filename = PurePosixPath(parsed.path).name
        if not filename or not filename.endswith(suffixes):
            continue
        if not _is_safe_relative_path(filename):
            continue
        items.append({"filename": filename, "url": urljoin(base_url, href)})
    return sorted(items, key=lambda item: item["filename"])


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "MateriaViva-dataset-acquisition/1.0"})
    with urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8")


def expand_source_downloads(
    source: dict[str, Any],
    *,
    fetch_text: Any = None,
) -> list[dict[str, Any]]:
    fetch = fetch_text or _fetch_text
    items = [dict(item) for item in source.get("downloads", [])]
    for index in source.get("indexes", []):
        discovered = extract_index_downloads(
            index["url"],
            fetch(index["url"]),
            suffixes=tuple(index["suffixes"]),
        )
        for item in discovered:
            item["filename"] = str(PurePosixPath(index["destination"]) / item["filename"])
            items.append(item)
    return items


def write_receipt(
    path: Path,
    *,
    data_root: Path,
    source_id: str,
    url: str,
) -> Path:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    payload = {
        "source_id": source_id,
        "url": url,
        "path": str(path.relative_to(data_root)),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt = path.with_name(path.name + ".receipt.json")
    building = receipt.with_name(receipt.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(receipt)
    return receipt


def _download_item(
    data_root: Path,
    source: dict[str, Any],
    item: dict[str, Any],
    *,
    retries: int = 5,
) -> Path:
    directory = data_root / source["data_path"]
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / item["filename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (item.get("bytes") is None or target.stat().st_size == item["bytes"]):
        return target
    part = target.with_name(target.name + ".part")
    expected_remaining = max(0, int(item.get("bytes") or 0) - (part.stat().st_size if part.exists() else 0))
    ensure_capacity(
        available_bytes=shutil.disk_usage(data_root).free,
        expected_bytes=expected_remaining,
    )
    run_curl_resumable(item["url"], part, retries=retries)
    if item.get("bytes") is not None and part.stat().st_size != item["bytes"]:
        raise RuntimeError(
            f"size mismatch for {source['id']}/{item['filename']}: "
            f"got {part.stat().st_size}, expected {item['bytes']}"
        )
    part.replace(target)
    write_receipt(
        target,
        data_root=data_root,
        source_id=source["id"],
        url=item["url"],
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).with_name("sources.json"))
    parser.add_argument("--source", action="append", help="Source id to download; repeatable")
    parser.add_argument("--list", action="store_true", help="List catalog entries")
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    validate_catalog(catalog)
    selected = set(args.source or [])
    for source in catalog["sources"]:
        if args.list:
            print(f"{source['id']}\t{source.get('status', 'cataloged')}\t{source['name']}")
            continue
        if selected and source["id"] not in selected:
            continue
        if source.get("estimated_bytes"):
            ensure_capacity(
                available_bytes=shutil.disk_usage(default_data_root()).free,
                expected_bytes=int(source["estimated_bytes"]),
            )
        for item in expand_source_downloads(source):
            path = _download_item(default_data_root(), source, item)
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
