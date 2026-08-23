#!/usr/bin/env python3
"""Probe upstream sources for new versions without downloading any data.

Reads the upstream identity out of the download URLs already in
`scripts/datasets/sources.json`, asks each host one metadata question, and
writes an opaque `seen` token per source to a side file. Nothing in the catalog
or the index is touched, so a bad run is undone by deleting the output.

Two things here are not derivable from the code and were learned the hard way:

* `api/records/<id>/versions/latest` answers with the newest sibling record on
  both Zenodo and Materials Cloud, so one request settles whether the record we
  ingested has been superseded — no concept id to resolve, nothing to cache.
* `ndownloader.figshare.com` URLs carry an immutable *file* id that does not move
  when the article gains a version, and the article id is nowhere in the
  catalog, so those sources stay unprobeable until someone records it by hand.

A `HEAD` fallback catches a file replaced in place but not a new release.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root, load_catalog

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPOSITORY_ROOT / "scripts" / "datasets" / "sources.json"
USER_AGENT = "MateriaViva-upstream-probe/1.0 (+https://github.com/AI4QC/materia-viva)"
HOST_DELAY_SECONDS = 1.0
TIMEOUT_SECONDS = 30

INVENIO_HOSTS = {"zenodo.org", "archive.materialscloud.org"}
# the same record is addressable with or without the `/api/` prefix
_INVENIO = re.compile(r"^https?://([^/]+)/(?:api/)?records/([^/]+)/")
_HF = re.compile(r"^https?://huggingface\.co/datasets/([^/]+/[^/]+)/resolve/[^/]+/(.+)$")
_GH_RAW = re.compile(r"^https?://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)$")
_GH_MEDIA = re.compile(
    r"^https?://media\.githubusercontent\.com/media/([^/]+)/([^/]+)/([^/]+)/(.+)$"
)
_GH_CODELOAD = re.compile(r"^https?://codeload\.github\.com/([^/]+)/([^/]+)/[^/]+/(.+)$")
# github.com/<owner>/<repo>/archive/refs/heads/<branch>.zip
_GH_ARCHIVE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/archive/refs/heads/(.+?)\.(?:zip|tar\.gz)$"
)
_FIGSHARE = re.compile(r"^https?://ndownloader\.figshare\.com/files/\d+")
# the article id is what moves when a figshare dataset gains a version; it sits
# in official_url for some sources and is recorded by hand for the rest
_FIGSHARE_ARTICLE_URL = re.compile(r"^https?://(?:[\w.-]+\.)?figshare\.com/articles/([^?#]+)")


@dataclass
class Probe:
    """One source's probe plan: how to ask, and what we asked about last time."""

    source_id: str
    kind: str
    endpoint: str | None = None
    note: str | None = None
    known: str | None = None  # the upstream id recorded in the catalog, when any


def _source_urls(source: dict[str, Any]) -> list[str]:
    return [d["url"] for d in source.get("downloads", []) if d.get("url")]


def _figshare_article(source: dict[str, Any]) -> str | None:
    """The recorded article id, else the one in official_url.

    A collection URL is not an article URL, so it is deliberately not matched;
    those sources carry the article id explicitly.
    """
    recorded = source.get("figshare_article")
    if recorded:
        return str(recorded)
    match = _FIGSHARE_ARTICLE_URL.match(source.get("official_url", ""))
    if not match:
        return None
    digits = re.findall(r"\d{6,}", match.group(1))
    return digits[-1] if digits else None


