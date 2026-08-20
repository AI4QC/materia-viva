#!/usr/bin/env python3
"""Resumable, relationally complete Catalysis-Hub GraphQL export."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
import time
from argparse import ArgumentParser
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

from scripts.datasets.acquire import default_data_root


ENDPOINT = "https://api.catalysis-hub.org/graphql"
USER_AGENT = "MateriaViva-catalysis-hub-acquisition/1.0"
ROLLING_WINDOW_SECONDS = 24 * 60 * 60
MAX_PAGE_SIZE = 10_000


class RequestGovernor:
    """Persistently enforce a minimum interval and rolling request budget."""

    def __init__(
        self,
        ledger_path: Path,
        *,
        minimum_interval: float = 6.1,
        requests_per_24_hours: int = 480,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if minimum_interval < 0:
            raise ValueError("minimum_interval must not be negative")
        if requests_per_24_hours < 1 or requests_per_24_hours > 500:
            raise ValueError("requests_per_24_hours must be between 1 and 500")
        self.ledger_path = Path(ledger_path)
        self.minimum_interval = float(minimum_interval)
        self.requests_per_24_hours = int(requests_per_24_hours)
        self.clock = clock
        self.sleep = sleep

    def _recent_timestamps(self, now: float) -> list[float]:
        if not self.ledger_path.exists():
            return []
        payload = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        timestamps = payload.get("request_timestamps")
        if not isinstance(timestamps, list):
            raise RuntimeError(f"invalid request ledger: {self.ledger_path}")
        cutoff = now - ROLLING_WINDOW_SECONDS
        return [float(value) for value in timestamps if float(value) > cutoff]

    def acquire(self) -> None:
        """Reserve one API attempt before it is sent."""

        now = self.clock()
        timestamps = self._recent_timestamps(now)
        if len(timestamps) >= self.requests_per_24_hours:
            oldest = min(timestamps)
            retry_after = max(0.0, oldest + ROLLING_WINDOW_SECONDS - now)
            raise RuntimeError(
                "Catalysis-Hub 24-hour request budget exhausted; "
                f"retry after at least {retry_after:.1f} seconds"
            )
        if timestamps:
            delay = self.minimum_interval - (now - max(timestamps))
            if delay > 0:
                self.sleep(delay)
                now = self.clock()
        timestamps.append(now)
        _atomic_json(
            self.ledger_path,
            {
                "request_timestamps": timestamps,
                "requests_in_rolling_24_hours": len(timestamps),
                "limit": self.requests_per_24_hours,
                "minimum_interval_seconds": self.minimum_interval,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )


@dataclass(frozen=True)
class TableSpec:
    """GraphQL connection name and node selection for one exported table."""

    graphql_name: str
    selection: str


TABLE_SPECS = {
    "reactions": TableSpec(
        graphql_name="reactions",
        selection="""
          id
          chemicalComposition
          surfaceComposition
          facet
          sites
          coverages
          reactants
          products
          reactionEnergy
          activationEnergy
          dftCode
          dftFunctional
          username
          pubId
          textsearch
          Equation
          reactionSystems {
            id
            name
            aseId
            energyCorrection
            systems { id uniqueId }
          }
        """,
    ),
    "reaction_systems": TableSpec(
        graphql_name="reactionSystems",
        selection="""
          id
          name
          aseId
          energyCorrection
          reactions { id }
          systems { id uniqueId }
        """,
    ),
    "systems": TableSpec(
        graphql_name="systems",
        selection="""
          id
          uniqueId
          ctime
          mtime
          username
          numbers
          positions
          cell
          pbc
          initialMagmoms
          initialCharges
          masses
          tags
          momenta
          constraints
          calculator
          calculatorParameters
          energy
          freeEnergy
          forces
          stress
          dipole
          magmoms
          magmom
          charges
          keyValuePairs
          data
          natoms
          fmax
          smax
          volume
          mass
          charge
          Formula
          Pbc
          Ctime
          Mtime
          Adsorbate
          Reaction
          Username
          Substrate
          Facet
          DftCode
          DftFunctional
          publication { pubId }
        """,
    ),
}


BARRIER_SYSTEM_SELECTION = """
  id
  uniqueId
  numbers
  positions
  cell
  pbc
  tags
  constraints
  calculator
  calculatorParameters
  energy
  freeEnergy
  forces
  keyValuePairs
  data
  natoms
  Formula
  Adsorbate
  Reaction
  Substrate
  Facet
  DftCode
  DftFunctional
  publication { pubId }
