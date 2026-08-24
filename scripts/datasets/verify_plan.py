#!/usr/bin/env python3
"""Gate a proposed pull plan: check the catalog diff, not the proposer.

A pull plan is a change to `downloads[]` in the source catalog, and the agent or
person who wrote it commits it on a branch. So the gate reads that diff — every
download entry this working tree adds or alters — and answers the four questions
of the plan contract without trusting whoever produced it:

* does the catalog still validate (https, safe relative filename, integer bytes);
* does each new URL resolve, and is it the size the plan claims;
* would the download fit inside the SSD reserve `acquire.py` protects;
* does a new source claim a `data_path` some other source already owns.

Nothing is downloaded and nothing is written. A non-zero exit means the plan is
not ready for the licence and admission gates, never that the data is bad.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

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
    report: dict[str, Any] = {"problems": [], "proposed": []}
    try:
        validate_catalog(after)
    except ValueError as error:
        report["problems"].append(f"catalog does not validate: {error}")
        return report

    report["problems"].extend(data_path_collisions(after))
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
    if not report["proposed"] and not report["problems"]:
        print("plan is empty: no download entry added or altered")
        return 0
    for check in report["proposed"]:
        print(f"  {check['source_id']}/{check['filename']}: {check['verdict']}")
    print(f"\n新增下载共 {report.get('expected_bytes', 0):,} bytes；可用 {free_bytes:,}")
    if report["problems"]:
        print(f"\n{len(report['problems'])} problem(s):")
        for problem in report["problems"]:
            print(f"  {problem}")
        return 1
    print("\nplan passes the machine checks — licence and admission gates are next")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
