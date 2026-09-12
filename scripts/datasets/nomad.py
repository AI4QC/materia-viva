#!/usr/bin/env python3
"""Resumable, selective export of public NOMAD materials and properties.

The public NOMAD deployment contains far more data than can be mirrored on a
workstation.  This downloader therefore separates the export into four stages:

``probe``
    Freeze a public snapshot cutoff, record live counts, and save the current
    searchable property schema.
``catalog``
    Page through all public entries, retaining material identifiers,
    provenance, method metadata, property availability, and scalar properties.
``select``
    Build a compact SQLite work queue with one representative entry per NOMAD
    material and property-bearing entry sets for selective Archive downloads.
``archive``
    Download only the requested Archive branches (structures, all properties,
    electronic bands/DOS, phonons, or spectra) in bounded gzip pages.  The
    selection can be split into deterministic ``entry_id`` shards
    (``--shards N --shard K`` for one process per shard, or ``--workers N`` to
    run every shard concurrently inside one process); each shard keeps its own
    resumable manifest under ``archive/<kind>/shard-KK-of-NN/``.

Every network phase is independently resumable.  Pages are written through a
``.building`` file and committed to an atomic manifest only after validation
and SHA-256 calculation.  The script intentionally does not download NOMAD raw
files.  Public data does not require authentication.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import shutil
import sqlite3
import sys
import threading
import time
import zlib
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from scripts.datasets.acquire import CapacityError, default_data_root
except ModuleNotFoundError as error:
    if error.name != "scripts":
        raise
    # Allow the documented direct invocation: python scripts/datasets/nomad.py
    from acquire import CapacityError, default_data_root


API_BASE = "https://nomad-lab.eu/prod/v1/api/v1"
USER_AGENT = "MateriaViva-NOMAD-export/1.0"
MANIFEST_SCHEMA_VERSION = 2
# Archive pages are addressed by entry_id, so the batch size only sets how many
# entries one request carries; fewer, larger requests suit NOMAD's per-request
# token bucket.  Responses for resolved properties weigh ~270 KB of JSON per
# entry, so 1000 already means ~2 GB of Python objects per worker.
MAX_ARCHIVE_BATCH = 5000
DEFAULT_RESERVE_BYTES = 50 * 1024**3
SNAPSHOT_TIME_FIELD = "entry_create_time"

CATALOG_BASE_FIELDS = (
    "entry_id",
    "upload_id",
    "mainfile",
    "entry_create_time",
    "entry_type",
    "parser_name",
    "upload_create_time",
    "publish_time",
    "datasets",
    "references",
    "results.material.material_id",
    "results.material.chemical_formula_reduced",
    "results.material.elements",
    "results.material.n_elements",
    "results.material.structural_type",
    "results.material.symmetry.crystal_system",
    "results.material.symmetry.space_group_number",
    "results.material.symmetry.space_group_symbol",
    "results.method.method_name",
    "results.method.simulation.program_name",
    "results.method.simulation.dft.xc_functional_type",
    "results.properties.available_properties",
)

PROPERTY_TAGS: dict[str, tuple[str, ...]] = {
    "band": ("band_structure_electronic",),
    "dos": ("dos_electronic", "dos_electronic_new"),
    "phonon-band": ("band_structure_phonon",),
    "phonon-dos": ("dos_phonon",),
    "spectra": ("spectra",),
    "xrd": ("structural.diffraction_pattern",),
}

PROPERTY_BITS = {
    "properties": 1 << 0,
    "band": 1 << 1,
    "dos": 1 << 2,
    "phonon-band": 1 << 3,
    "phonon-dos": 1 << 4,
    "spectra": 1 << 5,
}

COMMON_ARCHIVE_METADATA = {
    "entry_id": "*",
    "upload_id": "*",
    "mainfile": "*",
}

ARCHIVE_REQUIRED: dict[str, dict[str, Any]] = {
    "structures": {
        "metadata": COMMON_ARCHIVE_METADATA,
        "results": {"material": "*", "method": "*"},
        "run": {"system[-1]": {"atoms": "*"}},
    },
    "properties": {
        "metadata": COMMON_ARCHIVE_METADATA,
        "results": {
            "material": "*",
            "method": "*",
            "properties": "include-resolved",
        },
        # These legacy branches are not always referenced by results.properties.
        "run": {
            "calculation": {
                "band_structure_electronic": "*",
                "dos_electronic": "*",
                "band_structure_phonon": "*",
                "dos_phonon": "*",
                "spectra": "*",
            }
        },
    },
    "band": {
        "metadata": COMMON_ARCHIVE_METADATA,
        "results": {
            "material": "*",
            "method": "*",
            "properties": {
                "electronic": {
                    "band_structure_electronic": "include-resolved",
                }
            },
        },
        "run": {"calculation": {"band_structure_electronic": "*"}},
    },
    "dos": {
        "metadata": COMMON_ARCHIVE_METADATA,
        "results": {
            "material": "*",
            "method": "*",
            "properties": {
                "electronic": {
                    "dos_electronic": "include-resolved",
                    "dos_electronic_new": "include-resolved",
                }
            },
        },
        "run": {"calculation": {"dos_electronic": "*"}},
    },
    "phonon-band": {
        "metadata": COMMON_ARCHIVE_METADATA,
        "results": {
            "material": "*",
            "method": "*",
            "properties": {
                "vibrational": {
                    "band_structure_phonon": "include-resolved",
                }
            },
        },
        "run": {"calculation": {"band_structure_phonon": "*"}},
    },
    "phonon-dos": {
        "metadata": COMMON_ARCHIVE_METADATA,
        "results": {
            "material": "*",
            "method": "*",
            "properties": {
                "vibrational": {"dos_phonon": "include-resolved"},
            },
        },
        "run": {"calculation": {"dos_phonon": "*"}},
    },
    "spectra": {
        "metadata": COMMON_ARCHIVE_METADATA,
        "results": {
            "material": "*",
            "method": "*",
            "properties": "include-resolved",
        },
        "run": {"calculation": {"spectra": "*"}},
    },
}

JsonValue = dict[str, Any] | list[Any]
FetchJson = Callable[[str, dict[str, Any] | None], JsonValue]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _write_json_atomic(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".building")
    building.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    building.replace(path)
    return path


def _write_gzip_json_atomic(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(path)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_gzip_json(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object in {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_capacity(path: Path, reserve_bytes: int) -> None:
    if reserve_bytes < 0:
        raise ValueError("reserve_bytes must not be negative")
    available = shutil.disk_usage(path).free
    if available < reserve_bytes:
        raise CapacityError(
            f"NOMAD export stopped before violating the reserve "
            f"(available={available}, reserve={reserve_bytes})"
        )


RETRYABLE_HTTP = {429, 500, 502, 503, 504}


def _retry_after_seconds(header: str | None) -> float:
    if not header:
        return 0.0
    try:
        return max(0.0, float(header))
    except ValueError:
        return 0.0


def retry_delay(
    attempt: int, *, status: int | None = None, retry_after: str | None = None
) -> float:
    """Seconds to wait before retry number ``attempt`` (0-based).

    A ``Retry-After`` header always wins.  HTTP 429 means NOMAD is throttling
    this client, and our Archive requests take 30-60 s each, so a short
    exponential backoff (1, 2, 4 s...) would only collide with the requests
    still in flight; 429 therefore starts at 15 s and grows to five minutes,
    with jitter so concurrent shards do not retry in lockstep.  Other errors
    keep the original 1 s doubling capped at two minutes.
    """
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    if status == 429:
        base = min(300.0, 15.0 * 2**attempt)
        return base + random.uniform(0.0, 0.25 * base)
    return float(min(120, 2**attempt))


class AdaptiveLimiter:
    """Bound the requests in flight across shard threads, adapting to HTTP 429.

    NOMAD throttles a client that keeps too many heavy Archive queries in
    flight (measured 2026-09-05: four concurrent 100-entry queries passed,
    eight did not, and four 500-entry queries were refused after a burst of
    earlier requests).  The limit is not documented, so instead of guessing a
    constant this limiter starts at ``capacity`` slots, gives one slot back
    every time a request is throttled, and re-adds a slot after ``recovery``
    consecutive successes, never exceeding the initial capacity.
    """

    def __init__(
        self,
        capacity: int,
        *,
        floor: int = 1,
        recovery: int = 20,
        min_interval: float = 2.0,
        initial: int | None = None,
    ) -> None:
        """``capacity`` is the ceiling; ``initial`` (default: the ceiling) is where the
        in-flight cap starts, so a run can begin cautiously and still discover
        headroom later, one slot per ``recovery`` consecutive successes."""
        if capacity < 1 or floor < 1 or floor > capacity or recovery < 1:
            raise ValueError("invalid limiter parameters")
        if min_interval < 0:
            raise ValueError("min_interval must not be negative")
        start = capacity if initial is None else initial
        if not floor <= start <= capacity:
            raise ValueError("initial must lie between floor and capacity")
        self.ceiling = capacity
        self.floor = floor
        self.recovery = recovery
        # NOMAD answers a burst of simultaneous requests with 429 even when the
        # steady-state concurrency is fine, so request starts are spaced out.
        self.min_interval = min_interval
        self._capacity = start
        self._inflight = 0
        self._successes = 0
        self._throttles = 0
        self._resume_at = 0.0
        self._last_start = float("-inf")
        self._urgent_waiting = 0
        self._reserved = 0
        self._probing = False
        self._condition = threading.Condition()

    def probe_due(self) -> bool:
        """Claim the right to run one cheap concurrency probe, if one is due.

        Growing the cap by simply admitting a second full request proved
        expensive (2026-09-06): the newcomer took NOMAD's single service slot
        and the request already queued was rejected five minutes later.  A
        probe is instead a tiny request sent while a real one is in flight;
        only a 200 on that probe grows the cap.
        """
        with self._condition:
            if (
                self._probing
                or self._capacity >= self.ceiling
                or self._successes < self.recovery
            ):
                return False
            self._probing = True
            return True

    def probe_result(self, accepted: bool, *, cooldown: float = 0.0) -> None:
        with self._condition:
            self._probing = False
            self._successes = 0
            if accepted and self._capacity < self.ceiling:
                self._capacity += 1
            elif not accepted and cooldown > 0:
                self._resume_at = max(self._resume_at, time.monotonic() + cooldown)
            self._condition.notify_all()

    def reserve(self, delta: int) -> None:
        """Reserve (delta > 0) or free (delta < 0) slots for urgent callers.

        While ``reserved`` urgent streams exist, non-urgent callers may only
        use the capacity above that number, so with a cap of 1 the urgent
        stream runs back-to-back and non-urgent work waits for spare capacity.
        """
        with self._condition:
            self._reserved = max(0, self._reserved + delta)
            self._condition.notify_all()

    @property
    def capacity(self) -> int:
        with self._condition:
            return self._capacity

    @property
    def inflight(self) -> int:
        with self._condition:
            return self._inflight

    @property
    def consecutive_throttles(self) -> int:
        with self._condition:
            return self._throttles

    def _pause(self, now: float) -> float:
        return max(
            0.0, self._resume_at - now, self._last_start + self.min_interval - now
        )

    def wait_seconds(self, now: float | None = None) -> float:
        """Seconds a request starting now would wait for the cooldown/spacing."""
        now = time.monotonic() if now is None else now
        with self._condition:
            return self._pause(now)

    def acquire(self, priority: int = 0) -> None:
        """Block until a request may start.

        ``priority`` 0 is urgent: while any urgent caller is waiting, callers
        with a lower priority (larger number) keep waiting even if a slot is
        free, so a scarce concurrency budget goes to the phase that matters
        most (structures before properties) instead of being shared evenly.
        """
        urgent = priority <= 0
        with self._condition:
            if urgent:
                self._urgent_waiting += 1
            try:
                while True:
                    pause = self._pause(time.monotonic())
                    if urgent:
                        free = self._inflight < self._capacity
                    else:
                        free = (
                            self._inflight < self._capacity - self._reserved
                            and self._urgent_waiting == 0
                        )
                    if pause <= 0 and free:
                        break
                    self._condition.wait(timeout=pause if pause > 0 else None)
                self._inflight += 1
                self._last_start = time.monotonic()
            finally:
                if urgent:
                    self._urgent_waiting -= 1

    def release(self) -> None:
        with self._condition:
            self._inflight -= 1
            self._condition.notify_all()

    def slot(self, priority: int = 0) -> "_LimiterSlot":
        return _LimiterSlot(self, priority)

    def __enter__(self) -> "AdaptiveLimiter":
        self.acquire(0)
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()

    def throttled(self, cooldown: float = 0.0) -> None:
        """Record an HTTP 429: shrink concurrency and pause every thread.

        ``cooldown`` seconds pass before any thread may start a request again,
        so several shards cannot keep re-triggering the limit in turn.
        """
        with self._condition:
            self._capacity = max(self.floor, self._capacity - 1)
            self._successes = 0
            self._throttles += 1
            self._resume_at = max(self._resume_at, time.monotonic() + max(0.0, cooldown))

    def succeeded(self) -> None:
        with self._condition:
            self._throttles = 0
            self._successes += 1


class _LimiterSlot:
    def __init__(self, limiter: AdaptiveLimiter, priority: int) -> None:
        self._limiter = limiter
        self._priority = priority

    def __enter__(self) -> "_LimiterSlot":
        self._limiter.acquire(self._priority)
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._limiter.release()


class NomadClient:
    """Small retrying client for NOMAD's public JSON API."""

    def __init__(
        self,
        *,
        base_url: str = API_BASE,
        attempts: int = 6,
        timeout: int = 600,
        request_delay: float = 0.0,
        limiter: AdaptiveLimiter | None = None,
        throttle_patience: float = 3600.0,
        throttle_base: float = 60.0,
        throttle_cap: float = 600.0,
        network_patience: float = 1800.0,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be positive")
        if throttle_patience < 0 or throttle_base <= 0 or throttle_cap < throttle_base:
            raise ValueError("invalid throttle parameters")
        if network_patience < 0:
            raise ValueError("network_patience must not be negative")
        # NOMAD's Archive endpoint is metered per client as a small token bucket
        # of *requests* (measured 2026-09-06: roughly 2-3 per minute with a
        # burst of about 4, independent of request size).  A rejected request
        # still spends a token, so after a 429 the client must stay silent for
        # at least one refill period; the wait doubles with every consecutive
        # 429 seen by this process, up to ``throttle_cap``.
        self.throttle_base = throttle_base
        self.throttle_cap = throttle_cap
        # Seconds after a real request starts before its concurrency probe fires;
        # long enough that the real request is certainly still being served.
        self.probe_delay = 5.0
        self.probe_timeout = 60
        self.probe_reject_cooldown = 10.0
        self.base_url = base_url.rstrip("/")
        self.attempts = attempts
        self.timeout = timeout
        self.request_delay = request_delay
        self.limiter = limiter
        # Being throttled is not a failed request: keep waiting for up to this
        # many cumulative seconds per request before giving up on it.
        self.throttle_patience = throttle_patience
        # A dropped connection, a 5xx or a DNS failure is usually an outage on
        # one side of the wire, not a permanent error.  A fixed attempt count
        # covered only ~4 minutes and lost a 23-day run to a cluster network
        # outage (2026-09-11), so transient failures are bounded by time too:
        # keep retrying (with the same 1..120 s backoff) for this many
        # cumulative seconds before giving up on the request.
        self.network_patience = network_patience

    PROBE_PAYLOAD: dict[str, Any] = {
        "owner": "public",
        "query": {},
        "pagination": {"page_size": 1},
        "required": {"metadata": {"entry_id": "*"}},
    }

    def _schedule_probe(self) -> None:
        timer = threading.Timer(self.probe_delay, self._run_probe)
        timer.daemon = True
        timer.start()

    def _run_probe(self) -> None:
        """Send one tiny Archive request outside the limiter and report the verdict."""
        assert self.limiter is not None
        request = Request(
            f"{self.base_url}/entries/archive/query",
            data=_compact_json(self.PROBE_PAYLOAD).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=self.probe_timeout) as response:
                response.read()
            self.limiter.probe_result(True)
            print(
                f"NOMAD accepted a concurrent probe; in-flight limit now "
                f"{self.limiter.capacity}",
                flush=True,
            )
        except HTTPError as error:
            error.close()
            self.limiter.probe_result(
                False, cooldown=self.probe_reject_cooldown if error.code == 429 else 0.0
            )
            print(
                f"NOMAD rejected the concurrent probe (HTTP {error.code}); "
                f"in-flight limit stays {self.limiter.capacity}",
                flush=True,
            )
        except Exception:  # noqa: BLE001 - a failed probe must never hurt the export
            self.limiter.probe_result(False)

    def throttle_cooldown(self, consecutive: int, retry_after: str | None) -> float:
        """Seconds to stay silent after the ``consecutive``-th 429 in a row."""
        escalated = min(self.throttle_cap, self.throttle_base * 2 ** max(0, consecutive))
        jitter = random.uniform(0.0, 0.1 * escalated)
        return max(_retry_after_seconds(retry_after), escalated + jitter)

    def request_json(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int = 0,
    ) -> JsonValue:
        if self.request_delay:
            time.sleep(self.request_delay)
        body = _compact_json(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}/{path.lstrip('/')}",
            data=body,
            method="POST" if payload is not None else "GET",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        last_error: Exception | None = None
        attempt = 0  # real failures (5xx, network); throttling is counted apart
        network_waited = 0.0
        throttles = 0
        throttled_for = 0.0
        while True:
            try:
                with self.limiter.slot(priority) if self.limiter else _NO_LIMIT:
                    if self.limiter is not None and self.limiter.probe_due():
                        self._schedule_probe()
                    with urlopen(request, timeout=self.timeout) as response:
                        raw = response.read()
                        if response.headers.get("Content-Encoding", "").lower() == "gzip":
                            raw = gzip.decompress(raw)
                if self.limiter is not None:
                    self.limiter.succeeded()
                return json.loads(raw)
            except HTTPError as error:
                last_error = error
                if error.code == 429:
                    error.close()  # drop the socket now instead of at GC (CLOSE-WAIT pile-up)
                    # NOMAD's Retry-After is only a few seconds; obeying it
                    # literally from several threads kept the limit tripped
                    # (2026-09-06), so the wait escalates from ``throttle_base``
                    # and pauses every thread of this process, not just this one.
                    consecutive = (
                        self.limiter.consecutive_throttles
                        if self.limiter is not None
                        else throttles
                    )
                    cooldown = self.throttle_cooldown(
                        consecutive, error.headers.get("Retry-After")
                    )
                    throttles += 1
                    throttled_for += cooldown
                    if self.limiter is not None:
                        self.limiter.throttled(cooldown)
                    print(
                        f"NOMAD throttled us (429); pausing {cooldown:.0f} s"
                        + (
                            f", in-flight limit now {self.limiter.capacity}"
                            if self.limiter is not None
                            else ""
                        ),
                        flush=True,
                    )
                    if throttled_for > self.throttle_patience:
                        raise RuntimeError(
                            f"NOMAD kept throttling for {throttled_for:.0f} s: "
                            f"{request.full_url}"
                        ) from error
                    time.sleep(cooldown)
                    continue
                if error.code not in RETRYABLE_HTTP:
                    detail = error.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"NOMAD HTTP {error.code} for {request.full_url}: {detail[:1000]}"
                    ) from error
                delay = retry_delay(
                    attempt,
                    status=error.code,
                    retry_after=error.headers.get("Retry-After"),
                )
            except (HTTPException, OSError, EOFError, json.JSONDecodeError) as error:
                # URLError, timeouts and connection resets are OSErrors; a
                # response cut off mid-stream (NOMAD's 600 s server timeout
                # while a slow query trickles, seen 2026-09-07) surfaces as
                # http.client.IncompleteRead, and a truncated body as EOFError
                # from gzip or a JSON decode error.  All of them mean "try again".
                last_error = error
                delay = retry_delay(attempt)
            attempt += 1
            network_waited += delay
            if attempt >= self.attempts and network_waited >= self.network_patience:
                break
            if attempt % 10 == 0:
                print(
                    f"NOMAD request still failing after {attempt} attempts "
                    f"({network_waited:.0f} s): {type(last_error).__name__}",
                    flush=True,
                )
            time.sleep(delay)
        assert last_error is not None
        raise RuntimeError(
            f"NOMAD request failed after {attempt} attempts over "
            f"{network_waited:.0f} s: {request.full_url}"
        ) from last_error


