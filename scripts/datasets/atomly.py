#!/usr/bin/env python3
"""Resumable bulk acquisition of the Atomly materials database.

Atomly (https://atomly.matchat.cn/) hosts 349,043+ computed crystal
structures. This fetcher mirrors the full database through the documented
read-only API (``/api/matdata/...``) using an account session token
(``Authorization: token <userToken>``), which the site throttles only by the
documented 120 requests/minute per-IP base limit. API keys (``ak_...``) are
restricted to 10 requests/minute and 200/day and are supported as a fallback
auth mode.

Endpoints:

* ``POST /api/matdata/search_by_elements/`` ``{"include": "Si-O"}`` returns up
  to 100 summary rows (struct id, formula, space group, energies, band gap,
  flags) for materials in exactly that chemical system. The 100-row cap is
  absolute (pagination parameters are ignored), so systems with len==100 are
  subdivided by adding one more element, recursively.
* ``POST /api/matdata/get_struct_detail/`` ``{"struct_id": "0000091157"}``
  one material per request: lattice, energies, symmetry, CIF (primitive and
  conventional), electronic-structure diagram, elastic/piezo blocks.
  ``"No material found"`` marks unused id slots.

Struct id layout (probed 2026-07-31): a dense block in ``[1, ~110_000]``
(~90% hit rate) plus very sparse blocks near 1e9 and 3e9 (~1% hit rate,
reachable only via system enumeration).

Phases:

1. ``enum``   query all unary/binary chemical systems, subdividing capped
              systems recursively; stores summary rows under ``index/`` and
              the collected struct id set in ``index/struct_ids.json``.
2. ``detail`` fetch ``get_struct_detail`` for every enumerated id.
3. ``scan``   blind iteration of the dense id block to catch materials that
              enumeration cannot reach (overflow of 100-row-capped systems);
              skips ids already cached by ``detail``.

Rate limiting: a shared token bucket (default 1.8 req/s) paces all workers;
HTTP 429 answers sleep ``Retry-After`` and back the bucket off further.
State (cursor, misses, processed systems, quota-free) persists after every
batch, so any interruption simply resumes on the next run.

Layout under ``raw/acquired/atomly``::

    index/rows-00001.json.gz     batched search rows (summary index)
    index/struct_ids.json        sorted enumerated struct ids
    index/_enum_state.json       processed/pending system sets + cursor
    details/0000091157.json.gz   one gzipped detail per struct id
    _missing_ids.jsonl           struct ids answered "No material found"
    _scan_state.json             blind-scan cursor and hit/miss counters
    manifest.json                acquisition manifest
"""

from __future__ import annotations

import argparse
import gzip
import itertools
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts.datasets.acquire import REPOSITORY_ROOT, default_data_root

API_ROOT = "https://atomly.matchat.cn/api/matdata"
DETAIL_URL = f"{API_ROOT}/get_struct_detail/"
SEARCH_ELEMENTS_URL = f"{API_ROOT}/search_by_elements/"

SOURCE_ID = "atomly"
DATA_PATH = "raw/acquired/atomly"
DOTENV_PATH = REPOSITORY_ROOT / ".env"

# Periodic table through Og, matching the site's explore page.
ELEMENTS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba "
    "La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi "
    "Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr "
    "Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
).split()

REQUEST_TIMEOUT = 120
DEFAULT_RPS = 1.8
MAX_ENUM_DEPTH = 5  # stop subdividing systems at this many elements
DAILY_PARK_THRESHOLD = 600  # Retry-After seconds above which we treat 429 as the daily wall

_print_lock = threading.Lock()


class DailyQuotaExceeded(Exception):
    """Raised when the server answers 429 with a day-scale Retry-After.

    The session token has an undocumented daily request budget (~3,700/day as
    observed 2026-07-31); once exhausted the server replies 429 with
    ``Retry-After: 86400``. Phases propagate this exception so main() can
    park until the reset and resume from persisted state.
    """


def _log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _token(auth_mode: str) -> str:
    _load_dotenv(DOTENV_PATH)
    if auth_mode == "session":
        token = os.environ.get("ATOMLY_SESSION_TOKEN")
        if not token:
            raise RuntimeError("ATOMLY_SESSION_TOKEN not set in environment or .env")
        return token
    token = os.environ.get("ATOMLY_API_KEY")
    if not token:
        raise RuntimeError("ATOMLY_API_KEY not set in environment or .env")
    return token