"""

BARRIER_REACTION_SELECTION = f"""
  id
  chemicalComposition
  surfaceComposition
  facet
  sites
  coverages
  reactants
  products
  reactionEnergy
  activationEnergy
  dftCode
  dftFunctional
  username
  pubId
  textsearch
  Equation
  reactionSystems {{
    id
    name
    aseId
    energyCorrection
    systems {{
      {BARRIER_SYSTEM_SELECTION}
    }}
  }}
  systems {{
    {BARRIER_SYSTEM_SELECTION}
  }}
"""


def decode_relay_id(value: str) -> tuple[str, int]:
    """Decode a GraphQL Relay ID such as base64(``Reaction:938``)."""

    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(value + padding, validate=True).decode("utf-8")
    type_name, separator, raw_id = decoded.rpartition(":")
    if not separator or not type_name or not raw_id.isdigit():
        raise ValueError(f"invalid Relay ID: {value!r}")
    return type_name, int(raw_id)


def _page_query(table: str) -> str:
    spec = TABLE_SPECS[table]
    return f"""
      query Export($first: Int!, $after: String, $maxId: Int!) {{
        {spec.graphql_name}(
          first: $first
          after: $after
          order: "id"
          id: $maxId
          op: "<="
        ) {{
          totalCount
          pageInfo {{ hasNextPage endCursor }}
          edges {{
            cursor
            node {{
              {spec.selection}
            }}
          }}
        }}
      }}
    """


def _barrier_page_query() -> str:
    return f"""
      query BarrierExport(
        $first: Int!
        $after: String
        $minimumActivationEnergy: Float!
      ) {{
        reactions(
          first: $first
          after: $after
          order: "id"
          activationEnergy: $minimumActivationEnergy
          op: ">"
        ) {{
          totalCount
          pageInfo {{ hasNextPage endCursor }}
          edges {{
            cursor
            node {{
              {BARRIER_REACTION_SELECTION}
            }}
          }}
        }}
      }}
    """


def _watermark_query(table: str) -> str:
    spec = TABLE_SPECS[table]
    return f"""
      query HighWatermark {{
        {spec.graphql_name}(last: 1, order: "id") {{
          totalCount
          edges {{ node {{ id }} }}
        }}
      }}
    """


def _graphql_request(*, query: str, variables: dict, api_key: str) -> Request:
    if not api_key:
        raise ValueError("Catalysis-Hub API key is required")
    payload = {"query": query, "variables": variables}
    return Request(
        ENDPOINT,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )


def build_page_request(
    *,
    table: str,
    api_key: str,
    page_size: int,
    after: str | None,
    max_id: int,
) -> Request:
    """Build one authenticated GraphQL page request without leaking its key."""

    if table not in TABLE_SPECS:
        raise ValueError(f"unsupported Catalysis-Hub table: {table}")
    return _graphql_request(
        query=_page_query(table),
        variables={"first": page_size, "after": after, "maxId": max_id},
        api_key=api_key,
    )


def build_barrier_page_request(
    *,
    api_key: str,
    page_size: int,
    after: str | None,
    minimum_activation_energy: float = 0.0,
) -> Request:
    """Build one positive-barrier page request with linked role structures."""

    return _graphql_request(
        query=_barrier_page_query(),
        variables={
            "first": page_size,
            "after": after,
            "minimumActivationEnergy": float(minimum_activation_energy),
        },
        api_key=api_key,
    )


def build_watermark_request(*, table: str, api_key: str) -> Request:
    """Build the request that freezes a crawl at its starting maximum ID."""

    if table not in TABLE_SPECS:
        raise ValueError(f"unsupported Catalysis-Hub table: {table}")
    return _graphql_request(query=_watermark_query(table), variables={}, api_key=api_key)


class NonRetryableRequestError(RuntimeError):
    """An API rejection that should not consume retries."""


def _fetch_json_once(request: Request) -> dict:
    try:
        with urlopen(request, timeout=300) as response:
            return json.load(response)
    except HTTPError as error:
        if 400 <= error.code < 500:
            detail = error.read().decode("utf-8", errors="replace")
            raise NonRetryableRequestError(
                f"Catalysis-Hub API rejected the request (HTTP {error.code}): {detail}"
            ) from error
        raise


class GovernedFetcher:
    """Retry transient failures while governing every HTTP attempt."""

    def __init__(
        self,
        governor: RequestGovernor,
        *,
        fetch_once: Callable[[Request], dict] = _fetch_json_once,
        attempts: int = 3,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be positive")
        self.governor = governor
        self.fetch_once = fetch_once
        self.attempts = attempts

    def __call__(self, request: Request) -> dict:
        last_error: Exception | None = None
        for _ in range(self.attempts):
            self.governor.acquire()
            try:
                return self.fetch_once(request)
            except NonRetryableRequestError:
                raise
            except Exception as error:  # urllib exposes several transient errors
                last_error = error
        assert last_error is not None
        raise last_error


def _connection(payload: dict, graphql_name: str) -> dict:
    errors = payload.get("errors")
    if errors:
        raise RuntimeError(f"Catalysis-Hub GraphQL error: {errors}")
    connection = payload.get("data", {}).get(graphql_name)
    if not isinstance(connection, dict):
        raise RuntimeError(f"Catalysis-Hub response omitted data.{graphql_name}")
    return connection


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    building = path.with_name(path.name + ".building")
    building.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    building.replace(path)


def _write_page(directory: Path, *, index: int, payload: dict) -> tuple[Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"page-{index:06d}.json.gz"
    building = target.with_name(target.name + ".building")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return target, digest


def _verify_manifest_pages(directory: Path, pages: list[dict]) -> None:
    for page in pages:
        path = directory / page["filename"]
        if not path.is_file():
            raise RuntimeError(f"resume page is missing: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != page["sha256"]:
            raise RuntimeError(f"resume page checksum mismatch: {path}")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            json.load(handle)


def export_table(
    *,
    output_dir: Path,
    table: str,
    api_key: str,
    page_size: int = 200,
    fetch_json: Callable[[Request], dict] | None = None,
    request_delay: float = 6.1,
    daily_request_limit: int = 480,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Export one bounded GraphQL connection into resumable gzip pages."""

    if table not in TABLE_SPECS:
        raise ValueError(f"unsupported Catalysis-Hub table: {table}")
    if not api_key:
        raise ValueError("Catalysis-Hub API key is required")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")

    if fetch_json is None:
        governor = RequestGovernor(
            Path(output_dir) / "request-ledger.json",
            minimum_interval=request_delay,
            requests_per_24_hours=daily_request_limit,
        )
        fetch: Callable[[Request], dict] = GovernedFetcher(governor)
    else:
        fetch = fetch_json
    table_dir = Path(output_dir) / table
    table_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = table_dir / "manifest.json"
    query_hash = hashlib.sha256(_page_query(table).encode("utf-8")).hexdigest()

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {
            "table": table,
            "graphql_name": TABLE_SPECS[table].graphql_name,
            "page_size": page_size,
            "query_sha256": query_hash,
        }
        mismatched = [key for key, value in expected.items() if manifest.get(key) != value]
        if mismatched:
            raise RuntimeError(f"resume manifest is incompatible: {mismatched}")
        _verify_manifest_pages(table_dir, manifest.get("pages", []))
        if manifest.get("complete"):
            return manifest_path
    else:
        watermark_payload = fetch(build_watermark_request(table=table, api_key=api_key))
        watermark = _connection(watermark_payload, TABLE_SPECS[table].graphql_name)
        source_total = int(watermark.get("totalCount") or 0)
        edges = watermark.get("edges") or []
        if source_total == 0:
            max_id = 0
        elif len(edges) == 1:
            _, max_id = decode_relay_id(edges[0]["node"]["id"])
        else:
            raise RuntimeError(f"{table} high-watermark query returned no maximum ID")
        now = datetime.now(timezone.utc).isoformat()
        manifest = {
            "source": "Catalysis-Hub GraphQL API",
            "endpoint": ENDPOINT,
            "table": table,
            "graphql_name": TABLE_SPECS[table].graphql_name,
            "selection": TABLE_SPECS[table].selection.split(),
            "query_sha256": query_hash,
            "page_size": page_size,
            "max_id": max_id,
            "source_total_at_start": source_total,
            "bounded_total_documents": 0 if source_total == 0 else None,
            "downloaded_documents": 0,
            "next_cursor": None,
            "pages": [],
            "complete": source_total == 0,
            "started_at": now,
            "updated_at": now,
        }
        _atomic_json(manifest_path, manifest)
        if source_total == 0:
            return manifest_path

    while not manifest["complete"]:
        payload = fetch(
            build_page_request(
                table=table,
                api_key=api_key,
                page_size=page_size,
                after=manifest["next_cursor"],
                max_id=int(manifest["max_id"]),
            )
        )
        connection = _connection(payload, TABLE_SPECS[table].graphql_name)
        edges = connection.get("edges")
        page_info = connection.get("pageInfo")
        if not isinstance(edges, list) or not isinstance(page_info, dict):
            raise RuntimeError(f"invalid {table} connection page")

        bounded_total = int(connection.get("totalCount") or 0)
        previous_total = manifest.get("bounded_total_documents")
        if previous_total is not None and bounded_total != previous_total:
            raise RuntimeError(
                f"{table} bounded total changed from {previous_total} to {bounded_total}"
            )
        manifest["bounded_total_documents"] = bounded_total

        has_next = bool(page_info.get("hasNextPage"))
        end_cursor = page_info.get("endCursor")
        if has_next and not end_cursor:
            raise RuntimeError(f"{table} page hasNextPage without endCursor")
        if not edges and has_next:
            raise RuntimeError(f"{table} returned an empty non-final page")

        index = len(manifest["pages"])
        page_path, digest = _write_page(table_dir, index=index, payload=payload)
        manifest["pages"].append(
            {
                "filename": page_path.name,
                "records": len(edges),
                "bytes": page_path.stat().st_size,
                "sha256": digest,
                "start_cursor": edges[0].get("cursor") if edges else None,
                "end_cursor": end_cursor,
            }
        )
        manifest["downloaded_documents"] += len(edges)
        manifest["next_cursor"] = end_cursor
        manifest["complete"] = (
            not has_next
            and manifest["downloaded_documents"] == manifest["bounded_total_documents"]
        )
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(manifest_path, manifest)
        if progress is not None:
            progress(
                f"{table}: {manifest['downloaded_documents']}/"
                f"{manifest['bounded_total_documents']}"
            )

        if not has_next and not manifest["complete"]:
            raise RuntimeError(
                f"downloaded {manifest['downloaded_documents']} {table} rows, "
                f"expected {manifest['bounded_total_documents']}"
            )

    return manifest_path