def plan_probe(source: dict[str, Any]) -> Probe:
    """Derive the probe plan for one catalog entry. Pure; makes no requests."""
    source_id = source["id"]
    urls = _source_urls(source)
    if not urls:
        return Probe(source_id, "manual", note="no-download-endpoint")

    for url in urls:
        match = _INVENIO.match(url)
        if match and match.group(1) in INVENIO_HOSTS:
            host, record_id = match.group(1), match.group(2)
            return Probe(
                source_id,
                "invenio-latest",
                endpoint=f"https://{host}/api/records/{record_id}/versions/latest",
                known=record_id,
            )
        match = _HF.match(url)
        if match:
            repo = match.group(1)
            return Probe(
                source_id,
                "hf-revision",
                endpoint=f"https://huggingface.co/api/datasets/{repo}",
            )
        for pattern in (_GH_RAW, _GH_MEDIA):
            match = pattern.match(url)
            if match:
                owner, repo, ref, path = match.groups()
                return Probe(
                    source_id,
                    "git-commit",
                    endpoint=(
                        f"https://api.github.com/repos/{owner}/{repo}/commits"
                        f"?sha={ref}&path={path}&per_page=1"
                    ),
                )
        match = _GH_CODELOAD.match(url) or _GH_ARCHIVE.match(url)
        if match:
            owner, repo, ref = match.groups()
            return Probe(
                source_id,
                "git-commit",
                endpoint=f"https://api.github.com/repos/{owner}/{repo}/commits?sha={ref}&per_page=1",
            )

    if any(_FIGSHARE.match(url) for url in urls):
        article = _figshare_article(source)
        if article:
            return Probe(
                source_id,
                "figshare-article",
                endpoint=f"https://api.figshare.com/v2/articles/{article}",
            )
        return Probe(source_id, "manual", note="figshare-article-id-unknown")
    return Probe(source_id, "http-head", endpoint=urls[0])


def plan_probes(catalog: dict[str, Any]) -> dict[str, Probe]:
    return {source["id"]: plan_probe(source) for source in catalog["sources"]}


class _PolitePoller:
    """One request at a time, at most one per host per HOST_DELAY_SECONDS."""

    def __init__(self, delay: float = HOST_DELAY_SECONDS) -> None:
        self._delay = delay
        self._last: dict[str, float] = {}

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        elapsed = time.monotonic() - self._last.get(host, 0.0)
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last[host] = time.monotonic()

    def json(self, url: str) -> Any:
        self._wait(url)
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read())

    def head(self, url: str) -> dict[str, str]:
        self._wait(url)
        request = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return {k.lower(): v for k, v in response.headers.items()}


def _seen_invenio(probe: Probe, payload: Any) -> tuple[str, dict[str, Any]]:
    record_id = str(payload.get("id", ""))
    version = payload.get("metadata", {}).get("version")
    seen = f"{record_id}:{version}" if version else record_id
    extra: dict[str, Any] = {"latest_version": version}
    if probe.known and record_id and record_id != probe.known:
        extra["catalog_points_at_older_record"] = probe.known
    return seen, extra


def run_probe(probe: Probe, poller: _PolitePoller) -> dict[str, Any]:
    """Resolve one probe. Failures are recorded, never retried, never raised."""
    result: dict[str, Any] = {"kind": probe.kind, "checked_at": date.today().isoformat()}
    if probe.note:
        result["note"] = probe.note
    if probe.kind == "manual" or probe.endpoint is None:
        result["seen"] = None
        return result

    result["endpoint"] = probe.endpoint
    try:
        if probe.kind == "invenio-latest":
            seen, extra = _seen_invenio(probe, poller.json(probe.endpoint))
            result["seen"] = seen
            result.update(extra)
        elif probe.kind == "figshare-article":
            result["seen"] = str(poller.json(probe.endpoint).get("version"))
        elif probe.kind == "hf-revision":
            result["seen"] = poller.json(probe.endpoint).get("sha")
        elif probe.kind == "git-commit":
            commits = poller.json(probe.endpoint)
            result["seen"] = commits[0]["sha"] if commits else None
            if not commits:
                result["note"] = "no-commit-touches-the-stored-path"
        else:
            headers = poller.head(probe.endpoint)
            result["seen"] = headers.get("etag") or headers.get("last-modified")
            if result["seen"] is None:
                result["note"] = "host-sends-no-etag-or-last-modified"
    except HTTPError as error:
        result["seen"] = None
        result["error"] = f"http-{error.code}"
    except Exception as error:  # one host's failure must not lose the other probes
        result["seen"] = None
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def diff_against(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, list[str]]:
    """Classify every current probe against the previously written file."""
    old = previous.get("probes", {})
    verdict: dict[str, list[str]] = {
        "changed": [],
        "unchanged": [],
        "first-seen": [],
        "unprobeable": [],
        "failed": [],
    }
    for source_id, entry in sorted(current.items()):
        if entry.get("error"):
            verdict["failed"].append(source_id)
        elif entry["kind"] == "manual" or entry.get("seen") is None:
            verdict["unprobeable"].append(source_id)
        elif source_id not in old or old[source_id].get("seen") is None:
            verdict["first-seen"].append(source_id)
        elif old[source_id]["seen"] != entry["seen"]:
            verdict["changed"].append(source_id)
        else:
            verdict["unchanged"].append(source_id)
    return verdict