# ------------------------------------------------------------- rate limit


class RateLimiter:
    """Shared pacing token bucket with 429 backoff."""

    def __init__(self, rps: float):
        self.interval = 1.0 / rps
        self._lock = threading.Lock()
        self._next_at = time.monotonic()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_at - now)
            self._next_at = max(self._next_at, now) + self.interval
        if wait:
            time.sleep(wait)

    def backoff(self, seconds: float) -> None:
        with self._lock:
            self._next_at = max(self._next_at, time.monotonic() + seconds)


# ------------------------------------------------------------ fetch layer


def _post(url: str, payload: dict[str, Any], token: str, limiter: RateLimiter) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(8):
        limiter.acquire()
        try:
            request = Request(
                url,
                data=body,
                headers={
                    "Authorization": f"token {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "MateriaViva-dataset-acquisition/1.0",
                },
                method="POST",
            )
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read())
        except HTTPError as error:
            last_error = error
            if error.code == 429:
                retry_after = float(error.headers.get("Retry-After", "10") or 10)
                if retry_after >= DAILY_PARK_THRESHOLD:
                    raise DailyQuotaExceeded(retry_after)
                _log(f"429; backing off {retry_after:.0f}s")
                limiter.backoff(min(retry_after, 120))
            elif error.code in (500, 502, 503, 504):
                limiter.backoff(min(60, 2**attempt * 5))
            else:
                raise
        except (URLError, TimeoutError, ConnectionError) as error:
            last_error = error
            limiter.backoff(min(60, 2**attempt * 5))
    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------- storage


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".building")
    building.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    building.replace(path)


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write_gz_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(path)


def _detail_path(source_dir: Path, struct_id: str) -> Path:
    return source_dir / "details" / f"{struct_id}.json.gz"


def _is_missing(payload: dict[str, Any]) -> bool:
    return "No material found" in str(payload.get("message", ""))


def save_detail(source_dir: Path, struct_id: str, payload: dict[str, Any]) -> None:
    if payload.get("struct_id") != struct_id:
        raise RuntimeError(f"id mismatch: asked {struct_id}, got {payload.get('struct_id')}")
    _write_gz_json(_detail_path(source_dir, struct_id), payload)


# ------------------------------------------------------------ enum phase


def _system_key(system: Iterable[str]) -> str:
    return "-".join(sorted(system))


def _flush_rows(index_dir: Path, rows: list[Any], batch_no: int) -> int:
    if rows:
        _write_gz_json(index_dir / f"rows-{batch_no:05d}.json.gz", rows)
    return batch_no + 1


