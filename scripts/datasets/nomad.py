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
    electronic bands/DOS, phonons, or spectra) in bounded gzip pages.

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
import shutil
import sqlite3
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
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


class NomadClient:
    """Small retrying client for NOMAD's public JSON API."""

    def __init__(
        self,
        *,
        base_url: str = API_BASE,
        attempts: int = 6,
        timeout: int = 600,
        request_delay: float = 0.0,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be positive")
        self.base_url = base_url.rstrip("/")
        self.attempts = attempts
        self.timeout = timeout
        self.request_delay = request_delay

    def request_json(
        self, path: str, payload: dict[str, Any] | None = None
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
        for attempt in range(self.attempts):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    if response.headers.get("Content-Encoding", "").lower() == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw)
            except HTTPError as error:
                last_error = error
                if error.code not in {429, 500, 502, 503, 504}:
                    detail = error.read().decode("utf-8", errors="replace")
                    raise RuntimeError(
                        f"NOMAD HTTP {error.code} for {request.full_url}: {detail[:1000]}"
                    ) from error
                retry_after = error.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(120, 2**attempt)
            except (URLError, TimeoutError, ConnectionError) as error:
                last_error = error
                delay = min(120, 2**attempt)
            if attempt + 1 < self.attempts:
                time.sleep(delay)
        assert last_error is not None
        raise RuntimeError(
            f"NOMAD request failed after {self.attempts} attempts: {request.full_url}"
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


def _selection_batch(
    db: sqlite3.Connection,
    *,
    kind: str,
    last_entry_id: str | None,
    batch_size: int,
) -> list[str]:
    after = last_entry_id or ""
    if kind == "structures":
        rows = db.execute(
            "SELECT representative_entry_id FROM materials "
            "WHERE representative_entry_id > ? "
            "ORDER BY representative_entry_id LIMIT ?",
            (after, batch_size),
        )
    else:
        bit = PROPERTY_BITS[kind]
        rows = db.execute(
            "SELECT entry_id FROM entries "
            "WHERE entry_id > ? AND (property_mask & ?) != 0 "
            "ORDER BY entry_id LIMIT ?",
            (after, bit, batch_size),
        )
    return [str(row[0]) for row in rows]


def _selection_total(db: sqlite3.Connection, kind: str) -> int:
    if kind == "structures":
        return int(db.execute("SELECT COUNT(*) FROM materials").fetchone()[0])
    bit = PROPERTY_BITS[kind]
    return int(
        db.execute(
            "SELECT COUNT(*) FROM entries WHERE (property_mask & ?) != 0", (bit,)
        ).fetchone()[0]
    )


def export_archives(
    output_dir: Path,
    *,
    kind: str,
    batch_size: int,
    max_pages: int | None = None,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    allow_partial_selection: bool = False,
    fetch_json: FetchJson,
) -> Path:
    required = archive_required(kind)
    if not 1 <= batch_size <= 1000:
        raise ValueError("Archive batch_size must be between 1 and 1000")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be positive when provided")
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
    phase_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = phase_dir / "manifest.json"
    phase_name = f"archive:{kind}"
    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        _validate_resume_manifest(
            manifest,
            output_dir=output_dir,
            phase=phase_name,
            cutoff=str(snapshot["cutoff"]),
            page_size=batch_size,
            required=required,
        )
    else:
        manifest = _new_paged_manifest(
            phase=phase_name,
            cutoff=str(snapshot["cutoff"]),
            page_size=batch_size,
            required=required,
        )
        manifest["last_entry_id"] = None
    if manifest["complete"]:
        return manifest_path

    db = sqlite3.connect(f"file:{selection_db_path}?mode=ro", uri=True)
    try:
        total = _selection_total(db, kind)
        if manifest["total_documents"] is None:
            manifest["total_documents"] = total
        elif int(manifest["total_documents"]) != total:
            raise RuntimeError(
                f"selection count for {kind} changed from "
                f"{manifest['total_documents']} to {total}"
            )
        completed_this_run = 0
        while max_pages is None or completed_this_run < max_pages:
            ids = _selection_batch(
                db,
                kind=kind,
                last_entry_id=manifest.get("last_entry_id"),
                batch_size=batch_size,
            )
            if not ids:
                manifest["complete"] = manifest["downloaded_documents"] == total
                manifest["updated_at"] = utc_now()
                _write_json_atomic(manifest_path, manifest)
                if not manifest["complete"]:
                    raise RuntimeError(
                        f"Archive selection ended at {manifest['downloaded_documents']}, "
                        f"expected {total}"
                    )
                break
            _check_capacity(output_dir, reserve_bytes)
            response = fetch_json(
                "/entries/archive/query",
                build_archive_request(entry_ids=ids, kind=kind),
            )
            if not isinstance(response, dict):
                raise RuntimeError("NOMAD Archive response was not an object")
            rows = response.get("data")
            if not isinstance(rows, list):
                raise RuntimeError("NOMAD Archive response lacked a data list")
            returned_id_list = [
                row.get("entry_id") for row in rows if isinstance(row, dict)
            ]
            returned_ids = set(returned_id_list)
            expected_ids = set(ids)
            if len(returned_id_list) != len(ids) or returned_ids != expected_ids:
                missing = sorted(expected_ids - returned_ids)[:10]
                extra = sorted(returned_ids - expected_ids)[:10]
                raise RuntimeError(
                    f"NOMAD Archive batch mismatch: missing={missing}, extra={extra}"
                )
            page_index = len(manifest["pages"])
            page_path = phase_dir / f"page-{page_index:07d}.json.gz"
            _write_gzip_json_atomic(page_path, response)
            manifest["pages"].append(
                {
                    "index": page_index,
                    "path": str(page_path.relative_to(output_dir)),
                    "rows": len(rows),
                    "bytes": page_path.stat().st_size,
                    "sha256": _sha256(page_path),
                    "first_entry_id": ids[0],
                    "last_entry_id": ids[-1],
                }
            )
            manifest["downloaded_documents"] += len(rows)
            manifest["last_entry_id"] = ids[-1]
            manifest["complete"] = manifest["downloaded_documents"] == total
            manifest["updated_at"] = utc_now()
            _write_json_atomic(manifest_path, manifest)
            completed_this_run += 1
            print(
                f"{kind} page {page_index}: {len(rows):,} entries; "
                f"{manifest['downloaded_documents']:,}/{total:,}",
                flush=True,
            )
            if manifest["complete"]:
                break
    finally:
        db.close()
    return manifest_path


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
) -> dict[str, Path]:
    """Download the requested material structures and all NOMAD properties.

    This is the user-facing workflow.  The lower-level commands remain
    available for recovery and diagnostics, but a normal full export only
    needs this one call.  ``pilot_pages`` intentionally creates a bounded,
    partial export for validating storage and API access before a full run.
    """
    if pilot_pages is not None and pilot_pages < 1:
        raise ValueError("pilot_pages must be positive when provided")
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
    return {
        "snapshot": output_dir / "snapshot.json",
        "catalog": catalog_manifest,
        "selection": selection_manifest,
        "structures": export_archives(
            output_dir,
            kind="structures",
            batch_size=structure_batch_size,
            max_pages=pilot_pages,
            reserve_bytes=reserve_bytes,
            allow_partial_selection=partial,
            fetch_json=fetch_json,
        ),
        "properties": export_archives(
            output_dir,
            kind="properties",
            batch_size=property_batch_size,
            max_pages=pilot_pages,
            reserve_bytes=reserve_bytes,
            allow_partial_selection=partial,
            fetch_json=fetch_json,
        ),
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
    phases: dict[str, Any] = {}
    for path in manifests:
        if not path.exists():
            continue
        manifest = _read_json(path)
        phase = str(manifest.get("phase"))
        item = {
            "downloaded": manifest.get("downloaded_documents"),
            "total": manifest.get("total_documents"),
            "pages": len(manifest.get("pages", [])),
            "complete": manifest.get("complete"),
        }
        if verify:
            errors = []
            for page in manifest.get("pages", []):
                page_path = output_dir / page["path"]
                if not page_path.exists():
                    errors.append(f"missing:{page['path']}")
                elif _sha256(page_path) != page["sha256"]:
                    errors.append(f"sha256:{page['path']}")
            item["verification_errors"] = errors
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


def _client_from_args(args: argparse.Namespace) -> NomadClient:
    return NomadClient(
        base_url=args.api_base,
        attempts=args.attempts,
        timeout=args.timeout,
        request_delay=args.request_delay,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=default_output_root())
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--request-delay", type=float, default=0.1)
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
    archive.add_argument("--max-pages", type=int)
    archive.add_argument(
        "--reserve-gib",
        dest="reserve_bytes",
        type=_reserve_bytes,
        default=DEFAULT_RESERVE_BYTES,
    )
    archive.add_argument("--allow-partial-selection", action="store_true")

    download = subparsers.add_parser(
        "download",
        help="download one representative structure per material plus all properties",
    )
    download.add_argument("--cutoff", help="must match an existing snapshot")
    download.add_argument("--page-size", type=int, default=5000)
    download.add_argument("--structure-batch-size", type=int, default=500)
    download.add_argument("--property-batch-size", type=int, default=100)
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
        print(
            export_archives(
                output_dir,
                kind=args.kind,
                batch_size=args.batch_size or default_batch,
                max_pages=args.max_pages,
                reserve_bytes=args.reserve_bytes,
                allow_partial_selection=args.allow_partial_selection,
                fetch_json=fetch,
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
        )
        print(
            json.dumps(
                {name: str(path) for name, path in result.items()},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    parser.error(f"unhandled command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
