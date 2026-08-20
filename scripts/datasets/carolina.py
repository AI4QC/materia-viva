#!/usr/bin/env python3
"""Resumable acquirer for the Carolina Materials Database (CMD).

CMD (http://www.carolinamatdb.org/, Jianjun Hu's and Ming Hu's groups at the
University of South Carolina) publishes 214,436 AI-generated ternary and
quaternary inorganic materials under CC BY 4.0.  The site exposes **no** bulk
archive, no REST API and no OPTIMADE endpoint; the only machine-readable route
is the per-record static VASP export served by the site's static file handler:

    http://www.carolinamatdb.org/static/export/vasp/primitive_cell/<i>
    http://www.carolinamatdb.org/static/export/vasp/conventional_cell/<i>

with ``i`` running 0..214435.  The DFT-derived scalars (formation energy per
atom, cell volume, space-group assignment) live only in the record's HTML
detail page, ``/entry/<i+1>/`` -- note the one-based offset between the entry
page id and the static export index.

The site is served over plain HTTP only; its HTTPS listener returns a malformed
TLS record, so ``https://www.carolinamatdb.org/`` cannot be used.

Because a full mirror means one request per record, this module batches records
into gzipped JSONL shards -- the same "one page per N records" convention the
Materials Project and OPTIMADE exporters use -- so a completed shard is the
"file" that carries a ``*.receipt.json`` (source URL range, byte count,
SHA-256, completion time).  Shards already on disk are skipped, which makes the
whole run resumable.  Politeness is mandatory: serial by default, at most two
concurrent requests, a delay between requests, an honest User-Agent, and a hard
stop if the provider ever answers 429.

Examples
--------
Bounded verification sample (400 random records, structures only)::

    python -m scripts.datasets.carolina --sample 400 --seed 20260818

Full mirror of the primitive cells plus the HTML-only property scalars::

    python -m scripts.datasets.carolina --mode full --delay 0.4
"""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import random
import re
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root


SOURCE_ID = "carolina"
BASE_URL = "http://www.carolinamatdb.org"
CATALOG_URL = f"{BASE_URL}/"
LICENSE = "CC BY 4.0"
LICENSE_URL = "http://creativecommons.org/licenses/by/4.0/"

# Provider-stated scale, read from the CMD landing page.
PROVIDER_TOTAL = 214436
PROVIDER_TERNARY = 16302
PROVIDER_QUATERNARY = 198134

# Static export indices are zero-based; entry page ids are one-based.
FIRST_INDEX = 0
LAST_INDEX = PROVIDER_TOTAL - 1

USER_AGENT = (
    "MateriaViva-dataset-acquisition/1.0 "
    "(+https://github.com/materiaviva; academic crystal-structure aggregation; "
    "contact smoakvescio@gmail.com)"
)

MODES = ("primitive", "primitive+conventional", "full")

