#!/usr/bin/env python3
"""Derive the pull plan for a source whose upstream has moved on.

The probe says *that* a source changed; this says *what to pull*. It asks the
upstream for the latest version's file list and routes the source by how much of
that list the catalog still recognises, because the amount of judgement needed
follows from exactly that:

* every recorded name still present — the plan is a URL substitution;
* some present — mechanical for those, with the vanished and added names listed
  so the question put to a human is only about the delta;
* none present — upstream restructured, and deciding which new files correspond
  to what we ingested is not a mechanical question.

Nothing is written to the catalog. The output is a proposal to review, which is
also why a licence that changed between versions is compared here: passing the
licence gate once does not grant a pass forever.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlparse

from scripts.datasets.acquire import default_data_root, load_catalog
from scripts.datasets.probe_upstream import (
    DEFAULT_CATALOG,
    Probe,
    _PolitePoller,
    plan_probes,
)

DERIVABLE_KINDS = {"invenio-latest", "figshare-article"}


def _basename(path: str) -> str:
    """A recorded filename may be a local path; upstream knows only the name."""
    return path.rsplit("/", 1)[-1]


def _normalise_licence(value: Any) -> str:
    """Compare licences by content, not by punctuation.

    Upstream says `cc-by-4.0` where the catalog says `CC BY 4.0`; a plain string
    comparison would report every source as changed.
    """
    if isinstance(value, dict):
        value = value.get("id") or value.get("name") or value.get("value") or ""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def upstream_licence(payload: dict[str, Any]) -> Any:
    metadata = payload.get("metadata") or {}
    rights = metadata.get("rights") or []
    if rights:
        return rights[0]
    return metadata.get("license") or payload.get("license")


def upstream_files(probe: Probe, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The latest version's files as {name, bytes, url}."""
    if probe.kind == "figshare-article":
        return [
            {"name": f["name"], "bytes": f.get("size"), "url": f["download_url"]}
            for f in payload.get("files", [])
        ]
    # invenio: zenodo answers with a list, InvenioRDM with a keyed dict, and the
    # record id in the reply is the new one we must build URLs against
    record_id = payload.get("id")
    host = urlparse(probe.endpoint or "").netloc
    raw = payload.get("files") or []
    if isinstance(raw, dict):  # InvenioRDM keys its files by name
        entries = list((raw.get("entries") or {}).values())
    else:  # zenodo answers with a plain list
        entries = raw
    return [
        {
            "name": entry["key"],
            "bytes": entry.get("size"),
            "url": f"https://{host}/api/records/{record_id}/files/{entry['key']}/content",
        }
        for entry in entries
    ]


def recorded_for(probe: Probe, source: dict[str, Any]) -> tuple[list[str], int]:
    """Only the recorded files the probed target is actually responsible for.

    A source can mirror from several hosts — carolina takes one archive from
    zenodo and two parquet files from a Hugging Face dataset. Comparing all of
    them against one host's file list reports the others as vanished, which
    sends a reviewer chasing a problem that does not exist.
    """
    if probe.kind == "figshare-article":
        belongs = "ndownloader.figshare.com"
    else:
        belongs = f"/records/{probe.known}/"
    mine, others = [], 0
    for item in source.get("downloads", []):
        if not item.get("filename"):
            continue
        if belongs in item.get("url", ""):
            mine.append(item["filename"])
        else:
            others += 1
    return mine, others


def route_for(kept: list[str], recorded: list[str]) -> str:
    if not recorded:
        return "nothing-recorded"
    if len(kept) == len(recorded):
        return "mechanical"
    if kept:
        return "delta"
    return "restructured"


def derive(source: dict[str, Any], probe: Probe, poller: _PolitePoller) -> dict[str, Any]:
    result: dict[str, Any] = {"kind": probe.kind}
    if probe.kind not in DERIVABLE_KINDS:
        # hf, git and plain HEAD sources keep their URLs; a new version arrives
        # at the same address, so the recorded plan still applies
        result["route"] = "urls-unchanged"
        return result

    payload = poller.json(probe.endpoint)
    files = upstream_files(probe, payload)
    by_name = {f["name"]: f for f in files}
    recorded, from_other_hosts = recorded_for(probe, source)
    if from_other_hosts:
        result["recorded_files_from_other_hosts"] = from_other_hosts
    basenames = {name: _basename(name) for name in recorded}
    kept = [name for name in recorded if basenames[name] in by_name]

    result["route"] = route_for(kept, recorded)
    result["upstream_file_count"] = len(files)
    result["vanished"] = [basenames[n] for n in recorded if basenames[n] not in by_name]
    result["added"] = sorted(set(by_name) - {basenames[n] for n in recorded})
    result["proposed_downloads"] = [
        {
            "filename": name,
            "url": by_name[basenames[name]]["url"],
            "bytes": by_name[basenames[name]]["bytes"],
        }
        for name in kept
    ]

    catalogued = source.get("license")
    upstream = upstream_licence(payload)
    result["licence"] = {
        "catalogued": catalogued,
        "upstream": upstream if not isinstance(upstream, dict) else (
            upstream.get("id") or upstream.get("name")
        ),
        "verdict": "same"
        if _normalise_licence(catalogued) == _normalise_licence(upstream)
        else "differs-return-to-the-licence-gate",
    }

    stale_paths = [
        name
        for name in recorded
        if probe.known and probe.known in name  # the old record id is in the local path
    ]
    if stale_paths:
        result["local_paths_name_the_old_record"] = stale_paths
    return result