def export_barriers(
    *,
    output_dir: Path,
    api_key: str,
    page_size: int = MAX_PAGE_SIZE,
    minimum_activation_energy: float = 0.0,
    fetch_json: Callable[[Request], dict] | None = None,
    request_delay: float = 6.1,
    daily_request_limit: int = 480,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Export positive activation barriers with linked role structures."""

    if not api_key:
        raise ValueError("Catalysis-Hub API key is required")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    output_dir = Path(output_dir)
    table_dir = output_dir / "barriers"
    table_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = table_dir / "manifest.json"
    query_hash = hashlib.sha256(_barrier_page_query().encode("utf-8")).hexdigest()

    if fetch_json is None:
        governor = RequestGovernor(
            output_dir / "request-ledger.json",
            minimum_interval=request_delay,
            requests_per_24_hours=daily_request_limit,
        )
        fetch: Callable[[Request], dict] = GovernedFetcher(governor)
    else:
        fetch = fetch_json

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {
            "table": "positive_activation_barriers",
            "graphql_name": "reactions",
            "page_size": page_size,
            "minimum_activation_energy": float(minimum_activation_energy),
            "query_sha256": query_hash,
        }
        mismatched = [key for key, value in expected.items() if manifest.get(key) != value]
        if mismatched:
            raise RuntimeError(f"resume manifest is incompatible: {mismatched}")
        _verify_manifest_pages(table_dir, manifest.get("pages", []))
        if manifest.get("complete"):
            return manifest_path
    else:
        now = datetime.now(timezone.utc).isoformat()
        manifest = {
            "source": "Catalysis-Hub GraphQL API",
            "endpoint": ENDPOINT,
            "table": "positive_activation_barriers",
            "graphql_name": "reactions",
            "selection": BARRIER_REACTION_SELECTION.split(),
            "query_sha256": query_hash,
            "page_size": page_size,
            "minimum_activation_energy": float(minimum_activation_energy),
            "source_total_at_start": None,
            "bounded_total_documents": None,
            "downloaded_documents": 0,
            "next_cursor": None,
            "pages": [],
            "complete": False,
            "started_at": now,
            "updated_at": now,
        }
        _atomic_json(manifest_path, manifest)

    while not manifest["complete"]:
        payload = fetch(
            build_barrier_page_request(
                api_key=api_key,
                page_size=page_size,
                after=manifest["next_cursor"],
                minimum_activation_energy=minimum_activation_energy,
            )
        )
        connection = _connection(payload, "reactions")
        edges = connection.get("edges")
        page_info = connection.get("pageInfo")
        if not isinstance(edges, list) or not isinstance(page_info, dict):
            raise RuntimeError("invalid barrier connection page")

        bounded_total = int(connection.get("totalCount") or 0)
        previous_total = manifest.get("bounded_total_documents")
        if previous_total is not None and bounded_total != previous_total:
            raise RuntimeError(
                f"barrier total changed from {previous_total} to {bounded_total}"
            )
        if manifest.get("source_total_at_start") is None:
            manifest["source_total_at_start"] = bounded_total
        manifest["bounded_total_documents"] = bounded_total

        has_next = bool(page_info.get("hasNextPage"))
        end_cursor = page_info.get("endCursor")
        if has_next and not end_cursor:
            raise RuntimeError("barrier page hasNextPage without endCursor")
        if not edges and has_next:
            raise RuntimeError("barrier crawl returned an empty non-final page")

        index = len(manifest["pages"])
        page_path, digest = _write_page(table_dir, index=index, payload=payload)
        manifest["pages"].append(
            {
                "filename": page_path.name,
                "records": len(edges),
                "bytes": page_path.stat().st_size,
                "sha256": digest,
                "start_cursor": edges[0].get("cursor") if edges else None,
                "end_cursor": end_cursor,
            }
        )
        manifest["downloaded_documents"] += len(edges)
        manifest["next_cursor"] = end_cursor
        manifest["complete"] = (
            not has_next
            and manifest["downloaded_documents"] == manifest["bounded_total_documents"]
        )
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(manifest_path, manifest)
        if progress is not None:
            progress(
                f"barriers: {manifest['downloaded_documents']}/"
                f"{manifest['bounded_total_documents']}"
            )
        if not has_next and not manifest["complete"]:
            raise RuntimeError(
                f"downloaded {manifest['downloaded_documents']} barrier rows, "
                f"expected {manifest['bounded_total_documents']}"
            )

    return manifest_path


def _iter_table_nodes(output_dir: Path, table: str):
    table_dir = Path(output_dir) / table
    manifest_path = table_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"missing {table} manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("complete"):
        raise RuntimeError(f"{table} export is incomplete")
    pages = manifest.get("pages", [])
    _verify_manifest_pages(table_dir, pages)
    decoded = 0
    graphql_name = TABLE_SPECS[table].graphql_name
    for page in pages:
        with gzip.open(table_dir / page["filename"], "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        connection = _connection(payload, graphql_name)
        edges = connection.get("edges")
        if not isinstance(edges, list):
            raise RuntimeError(f"invalid edges in {table}/{page['filename']}")
        if len(edges) != int(page["records"]):
            raise RuntimeError(f"record-count mismatch in {table}/{page['filename']}")
        for edge in edges:
            node = edge.get("node")
            if not isinstance(node, dict):
                raise RuntimeError(f"invalid node in {table}/{page['filename']}")
            decoded += 1
            yield node
    if decoded != int(manifest.get("downloaded_documents", -1)):
        raise RuntimeError(
            f"decoded {decoded} {table} rows, manifest records "
            f"{manifest.get('downloaded_documents')}"
        )


def _record_id(node: dict, expected_type: str) -> int:
    type_name, value = decode_relay_id(str(node.get("id") or ""))
    if type_name != expected_type:
        raise RuntimeError(f"expected {expected_type} Relay ID, received {type_name}")
    return value


def _reference_ids(value, expected_type: str) -> list[int]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        type_name, numeric_id = decode_relay_id(str(item["id"]))
        if type_name != expected_type:
            raise RuntimeError(
                f"expected {expected_type} relation endpoint, received {type_name}"
            )
        result.append(numeric_id)
    return result


_BULK_KEYS = {
    "bulk",
    "bulkid",
    "bulkstructureid",
    "materialsprojectid",
    "mpid",
}


def _has_explicit_bulk_id(raw_value) -> bool:
    if not raw_value:
        return False
    if isinstance(raw_value, str):
        try:
            value = json.loads(raw_value)
        except (TypeError, ValueError):
            return False
    else:
        value = raw_value

    def walk(item) -> bool:
        if isinstance(item, dict):
            for key, child in item.items():
                canonical = re.sub(r"[^a-z0-9]", "", str(key).lower())
                if canonical in _BULK_KEYS and child not in (None, "", [], {}):
                    return True
                if walk(child):
                    return True
        elif isinstance(item, list):
            return any(walk(child) for child in item)
        return False

    return walk(value)


def validate_export(output_dir: Path) -> Path:
    """Verify table checksums and all reaction-system foreign-key endpoints."""

    output_dir = Path(output_dir)
    reaction_ids: set[int] = set()
    duplicate_reactions: set[int] = set()
    barrier_ids: set[int] = set()
    nested_relation_ids: set[int] = set()
    reaction_row_count = 0
    for node in _iter_table_nodes(output_dir, "reactions"):
        reaction_row_count += 1
        record_id = _record_id(node, "Reaction")
        if record_id in reaction_ids:
            duplicate_reactions.add(record_id)
        reaction_ids.add(record_id)
        value = node.get("activationEnergy")
        if isinstance(value, (int, float)):
            barrier_ids.add(record_id)
        nested_relation_ids.update(
            _reference_ids(node.get("reactionSystems"), "ReactionSystem")
        )

    system_ids: set[int] = set()
    duplicate_systems: set[int] = set()
    bulk_system_ids: set[int] = set()
    system_row_count = 0
    for node in _iter_table_nodes(output_dir, "systems"):
        system_row_count += 1
        record_id = _record_id(node, "System")
        if record_id in system_ids:
            duplicate_systems.add(record_id)
        system_ids.add(record_id)
        if _has_explicit_bulk_id(node.get("keyValuePairs")):
            bulk_system_ids.add(record_id)

    relation_ids: set[int] = set()
    duplicate_relations: set[int] = set()
    related_reactions: set[int] = set()
    related_systems: set[int] = set()
    roles: Counter[str] = Counter()
    reaction_roles: dict[int, set[str]] = {}
    reaction_system_ids: dict[int, set[int]] = {}
    relation_row_count = 0
    for node in _iter_table_nodes(output_dir, "reaction_systems"):
        relation_row_count += 1
        record_id = _record_id(node, "ReactionSystem")
        if record_id in relation_ids:
            duplicate_relations.add(record_id)
        relation_ids.add(record_id)
        reaction_refs = _reference_ids(node.get("reactions"), "Reaction")
        system_refs = _reference_ids(node.get("systems"), "System")
        if not system_refs:
            ase_id = str(node.get("aseId") or "").strip()
            if ase_id.isdigit():
                system_refs = [int(ase_id)]
        related_reactions.update(reaction_refs)
        related_systems.update(system_refs)
        role = str(node.get("name") or "<missing>")
        roles[role] += 1
        canonical_role = re.sub(r"[^a-z0-9]", "", role.lower())
        if "transition" in canonical_role or canonical_role in {"ts", "saddlepoint"}:
            role_group = "transition_state"
        elif "reactant" in canonical_role or canonical_role in {"initial", "is"}:
            role_group = "reactant"
        elif "product" in canonical_role or canonical_role in {"final", "fs"}:
            role_group = "product"
        else:
            role_group = canonical_role or "<missing>"
        for reaction_id in reaction_refs:
            reaction_roles.setdefault(reaction_id, set()).add(role_group)
            reaction_system_ids.setdefault(reaction_id, set()).update(system_refs)

    orphan_reactions = sorted(related_reactions - reaction_ids)
    orphan_systems = sorted(related_systems - system_ids)
    relation_manifest = json.loads(
        (output_dir / "reaction_systems" / "manifest.json").read_text(encoding="utf-8")
    )
    relation_max_id = relation_manifest.get("max_id")
    bounded_nested_relation_ids = (
        {value for value in nested_relation_ids if value <= int(relation_max_id)}
        if relation_max_id is not None
        else nested_relation_ids
    )
    nested_missing = sorted(bounded_nested_relation_ids - relation_ids)
    relation_missing_from_nesting = sorted(relation_ids - bounded_nested_relation_ids)
    ts_barriers = {
        reaction_id
        for reaction_id in barrier_ids
        if "transition_state" in reaction_roles.get(reaction_id, set())
    }
    complete_triplet_barriers = {
        reaction_id
        for reaction_id in barrier_ids
        if {"reactant", "transition_state", "product"}
        <= reaction_roles.get(reaction_id, set())
    }
    reactions_with_bulk = {
        reaction_id
        for reaction_id, linked_ids in reaction_system_ids.items()
        if linked_ids & bulk_system_ids
    }
    report = {
        "source": "Catalysis-Hub relational export",
        "reaction_rows": reaction_row_count,
        "barrier_reactions": len(barrier_ids),
        "reaction_system_rows": relation_row_count,
        "system_rows": system_row_count,
        "reactions_with_links": len(related_reactions & reaction_ids),
        "barrier_reactions_with_links": len(barrier_ids & related_reactions),
        "barrier_reactions_with_transition_state_link": len(ts_barriers),
        "barrier_reactions_with_is_ts_fs_links": len(complete_triplet_barriers),
        "reactions_with_explicit_bulk_link": len(reactions_with_bulk & reaction_ids),
        "linked_systems": len(related_systems & system_ids),
        "linked_systems_with_explicit_bulk_id": len(
            related_systems & system_ids & bulk_system_ids
        ),
        "relation_roles": dict(sorted(roles.items())),
        "duplicate_reaction_ids": sorted(duplicate_reactions),
        "duplicate_reaction_system_ids": sorted(duplicate_relations),
        "duplicate_system_ids": sorted(duplicate_systems),
        "orphan_reaction_ids": orphan_reactions,
        "orphan_system_ids": orphan_systems,
        "nested_relation_ids_missing_from_relation_table": nested_missing,
        "relation_ids_missing_from_reaction_nesting": relation_missing_from_nesting,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    report["relationally_valid"] = not any(
        (
            duplicate_reactions,
            duplicate_relations,
            duplicate_systems,
            orphan_reactions,
            orphan_systems,
            nested_missing,
            relation_missing_from_nesting,
        )
    )
    target = output_dir / "relational-integrity.json"
    _atomic_json(target, report)
    return target


def default_output_dir(*, data_root: Path | None = None, snapshot: date | None = None) -> Path:
    """Return the additive destination for a relational snapshot."""

    root = Path(data_root) if data_root is not None else default_data_root()
    stamp = snapshot or datetime.now(timezone.utc).date()
    return root / "raw" / "acquired" / "catalysis-hub" / f"relational-{stamp.isoformat()}"


def export_all(
    *,
    output_dir: Path,
    api_key: str,
    page_size: int = MAX_PAGE_SIZE,
    request_delay: float = 6.1,
    fetch_json: Callable[[Request], dict] | None = None,
    progress: Callable[[str], None] | None = print,
) -> Path:
    """Export all three connected tables and write their integrity report."""

    for table in ("reaction_systems", "reactions", "systems"):
        export_table(
            output_dir=output_dir,
            table=table,
            api_key=api_key,
            page_size=page_size,
            fetch_json=fetch_json,
            request_delay=request_delay,
            progress=progress,
        )
    return validate_export(output_dir)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--page-size", type=int, default=MAX_PAGE_SIZE)
    parser.add_argument("--request-delay", type=float, default=6.1)
    parser.add_argument(
        "--barriers-only",
        action="store_true",
        help="download only positive barriers with nested reactionSystems/structures",
    )
    parser.add_argument("--minimum-activation-energy", type=float, default=0.0)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="verify an existing three-table export without contacting the API",
    )
    args = parser.parse_args(argv)
    output = args.output or default_output_dir()

    if args.validate_only and args.barriers_only:
        parser.error("--validate-only and --barriers-only cannot be combined")

    if args.validate_only:
        report_path = validate_export(output)
    else:
        environment = os.environ if environ is None else environ
        api_key = environment.get("CATALYSIS_HUB_API_KEY") or environment.get(
            "CATHUB_API_KEY"
        )
        if not api_key:
            parser.error(
                "set CATALYSIS_HUB_API_KEY (or CATHUB_API_KEY) after signing in with "
                "ORCID at https://api.catalysis-hub.org/auth/login"
            )
        if args.barriers_only:
            report_path = export_barriers(
                output_dir=output,
                api_key=api_key,
                page_size=args.page_size,
                minimum_activation_energy=args.minimum_activation_energy,
                request_delay=args.request_delay,
            )
        else:
            report_path = export_all(
                output_dir=output,
                api_key=api_key,
                page_size=args.page_size,
                request_delay=args.request_delay,
            )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    print(report_path)
    if args.barriers_only:
        return 0 if report.get("complete") else 1
    return 0 if report.get("relationally_valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