# Third-party bulk redistributions of CMD.  The provider itself publishes no
# archive, but two CC BY 4.0 curated snapshots exist and both name CMD (and the
# Adv. Sci. 2021 paper) as their origin.  These are the only bulk routes.
BULK_ARCHIVES: tuple[dict[str, Any], ...] = (
    {
        "filename": "matsciml-zenodo-8381476/carolina_matdb.zip",
        "url": "https://zenodo.org/api/records/8381476/files/carolina_matdb.zip/content",
        "bytes": 63053941,
        "landing_page": "https://zenodo.org/records/8381476",
        "doi": "10.5281/zenodo.8381476",
        "publisher": "MatSciML benchmark (Miret et al., Intel Labs)",
        "version": "v1.0.0",
        "published": "2023-08-31",
        "license": "CC BY 4.0",
        "format": "zip of an LMDB of pickled pymatgen Structure dicts",
    },
    {
        "filename": "colabfit-hf/ds.parquet",
        "url": "https://huggingface.co/datasets/colabfit/Carolina_Materials/resolve/main/ds.parquet",
        "bytes": 17970,
        "landing_page": "https://huggingface.co/datasets/colabfit/Carolina_Materials",
        "doi": "10.60732/f2f98394",
        "publisher": "ColabFit Exchange",
        "version": "ColabFit DS_r2r8k3fyb6ny_0",
        "published": "2023-10-17",
        "license": "CC BY 4.0",
        "format": "parquet dataset-info row",
    },
    {
        "filename": "colabfit-hf/co/co_0.parquet",
        "url": (
            "https://huggingface.co/datasets/colabfit/Carolina_Materials/"
            "resolve/main/co/co_0.parquet"
        ),
        "bytes": 114276714,
        "landing_page": "https://huggingface.co/datasets/colabfit/Carolina_Materials",
        "doi": "10.60732/f2f98394",
        "publisher": "ColabFit Exchange",
        "version": "ColabFit DS_r2r8k3fyb6ny_0",
        "published": "2023-10-17",
        "license": "CC BY 4.0",
        "format": "parquet configurations with formation energy",
    },
)


class RateLimited(RuntimeError):
    """Raised when the provider signals rate limiting; the run stops at once."""


def primitive_url(index: int) -> str:
    return f"{BASE_URL}/static/export/vasp/primitive_cell/{index}"


def conventional_url(index: int) -> str:
    return f"{BASE_URL}/static/export/vasp/conventional_cell/{index}"


def entry_url(index: int) -> str:
    """Detail page for a static export index (entry ids are one-based)."""
    return f"{BASE_URL}/entry/{index + 1}/"