def discover_scalar_fields(fetch_json: FetchJson) -> tuple[list[str], list[dict[str, Any]]]:
    """Return compact scalar fields plus the schema records used to select them."""
    payload = fetch_json(
        "/apps/search-quantities",
        {
            "app_path": "entries",
            "query": {"input": "results.properties"},
            "pagination": {"page_size": 10000},
        },
    )
    if not isinstance(payload, list):
        raise RuntimeError("NOMAD search-quantities response was not a list")
    scalar_dtypes = {"int", "float", "boolean", "string", "enum", "datetime"}
    fields = set(CATALOG_BASE_FIELDS)
    for item in payload:
        if not isinstance(item, dict):
            continue
        quantity = item.get("quantity")
        if not isinstance(quantity, str) or not quantity.startswith("results.properties"):
            continue
        if item.get("dtype") not in scalar_dtypes:
            continue
        if item.get("shape") in (None, []):
            fields.add(quantity)
    return sorted(fields), payload


def _material_aggregation() -> dict[str, Any]:
    return {
        "materials": {
            "terms": {
                "quantity": "results.material.material_id",
                "pagination": {"page_size": 1},
            }
        }
    }


def _public_count(
    fetch_json: FetchJson,
    *,
    query: dict[str, Any],
) -> tuple[int, int]:
    response = fetch_json(
        "/entries/query",
        {
            "owner": "public",
            "query": query,
            "pagination": {"page_size": 0},
            "aggregations": _material_aggregation(),
        },
    )
    if not isinstance(response, dict):
        raise RuntimeError("NOMAD entries response was not an object")
    try:
        entries = int(response["pagination"]["total"])
        materials = int(
            response["aggregations"]["materials"]["terms"]["pagination"]["total"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("NOMAD count response was missing totals") from error
    return entries, materials


def build_snapshot(
    output_dir: Path,
    *,
    cutoff: str,
    fetch_json: FetchJson,
) -> Path:
    """Write immutable live counts and schema metadata for one public snapshot."""
    target = output_dir / "snapshot.json"
    if target.exists():
        existing = _read_json(target)
        if existing.get("cutoff_field") != SNAPSHOT_TIME_FIELD:
            raise RuntimeError(
                "existing snapshot uses an obsolete cutoff field; choose a new "
                "output directory and run probe again"
            )
        if existing.get("cutoff") != cutoff:
            raise RuntimeError(
                f"snapshot cutoff mismatch: {existing.get('cutoff')} != {cutoff}"
            )
        return target

    info = fetch_json("/info", None)
    if not isinstance(info, dict):
        raise RuntimeError("NOMAD info response was not an object")
    scalar_fields, search_quantities = discover_scalar_fields(fetch_json)
    base_query = {f"{SNAPSHOT_TIME_FIELD}:lte": cutoff}
    public_entries, public_materials = _public_count(fetch_json, query=base_query)

    coverage: dict[str, dict[str, int]] = {}
    for kind, tags in PROPERTY_TAGS.items():
        query = dict(base_query)
        key = (
            "results.properties.available_properties:any"
            if len(tags) > 1
            else "results.properties.available_properties"
        )
        query[key] = list(tags) if len(tags) > 1 else tags[0]
        entries, materials = _public_count(fetch_json, query=query)
        coverage[kind] = {"entries": entries, "materials": materials}

    schema_path = output_dir / "schema" / "search-quantities.json.gz"
    _write_gzip_json_atomic(schema_path, {"data": search_quantities})
    return _write_json_atomic(
        target,
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "source": "NOMAD public API",
            "endpoint": API_BASE,
            "owner": "public",
            "cutoff": cutoff,
            "cutoff_field": SNAPSHOT_TIME_FIELD,
            "created_at": utc_now(),
            "nomad": {
                "version": info.get("version"),
                "deployment": info.get("deployment"),
                "statistics": info.get("statistics"),
            },
            "public": {
                "entries": public_entries,
                "materials": public_materials,
                "property_coverage": coverage,
            },
            "catalog_fields": scalar_fields,
            "search_quantities_path": str(schema_path.relative_to(output_dir)),
        },
    )


def ensure_snapshot(
    output_dir: Path,
    *,
    cutoff: str | None,
    fetch_json: FetchJson,
) -> dict[str, Any]:
    target = output_dir / "snapshot.json"
    if target.exists():
        snapshot = _read_json(target)
        if snapshot.get("cutoff_field") != SNAPSHOT_TIME_FIELD:
            raise RuntimeError(
                "existing snapshot uses an obsolete cutoff field; choose a new "
                "output directory and run probe again"
            )
        if cutoff is not None and snapshot.get("cutoff") != cutoff:
            raise RuntimeError(
                f"snapshot cutoff mismatch: {snapshot.get('cutoff')} != {cutoff}"
            )
        return snapshot
    frozen_cutoff = cutoff or utc_now()
    build_snapshot(output_dir, cutoff=frozen_cutoff, fetch_json=fetch_json)
    return _read_json(target)


def build_catalog_request(
    *,
    cutoff: str,
    fields: Sequence[str],
    page_size: int,
    cursor: str | None,
) -> dict[str, Any]:
    if not 1 <= page_size <= 10000:
        raise ValueError("catalog page_size must be between 1 and 10000")
    pagination: dict[str, Any] = {
        "page_size": page_size,
        "order_by": "entry_id",
        "order": "asc",
    }
    if cursor is not None:
        pagination["page_after_value"] = cursor
    return {
        "owner": "public",
        "query": {f"{SNAPSHOT_TIME_FIELD}:lte": cutoff},
        "pagination": pagination,
        "required": {"include": list(fields)},
    }


def _new_paged_manifest(
    *,
    phase: str,
    cutoff: str,
    page_size: int,
    required: Any,
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source": "NOMAD public API",
        "endpoint": API_BASE,
        "phase": phase,
        "cutoff": cutoff,
        "page_size": page_size,
        "required": required,
        "total_documents": None,
        "downloaded_documents": 0,
        "next_page_after_value": None,
        "pages": [],
        "complete": False,
        "updated_at": utc_now(),
    }


def _validate_resume_manifest(
    manifest: dict[str, Any],
    *,
    output_dir: Path,
    phase: str,
    cutoff: str,
    page_size: int,
    required: Any,
) -> None:
    expected = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "phase": phase,
        "cutoff": cutoff,
        "page_size": page_size,
        "required": required,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(
                f"cannot resume {phase}: manifest {key}={manifest.get(key)!r}, "
                f"requested {value!r}"
            )
    pages = manifest.get("pages", [])
    if pages:
        last = pages[-1]
        last_path = output_dir / last["path"]
        if not last_path.exists() or _sha256(last_path) != last["sha256"]:
            raise RuntimeError(f"last completed page failed verification: {last_path}")


def export_catalog(
    output_dir: Path,
    *,
    cutoff: str | None = None,
    page_size: int = 5000,
    max_pages: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    fetch_json: FetchJson,
) -> Path:
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be positive when provided")
    snapshot = ensure_snapshot(
        output_dir, cutoff=cutoff, fetch_json=fetch_json
    )
    frozen_cutoff = str(snapshot["cutoff"])
    fields = list(snapshot["catalog_fields"])
    phase_dir = output_dir / "catalog"
    phase_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = phase_dir / "manifest.json"
    required = {"include": fields}
    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        _validate_resume_manifest(
            manifest,
            output_dir=output_dir,
            phase="catalog",
            cutoff=frozen_cutoff,
            page_size=page_size,
            required=required,
        )
    else:
        manifest = _new_paged_manifest(
            phase="catalog",
            cutoff=frozen_cutoff,
            page_size=page_size,
            required=required,
        )
    if manifest["complete"]:
        return manifest_path

    cursor = manifest.get("next_page_after_value")
    completed_this_run = 0
    while max_pages is None or completed_this_run < max_pages:
        _check_capacity(output_dir, reserve_bytes)
        request_payload = build_catalog_request(
            cutoff=frozen_cutoff,
            fields=fields,
            page_size=page_size,
            cursor=cursor,
        )
        response = fetch_json("/entries/query", request_payload)
        if not isinstance(response, dict):
            raise RuntimeError("NOMAD catalog response was not an object")
        rows = response.get("data")
        pagination = response.get("pagination")
        if not isinstance(rows, list) or not isinstance(pagination, dict):
            raise RuntimeError("NOMAD catalog response lacked data/pagination")
        total = int(pagination.get("total", -1))
        if total < 0:
            raise RuntimeError("NOMAD catalog response lacked a non-negative total")
        if manifest["total_documents"] is None:
            manifest["total_documents"] = total
        elif int(manifest["total_documents"]) != total:
            raise RuntimeError(
                f"NOMAD snapshot total changed from {manifest['total_documents']} to {total}"
            )
        if not rows and manifest["downloaded_documents"] < total:
            raise RuntimeError("NOMAD returned an empty catalog page before completion")

        page_index = len(manifest["pages"])
        page_path = phase_dir / f"page-{page_index:07d}.json.gz"
        _write_gzip_json_atomic(page_path, response)
        next_cursor = pagination.get("next_page_after_value")
        entry_ids = [row.get("entry_id") for row in rows if isinstance(row, dict)]
        relative_path = str(page_path.relative_to(output_dir))
        manifest["pages"].append(
            {
                "index": page_index,
                "path": relative_path,
                "rows": len(rows),
                "bytes": page_path.stat().st_size,
                "sha256": _sha256(page_path),
                "first_entry_id": entry_ids[0] if entry_ids else None,
                "last_entry_id": entry_ids[-1] if entry_ids else None,
                "request_page_after_value": cursor,
                "next_page_after_value": next_cursor,
            }
        )
        manifest["downloaded_documents"] += len(rows)
        manifest["next_page_after_value"] = next_cursor
        manifest["complete"] = (
            manifest["downloaded_documents"] == total and next_cursor is None
        )
        manifest["updated_at"] = utc_now()
        _write_json_atomic(manifest_path, manifest)
        completed_this_run += 1
        cursor = next_cursor
        print(
            f"catalog page {page_index}: {len(rows):,} rows; "
            f"{manifest['downloaded_documents']:,}/{total:,}",
            flush=True,
        )
        if manifest["complete"]:
            break
        if next_cursor is None:
            raise RuntimeError("NOMAD pagination ended before the declared total")
    return manifest_path


def _property_mask(properties: Sequence[str]) -> int:
    if not properties:
        return 0
    values = set(properties)
    mask = PROPERTY_BITS["properties"]
    for kind, bit in PROPERTY_BITS.items():
        if kind == "properties":
            continue
        if any(tag in values for tag in PROPERTY_TAGS[kind]):
            mask |= bit
    return mask


def _representative_score(properties: Sequence[str]) -> int:
    values = set(properties)
    if {
        "structure_optimized",
        "geometry_optimization.structure_optimized",
    } & values:
        structure_rank = 4
    elif "structure_primitive" in values:
        structure_rank = 3
    elif "structure_original" in values:
        structure_rank = 2
    elif "geometry_optimization" in values:
        structure_rank = 1
    else:
        structure_rank = 0
    return structure_rank * 1000 + min(len(values), 999)


def _catalog_pages(output_dir: Path) -> tuple[dict[str, Any], list[Path]]:
    manifest_path = output_dir / "catalog" / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("catalog manifest is missing; run the catalog phase first")
    manifest = _read_json(manifest_path)
    pages = [output_dir / page["path"] for page in manifest.get("pages", [])]
    if not pages:
        raise RuntimeError("catalog contains no completed pages")
    return manifest, pages


def _open_selection(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS materials (
            material_id TEXT PRIMARY KEY,
            representative_entry_id TEXT NOT NULL,
            score INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entries (
            entry_id TEXT PRIMARY KEY,
            material_id TEXT NOT NULL,
            property_mask INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS processed_pages (
            path TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            rows INTEGER NOT NULL
        );
        """
    )
    return db


def build_selection(output_dir: Path) -> Path:
    """Build or resume the material/Archive work queue from catalog pages."""
    catalog_manifest, pages = _catalog_pages(output_dir)
    db_path = output_dir / "selection.sqlite"
    db = _open_selection(db_path)
    try:
        processed = {
            row[0]: (row[1], row[2])
            for row in db.execute("SELECT path, sha256, rows FROM processed_pages")
        }
        for page_path in pages:
            relative = str(page_path.relative_to(output_dir))
            digest = _sha256(page_path)
            if relative in processed:
                if processed[relative][0] != digest:
                    raise RuntimeError(f"catalog page changed after selection: {page_path}")
                continue
            payload = _read_gzip_json(page_path)
            rows = payload.get("data", [])
            if not isinstance(rows, list):
                raise RuntimeError(f"invalid catalog data in {page_path}")
            material_batch: list[tuple[str, str, int]] = []
            entry_batch: list[tuple[str, str, int]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                entry_id = row.get("entry_id")
                results = row.get("results") or {}
                material = results.get("material") or {}
                material_id = material.get("material_id")
                properties_section = results.get("properties") or {}
                properties = properties_section.get("available_properties") or []
                if not isinstance(entry_id, str) or not isinstance(material_id, str):
                    continue
                if not isinstance(properties, list):
                    properties = []
                clean_properties = [value for value in properties if isinstance(value, str)]
                material_batch.append(
                    (material_id, entry_id, _representative_score(clean_properties))
                )
                entry_batch.append(
                    (entry_id, material_id, _property_mask(clean_properties))
                )
            db.executemany(
                """
                INSERT INTO materials(material_id, representative_entry_id, score)
                VALUES (?, ?, ?)
                ON CONFLICT(material_id) DO UPDATE SET
                    representative_entry_id=excluded.representative_entry_id,
                    score=excluded.score
                WHERE excluded.score > materials.score
                   OR (excluded.score = materials.score
                       AND excluded.representative_entry_id
                           < materials.representative_entry_id)
                """,
                material_batch,
            )
            db.executemany(
                "INSERT OR REPLACE INTO entries(entry_id, material_id, property_mask) "
                "VALUES (?, ?, ?)",
                entry_batch,
            )
            db.execute(
                "INSERT INTO processed_pages(path, sha256, rows) VALUES (?, ?, ?)",
                (relative, digest, len(rows)),
            )
            db.commit()
            print(f"selected {relative}: {len(rows):,} catalog rows", flush=True)
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_materials_representative "
            "ON materials(representative_entry_id)"
        )
        db.commit()
        counts = {
            "materials": int(db.execute("SELECT COUNT(*) FROM materials").fetchone()[0]),
            "entries_with_material": int(
                db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            ),
        }
        for kind, bit in PROPERTY_BITS.items():
            counts[kind] = int(
                db.execute(
                    "SELECT COUNT(*) FROM entries WHERE (property_mask & ?) != 0",
                    (bit,),
                ).fetchone()[0]
            )
    finally:
        db.close()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source": "NOMAD catalog selection",
        "catalog_complete": bool(catalog_manifest.get("complete")),
        "catalog_downloaded_documents": catalog_manifest.get("downloaded_documents"),
        "catalog_total_documents": catalog_manifest.get("total_documents"),
        "catalog_pages_processed": len(pages),
        "counts": counts,
        "complete": bool(catalog_manifest.get("complete")),
        "updated_at": utc_now(),
    }
    return _write_json_atomic(output_dir / "selection-manifest.json", manifest)


def archive_required(kind: str) -> dict[str, Any]:
    try:
        return ARCHIVE_REQUIRED[kind]
    except KeyError as error:
        raise ValueError(f"unsupported Archive kind: {kind}") from error


def build_archive_request(
    *,
    entry_ids: Sequence[str],
    kind: str,
) -> dict[str, Any]:
    if not entry_ids:
        raise ValueError("entry_ids must not be empty")
    return {
        "owner": "public",
        "query": {"entry_id:any": list(entry_ids)},
        "pagination": {
            "page_size": len(entry_ids),
            "order_by": "entry_id",
            "order": "asc",
        },
        "required": archive_required(kind),
    }


def shard_of(entry_id: str, shards: int) -> int:
    """Deterministic shard index of an entry id; stable across runs and hosts."""
    return zlib.crc32(entry_id.encode("utf-8")) % shards


def _validate_shard(shards: int, shard: int) -> None:
    if shards < 1:
        raise ValueError("shards must be positive")
    if not 0 <= shard < shards:
        raise ValueError(f"shard must be in [0, {shards}), got {shard}")


def _register_shard_function(db: sqlite3.Connection) -> None:
    db.create_function("nomad_shard", 2, shard_of, deterministic=True)


def _selection_where(
    kind: str, *, shards: int, shard: int
) -> tuple[str, str, str, list[Any]]:
    """Return (table, id column, extra WHERE clauses, their parameters)."""
    if kind == "structures":
        table, column, clauses, params = "materials", "representative_entry_id", "", []
    else:
        table, column = "entries", "entry_id"
        clauses, params = " AND (property_mask & ?) != 0", [PROPERTY_BITS[kind]]
    if shards > 1:
        clauses += f" AND nomad_shard({column}, ?) = ?"
        params += [shards, shard]
    return table, column, clauses, params


def _selection_batch(
    db: sqlite3.Connection,
    *,
    kind: str,
    last_entry_id: str | None,
    batch_size: int,
    shards: int = 1,
    shard: int = 0,
) -> list[str]:
    after = last_entry_id or ""
    table, column, clauses, params = _selection_where(kind, shards=shards, shard=shard)
    rows = db.execute(
        f"SELECT {column} FROM {table} WHERE {column} > ?{clauses} "
        f"ORDER BY {column} LIMIT ?",
        (after, *params, batch_size),
    )
    return [str(row[0]) for row in rows]


def _selection_total(
    db: sqlite3.Connection, kind: str, *, shards: int = 1, shard: int = 0
) -> int:
    table, column, clauses, params = _selection_where(kind, shards=shards, shard=shard)
    where = f" WHERE 1=1{clauses}" if clauses else ""
    return int(db.execute(f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0])


def _archive_rows(response: JsonValue, expected: Sequence[str]) -> tuple[list[dict[str, Any]], set[str]]:
    """Validate one Archive response; return its rows and the ids it lacks.

    Duplicated or unrequested entries mean the protocol went wrong and raise;
    a *subset* of the requested ids is returned as "missing" for the caller.
    """
    if not isinstance(response, dict):
        raise RuntimeError("NOMAD Archive response was not an object")
    rows = response.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("NOMAD Archive response lacked a data list")
    returned_id_list = [row.get("entry_id") for row in rows if isinstance(row, dict)]
    returned_ids = set(returned_id_list)
    expected_ids = set(expected)
    extra = sorted(returned_ids - expected_ids)[:10]
    if extra or len(returned_id_list) != len(returned_ids):
        raise RuntimeError(
            f"NOMAD Archive batch mismatch: extra={extra}, "
            f"duplicates={len(returned_id_list) - len(returned_ids)}"
        )
    return [row for row in rows if isinstance(row, dict)], expected_ids - returned_ids


def _fetch_archive_batch(
    ids: Sequence[str], kind: str, fetch_json: FetchJson
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Fetch one Archive batch, retrying missing ids once; return response, rows, missing."""
    response = fetch_json("/entries/archive/query", build_archive_request(entry_ids=ids, kind=kind))
    rows, missing = _archive_rows(response, ids)
    if missing:
        retry_ids = sorted(missing)
        retry = fetch_json(
            "/entries/archive/query", build_archive_request(entry_ids=retry_ids, kind=kind)
        )
        retry_rows, missing = _archive_rows(retry, retry_ids)
        rows.extend(retry_rows)
        assert isinstance(response, dict)
        response["data"] = rows
    still_missing = sorted(missing)
    tolerated = max(10, len(ids) // 10)
    if len(still_missing) > tolerated:
        raise RuntimeError(
            f"NOMAD Archive batch mismatch: {len(still_missing)} of {len(ids)} entries "
            f"missing after retry (first: {still_missing[:5]})"
        )
    assert isinstance(response, dict)
    return response, rows, still_missing


def export_archives(
    output_dir: Path,
    *,
    kind: str,
    batch_size: int,
    max_pages: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    allow_partial_selection: bool = False,
    fetch_json: FetchJson,
    shards: int = 1,
    shard: int = 0,
    stop: threading.Event | None = None,
) -> Path:
    """Export one Archive kind for the whole selection, or for one entry_id shard.

    With ``shards > 1`` only entries whose :func:`shard_of` equals ``shard`` are
    exported, into ``archive/<kind>/shard-KK-of-NN/`` with its own manifest, so
    N processes or threads can run side by side and each remains resumable.
    ``stop`` lets a coordinating caller ask this export to stop after the page
    in flight; the manifest stays consistent and the export can be resumed.
    """
    required = archive_required(kind)
    if not 1 <= batch_size <= MAX_ARCHIVE_BATCH:
        raise ValueError(f"Archive batch_size must be between 1 and {MAX_ARCHIVE_BATCH}")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be positive when provided")
    _validate_shard(shards, shard)
    selection_manifest_path = output_dir / "selection-manifest.json"
    selection_db_path = output_dir / "selection.sqlite"
    if not selection_manifest_path.exists() or not selection_db_path.exists():
        raise RuntimeError("selection artifacts are missing; run the select phase first")
    selection_manifest = _read_json(selection_manifest_path)
    if not selection_manifest.get("complete") and not allow_partial_selection:
        raise RuntimeError(
            "selection is based on a partial catalog; pass --allow-partial-selection "
            "only for a bounded pilot"
        )
    snapshot = _read_json(output_dir / "snapshot.json")
    phase_dir = output_dir / "archive" / kind
    if shards > 1:
        phase_dir = phase_dir / f"shard-{shard:02d}-of-{shards:02d}"
    phase_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = phase_dir / "manifest.json"
    phase_name = f"archive:{kind}"
    label = kind if shards == 1 else f"{kind} shard {shard:02d}/{shards:02d}"
    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        previous_batch = int(manifest.get("page_size", batch_size))
        _validate_resume_manifest(
            manifest,
            output_dir=output_dir,
            phase=phase_name,
            cutoff=str(snapshot["cutoff"]),
            page_size=previous_batch,
            required=required,
        )
        if previous_batch != batch_size:
            # Archive resumption keys on last_entry_id, not on page geometry, so
            # the batch size may change between runs; each page records its rows.
            print(
                f"{label}: batch size {previous_batch} -> {batch_size} on resume",
                flush=True,
            )
            manifest["page_size"] = batch_size
        found = (int(manifest.get("shards", 1)), int(manifest.get("shard", 0)))
        if found != (shards, shard):
            raise RuntimeError(
                f"cannot resume {phase_name}: manifest is shard {found[1]} of "
                f"{found[0]}, requested {shard} of {shards}"
            )
    else:
        manifest = _new_paged_manifest(
            phase=phase_name,
            cutoff=str(snapshot["cutoff"]),
            page_size=batch_size,
            required=required,
        )
        manifest["shards"] = shards
        manifest["shard"] = shard
        manifest["last_entry_id"] = None
    manifest.setdefault("missing_documents", 0)
    missing_log = phase_dir / "missing-entry-ids.txt"
    if manifest["complete"]:
        return manifest_path

    db = sqlite3.connect(f"file:{selection_db_path}?mode=ro", uri=True)
    try:
        if shards > 1:
            _register_shard_function(db)
        total = _selection_total(db, kind, shards=shards, shard=shard)
        if manifest["total_documents"] is None:
            manifest["total_documents"] = total
        elif int(manifest["total_documents"]) != total:
            raise RuntimeError(
                f"selection count for {kind} changed from "
                f"{manifest['total_documents']} to {total}"
            )
        completed_this_run = 0
        while max_pages is None or completed_this_run < max_pages:
            if stop is not None and stop.is_set():
                break
            ids = _selection_batch(
                db,
                kind=kind,
                last_entry_id=manifest.get("last_entry_id"),
                batch_size=batch_size,
                shards=shards,
                shard=shard,
            )
            accounted = manifest["downloaded_documents"] + manifest["missing_documents"]
            if not ids:
                manifest["complete"] = accounted == total
                manifest["updated_at"] = utc_now()
                _write_json_atomic(manifest_path, manifest)
                if not manifest["complete"]:
                    raise RuntimeError(
                        f"Archive selection ended at {accounted} accounted entries, "
                        f"expected {total}"
                    )
                break
            _check_capacity(output_dir, reserve_bytes)
            response, rows, still_missing = _fetch_archive_batch(ids, kind, fetch_json)
            page_index = len(manifest["pages"])
            page_path = phase_dir / f"page-{page_index:07d}.json.gz"
            _write_gzip_json_atomic(page_path, response)
            page_record = {
                "index": page_index,
                "path": str(page_path.relative_to(output_dir)),
                "rows": len(rows),
                "bytes": page_path.stat().st_size,
                "sha256": _sha256(page_path),
                "first_entry_id": ids[0],
                "last_entry_id": ids[-1],
            }
            if still_missing:
                # NOMAD lists these entries but serves no Archive for them (the
                # /entries/<id>/archive endpoint answers 404; seen 2026-09-06).
                # Record them and move on rather than aborting the whole export.
                page_record["missing_entry_ids"] = still_missing
                with missing_log.open("a", encoding="utf-8") as handle:
                    handle.write("".join(f"{entry_id}\n" for entry_id in still_missing))
                manifest["missing_documents"] += len(still_missing)
                print(
                    f"{label} page {page_index}: {len(still_missing)} entries have no "
                    f"Archive on NOMAD; recorded in {missing_log.name}",
                    flush=True,
                )
            manifest["pages"].append(page_record)
            manifest["downloaded_documents"] += len(rows)
            manifest["last_entry_id"] = ids[-1]
            manifest["complete"] = (
                manifest["downloaded_documents"] + manifest["missing_documents"] == total
            )
            manifest["updated_at"] = utc_now()
            _write_json_atomic(manifest_path, manifest)
            completed_this_run += 1
            print(
                f"{label} page {page_index}: {len(rows):,} entries; "
                f"{manifest['downloaded_documents']:,}/{total:,}",
                flush=True,
            )
            if manifest["complete"]:
                break
    finally:
        db.close()
    return manifest_path


def export_archives_parallel(
    output_dir: Path,
    *,
    kind: str,
    batch_size: int,
    workers: int,
    max_pages: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    allow_partial_selection: bool = False,
    fetch_json: FetchJson,
) -> list[Path]:
    """Export every shard of one Archive kind concurrently with ``workers`` threads.

    Shard ``k`` of ``workers`` runs :func:`export_archives` in its own thread.
    The work is network-bound (NOMAD spends several seconds per request), so
    threads are enough; the first failing shard asks the others to stop after
    their current page and its error is re-raised once all threads have exited.
    """
    if workers < 1:
        raise ValueError("workers must be positive")
    common = dict(
        kind=kind,
        batch_size=batch_size,
        max_pages=max_pages,
        reserve_bytes=reserve_bytes,
        allow_partial_selection=allow_partial_selection,
        fetch_json=fetch_json,
    )
    if workers == 1:
        return [export_archives(output_dir, **common)]
    stop = threading.Event()

    def run(shard: int) -> Path:
        try:
            return export_archives(
                output_dir, shards=workers, shard=shard, stop=stop, **common
            )
        except BaseException:
            stop.set()
            raise

    results: list[Path] = []
    errors: list[BaseException] = []
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix=f"nomad-{kind}"
    ) as pool:
        futures = [pool.submit(run, shard) for shard in range(workers)]
        for future in futures:
            try:
                results.append(future.result())
            except Exception as error:  # noqa: BLE001 - re-raised below
                errors.append(error)
    if errors:
        raise errors[0]
    return results


class ArchivePlan:
    """One Archive kind to export inside :func:`export_archives_multi`."""

    def __init__(self, kind: str, batch_size: int, workers: int = 1, priority: int = 0) -> None:
        archive_required(kind)
        if workers < 1:
            raise ValueError("workers must be positive")
        self.kind = kind
        self.batch_size = batch_size
        self.workers = workers
        self.priority = priority

    @classmethod
    def parse(cls, spec: str) -> "ArchivePlan":
        """Parse ``kind:batch[:workers[:priority]]`` (e.g. ``properties:500:4:1``)."""
        parts = spec.split(":")
        if not 2 <= len(parts) <= 4:
            raise ValueError(f"plan must look like kind:batch[:workers[:priority]], got {spec!r}")
        kind = parts[0]
        numbers = [int(part) for part in parts[1:]]
        return cls(kind, numbers[0], *(numbers[1:]))

    def __repr__(self) -> str:
        return f"{self.kind}:{self.batch_size}:{self.workers}:{self.priority}"


PrioritisedFetch = Callable[[str, dict[str, Any] | None, int], JsonValue]


def export_archives_multi(
    output_dir: Path,
    plans: Sequence[ArchivePlan],
    *,
    request: PrioritisedFetch,
    max_pages: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    allow_partial_selection: bool = False,
    limiter: AdaptiveLimiter | None = None,
) -> dict[str, list[Path]]:
    """Export several Archive kinds at once through one shared request budget.

    Every shard of every plan runs in its own thread, but all of them send
    their requests through ``request(path, payload, priority)``: with the
    client's :class:`AdaptiveLimiter` that means one process-wide in-flight
    cap, one cooldown after a 429, and priority for the plan that matters most.
    Measured 2026-09-06: NOMAD admitted one Archive request per IP at a time,
    so two independent processes only starved each other.
    """
    if not plans:
        raise ValueError("at least one plan is required")
    if len({plan.kind for plan in plans}) != len(plans):
        raise ValueError("each Archive kind may appear in one plan only")
    stop = threading.Event()

    def run(plan: ArchivePlan, shard: int) -> Path:
        def fetch(path: str, payload: dict[str, Any] | None = None) -> JsonValue:
            return request(path, payload, plan.priority)

        urgent = limiter is not None and plan.priority <= 0
        if urgent:
            limiter.reserve(+1)
        try:
            return export_archives(
                output_dir,
                kind=plan.kind,
                batch_size=plan.batch_size,
                max_pages=max_pages,
                reserve_bytes=reserve_bytes,
                allow_partial_selection=allow_partial_selection,
                fetch_json=fetch,
                shards=plan.workers,
                shard=shard,
                stop=stop,
            )
        except BaseException:
            stop.set()
            raise
        finally:
            if urgent:
                limiter.reserve(-1)

    total_threads = sum(plan.workers for plan in plans)
    results: dict[str, list[Path]] = {plan.kind: [] for plan in plans}
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=total_threads, thread_name_prefix="nomad-multi") as pool:
        futures = [
            (plan.kind, pool.submit(run, plan, shard))
            for plan in plans
            for shard in range(plan.workers)
        ]
        for kind, future in futures:
            try:
                results[kind].append(future.result())
            except Exception as error:  # noqa: BLE001 - re-raised below
                errors.append(error)
    if errors:
        raise errors[0]
    return results


def download_all(
    output_dir: Path,
    *,
    cutoff: str | None = None,
    catalog_page_size: int = 5000,
    structure_batch_size: int = 500,
    property_batch_size: int = 100,
    pilot_pages: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    fetch_json: FetchJson,
    structure_workers: int = 1,
    property_workers: int = 1,
) -> dict[str, Path | list[Path]]:
    """Download the requested material structures and all NOMAD properties.

    This is the user-facing workflow.  The lower-level commands remain
    available for recovery and diagnostics, but a normal full export only
    needs this one call.  ``pilot_pages`` intentionally creates a bounded,
    partial export for validating storage and API access before a full run.
    ``structure_workers`` / ``property_workers`` above 1 shard that Archive
    phase by entry_id and run the shards concurrently; the result then holds
    one manifest path per shard instead of a single path.
    """
    if pilot_pages is not None and pilot_pages < 1:
        raise ValueError("pilot_pages must be positive when provided")
    if structure_workers < 1 or property_workers < 1:
        raise ValueError("worker counts must be positive")
    ensure_snapshot(output_dir, cutoff=cutoff, fetch_json=fetch_json)
    catalog_manifest = export_catalog(
        output_dir,
        cutoff=cutoff,
        page_size=catalog_page_size,
        max_pages=pilot_pages,
        reserve_bytes=reserve_bytes,
        fetch_json=fetch_json,
    )
    selection_manifest = build_selection(output_dir)
    selection = _read_json(selection_manifest)
    partial = not bool(selection.get("complete"))
    if partial and pilot_pages is None:
        raise RuntimeError(
            "catalog did not complete; refusing to start Archive export without "
            "pilot_pages"
        )

    def archive(kind: str, batch_size: int, workers: int) -> Path | list[Path]:
        paths = export_archives_parallel(
            output_dir,
            kind=kind,
            batch_size=batch_size,
            workers=workers,
            max_pages=pilot_pages,
            reserve_bytes=reserve_bytes,
            allow_partial_selection=partial,
            fetch_json=fetch_json,
        )
        return paths[0] if workers == 1 else paths

    return {
        "snapshot": output_dir / "snapshot.json",
        "catalog": catalog_manifest,
        "selection": selection_manifest,
        "structures": archive("structures", structure_batch_size, structure_workers),
        "properties": archive("properties", property_batch_size, property_workers),
    }


def status(output_dir: Path, *, verify: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"output": str(output_dir.resolve())}
    snapshot_path = output_dir / "snapshot.json"
    if snapshot_path.exists():
        snapshot = _read_json(snapshot_path)
        result["snapshot"] = {
            "cutoff": snapshot.get("cutoff"),
            "version": snapshot.get("nomad", {}).get("version"),
            "public": snapshot.get("public"),
        }
    manifests = [output_dir / "catalog" / "manifest.json"]
    manifests.extend(sorted((output_dir / "archive").glob("*/manifest.json")))
    manifests.extend(sorted((output_dir / "archive").glob("*/shard-*/manifest.json")))
    phases: dict[str, Any] = {}
    for path in manifests:
        if not path.exists():
            continue
        manifest = _read_json(path)
        phase = str(manifest.get("phase"))
        item = {
            "downloaded": manifest.get("downloaded_documents"),
            "missing": manifest.get("missing_documents", 0),
            "total": manifest.get("total_documents"),
            "pages": len(manifest.get("pages", [])),
            "complete": manifest.get("complete"),
        }
        shards = int(manifest.get("shards", 1))
        if shards > 1:
            # Sharded exports are reported as one aggregate per phase, with the
            # per-shard rows nested, so a partially finished parallel run reads
            # the same way as a sequential one.
            key = f"{phase}:sharded"
            aggregate = phases.setdefault(
                key,
                {
                    "shards": shards,
                    "shards_seen": 0,
                    "downloaded": 0,
                    "missing": 0,
                    "total": 0,
                    "pages": 0,
                    "complete": False,
                    "per_shard": {},
                },
            )
            item["path"] = str(path.relative_to(output_dir))
            aggregate["per_shard"][f"{int(manifest.get('shard', 0)):02d}"] = item
            aggregate["shards_seen"] = len(aggregate["per_shard"])
            aggregate["downloaded"] += int(item["downloaded"] or 0)
            aggregate["missing"] += int(item["missing"] or 0)
            aggregate["total"] += int(item["total"] or 0)
            aggregate["pages"] += item["pages"]
            aggregate["complete"] = aggregate["shards_seen"] == shards and all(
                row["complete"] for row in aggregate["per_shard"].values()
            )
        if verify:
            errors = []
            for page in manifest.get("pages", []):
                page_path = output_dir / page["path"]
                if not page_path.exists():
                    errors.append(f"missing:{page['path']}")
                elif _sha256(page_path) != page["sha256"]:
                    errors.append(f"sha256:{page['path']}")
            item["verification_errors"] = errors
        if shards > 1:
            continue
        phases[phase] = item
    result["phases"] = phases
    selection_path = output_dir / "selection-manifest.json"
    if selection_path.exists():
        result["selection"] = _read_json(selection_path)
    return result


def default_output_root() -> Path:
    snapshot_date = datetime.now(timezone.utc).date().isoformat()
    return (
        default_data_root()
        / "raw"
        / "acquired"
        / "nomad"
        / f"snapshot-{snapshot_date}"
    )


def _reserve_bytes(value: str | float) -> int:
    try:
        gib = float(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("reserve GiB must be a number") from error
    if gib < 0:
        raise argparse.ArgumentTypeError("reserve GiB must not be negative")
    return int(gib * 1024**3)


class _NoLimit:
    def __enter__(self) -> "_NoLimit":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


_NO_LIMIT = _NoLimit()


def _client_from_args(args: argparse.Namespace) -> NomadClient:
    workers = max(
        getattr(args, "workers", 1),
        getattr(args, "structure_workers", 1),
        getattr(args, "property_workers", 1),
    )
    initial = None
    if getattr(args, "plan", None):
        # The cap may start below the thread count (threads then take turns)
        # and grow towards it while NOMAD keeps accepting requests.
        workers = sum(plan.workers for plan in args.plan)
        initial = max(1, min(workers, args.capacity))
    limiter = AdaptiveLimiter(
        workers,
        min_interval=getattr(args, "min_interval", 0.0),
        recovery=getattr(args, "recovery", 20),
        initial=initial,
    )
    return NomadClient(
        base_url=args.api_base,
        attempts=args.attempts,
        timeout=args.timeout,
        request_delay=args.request_delay,
        limiter=limiter,
        throttle_base=getattr(args, "throttle_base", 60.0),
        network_patience=getattr(args, "network_patience", 1800.0),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=default_output_root())
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--request-delay", type=float, default=0.1)
    parser.add_argument(
        "--min-interval",
        type=float,
        default=0.0,
        help="minimum seconds between request starts across all threads",
    )
    parser.add_argument(
        "--throttle-base",
        type=float,
        default=60.0,
        help="seconds to stay silent after the first HTTP 429; doubles per consecutive 429",
    )
    parser.add_argument(
        "--network-patience",
        type=float,
        default=1800.0,
        help="seconds to keep retrying a request through connection errors and 5xx",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="freeze counts and property schema")
    probe.add_argument("--cutoff", help="ISO timestamp; defaults to current UTC time")

    catalog = subparsers.add_parser("catalog", help="download catalog/scalar pages")
    catalog.add_argument("--cutoff", help="must match an existing snapshot")
    catalog.add_argument("--page-size", type=int, default=5000)
    catalog.add_argument("--max-pages", type=int)
    catalog.add_argument(
        "--reserve-gib",
        dest="reserve_bytes",
        type=_reserve_bytes,
        default=DEFAULT_RESERVE_BYTES,
    )

    subparsers.add_parser("select", help="build material/property Archive work queues")

    archive = subparsers.add_parser("archive", help="download selected Archive branches")
    archive.add_argument("--kind", choices=sorted(ARCHIVE_REQUIRED), required=True)
    archive.add_argument("--batch-size", type=int)
    archive.add_argument("--max-pages", type=int, help="pages per shard for a bounded run")
    archive.add_argument(
        "--shards",
        type=int,
        default=1,
        help="split the selection into N deterministic entry_id shards",
    )
    archive.add_argument(
        "--shard",
        type=int,
        default=0,
        help="which shard (0-based) this process exports; use with --shards",
    )
    archive.add_argument(
        "--workers",
        type=int,
        default=1,
        help="export all N shards concurrently in this process (implies --shards N)",
    )
    archive.add_argument(
        "--reserve-gib",
        dest="reserve_bytes",
        type=_reserve_bytes,
        default=DEFAULT_RESERVE_BYTES,
    )
    archive.add_argument("--allow-partial-selection", action="store_true")

    multi = subparsers.add_parser(
        "archive-multi",
        help="export several Archive kinds concurrently through one request budget",
    )
    multi.add_argument(
        "--plan",
        action="append",
        required=True,
        type=ArchivePlan.parse,
        help="kind:batch[:workers[:priority]]; lower priority number wins the slot",
    )
    multi.add_argument("--max-pages", type=int, help="pages per shard for a bounded run")
    multi.add_argument(
        "--reserve-gib",
        dest="reserve_bytes",
        type=_reserve_bytes,
        default=DEFAULT_RESERVE_BYTES,
    )
    multi.add_argument("--allow-partial-selection", action="store_true")
    multi.add_argument(
        "--capacity",
        type=int,
        default=1,
        help="initial in-flight cap shared by all plans (grows towards the thread count)",
    )
    multi.add_argument(
        "--recovery",
        type=int,
        default=20,
        help="consecutive successes needed before the in-flight cap grows by one",
    )

    download = subparsers.add_parser(
        "download",
        help="download one representative structure per material plus all properties",
    )
    download.add_argument("--cutoff", help="must match an existing snapshot")
    download.add_argument("--page-size", type=int, default=5000)
    download.add_argument("--structure-batch-size", type=int, default=500)
    download.add_argument("--property-batch-size", type=int, default=100)
    download.add_argument(
        "--structure-workers",
        type=int,
        default=1,
        help="shard the structures phase by entry_id and run N shards concurrently",
    )
    download.add_argument(
        "--property-workers",
        type=int,
        default=1,
        help="shard the properties phase by entry_id and run N shards concurrently",
    )
    download.add_argument(
        "--pilot-pages",
        type=int,
        help="download only this many pages in each phase for a bounded smoke test",
    )
    download.add_argument(
        "--reserve-gib",
        dest="reserve_bytes",
        type=_reserve_bytes,
        default=DEFAULT_RESERVE_BYTES,
    )

    status_parser = subparsers.add_parser("status", help="show progress manifests")
    status_parser.add_argument("--verify", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "status":
        print(json.dumps(status(output_dir, verify=args.verify), indent=2, sort_keys=True))
        return 0
    if args.command == "select":
        print(build_selection(output_dir))
        return 0

    client = _client_from_args(args)
    fetch = client.request_json
    if args.command == "probe":
        cutoff = args.cutoff or utc_now()
        print(build_snapshot(output_dir, cutoff=cutoff, fetch_json=fetch))
        return 0
    if args.command == "catalog":
        print(
            export_catalog(
                output_dir,
                cutoff=args.cutoff,
                page_size=args.page_size,
                max_pages=args.max_pages,
                reserve_bytes=args.reserve_bytes,
                fetch_json=fetch,
            )
        )
        return 0
    if args.command == "archive":
        default_batch = 500 if args.kind == "structures" else 100
        if args.workers < 1 or args.shards < 1 or not 0 <= args.shard < args.shards:
            parser.error("--workers and --shards must be positive; 0 <= --shard < --shards")
        if args.workers > 1 and (args.shards != 1 or args.shard != 0):
            parser.error("--workers runs every shard itself; do not combine with --shards/--shard")
        if args.workers > 1:
            paths = export_archives_parallel(
                output_dir,
                kind=args.kind,
                batch_size=args.batch_size or default_batch,
                workers=args.workers,
                max_pages=args.max_pages,
                reserve_bytes=args.reserve_bytes,
                allow_partial_selection=args.allow_partial_selection,
                fetch_json=fetch,
            )
            print(json.dumps([str(path) for path in paths], indent=2))
            return 0
        print(
            export_archives(
                output_dir,
                kind=args.kind,
                batch_size=args.batch_size or default_batch,
                max_pages=args.max_pages,
                reserve_bytes=args.reserve_bytes,
                allow_partial_selection=args.allow_partial_selection,
                fetch_json=fetch,
                shards=args.shards,
                shard=args.shard,
            )
        )
        return 0
    if args.command == "archive-multi":
        result = export_archives_multi(
            output_dir,
            args.plan,
            request=lambda path, payload, priority: client.request_json(
                path, payload, priority=priority
            ),
            max_pages=args.max_pages,
            reserve_bytes=args.reserve_bytes,
            allow_partial_selection=args.allow_partial_selection,
            limiter=client.limiter,
        )
        print(
            json.dumps(
                {kind: [str(p) for p in paths] for kind, paths in result.items()},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "download":
        result = download_all(
            output_dir,
            cutoff=args.cutoff,
            catalog_page_size=args.page_size,
            structure_batch_size=args.structure_batch_size,
            property_batch_size=args.property_batch_size,
            pilot_pages=args.pilot_pages,
            reserve_bytes=args.reserve_bytes,
            fetch_json=fetch,
            structure_workers=args.structure_workers,
            property_workers=args.property_workers,
        )
        print(
            json.dumps(
                {
                    name: [str(p) for p in path] if isinstance(path, list) else str(path)
                    for name, path in result.items()
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    parser.error(f"unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