def verify(proposed: list[dict[str, Any]], poller: _PolitePoller) -> list[dict[str, Any]]:
    """HEAD each URL we constructed: does it resolve, and is it the size claimed."""
    checks = []
    for item in proposed:
        entry: dict[str, Any] = {"filename": item["filename"]}
        try:
            headers = poller.head(item["url"])
            length = headers.get("content-length")
            entry["status"] = "ok"
            entry["content_length"] = int(length) if length else None
            if entry["content_length"] and item["bytes"]:
                entry["matches_upstream_size"] = entry["content_length"] == item["bytes"]
        except HTTPError as error:
            # figshare's ndownloader refuses HEAD; the article API is the authority
            entry["status"] = f"http-{error.code}"
        except Exception as error:
            entry["status"] = f"{type(error).__name__}: {error}"
        checks.append(entry)
    return checks


def lagging_sources(probe_file: Path) -> list[str]:
    if not probe_file.exists():
        return []
    probes = json.loads(probe_file.read_text(encoding="utf-8")).get("probes", {})
    return sorted(k for k, v in probes.items() if "catalog_points_at_older_record" in v)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", default=[], metavar="SOURCE_ID")
    args = parser.parse_args(argv)

    catalog = load_catalog(DEFAULT_CATALOG)
    sources = {s["id"]: s for s in catalog["sources"]}
    probes = plan_probes(catalog)
    data_root = default_data_root()

    wanted = args.source or lagging_sources(data_root / "probe" / "seen.json")
    if not wanted:
        parser.error("no source given and the probe file flags none as lagging")
    unknown = [s for s in wanted if s not in sources]
    if unknown:
        parser.error(f"unknown source id(s): {', '.join(unknown)}")

    poller = _PolitePoller()
    report: dict[str, Any] = {}
    for source_id in wanted:
        plan = derive(sources[source_id], probes[source_id], poller)
        if plan.get("proposed_downloads"):
            plan["head_checks"] = verify(plan["proposed_downloads"], poller)
        report[source_id] = plan

        print(f"\n{source_id}  [{plan['kind']}]  route = {plan['route']}")
        if plan["route"] == "urls-unchanged":
            print("  URL 不变，沿用目录里的计划")
            continue
        recorded = len(plan["proposed_downloads"]) + len(plan["vanished"])
        print(f"  该上游负责的记录文件 {recorded} 个，上游最新版本 {plan['upstream_file_count']} 个")
        if plan.get("recorded_files_from_other_hosts"):
            print(f"  （另有 {plan['recorded_files_from_other_hosts']} 个记录文件来自其他 host，未参与比对）")
        print(f"  沿用 {len(plan['proposed_downloads'])}，消失 {len(plan['vanished'])}，新增 {len(plan['added'])}")
        for name in plan["vanished"]:
            print(f"    - 消失: {name}")
        for name in plan["added"][:5]:
            print(f"    + 新增: {name}")
        if len(plan["added"]) > 5:
            print(f"    + 新增（另 {len(plan['added']) - 5} 个）")
        licence = plan["licence"]
        print(f"  许可: 目录={licence['catalogued']!r} 上游={licence['upstream']!r} -> {licence['verdict']}")
        if "local_paths_name_the_old_record" in plan:
            print(f"  ⚠️  本地路径里写着旧 record id，需人工决定是否改: "
                  f"{plan['local_paths_name_the_old_record']}")
        for check in plan.get("head_checks", []):
            if check["status"] != "ok" or check.get("matches_upstream_size") is False:
                print(f"  ⚠️  {check['filename']}: {check}")

    out = data_root / "probe" / "upgrades.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