def run_enum(source_dir: Path, *, token: str, limiter: RateLimiter, workers: int = 6) -> dict[str, int]:
    """Breadth-first waves over chemical systems, processed in parallel.

    The search endpoint takes ~3s per response, so sequential querying would
    need many hours for the unary+binary wave alone; six workers stay under
    the documented 120 requests/minute IP limit (6 x ~0.31/s ~ 1.9/s).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    index_dir = source_dir / "index"
    state_path = index_dir / "_enum_state.json"
    state = _load_json(
        state_path,
        {
            "processed": [],
            "pending": [_system_key(s) for n in (1, 2) for s in itertools.combinations(ELEMENTS, n)],
            "batch_no": 1,
            "capped_overflow": [],
        },
    )
    processed: set[str] = set(state["processed"])
    pending: list[str] = sorted(set(state["pending"]) - processed)
    batch_no = int(state["batch_no"])
    struct_ids: set[str] = set(_load_json(index_dir / "struct_ids.json", []))
    overflow: set[str] = set(state.get("capped_overflow", []))
    stats = {"queries": 0, "rows": 0, "new_ids": 0, "capped": 0, "failed": 0}
    started = time.time()
    buffer: list[dict[str, Any]] = []
    fail_count: dict[str, int] = {}

    def persist() -> None:
        _write_json(
            state_path,
            {
                "processed": sorted(processed),
                "pending": pending,
                "batch_no": batch_no,
                "capped_overflow": sorted(overflow),
            },
        )
        _write_json(index_dir / "struct_ids.json", sorted(struct_ids))

    def query(system: str) -> tuple[str, dict[str, Any] | None]:
        try:
            return system, _post(SEARCH_ELEMENTS_URL, {"include": system}, token, limiter)
        except DailyQuotaExceeded:
            raise
        except Exception as error:
            _log(f"enum query failed {system}: {error}")
            return system, None

    while pending:
        wave, pending = pending, []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(query, system): system for system in wave}
            try:
                for future in as_completed(futures):
                    system, payload = future.result()
                    if payload is None:
                        stats["failed"] += 1
                        fail_count[system] = fail_count.get(system, 0) + 1
                        if fail_count[system] < 3:
                            pending.append(system)  # retry in a later wave
                        else:
                            overflow.add(f"FAILED:{system}")
                        continue
                    rows = payload.get("results", [])
                    stats["queries"] += 1
                    stats["rows"] += len(rows)
                    before = len(struct_ids)
                    struct_ids.update(str(r[0]) for r in rows)
                    stats["new_ids"] += len(struct_ids) - before
                    buffer.append({"system": system, "len": payload.get("len"), "results": rows})
                    processed.add(system)
                    if payload.get("len") == 100:
                        stats["capped"] += 1
                        elements = system.split("-")
                        if len(elements) < MAX_ENUM_DEPTH:
                            for extra in ELEMENTS:
                                if extra not in elements:
                                    candidate = _system_key([*elements, extra])
                                    if candidate not in processed and candidate not in pending:
                                        pending.append(candidate)
                        else:
                            overflow.add(system)
                    if stats["queries"] % 200 == 0:
                        batch_no = _flush_rows(index_dir, buffer, batch_no)
                        buffer.clear()
                        persist()
                        rate = stats["queries"] / max(time.time() - started, 1e-6)
                        _log(
                            f"enum q={stats['queries']} wave_left={len(wave)} pending={len(pending)} "
                            f"ids={len(struct_ids)} capped={stats['capped']} ({rate:.2f} q/s)"
                        )
            except DailyQuotaExceeded:
                pool.shutdown(wait=False, cancel_futures=True)
                persist()
                raise
        batch_no = _flush_rows(index_dir, buffer, batch_no)
        buffer.clear()
        persist()

    stats["total_ids"] = len(struct_ids)
    return stats


# ---------------------------------------------------------- detail phase


def run_detail_ids(
    source_dir: Path,
    *,
    token: str,
    limiter: RateLimiter,
    struct_ids: list[str],
    phase_name: str = "detail",
) -> dict[str, int]:
    stats = {"fetched": 0, "cached": 0, "missing": 0, "failed": 0}
    missing_log = source_dir / "_missing_ids.jsonl"
    known_missing: set[str] = set()
    if missing_log.exists():
        known_missing.update(missing_log.read_text(encoding="utf-8").split())
    total = len(struct_ids)
    started = time.time()
    done = 0

    def work(struct_id: str) -> str:
        if _detail_path(source_dir, struct_id).exists():
            return "cached"
        if struct_id in known_missing:
            return "missing"
        payload = _post(DETAIL_URL, {"struct_id": struct_id}, token, limiter)
        if _is_missing(payload):
            return "missing"
        save_detail(source_dir, struct_id, payload)
        return "fetched"

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(work, sid): sid for sid in struct_ids}
        try:
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    outcome = future.result()
                except DailyQuotaExceeded:
                    raise
                except Exception as error:
                    _log(f"failed {sid}: {error}")
                    outcome = "failed"
                stats[outcome] += 1
                if outcome == "missing":
                    with missing_log.open("a", encoding="utf-8") as handle:
                        handle.write(sid + "\n")
                done += 1
                if done % 500 == 0 or done == total:
                    rate = done / max(time.time() - started, 1e-6)
                    eta_h = (total - done) / max(rate, 1e-6) / 3600
                    _log(f"{phase_name} {done}/{total} ({rate:.2f}/s, eta {eta_h:.1f}h) {stats}")
        except DailyQuotaExceeded:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    return stats


def run_detail_phase(source_dir: Path, *, token: str, limiter: RateLimiter) -> dict[str, int]:
    struct_ids = _load_json(source_dir / "index" / "struct_ids.json", [])
    if not struct_ids:
        _log("no enumerated ids; run --phase enum first")
        return {"fetched": 0, "cached": 0, "missing": 0, "failed": 0}
    return run_detail_ids(source_dir, token=token, limiter=limiter, struct_ids=struct_ids)


# ------------------------------------------------------------ scan phase


def run_scan(
    source_dir: Path,
    *,
    token: str,
    limiter: RateLimiter,
    start_id: int,
    end_id: int,
) -> dict[str, int]:
    state_path = source_dir / "_scan_state.json"
    state = _load_json(state_path, {"next_id": start_id, "hits": 0, "misses": 0})
    next_id = max(start_id, int(state.get("next_id", start_id)))
    candidates = [f"{i:010d}" for i in range(next_id, end_id + 1)]
    stats = run_detail_ids(
        source_dir, token=token, limiter=limiter, struct_ids=candidates, phase_name="scan"
    )
    state["next_id"] = end_id + 1
    state["hits"] = int(state.get("hits", 0)) + stats["fetched"]
    state["misses"] = int(state.get("misses", 0)) + stats["missing"]
    _write_json(state_path, state)
    return stats


# --------------------------------------------------------------- manifest


def write_manifest(source_dir: Path, *, phase_stats: dict[str, Any]) -> Path:
    details = list((source_dir / "details").glob("*.json.gz"))
    index_dir = source_dir / "index"
    payload = {
        "source_id": SOURCE_ID,
        "name": "Atomly materials science database",
        "official_url": "https://atomly.matchat.cn/explore-materials",
        "api": {"search": SEARCH_ELEMENTS_URL, "detail": DETAIL_URL},
        "estimated_documents": 349043,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "phase_stats": phase_stats,
        "files": {
            "details": {"count": len(details), "bytes": sum(p.stat().st_size for p in details)},
            "index_rows_batches": len(list(index_dir.glob("rows-*.json.gz")))
            if index_dir.exists()
            else 0,
            "enumerated_ids": len(_load_json(index_dir / "struct_ids.json", []))
            if index_dir.exists()
            else 0,
        },
    }
    _write_json(source_dir / "manifest.json", payload)
    return source_dir / "manifest.json"


# -------------------------------------------------------------------- cli


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=["enum", "detail", "scan", "all"],
        default="all",
        help="enum: system enumeration; detail: fetch enumerated ids; scan: blind dense-block sweep",
    )
    parser.add_argument("--auth", choices=["session", "key"], default="session")
    parser.add_argument("--rps", type=float, default=DEFAULT_RPS, help="max requests per second")
    parser.add_argument("--scan-start", type=int, default=1)
    parser.add_argument("--scan-end", type=int, default=150_000)
    args = parser.parse_args()

    token = _token(args.auth)
    limiter = RateLimiter(args.rps if args.auth == "session" else min(args.rps, 0.15))
    source_dir = default_data_root() / DATA_PATH
    phase_stats: dict[str, Any] = {}

    phases = [p for p in ("enum", "detail", "scan") if args.phase in (p, "all")]
    idx = 0
    while idx < len(phases):
        phase = phases[idx]
        try:
            if phase == "enum":
                phase_stats["enum"] = run_enum(source_dir, token=token, limiter=limiter)
            elif phase == "detail":
                phase_stats["detail"] = run_detail_phase(source_dir, token=token, limiter=limiter)
            else:
                phase_stats["scan"] = run_scan(
                    source_dir,
                    token=token,
                    limiter=limiter,
                    start_id=args.scan_start,
                    end_id=args.scan_end,
                )
            write_manifest(source_dir, phase_stats=phase_stats)
            idx += 1
        except DailyQuotaExceeded as quota:
            park = float(quota.args[0]) + 120
            write_manifest(source_dir, phase_stats=phase_stats)
            _log(
                f"daily quota wall; parking {park / 3600:.2f}h "
                f"then resuming phase '{phase}' from persisted state"
            )
            time.sleep(park)
    write_manifest(source_dir, phase_stats=phase_stats)
    _log(f"done: {phase_stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
