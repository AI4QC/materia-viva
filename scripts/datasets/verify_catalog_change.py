#!/usr/bin/env python3
"""Gate a proposed catalog change: check the diff, not the proposer.

Both agent roles that touch the catalog produce the same kind of artifact — a
branch whose diff either adds a source (a discovery candidate) or changes a
source's `downloads[]` (a pull plan). So the gate reads that diff and answers the
contract's questions without trusting whoever produced it.

For a source the diff adds:

* does its `official_url` resolve;
* is it already in the catalog under another id (same host, or the same name);
* if it supplied a `licence_url`, does that resolve. The catalog has no such
  field today and `license` is free text, so this check is conditional rather
  than required — it anchors the agent's licence claim to a page a reviewer can
  open, and its absence is reported rather than passed over.

For a download entry the diff adds or alters:

* does the catalog still validate (https, safe relative filename, integer bytes);
* does each new URL resolve, and is it the size the plan claims;
* would the download fit inside the SSD reserve `acquire.py` protects;
* does a new source claim a `data_path` some other source already owns;
* does any free-text field still name an upstream id the plan just replaced.

Nothing here judges whether a candidate is worth having: the record count it
claims and whether it really is a crystal structure database are claims, and they
queue for the human gates.

Nothing is downloaded and nothing is written. A non-zero exit means the plan is
not ready for the licence and admission gates, never that the data is bad.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse

from scripts.datasets.acquire import (
    CapacityError,
    default_data_root,
    ensure_capacity,
    validate_catalog,
)
from scripts.datasets.probe_upstream import DEFAULT_CATALOG, PolitePoller

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def catalog_at_head(path: Path) -> dict[str, Any]:
    relative = path.resolve().relative_to(PROJECT_ROOT)
    blob = subprocess.run(
        ["git", "show", f"HEAD:{relative.as_posix()}"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(blob)


def _downloads(catalog: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {s["id"]: list(s.get("downloads", [])) for s in catalog["sources"]}


def proposed_downloads(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Every download entry the plan adds or alters, tagged with its source."""
    old, new = _downloads(before), _downloads(after)
    proposed = []
    for source_id, entries in new.items():
        was = old.get(source_id, [])
        for entry in entries:
            if entry not in was:
                proposed.append({"source_id": source_id, **entry})
    return proposed