_VALUE_RE = re.compile(
    r"<h5>\s*(?P<label>[^<]+?)\s*</h5>\s*<span class=\"value\">(?P<value>.*?)</span>",
    re.S | re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_HM_RE = re.compile(r"^(?P<symbol>.+?)\s*\[(?P<number>\d+)\]\s*$")

_LABEL_KEYS = {
    "reduced formula": "reduced_formula",
    "formation energy / atom": "formation_energy_per_atom",
    "volume": "volume",
    "hermann mauguin": "hermann_mauguin",
    "hall": "hall",
    "point group": "point_group",
    "crystal system": "crystal_system",
}


def parse_entry_html(text: str) -> dict[str, Any]:
    """Extract the CMD detail-page scalars.

    Returns a dict with the raw string values plus parsed numeric fields.  The
    original strings are kept so the adapter can re-derive units later without
    another network round trip.
    """
    raw: dict[str, str] = {}
    for match in _VALUE_RE.finditer(text):
        label = _TAG_RE.sub("", match.group("label")).strip().lower()
        key = _LABEL_KEYS.get(label)
        if key is None:
            continue
        value = html.unescape(_TAG_RE.sub("", match.group("value"))).strip()
        raw[key] = value

    parsed: dict[str, Any] = {"raw": raw}
    if "reduced_formula" in raw:
        # <sub>6</sub> was stripped above, so re-read the subscripts from markup.
        parsed["reduced_formula"] = raw["reduced_formula"]
    fe = raw.get("formation_energy_per_atom")
    if fe is not None:
        try:
            parsed["formation_energy_per_atom_ev"] = float(fe)
        except ValueError:
            pass
    volume = raw.get("volume")
    if volume is not None:
        number = volume.split()[0] if volume.split() else ""
        try:
            parsed["volume_ang3"] = float(number)
        except ValueError:
            pass
    hm = raw.get("hermann_mauguin")
    if hm is not None:
        match = _HM_RE.match(hm)
        if match:
            parsed["spacegroup_symbol"] = match.group("symbol").strip()
            parsed["spacegroup_number"] = int(match.group("number"))
    for key in ("hall", "point_group", "crystal_system"):
        if key in raw:
            parsed[key] = raw[key].strip()
    return parsed


def _reduced_formula_with_subscripts(text: str) -> str | None:
    """Read the reduced formula with <sub> digits folded back in."""
    match = re.search(
        r"<h5>\s*Reduced Formula\s*</h5>\s*<span class=\"value\">(.*?)</span>",
        text,
        re.S | re.I,
    )
    if not match:
        return None
    inner = match.group(1)
    inner = re.sub(r"<sub>(.*?)</sub>", r"\1", inner, flags=re.S | re.I)
    return html.unescape(_TAG_RE.sub("", inner)).strip()


def fetch_text(
    url: str,
    *,
    attempts: int = 5,
    timeout: int = 120,
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[[Request, int], Any] | None = None,
) -> str | None:
    """Fetch one URL, returning ``None`` for a clean 404.

    Backs off on 5xx and transport errors; raises :class:`RateLimited` on 429 so
    the caller can abandon the whole run rather than keep pushing.
    """
    request = Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            if opener is not None:
                response = opener(request, timeout)
                return response
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            if error.code == 429:
                raise RateLimited(f"provider returned 429 for {url}") from error
            if error.code == 404:
                return None
            if error.code < 500:
                raise
            last_error = error
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
        if attempt + 1 < attempts:
            sleep(min(60.0, 2.0**attempt))
    assert last_error is not None
    raise last_error


def _shard_path(output_dir: Path, start: int) -> Path:
    return output_dir / f"records-{start:09d}.jsonl.gz"


def _write_shard(path: Path, rows: Sequence[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".part")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    building.replace(path)
    return path


def _write_receipt(path: Path, *, data_root: Path, urls: dict[str, Any]) -> Path:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    try:
        relative = str(path.relative_to(data_root))
    except ValueError:
        relative = str(path)
    payload = {
        "source_id": SOURCE_ID,
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        **urls,
    }
    receipt = path.with_name(path.name + ".receipt.json")
    building = receipt.with_name(receipt.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(receipt)
    return receipt


def _write_manifest(output_dir: Path, payload: dict[str, Any]) -> Path:
    target = output_dir / "manifest.json"
    building = target.with_name(target.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(target)
    return target


def fetch_record(
    index: int,
    *,
    mode: str,
    delay: float,
    fetch: Callable[[str], str | None],
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch one CMD record at the requested level of detail."""
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    row: dict[str, Any] = {
        "index": index,
        "entry_id": index + 1,
        "native_id": f"cmd-{index}",
        "urls": {"primitive_cell": primitive_url(index)},
    }
    primitive = fetch(primitive_url(index))
    if primitive is None:
        row["missing"] = True
        return row
    row["primitive_poscar"] = primitive

    if mode in ("primitive+conventional", "full"):
        if delay:
            sleep(delay)
        row["urls"]["conventional_cell"] = conventional_url(index)
        conventional = fetch(conventional_url(index))
        if conventional is not None:
            row["conventional_poscar"] = conventional

    if mode == "full":
        if delay:
            sleep(delay)
        row["urls"]["entry"] = entry_url(index)
        page = fetch(entry_url(index))
        if page is not None:
            properties = parse_entry_html(page)
            formula = _reduced_formula_with_subscripts(page)
            if formula:
                properties["reduced_formula"] = formula
            row["properties"] = properties
    return row


def acquire(
    *,
    output_dir: Path,
    indices: Iterable[int],
    mode: str = "primitive",
    shard_size: int = 1000,
    delay: float = 0.5,
    data_root: Path | None = None,
    fetch: Callable[[str], str | None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    provider_total: int = PROVIDER_TOTAL,
) -> Path:
    """Download the requested records into resumable gzipped JSONL shards."""
    if shard_size < 1:
        raise ValueError("shard_size must be positive")
    if delay < 0:
        raise ValueError("delay must not be negative")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(data_root) if data_root is not None else default_data_root()
    do_fetch = fetch or (lambda url: fetch_text(url, sleep=sleep))

    ordered = list(indices)
    shards = [ordered[i : i + shard_size] for i in range(0, len(ordered), shard_size)]
    downloaded = 0
    missing: list[int] = []
    shard_names: list[str] = []
    started = datetime.now(timezone.utc).isoformat()

    for shard_number, block in enumerate(shards):
        path = _shard_path(output_dir, shard_number * shard_size)
        shard_names.append(path.name)
        if path.exists():
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle if line.strip()]
            downloaded += sum(1 for row in rows if not row.get("missing"))
            missing.extend(row["index"] for row in rows if row.get("missing"))
            print(f"[shard {shard_number + 1}/{len(shards)}] resumed {path.name}", flush=True)
            continue

        rows = []
        for position, index in enumerate(block):
            if delay and position:
                sleep(delay)
            row = fetch_record(index, mode=mode, delay=delay, fetch=do_fetch, sleep=sleep)
            rows.append(row)
            if row.get("missing"):
                missing.append(index)
            else:
                downloaded += 1
        _write_shard(path, rows)
        _write_receipt(
            path,
            data_root=root,
            urls={
                "url_pattern": primitive_url(0).replace("/0", "/<index>"),
                "catalog_url": CATALOG_URL,
                "index_first": block[0],
                "index_last": block[-1],
                "records": len(rows),
                "mode": mode,
            },
        )
        print(
            f"[shard {shard_number + 1}/{len(shards)}] wrote {path.name} "
            f"({len(rows)} records, {path.stat().st_size} bytes)",
            flush=True,
        )

        _write_manifest(
            output_dir,
            _manifest_payload(
                mode=mode,
                shard_size=shard_size,
                requested=len(ordered),
                downloaded=downloaded,
                missing=missing,
                shard_names=shard_names[: shard_number + 1],
                complete=False,
                started=started,
                provider_total=provider_total,
                indices=ordered,
            ),
        )

    return _write_manifest(
        output_dir,
        _manifest_payload(
            mode=mode,
            shard_size=shard_size,
            requested=len(ordered),
            downloaded=downloaded,
            missing=missing,
            shard_names=shard_names,
            complete=downloaded + len(missing) == len(ordered),
            started=started,
            provider_total=provider_total,
            indices=ordered,
        ),
    )


def _manifest_payload(
    *,
    mode: str,
    shard_size: int,
    requested: int,
    downloaded: int,
    missing: Sequence[int],
    shard_names: Sequence[str],
    complete: bool,
    started: str,
    provider_total: int,
    indices: Sequence[int],
) -> dict[str, Any]:
    full_mirror = requested == provider_total
    return {
        "source_id": SOURCE_ID,
        "source_name": "Carolina Materials Database",
        "catalog_url": CATALOG_URL,
        "route": "per-record static VASP export (no bulk archive, no API, no OPTIMADE)",
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "provider_stated_total": provider_total,
        "provider_stated_ternary": PROVIDER_TERNARY,
        "provider_stated_quaternary": PROVIDER_QUATERNARY,
        "mode": mode,
        "shard_size": shard_size,
        "requested_records": requested,
        "downloaded_records": downloaded,
        "missing_indices": list(missing),
        "shards": list(shard_names),
        "index_min": min(indices) if indices else None,
        "index_max": max(indices) if indices else None,
        "full_mirror": full_mirror,
        "complete": bool(complete),
        "started_at": started,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def acquire_bulk(
    *,
    output_dir: Path,
    data_root: Path | None = None,
    archives: Sequence[dict[str, Any]] = BULK_ARCHIVES,
) -> Path:
    """Mirror the CC BY 4.0 bulk redistributions with receipts and a manifest."""
    from scripts.datasets.acquire import ensure_capacity, run_curl_resumable
    import shutil

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(data_root) if data_root is not None else default_data_root()
    entries: list[dict[str, Any]] = []

    for archive in archives:
        target = output_dir / archive["filename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target.exists() and target.stat().st_size == archive["bytes"]):
            part = target.with_name(target.name + ".part")
            already = part.stat().st_size if part.exists() else 0
            ensure_capacity(
                available_bytes=shutil.disk_usage(output_dir).free,
                expected_bytes=max(0, int(archive["bytes"]) - already),
            )
            run_curl_resumable(archive["url"], part)
            size = part.stat().st_size
            if size != archive["bytes"]:
                raise RuntimeError(
                    f"{archive['filename']}: expected {archive['bytes']} bytes, got {size}"
                )
            part.replace(target)
        receipt = _write_receipt(
            target,
            data_root=root,
            urls={
                "url": archive["url"],
                "landing_page": archive["landing_page"],
                "doi": archive["doi"],
                "publisher": archive["publisher"],
                "version": archive["version"],
                "published": archive["published"],
                "license": archive["license"],
                "format": archive["format"],
            },
        )
        entries.append(
            {
                "filename": archive["filename"],
                "bytes": target.stat().st_size,
                "sha256": json.loads(receipt.read_text(encoding="utf-8"))["sha256"],
                "url": archive["url"],
                "landing_page": archive["landing_page"],
                "doi": archive["doi"],
                "publisher": archive["publisher"],
                "version": archive["version"],
                "published": archive["published"],
                "license": archive["license"],
                "format": archive["format"],
            }
        )
        print(f"bulk: {archive['filename']} {target.stat().st_size} bytes", flush=True)

    return _write_manifest(
        output_dir,
        {
            "source_id": SOURCE_ID,
            "source_name": "Carolina Materials Database",
            "catalog_url": CATALOG_URL,
            "route": (
                "third-party CC BY 4.0 bulk redistributions; the provider itself "
                "publishes no archive, API or OPTIMADE endpoint"
            ),
            "license": LICENSE,
            "license_url": LICENSE_URL,
            "provider_stated_total": PROVIDER_TOTAL,
            "provider_stated_ternary": PROVIDER_TERNARY,
            "provider_stated_quaternary": PROVIDER_QUATERNARY,
            "archives": entries,
            "complete": len(entries) == len(archives),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bulk",
        action="store_true",
        help="mirror the CC BY 4.0 third-party bulk archives instead of crawling the site",
    )
    parser.add_argument("--mode", choices=MODES, default="primitive")
    parser.add_argument("--shard-size", type=int, default=1000)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="seconds between requests (serial; the site is a small academic host)",
    )
    parser.add_argument("--sample", type=int, help="fetch a random bounded sample instead of all")
    parser.add_argument("--seed", type=int, default=0, help="seed for --sample")
    parser.add_argument("--start", type=int, default=FIRST_INDEX)
    parser.add_argument("--end", type=int, default=LAST_INDEX, help="inclusive")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.bulk:
        output = args.output or (default_data_root() / "raw" / "acquired" / SOURCE_ID / "bulk")
        print(acquire_bulk(output_dir=output), flush=True)
        return 0

    if args.sample is not None and args.sample < 1:
        parser.error("--sample must be positive")
    if args.start < 0 or args.end < args.start:
        parser.error("invalid --start/--end range")

    population = list(range(args.start, args.end + 1))
    if args.sample is not None:
        rng = random.Random(args.seed)
        indices = sorted(rng.sample(population, min(args.sample, len(population))))
        label = f"sample-{args.sample}-seed{args.seed}"
    else:
        indices = population
        label = "full"

    snapshot = datetime.now(timezone.utc).date().isoformat()
    output = args.output or (
        default_data_root() / "raw" / "acquired" / SOURCE_ID / f"cmd-{label}-{snapshot}"
    )

    try:
        manifest = acquire(
            output_dir=output,
            indices=indices,
            mode=args.mode,
            shard_size=args.shard_size,
            delay=args.delay,
        )
    except RateLimited as error:
        print(f"stopping: {error}", flush=True)
        return 2
    print(manifest, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