def merge_probes(
    previous: dict[str, Any], results: dict[str, Any], catalogued: set[str]
) -> dict[str, Any]:
    """Fold this run into the previous file.

    A `--only` run probes a handful of sources; it must not drop the entries it
    did not visit. Sources that have left the catalog are dropped.

    A failed probe learns nothing, so it must not overwrite a token we already
    hold: otherwise one transient network error erases the baseline and the next
    genuine upstream change is reported as `first-seen` instead of `changed`.
    """
    old = previous.get("probes", {})
    merged = {k: v for k, v in old.items() if k in catalogued}
    for source_id, entry in results.items():
        carried = old.get(source_id, {})
        if entry.get("error") and carried.get("seen") is not None:
            entry = {**entry, "seen": carried["seen"], "seen_carried_over": True}
        merged[source_id] = entry
    return merged


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output file (default <data root>/probe/seen.json)",
    )
    parser.add_argument(
        "--only", action="append", default=[], metavar="SOURCE_ID", help="probe just these"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan, make no requests"
    )
    args = parser.parse_args(argv)

    catalog = load_catalog(args.catalog)
    catalogued = plan_probes(catalog)
    probes = catalogued
    if args.only:
        missing = [s for s in args.only if s not in probes]
        if missing:
            parser.error(f"unknown source id(s): {', '.join(missing)}")
        probes = {k: v for k, v in probes.items() if k in args.only}

    if args.dry_run:
        by_kind: dict[str, list[str]] = {}
        for probe in probes.values():
            by_kind.setdefault(probe.kind, []).append(probe.source_id)
        for kind, ids in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
            print(f"{kind:16s} {len(ids):3d}  {', '.join(sorted(ids))}")
        probeable = sum(len(v) for k, v in by_kind.items() if k != "manual")
        print(f"\n{probeable} of {len(probes)} sources are probeable without a schema change")
        return 0

    out_path = args.out or (default_data_root() / "probe" / "seen.json")
    previous: dict[str, Any] = {}
    if out_path.exists():
        previous = json.loads(out_path.read_text(encoding="utf-8"))

    poller = _PolitePoller()
    results: dict[str, Any] = {}
    for source_id, probe in sorted(probes.items()):
        results[source_id] = run_probe(probe, poller)

    verdict = diff_against(previous, results)
    payload = {
        "generated_at": date.today().isoformat(),
        "catalog": os.path.relpath(args.catalog, REPOSITORY_ROOT),
        "probes": merge_probes(previous, results, set(catalogued)),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    for label in ("changed", "first-seen", "failed", "unchanged", "unprobeable"):
        ids = verdict[label]
        print(f"{label:12s} {len(ids):3d}" + (f"  {', '.join(ids)}" if ids and label != "unprobeable" else ""))
    stale = {
        source_id: entry["catalog_points_at_older_record"]
        for source_id, entry in results.items()
        if "catalog_points_at_older_record" in entry
    }
    if stale:
        print("\nupstream has a newer version than the catalog record:")
        for source_id, old_record in sorted(stale.items()):
            print(f"  {source_id:20s} catalog={old_record}  latest={results[source_id]['seen']}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
