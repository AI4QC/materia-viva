#!/usr/bin/env python3
"""Resumable acquisition of the Materiae topological materials catalogue.

Materiae (https://cmpdc.iphy.ac.cn/materiae/) is the Condensed Matter Physics
Data Center catalogue of topological electronic materials (Zhang et al.,
Nature 566, 475-479 (2019)). Its public web API exposes three resource types:

* ``GET /materiae/api/materials``           full summary catalogue (all rows)
* ``GET /materiae/api/materials/{id}``      per-material detail: structure CIFs,
  symmetry indicators, topological classification, DOS curve, BZ data
* ``GET /materiae/data/bandplot/bandplot_{nsoc,soc}/{mp_id}.svg``
  static band-structure plots, available only when the detail record flags
  ``nsoc_band`` / ``soc_band``

Authentication follows the official API documentation: registered users create
an access token (7-day validity) plus a refresh token (1-year validity) at the
site's User -> Profile panel. Place them in the repository ``.env`` as
``MATERIAE_API_ACCESS_TOKEN`` / ``MATERIAE_API_REFRESH_TOKEN``; the fetcher
sends ``Authorization: Bearer <token>``, refreshes an expired access token via
``POST /materiae/api/user/api_token/refresh`` and persists the new token back
to ``.env``. Without tokens it falls back to anonymous browser-profile headers,
which the API also answers.

Layout written under ``raw/acquired/materiae``::

    summary/materials.json.gz        one-shot catalogue export (+ receipt)
    details/MAT00000001.json.gz      one gzipped JSON per material detail
    bandplots/soc/mp-703521.svg      band structure plots that exist
    bandplots/nsoc/mp-703521.svg
    bandplots/_unavailable.json      mp_ids the server answered 404 for
    manifest.json                    acquisition manifest with counts/bytes

Every file is written via a ``.building`` temporary name and atomically
renamed, so an interrupted run can simply be repeated; existing files are
never re-requested.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import http.client
import json
import os
import re
import shutil
import ssl
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.datasets.acquire import (
    REPOSITORY_ROOT,
    default_data_root,
    ensure_capacity,
    write_receipt,
)

SITE_HOST = "cmpdc.iphy.ac.cn"
SITE_ROOT = f"https://{SITE_HOST}"
API_ROOT = "/materiae/api"
SUMMARY_PATH = f"{API_ROOT}/materials"
DETAIL_PATH = f"{API_ROOT}/materials/{{material_id}}"
BANDPLOT_PATH = "/materiae/data/bandplot/bandplot_{kind}/{mp_id}.svg"
SUMMARY_URL = f"{SITE_ROOT}{SUMMARY_PATH}"
DETAIL_URL = f"{SITE_ROOT}{DETAIL_PATH}"
BANDPLOT_URL = f"{SITE_ROOT}{BANDPLOT_PATH}"
BAND_KINDS = ("soc", "nsoc")

SOURCE_ID = "materiae"
DATA_PATH = "raw/acquired/materiae"

HEADERS = {
    "User-Agent": "MateriaViva-dataset-acquisition/1.0",
    "Referer": "https://cmpdc.iphy.ac.cn/materiae/",
    "Accept": "*/*",
}

DETAIL_ID_PATTERN = re.compile(r"^MAT\d{8}$")
EXPECTED_DETAIL_BYTES = 70 * 1024  # observed median raw detail size
REQUEST_TIMEOUT = 300

REFRESH_PATH = "/materiae/api/user/api_token/refresh"
DOTENV_PATH = REPOSITORY_ROOT / ".env"

_print_lock = threading.Lock()
_tls = threading.local()
_auth_lock = threading.Lock()
_access_token: str | None = None
_refresh_token: str | None = None


def _log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def _load_dotenv(path: Path) -> None:
    """Fill missing environment keys from the repository .env (stdlib-only)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _jwt_expiry(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except Exception:
        return 0.0


def _init_auth() -> None:
    """Pick up Materiae API tokens from env/.env, refreshing an expired access token."""
    global _access_token, _refresh_token
    _load_dotenv(DOTENV_PATH)
    _access_token = os.environ.get("MATERIAE_API_ACCESS_TOKEN") or None
    _refresh_token = os.environ.get("MATERIAE_API_REFRESH_TOKEN") or None
    if _access_token and _jwt_expiry(_access_token) < time.time() + 60:
        _log("access token expired; refreshing via refresh token")
        if not _refresh_access_token():
            _access_token = None
    if _access_token:
        _log("auth mode: official API token (Authorization: Bearer)")
    else:
        _log("auth mode: anonymous browser-profile headers (no token found)")


def _request_headers(*, token: str | None = None) -> dict[str, str]:
    headers = dict(HEADERS)
    use = token if token is not None else _access_token
    if use:
        headers["Authorization"] = f"Bearer {use}"
    return headers


def _refresh_access_token() -> bool:
    """Exchange the refresh token for a new access token and persist it to .env."""
    global _access_token
    if not _refresh_token:
        return False
    with _auth_lock:
        if _access_token and _jwt_expiry(_access_token) > time.time() + 60:
            return True  # another worker already refreshed
        try:
            conn = http.client.HTTPSConnection(
                SITE_HOST, 443, timeout=REQUEST_TIMEOUT, context=ssl.create_default_context()
            )
            conn.request(
                "POST", REFRESH_PATH, body="", headers=_request_headers(token=_refresh_token)
            )
            response = conn.getresponse()
            body = response.read()
            conn.close()
            if response.status != 200:
                _log(f"token refresh failed: HTTP {response.status}")
                return False
            _access_token = json.loads(body)["api_access_token"]
        except Exception as error:
            _log(f"token refresh failed: {error}")
            return False
        _persist_access_token(_access_token)
        _log("access token refreshed and persisted to .env")
        return True


def _persist_access_token(token: str) -> None:
    if not DOTENV_PATH.exists():
        return
    lines = DOTENV_PATH.read_text(encoding="utf-8").splitlines()
    with DOTENV_PATH.open("w", encoding="utf-8") as handle:
        for line in lines:
            if line.startswith("MATERIAE_API_ACCESS_TOKEN="):
                handle.write(f"MATERIAE_API_ACCESS_TOKEN={token}\n")
            else:
                handle.write(line + "\n")


def _connection() -> http.client.HTTPSConnection:
    """One keep-alive connection per worker thread."""
    conn = getattr(_tls, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(
            SITE_HOST, 443, timeout=REQUEST_TIMEOUT, context=ssl.create_default_context()
        )
        _tls.conn = conn
    return conn


def _fetch_bytes(url: str, *, attempts: int = 5) -> bytes | None:
    """GET a site path with backoff; return None only for a definitive HTTP 404."""
    path = url[len(SITE_ROOT):] if url.startswith(SITE_ROOT) else url
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            conn = _connection()
            conn.request("GET", path, headers=_request_headers())
            response = conn.getresponse()
            body = response.read()
            if response.status == 404:
                return None
            if response.status == 401 and _refresh_access_token():
                continue
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status} for {path}")
            return body
        except Exception as error:  # keep-alive sockets fail in many transient ways
            last_error = error
            _tls.conn = None
            if attempt + 1 < attempts:
                time.sleep(min(30, 2**attempt))
    assert last_error is not None
    raise last_error


def _fetch_json(url: str, *, attempts: int = 5) -> dict | None:
    payload = _fetch_bytes(url, attempts=attempts)
    if payload is None:
        return None
    return json.loads(payload)


def _write_gz_json(target: Path, payload: Any) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    building = target.with_name(target.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(target)
    return target


def _write_bytes(target: Path, payload: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    building = target.with_name(target.name + ".building")
    building.write_bytes(payload)
    building.replace(target)
    return target


def _read_gz_json(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------- summary


def acquire_summary(source_dir: Path, *, force: bool = False) -> Path:
    target = source_dir / "summary" / "materials.json.gz"
    if target.exists() and not force:
        _log(f"summary already present: {target}")
        return target
    payload = _fetch_json(SUMMARY_URL)
    assert payload is not None
    count = payload.get("count")
    materials = payload.get("materials")
    if not isinstance(count, int) or not isinstance(materials, list) or count != len(materials):
        raise RuntimeError(
            f"summary payload inconsistent: count={count}, rows={len(materials) if isinstance(materials, list) else 'n/a'}"
        )
    _write_gz_json(target, payload)
    write_receipt(target, data_root=default_data_root(), source_id=SOURCE_ID, url=SUMMARY_URL)
    _log(f"summary acquired: {count} materials -> {target}")
    return target


def load_summary_ids(source_dir: Path) -> list[str]:
    payload = _read_gz_json(source_dir / "summary" / "materials.json.gz")
    ids = [row["material_id"] for row in payload["materials"]]
    for material_id in ids:
        if not DETAIL_ID_PATTERN.match(material_id):
            raise ValueError(f"unexpected material_id in summary: {material_id}")
    return ids


# ---------------------------------------------------------------- details


def _detail_path(source_dir: Path, material_id: str) -> Path:
    return source_dir / "details" / f"{material_id}.json.gz"


def _fetch_one_detail(source_dir: Path, material_id: str, delay: float) -> str:
    target = _detail_path(source_dir, material_id)
    if target.exists():
        return "cached"
    if delay:
        time.sleep(delay)
    payload = _fetch_json(DETAIL_URL.format(material_id=material_id))
    if payload is None:
        return "missing"
    if payload.get("material_id") != material_id:
        raise RuntimeError(f"detail id mismatch for {material_id}")
    _write_gz_json(target, payload)
    return "fetched"


def acquire_details(source_dir: Path, *, workers: int, delay: float) -> dict[str, int]:
    material_ids = load_summary_ids(source_dir)
    ensure_capacity(
        available_bytes=shutil.disk_usage(default_data_root()).free,
        expected_bytes=len(material_ids) * EXPECTED_DETAIL_BYTES,
    )
    stats = {"fetched": 0, "cached": 0, "missing": 0}
    started = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_one_detail, source_dir, material_id, delay): material_id
            for material_id in material_ids
        }
        for future in as_completed(futures):
            stats[future.result()] += 1
            done += 1
            if done % 500 == 0 or done == len(material_ids):
                rate = done / max(time.time() - started, 1e-6)
                _log(f"details {done}/{len(material_ids)} ({rate:.1f}/s) {stats}")
    return stats


# -------------------------------------------------------------- bandplots


def _bandplot_path(source_dir: Path, kind: str, mp_id: str) -> Path:
    return source_dir / "bandplots" / kind / f"{mp_id}.svg"


def _unavailable_path(source_dir: Path) -> Path:
    return source_dir / "bandplots" / "_unavailable.json"


def _load_unavailable(source_dir: Path) -> dict[str, list[str]]:
    path = _unavailable_path(source_dir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {kind: [] for kind in BAND_KINDS}


def _iter_bandplot_jobs(source_dir: Path) -> list[tuple[str, str]]:
    """(kind, mp_id) pairs for every detail record flagging a band plot."""
    jobs: list[tuple[str, str]] = []
    details_dir = source_dir / "details"
    for path in sorted(details_dir.glob("MAT*.json.gz")):
        detail = _read_gz_json(path)
        mp_id = detail.get("mp_id")
        if not mp_id:
            continue
        for kind in BAND_KINDS:
            if detail.get(f"{kind}_band"):
                jobs.append((kind, mp_id))
    return jobs


def _fetch_one_bandplot(
    source_dir: Path,
    kind: str,
    mp_id: str,
    delay: float,
    unavailable: dict[str, set[str]],
) -> str:
    if mp_id in unavailable[kind]:
        return "unavailable"
    target = _bandplot_path(source_dir, kind, mp_id)
    if target.exists():
        return "cached"
    if delay:
        time.sleep(delay)
    payload = _fetch_bytes(BANDPLOT_URL.format(kind=kind, mp_id=mp_id))
    if payload is None:
        unavailable[kind].add(mp_id)
        return "unavailable"
    _write_bytes(target, payload)
    return "fetched"


def acquire_bandplots(source_dir: Path, *, workers: int, delay: float) -> dict[str, int]:
    jobs = _iter_bandplot_jobs(source_dir)
    unavailable_lists = _load_unavailable(source_dir)
    unavailable: dict[str, set[str]] = {
        kind: set(unavailable_lists.get(kind, [])) for kind in BAND_KINDS
    }
    stats = {"fetched": 0, "cached": 0, "unavailable": 0}
    started = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_one_bandplot, source_dir, kind, mp_id, delay, unavailable): (
                kind,
                mp_id,
            )
            for kind, mp_id in jobs
        }
        for future in as_completed(futures):
            stats[future.result()] += 1
            done += 1
            if done % 500 == 0 or done == len(jobs):
                rate = done / max(time.time() - started, 1e-6)
                _log(f"bandplots {done}/{len(jobs)} ({rate:.1f}/s) {stats}")
    _write_gz_json(
        _unavailable_path(source_dir).with_suffix(".json.gz"),
        {kind: sorted(values) for kind, values in unavailable.items()},
    )
    # keep the plain-json variant removed to avoid stale duplicates
    plain = _unavailable_path(source_dir)
    if plain.exists():
        plain.unlink()
    return stats


# --------------------------------------------------------------- manifest


def write_manifest(source_dir: Path, *, phases: dict[str, dict[str, int]]) -> Path:
    def _tree_stats(pattern_root: Path, suffix: str) -> tuple[int, int]:
        files = [p for p in pattern_root.rglob(suffix) if p.is_file()]
        return len(files), sum(p.stat().st_size for p in files)

    summary_file = source_dir / "summary" / "materials.json.gz"
    n_details, detail_bytes = _tree_stats(source_dir / "details", "*.json.gz")
    n_bandplots, bandplot_bytes = _tree_stats(source_dir / "bandplots", "*.svg")
    payload = {
        "source_id": SOURCE_ID,
        "name": "Materiae - Material Sciences Database (CMPDC, IOP & CNIC, CAS)",
        "official_url": "https://cmpdc.iphy.ac.cn/materiae/",
        "api": {
            "summary": SUMMARY_URL,
            "detail": DETAIL_URL,
            "bandplot": BANDPLOT_URL,
        },
        "citation": (
            "Tiantian Zhang et al., Catalogue of topological electronic "
            "materials, Nature 566, 475-479 (2019)"
        ),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "phases": phases,
        "files": {
            "summary": {
                "path": str(summary_file.relative_to(source_dir.parent.parent.parent))
                if summary_file.exists()
                else None,
                "bytes": summary_file.stat().st_size if summary_file.exists() else 0,
            },
            "details": {"count": n_details, "bytes": detail_bytes},
            "bandplots": {"count": n_bandplots, "bytes": bandplot_bytes},
        },
    }
    target = source_dir / "manifest.json"
    building = target.with_name(target.name + ".building")
    building.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    building.replace(target)
    return target


# -------------------------------------------------------------------- cli


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=["summary", "details", "bandplots", "all"],
        default="all",
        help="acquisition phase to run (default: all)",
    )
    parser.add_argument("--workers", type=int, default=4, help="concurrent fetch workers")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="polite delay in seconds before each request, per worker",
    )
    parser.add_argument(
        "--force-summary",
        action="store_true",
        help="re-download the summary catalogue even if cached",
    )
    args = parser.parse_args()

    _init_auth()
    source_dir = default_data_root() / DATA_PATH
    phases: dict[str, dict[str, int]] = {}

    if args.phase in ("summary", "all"):
        acquire_summary(source_dir, force=args.force_summary)
        phases["summary"] = {"fetched": 1}
    if args.phase in ("details", "all"):
        phases["details"] = acquire_details(source_dir, workers=args.workers, delay=args.delay)
    if args.phase in ("bandplots", "all"):
        phases["bandplots"] = acquire_bandplots(source_dir, workers=args.workers, delay=args.delay)

    manifest = write_manifest(source_dir, phases=phases)
    _log(f"manifest written: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