def proposed_sources(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Sources the diff adds."""
    known = {s["id"] for s in before["sources"]}
    return [s for s in after["sources"] if s["id"] not in known]


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def duplicate_candidates(before: dict[str, Any], added: list[dict[str, Any]]) -> list[str]:
    """A candidate the catalog already holds under another id.

    Matched on the official_url's host and on the name, because those are what a
    search turns up twice; an exact URL match is the easy case and is caught by
    either.
    """
    hosts = {urlparse(s.get("official_url", "")).netloc: s["id"] for s in before["sources"]}
    names = {_name_key(s.get("name", "")): s["id"] for s in before["sources"]}
    problems = []
    for source in added:
        host = urlparse(source.get("official_url", "")).netloc
        if host and host in hosts:
            problems.append(
                f"{source['id']}: {hosts[host]} already uses the host {host}"
            )
        key = _name_key(source.get("name", ""))
        if key and key in names:
            problems.append(f"{source['id']}: {names[key]} already has this name")
    return problems


def check_candidate_urls(added: list[dict[str, Any]], poller: PolitePoller) -> list[dict[str, Any]]:
    """Resolve each added source's official_url, and its licence_url when given."""
    checks = []
    for source in added:
        result: dict[str, Any] = {"source_id": source["id"]}
        for field in ("official_url", "licence_url"):
            url = source.get(field)
            if not url:
                result[field] = "not supplied" if field == "licence_url" else "missing"
                continue
            try:
                result[field] = f"http-{poller.status(url)}"
            except HTTPError as error:
                result[field] = f"http-{error.code}"
            except Exception as error:  # one unreachable host must not hide the rest
                result[field] = f"{type(error).__name__}: {error}"
        checks.append(result)
    return checks


def data_path_collisions(after: dict[str, Any]) -> list[str]:
    seen: dict[str, str] = {}
    collisions = []
    for source in after["sources"]:
        path, source_id = source.get("data_path"), source["id"]
        if path in seen:
            collisions.append(f"{source_id} claims the data_path of {seen[path]}: {path}")
        else:
            seen[path] = source_id
    return collisions


def stale_prose(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Free text still naming an upstream id the plan just replaced.

    `status` and `notes` are prose, so nothing else notices when a plan moves a
    source to a new upstream record and leaves the old id written in them. The
    catalog then states two different upstream versions at once.
    """
    old, new = _downloads(before), _downloads(after)
    stale = []
    for source in after["sources"]:
        source_id = source["id"]
        dropped = [e["url"] for e in old.get(source_id, []) if e not in new.get(source_id, [])]
        if not dropped:
            continue
        gone = {i for url in dropped for i in re.findall(r"\d{6,}", url)}
        kept = {i for e in new.get(source_id, []) for i in re.findall(r"\d{6,}", e["url"])}
        for field in ("status", "notes"):
            text = source.get(field) or ""
            for identifier in sorted(gone - kept):
                if identifier in text:
                    stale.append(
                        f"{source_id}: {field} still names the replaced upstream id {identifier}"
                    )
    return stale


def check_urls(proposed: list[dict[str, Any]], poller: PolitePoller) -> list[dict[str, Any]]:
    checks = []
    for entry in proposed:
        result = {"source_id": entry.get("source_id"), "filename": entry.get("filename")}
        try:
            headers = poller.head(entry["url"])
            length = headers.get("content-length")
            result["content_length"] = int(length) if length else None
            claimed = entry.get("bytes")
            if result["content_length"] is None:
                result["verdict"] = "resolves, host sends no content-length"
            elif claimed is None:
                result["verdict"] = "resolves, plan claims no size"
            elif result["content_length"] == claimed:
                result["verdict"] = "ok"
            else:
                result["verdict"] = f"size mismatch: claimed {claimed}"
        except HTTPError as error:
            result["verdict"] = f"http-{error.code}"
        except Exception as error:  # one unreachable host must not hide the rest
            result["verdict"] = f"{type(error).__name__}: {error}"
        checks.append(result)
    return checks


def verify(before: dict[str, Any], after: dict[str, Any], poller: PolitePoller,
           free_bytes: int) -> dict[str, Any]:
    report: dict[str, Any] = {"problems": [], "proposed": [], "candidates": []}
    try:
        validate_catalog(after)
    except ValueError as error:
        report["problems"].append(f"catalog does not validate: {error}")
        return report

    report["problems"].extend(data_path_collisions(after))
    report["problems"].extend(stale_prose(before, after))

    added = proposed_sources(before, after)
    report["problems"].extend(duplicate_candidates(before, added))
    report["candidates"] = check_candidate_urls(added, poller)
    report["problems"].extend(
        f"{c['source_id']}: official_url {c['official_url']}"
        for c in report["candidates"] if c["official_url"] != "http-200"
    )
    proposed = proposed_downloads(before, after)
    report["proposed"] = check_urls(proposed, poller)
    report["problems"].extend(
        f"{c['source_id']}/{c['filename']}: {c['verdict']}"
        for c in report["proposed"] if c["verdict"] != "ok"
    )

    expected = sum(e.get("bytes") or 0 for e in proposed)
    report["expected_bytes"] = expected
    try:
        ensure_capacity(available_bytes=free_bytes, expected_bytes=expected)
    except CapacityError as error:
        report["problems"].append(str(error))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--before", type=Path, default=None,
                        help="baseline catalog (default: the committed version at HEAD)")
    args = parser.parse_args(argv)

    after = json.loads(args.catalog.read_text(encoding="utf-8"))
    before = (
        json.loads(args.before.read_text(encoding="utf-8")) if args.before
        else catalog_at_head(args.catalog)
    )
    root = default_data_root()
    free_bytes = shutil.disk_usage(root if root.exists() else PROJECT_ROOT).free

    report = verify(before, after, PolitePoller(), free_bytes)
    if not report["proposed"] and not report["candidates"] and not report["problems"]:
        print("nothing proposed: the catalog is unchanged")
        return 0
    for check in report["candidates"]:
        print(f"  candidate {check['source_id']}: official_url {check['official_url']}, "
              f"licence_url {check['licence_url']}")
    for check in report["proposed"]:
        print(f"  {check['source_id']}/{check['filename']}: {check['verdict']}")
    print(f"\n新增下载共 {report.get('expected_bytes', 0):,} bytes；可用 {free_bytes:,}")
    if report["problems"]:
        print(f"\n{len(report['problems'])} problem(s):")
        for problem in report["problems"]:
            print(f"  {problem}")
        return 1
    print("\npasses the machine checks — the licence and admission gates are next")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
