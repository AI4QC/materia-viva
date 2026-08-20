#!/usr/bin/env python3
"""Resumable acquisition of Materials Project spectra / curve families.

MateriaViva already holds MP's ``summary`` endpoint (154,377 docs, snapshot
``materials-project/summary-2026-07-26``).  None of the curve-bearing families
are in the pool.  This fetcher pulls them, one ``--family`` at a time, into
``data/raw/acquired/materials-project/<family>-<date>/``.

Two transports, because MP serves these families two different ways:

* **REST** (``xas``, ``absorption``) — ``api.materialsproject.org`` returns the
  spectra inline in the document.  Paged into gzipped JSONL shards.
* **S3 open data** (``dos``, ``phonon``, ``bandstructure``) — the REST
  ``electronic_structure``/``phonon`` endpoints strip the heavy objects and
  return metadata only (verified: ``_all_fields=true`` and an explicit
  ``_fields=phonon_dos`` both come back ``null``).  The objects live in the
  public, unsigned ``materialsproject-parsed`` bucket as Delta-Lake tables of
  zstd parquet.  We replay each table's ``_delta_log`` to get the *active*
  part files and download those.

  The legacy per-task keys ``dos/<mp-NNN>.json.gz`` and
  ``bandstructures/<mp-NNN>.json.gz`` that ``mp_api`` still uses are a 2023
  dump keyed by *legacy numeric* ids; the 2026.04.13 database has alphabetic
  ids (``mp-aaahikie``) and nothing under those keys, so they are unusable here.

Sizing that drove the family selection (measured 2026-08-19, active files
only, compressed-on-the-wire):

    table                                             size     rows   KiB/row
    core/electronic-structure/total-dos              4.32 GB  691,978     6.5
    core/electronic-structure/projected-dos         21.11 GB  ~613,000    ~34
    core/electronic-structure/bandstructures        75.25 GB   ~1.14 M     ~66
      …path_convention=setyawan_curtarolo only      20.37 GB  116,641   170.6
    core/electronic-structure/projected-bandstruct 1105.06 GB   ~98,800  ~11,200
    phonon/electronic-structure/dos                  0.35 GB   27,914    12.2
    phonon/electronic-structure/bandstructures      23.71 GB   80,644    287.1

``--family dos`` and ``--family phonon`` therefore take the *total* DOS tables
(4.32 GB / 0.35 GB) and never the projected ones; ``--family bandstructure``
takes only ``path_convention=setyawan_curtarolo`` (99.8% of the materials that
have a band structure carry that convention) and only the energies table, never
``projected-bandstructures``.

Conventions: serial, one request at a time, polite delay, exponential backoff
on 429/5xx with a hard stop on sustained rate limiting, ``.part`` files renamed
into place only once complete, one ``<file>.receipt.json`` per artifact holding
the URL (never the API key — that travels in the ``X-API-KEY`` header),
byte count, sha256 and completion time, plus a rolling ``manifest.json``.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.datasets.acquire import (  # noqa: E402
    default_data_root,
    ensure_capacity,
)

USER_AGENT = "MateriaViva-dataset-acquisition/1.0 (+materiaviva pool; python-urllib)"
API_ROOT = "https://api.materialsproject.org"
S3_ROOT = "https://materialsproject-parsed.s3.amazonaws.com/"

#: Local MP summary snapshot used to enumerate targets and to map
#: calculation task ids back onto material ids.
SUMMARY_SNAPSHOT = "summary-2026-07-26"

MAX_CONSECUTIVE_THROTTLES = 6  # hard stop: the API is telling us to go away


class RateLimited(RuntimeError):
    """Raised when the server keeps throttling us; the caller must stop."""


# --------------------------------------------------------------------------
# family definitions
# --------------------------------------------------------------------------

S3_FAMILIES = {
    # family -> (delta table prefix, partition filter or None, has_props key,
    #            how the parquet `identifier` column joins back to a material)
    "dos": (
        "core/electronic-structure/total-dos/",
        None,
        "dos",
        "task_id",
    ),
    "phonon": (
        "phonon/electronic-structure/dos/",
        None,
        "phonon",
        "material_id",
    ),
    "bandstructure": (
        "core/electronic-structure/bandstructures/",
        "path_convention=setyawan_curtarolo",
        "bandstructure",
        "task_id",
    ),
}

REST_FAMILIES = {
    # family -> (endpoint path, has_props key)
    "xas": ("/materials/xas/", "xas"),
    "absorption": ("/materials/absorption/", "absorption"),
}

FAMILIES = sorted({*S3_FAMILIES, *REST_FAMILIES})


# --------------------------------------------------------------------------
# credentials / transport
# --------------------------------------------------------------------------


def read_api_key() -> str:
    """MP_API_KEY from the environment, else from the repo's gitignored .env.

    The key is only ever sent as the ``X-API-KEY`` header; it is never placed
    in a URL, a receipt, the manifest or any log line.
    """

    key = os.environ.get("MP_API_KEY") or os.environ.get("MAPI_KEY")
    if key:
        return key.strip()
    env = PROJECT_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("MP_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("MP_API_KEY not found in the environment or .env")


def _open(url: str, *, headers: dict | None = None, timeout: int = 600):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   **(headers or {})})
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_bytes(
    url: str,
    *,
    headers: dict | None = None,
    attempts: int = 6,
    throttle_state: list | None = None,
) -> bytes:
    """One GET with exponential backoff; raises RateLimited on sustained 429s."""

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with _open(url, headers=headers) as response:
                data = response.read()
            if throttle_state is not None:
                throttle_state[0] = 0
            return data
        except urllib.error.HTTPError as error:
            last = error
            if error.code in (429, 500, 502, 503, 504):
                if error.code == 429 and throttle_state is not None:
                    throttle_state[0] += 1
                    if throttle_state[0] >= MAX_CONSECUTIVE_THROTTLES:
                        raise RateLimited(
                            f"{throttle_state[0]} consecutive 429s; stopping"
                        ) from error
                retry_after = error.headers.get("Retry-After") if error.headers else None
                delay = float(retry_after) if retry_after and retry_after.isdigit() \
                    else min(120.0, 2.0 ** attempt * 2)
                print(f"    HTTP {error.code}; sleeping {delay:.0f}s", flush=True)
                time.sleep(delay)
                continue
            raise
        except Exception as error:  # transient socket/DNS/timeouts
            last = error
            if attempt + 1 < attempts:
                time.sleep(min(60, 2 ** attempt * 2))
                continue
            raise
    assert last is not None
    raise last


def fetch_json(url: str, *, api_key: str, throttle_state: list) -> tuple[dict, int]:
    raw = fetch_bytes(
        url,
        headers={"X-API-KEY": api_key, "Accept-Encoding": "gzip"},
        throttle_state=throttle_state,
    )
    wire = len(raw)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw), wire


# --------------------------------------------------------------------------
# artifact bookkeeping
# --------------------------------------------------------------------------


def _atomic_write_text(target: Path, text: str) -> None:
    building = target.with_name(target.name + ".building")
    building.write_text(text, encoding="utf-8")
    building.replace(target)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_receipt(path: Path, *, url: str, started: float, extra: dict | None = None) -> Path:
    """``<file>.receipt.json``: URL (key-free), bytes, sha256, timings."""

    payload = {
        "source_id": "materials-project",
        "url": url,
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "seconds": round(time.time() - started, 3),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(extra or {})
    receipt = path.with_name(path.name + ".receipt.json")
    _atomic_write_text(receipt, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return receipt


def receipt_ok(path: Path) -> bool:
    """A file counts as done when its receipt exists and the size still matches."""

    receipt = path.with_name(path.name + ".receipt.json")
    if not (path.exists() and receipt.exists()):
        return False
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return payload.get("bytes") == path.stat().st_size


def write_manifest(output_dir: Path, payload: dict) -> None:
    payload = dict(payload)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_text(
        output_dir / "manifest.json",
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


# --------------------------------------------------------------------------
# targets, read from the local summary snapshot
# --------------------------------------------------------------------------


def summary_dir() -> Path:
    return default_data_root() / "raw" / "acquired" / "materials-project" / SUMMARY_SNAPSHOT


def iter_summary_docs():
    for page in sorted(summary_dir().glob("page-*.json.gz")):
        with gzip.open(page, "rt", encoding="utf-8") as handle:
            for row in json.load(handle).get("data", []):
                yield row


def build_targets(family: str, output_dir: Path) -> Path:
    """Write ``targets.tsv.gz`` = the join key each row of the family maps to.

    * ``dos`` / ``bandstructure``: ``<task_id>\\t<material_id>`` — the parquet
      ``identifier`` column is a *calculation* id, and the summary doc names
      which calculation is the blessed one for the material.
    * ``phonon``: ``<material_id>\\t<material_id>`` — the parquet identifier is
      already the material id (minus the ``mp-`` prefix).
    * ``xas`` / ``absorption``: ``<material_id>\\t<material_id>`` — the request
      loop pages over these ids.
    """

    target = output_dir / "targets.tsv.gz"
    if receipt_ok(target):
        return target
    started = time.time()
    building = target.with_name(target.name + ".part")
    prop_key = (S3_FAMILIES.get(family) or REST_FAMILIES.get(family))[
        2 if family in S3_FAMILIES else 1
    ]
    rows = 0
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        handle.write("join_key\tmaterial_id\n")
        for doc in iter_summary_docs():
            if not (doc.get("has_props") or {}).get(prop_key):
                continue
            material_id = doc["material_id"]
            if family == "dos":
                dos = doc.get("dos")
                key = dos.get("task_id") if isinstance(dos, dict) else None
            elif family == "bandstructure":
                bands = doc.get("bandstructure")
                entry = bands.get("setyawan_curtarolo") if isinstance(bands, dict) else None
                key = entry.get("task_id") if isinstance(entry, dict) else None
            else:
                key = material_id
            if not key:
                continue
            handle.write(f"{key}\t{material_id}\n")
            rows += 1
    building.replace(target)
    write_receipt(
        target,
        url=f"local:{SUMMARY_SNAPSHOT}",
        started=started,
        extra={"rows": rows, "note": "join keys derived from the local MP summary snapshot"},
    )
    print(f"  targets.tsv.gz: {rows:,} rows", flush=True)
    return target


def read_targets(output_dir: Path) -> list[tuple[str, str]]:
    out = []
    with gzip.open(output_dir / "targets.tsv.gz", "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            key, material_id = line.rstrip("\n").split("\t")
            out.append((key, material_id))
    return out


# --------------------------------------------------------------------------
# S3 open-data (Delta Lake) transport
# --------------------------------------------------------------------------


def s3_list(prefix: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    token = None
    while True:
        url = (f"{S3_ROOT}?list-type=2"
               f"&prefix={urllib.parse.quote(prefix, safe='')}&max-keys=1000")
        if token:
            url += "&continuation-token=" + urllib.parse.quote(token, safe="")
        body = fetch_bytes(url).decode()
        out += [(k, int(s)) for k, s in
                re.findall(r"<Key>(.*?)</Key>.*?<Size>(\d+)</Size>", body, re.S)]
        match = re.search(r"<NextContinuationToken>(.*?)</NextContinuationToken>", body)
        if not match:
            return out
        token = match.group(1)
        time.sleep(0.1)


def delta_active_files(table: str) -> dict[str, int]:
    """Replay the Delta transaction log: adds minus removes.

    Listing the prefix is not enough — these tables keep tombstoned parquet
    parts around, so a plain listing over-counts.
    """

    logs = [k for k, _ in s3_list(table + "_delta_log/")
            if k.endswith(".json") and "checkpoint" not in k]
    live: dict[str, int] = {}
    for key in sorted(logs):
        body = fetch_bytes(S3_ROOT + urllib.parse.quote(key, safe="/=")).decode()
        for line in body.splitlines():
            if not line.strip():
                continue
            try:
                action = json.loads(line)
            except ValueError:
                continue
            if "add" in action:
                live[action["add"]["path"]] = action["add"].get("size", 0)
            elif "remove" in action:
                live.pop(action["remove"]["path"], None)
        time.sleep(0.05)
    return live


def _s3_url(key: str) -> str:
    return S3_ROOT + urllib.parse.quote(key, safe="/=")


def download_resumable(url: str, part: Path, expected: int, *, delay: float) -> None:
    """Range-resume into ``.part`` until it holds ``expected`` bytes."""

    attempt = 0
    while True:
        have = part.stat().st_size if part.exists() else 0
        if have >= expected:
            return
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with _open(url, headers=headers) as response:
                with part.open("ab") as handle:
                    while True:
                        chunk = response.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
        except Exception as error:
            attempt += 1
            if attempt > 8:
                raise
            grew = (part.stat().st_size if part.exists() else 0) > have
            if grew:
                attempt = 0
            wait = min(120, 2 ** min(attempt, 6) * 2)
            print(f"    transfer interrupted ({type(error).__name__}); "
                  f"{part.stat().st_size if part.exists() else 0:,}/{expected:,} B, "
                  f"retrying in {wait}s", flush=True)
            time.sleep(wait)
            continue
        if delay:
            time.sleep(delay)


def fetch_s3_family(family: str, output_dir: Path, *, delay: float,
                    limit: int | None) -> dict:
    table, partition_filter, _, id_kind = S3_FAMILIES[family]
    print(f"[{family}] resolving active files of {table}", flush=True)
    live = delta_active_files(table)
    if partition_filter:
        live = {p: s for p, s in live.items()
                if partition_filter in urllib.parse.unquote(p)}
    files = sorted(live.items())
    if limit:
        files = files[:limit]
    total = sum(s for _, s in files)
    print(f"[{family}] {len(files)} active parquet parts, "
          f"{total / 1e9:.2f} GB", flush=True)

    pending = sum(
        size for path, size in files
        if not receipt_ok(output_dir / Path(urllib.parse.unquote(path)).name)
    )
    ensure_capacity(available_bytes=shutil.disk_usage(output_dir).free,
                    expected_bytes=pending)

    manifest = {
        "source": "Materials Project open data (AWS S3, unsigned)",
        "family": family,
        "bucket": "materialsproject-parsed",
        "delta_table": table,
        "partition_filter": partition_filter,
        "identifier_column_is": id_kind,
        "summary_snapshot": SUMMARY_SNAPSHOT,
        "active_parts": len(files),
        "active_bytes": total,
        "files": [],
    }
    done_bytes = 0
    for index, (path, size) in enumerate(files, 1):
        key = table + urllib.parse.unquote(path)
        name = Path(urllib.parse.unquote(path)).name
        partition = "/".join(urllib.parse.unquote(path).split("/")[:-1])
        # keep the partition in the local filename; the part basenames repeat
        local = output_dir / (
            (partition.replace("/", "__").replace("=", "-") + "__" if partition else "")
            + name
        )
        url = _s3_url(key)
        if receipt_ok(local):
            print(f"[{family}] {index}/{len(files)} have {local.name}", flush=True)
        else:
            print(f"[{family}] {index}/{len(files)} GET {size / 1e6:.0f} MB "
                  f"{partition or '(root)'}/{name}", flush=True)
            started = time.time()
            part = local.with_name(local.name + ".part")
            download_resumable(url, part, size, delay=delay)
            if part.stat().st_size != size:
                raise RuntimeError(
                    f"size mismatch for {name}: got {part.stat().st_size}, want {size}")
            part.replace(local)
            write_receipt(local, url=url, started=started,
                          extra={"delta_path": path, "partition": partition})
            print(f"    {size / 1e6:.0f} MB in {time.time() - started:.0f}s", flush=True)
        done_bytes += size
        manifest["files"].append({
            "name": local.name, "bytes": size, "partition": partition,
            "delta_path": path,
        })
        manifest["downloaded_bytes"] = done_bytes
        manifest["complete"] = done_bytes == total
        write_manifest(output_dir, manifest)
    return manifest


# --------------------------------------------------------------------------
# REST transport
# --------------------------------------------------------------------------


def _trim_xas(doc: dict, keep_structures: bool) -> dict:
    """Drop the structure embedded in every XAS spectrum unless asked to keep it.

    MP repeats the full pymatgen ``Structure`` inside each of a material's ~7
    spectra; measured over a 200-material random sample that is 70% of the
    payload (15.9 KB/spectrum full vs 4.8 KB without) and the pool already
    stores every one of these structures.  Everything else is kept verbatim.
    """

    if keep_structures:
        return doc
    spectrum = doc.get("spectrum")
    if isinstance(spectrum, dict) and "structure" in spectrum:
        spectrum = {k: v for k, v in spectrum.items() if k != "structure"}
        doc = {**doc, "spectrum": spectrum}
    return doc


def fetch_xas(output_dir: Path, *, api_key: str, delay: float, chunk: int,
              limit: int | None, keep_structures: bool) -> dict:
    """Page ``/materials/xas/`` by ``task_ids`` chunks.

    Deep ``_skip`` paging is not viable here: the endpoint holds ~515k spectra
    and ``_skip=400000`` returns HTTP 504.  Chunking by material id keeps every
    request shallow and lets the run resume shard by shard.
    """

    targets = [material_id for _, material_id in read_targets(output_dir)]
    if limit:
        targets = targets[:limit]
    shards = [targets[i:i + chunk] for i in range(0, len(targets), chunk)]
    manifest = {
        "source": "Materials Project REST API",
        "family": "xas",
        "endpoint": API_ROOT + "/materials/xas/",
        "paging": f"task_ids chunks of {chunk} material ids",
        "summary_snapshot": SUMMARY_SNAPSHOT,
        "structures_stripped": not keep_structures,
        "materials": len(targets),
        "shards": len(shards),
        "files": [],
    }
    throttle = [0]
    spectra = 0
    for index, ids in enumerate(shards):
        local = output_dir / f"xas-{index:05d}.jsonl.gz"
        if receipt_ok(local):
            try:
                payload = json.loads(
                    local.with_name(local.name + ".receipt.json").read_text())
                spectra += int(payload.get("records", 0))
            except (OSError, ValueError):
                pass
            manifest["files"].append({"name": local.name})
            continue
        query = urllib.parse.urlencode(
            {"task_ids": ",".join(ids), "_limit": 1000, "_all_fields": "true"})
        url = f"{API_ROOT}/materials/xas/?{query}"
        started = time.time()
        payload, wire = fetch_json(url, api_key=api_key, throttle_state=throttle)
        rows = payload.get("data", [])
        if len(rows) >= 1000:
            raise RuntimeError(
                f"shard {index} hit the 1000-doc page cap; lower --chunk")
        part = local.with_name(local.name + ".part")
        with gzip.open(part, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(_trim_xas(row, keep_structures),
                                        separators=(",", ":")) + "\n")
        part.replace(local)
        write_receipt(local, url=url, started=started,
                      extra={"records": len(rows), "materials": len(ids),
                             "wire_bytes": wire})
        spectra += len(rows)
        manifest["files"].append({"name": local.name})
        manifest["spectra"] = spectra
        manifest["complete"] = index + 1 == len(shards)
        write_manifest(output_dir, manifest)
        if index % 25 == 0 or index + 1 == len(shards):
            print(f"[xas] shard {index + 1}/{len(shards)}  {spectra:,} spectra  "
                  f"({time.time() - started:.1f}s last)", flush=True)
        if delay:
            time.sleep(delay)
    manifest["spectra"] = spectra
    manifest["complete"] = True
    write_manifest(output_dir, manifest)
    return manifest


def fetch_absorption(output_dir: Path, *, api_key: str, delay: float,
                     page: int, limit: int | None) -> dict:
    """Page ``/materials/absorption/`` with ``_skip``; only ~946 docs exist."""

    manifest = {
        "source": "Materials Project REST API",
        "family": "absorption",
        "endpoint": API_ROOT + "/materials/absorption/",
        "paging": f"_skip/_limit pages of {page}",
        "summary_snapshot": SUMMARY_SNAPSHOT,
        "files": [],
    }
    throttle = [0]
    skip = 0
    docs = 0
    total = None
    existing = output_dir / "manifest.json"
    if existing.exists():
        try:
            total = json.loads(existing.read_text()).get("total_documents") or None
        except (OSError, ValueError):
            total = None
    while True:
        local = output_dir / f"absorption-{skip:07d}.jsonl.gz"
        if receipt_ok(local):
            with gzip.open(local, "rt", encoding="utf-8") as handle:
                count = sum(1 for _ in handle)
        else:
            query = urllib.parse.urlencode(
                {"_skip": skip, "_limit": page, "_all_fields": "true"})
            url = f"{API_ROOT}/materials/absorption/?{query}"
            started = time.time()
            payload, wire = fetch_json(url, api_key=api_key, throttle_state=throttle)
            rows = payload.get("data", [])
            total = int(payload.get("meta", {}).get("total_doc") or 0) or total
            if not rows:
                break
            part = local.with_name(local.name + ".part")
            with gzip.open(part, "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            part.replace(local)
            write_receipt(local, url=url, started=started,
                          extra={"records": len(rows), "wire_bytes": wire})
            count = len(rows)
            print(f"[absorption] skip={skip} -> {count} docs", flush=True)
            if delay:
                time.sleep(delay)
        docs += count
        manifest["files"].append({"name": local.name})
        manifest["documents"] = docs
        manifest["total_documents"] = total
        write_manifest(output_dir, manifest)
        if count == 0 or (limit and docs >= limit):
            break
        if total is not None and docs >= total:
            break
        skip += count
    manifest["complete"] = total is None or docs >= total
    write_manifest(output_dir, manifest)
    return manifest


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", required=True, choices=FAMILIES)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--date", default="2026-08-19",
                        help="snapshot date used in the output directory name")
    parser.add_argument("--request-delay", type=float, default=0.5)
    parser.add_argument("--chunk", type=int, default=40,
                        help="xas: material ids per request")
    parser.add_argument("--page", type=int, default=100,
                        help="absorption: documents per request")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after N units (parts / materials / docs)")
    parser.add_argument("--keep-structures", action="store_true",
                        help="xas: keep the Structure embedded in each spectrum")
    args = parser.parse_args()

    output = args.output or (
        default_data_root() / "raw" / "acquired" / "materials-project"
        / f"{args.family}-{args.date}"
    )
    output.mkdir(parents=True, exist_ok=True)
    print(f"[{args.family}] -> {output}", flush=True)

    build_targets(args.family, output)

    started = time.time()
    try:
        if args.family in S3_FAMILIES:
            fetch_s3_family(args.family, output, delay=args.request_delay,
                            limit=args.limit)
        elif args.family == "xas":
            fetch_xas(output, api_key=read_api_key(), delay=args.request_delay,
                      chunk=args.chunk, limit=args.limit,
                      keep_structures=args.keep_structures)
        else:
            fetch_absorption(output, api_key=read_api_key(),
                             delay=args.request_delay, page=args.page,
                             limit=args.limit)
    except RateLimited as error:
        print(f"[{args.family}] HARD STOP: {error}", flush=True)
        return 2
    print(f"[{args.family}] done in {(time.time() - started) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
