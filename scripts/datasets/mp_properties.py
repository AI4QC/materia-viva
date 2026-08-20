#!/usr/bin/env python3
"""Resumable exporter for the Materials Project *property* endpoints.

The 2026-07-26 acquisition took only ``materials/summary/`` (154,377 docs).
Counting ``has_props`` across that dump shows nine further property families
MateriaViva never downloaded; this script pulls the scalar/text ones through a
single code path::

    scripts/datasets/mp_properties.py --family oxidation_states
    scripts/datasets/mp_properties.py --family all

Method
------
* ``GET https://api.materialsproject.org/materials/<family>/`` with
  ``_skip``/``_limit`` paging (``_limit`` maxes out at 1000) and an explicit
  ``_fields`` list -- the full docs carry relaxed structures, 6x6 tensors and
  per-deformation fitting data, so every family requests only the columns the
  property pipeline can actually stage.
* The API key travels in the ``X-API-KEY`` header, never in the URL, so the
  URLs recorded in the receipts and the manifest are safe to publish.
* Serial requests with ``--request-delay`` seconds between them, exponential
  backoff on 5xx/timeouts, and a hard stop when the server answers 429 (or 403)
  twice in a row rather than pushing through a rate limit.

Outputs (under ``data/raw/acquired/materials-project/<family>-<date>/``)
-----------------------------------------------------------------------
* ``page-NNNNNNNNN.json.gz``              one API response per ``_skip`` offset
* ``page-NNNNNNNNN.json.gz.receipt.json`` key-free URL, bytes, sha256, time
* ``manifest.json``                       endpoint, fields, counts, page list

A resumed run re-reads the pages already on disk (a page counts as complete
only when its receipt exists too, so a half-written page is refetched).

Field selection, per family
---------------------------
oxidation_states
    ``average_oxidation_states`` is the point: ~21% of MP materials put an
    element on more than one site valence and only the average resolves them.
    ``possible_valences`` is a per-site array and is deliberately not requested.
chemenv
    Coordination environments per symmetry-distinct cation site plus the
    continuous symmetry measure. Only ~2.5% of the 154,370 docs are actually
    populated (the rest carry "No oxidation states available. Cation-anion
    bonds cannot be identified."), which is only visible after fetching.
insertion_electrodes
    An entirely new property domain for the pool: 6,847 electrodes covering
    17,331 materials, keyed by ``material_ids`` (charge + discharge endpoints,
    and one material can host several electrodes with different working ions).
    ``electrode_object``/``adj_pairs``/``host_structure`` are skipped -- the
    first two are per-step tables, the third is a structure we already hold.
    MP publishes ``max_voltage_step`` but no minimum: the per-step plateau
    voltages live inside ``adj_pairs``, and 90.4% of these electrodes are
    single-step, so a min/max over them would only repeat ``average_voltage``.
elasticity
    Only the columns ``summary`` lacks: the Voigt/Reuss bounds beside the VRH
    averages we already staged, Young's modulus, the Debye temperature, the
    sound velocities and the Clarke/Cahill minimum thermal conductivities.
    The 6x6 elastic/compliance tensors and the raw fitting data are skipped.
piezoelectric
    ``e_ij_max`` is already staged from summary; ``max_direction`` (the
    crystallographic direction of the maximum response) is not, and is the
    reason this family is fetched at all.
eos
    Energy-volume equation-of-state fits, keyed by a bare ``task_id`` whose
    material id is ``mp-<task_id>``. The ``energies``/``volumes`` arrays are
    the E(V) curve and belong to the curve pipeline, not here.
surface_properties
    The per-facet ``surfaces`` table (Miller index, surface energy, work
    function); the Wulff-weighted scalars beside it are already in summary.
    Requested with the per-facet slab structures because the endpoint has no
    sub-field selection -- 138 docs, ~7 MB.
grain_boundaries
    One doc per computed grain boundary (327 of them over 58 materials): sigma,
    boundary plane, rotation, GB energy and work of separation. The initial and
    final GB supercells are skipped.

``materials/dielectric/`` is deliberately absent: every scalar it publishes
(``e_total``, ``e_ionic``, ``e_electronic``, ``n``) is already staged from
summary for the same materials, and the remainder is a 3x3 tensor the property
schema does not store.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.datasets.acquire import default_data_root, write_receipt

BASE = "https://api.materialsproject.org"
SOURCE_ID = "materials-project"
USER_AGENT = (
    "MateriaViva-dataset-acquisition/1.0 "
    "(materials-database property ingestion; contact smoakvescio@gmail.com)"
)
DOTENV_PATH = Path(__file__).resolve().parents[2] / ".env"
MAX_PAGE_SIZE = 1000
SNAPSHOT = "2026-08-19"

#: family -> requested columns. Always restrict: the unrestricted docs carry
#: relaxed structures and tensors that dwarf the values we can stage.
FAMILIES: dict[str, tuple[str, ...]] = {
    "oxidation_states": (
        "material_id",
        "average_oxidation_states",
        "possible_species",
        "method",
        "deprecated",
    ),
    "chemenv": (
        "material_id",
        "species",
        "chemenv_symbol",
        "chemenv_name",
        "csm",
        "method",
        "warnings",
    ),
    "insertion_electrodes": (
        "material_ids",
        "id_charge",
        "id_discharge",
        "working_ion",
        "battery_formula",
        "framework_formula",
        "formula_charge",
        "formula_discharge",
        "average_voltage",
        "max_voltage_step",
        "num_steps",
        "capacity_grav",
        "capacity_vol",
        "energy_grav",
        "energy_vol",
        "fracA_charge",
        "fracA_discharge",
        "stability_charge",
        "stability_discharge",
        "max_delta_volume",
        "warnings",
    ),
    "elasticity": (
        "material_id",
        "bulk_modulus",
        "shear_modulus",
        "young_modulus",
        "debye_temperature",
        "sound_velocity",
        "thermal_conductivity",
        "universal_anisotropy",
        "homogeneous_poisson",
        "fitting_method",
        "order",
        "state",
        "deprecated",
    ),
    "piezoelectric": (
        "material_id",
        "e_ij_max",
        "max_direction",
        "deprecated",
    ),
    "eos": (
        "task_id",
        "eos",
    ),
    "surface_properties": (
        "material_id",
        "surfaces",
        "weighted_surface_energy",
        "weighted_work_function",
        "surface_anisotropy",
        "shape_factor",
        "has_reconstructed",
    ),
    "grain_boundaries": (
        "material_id",
        "sigma",
        "type",
        "rotation_axis",
        "rotation_angle",
        "gb_plane",
        "gb_energy",
        "w_sep",
    ),
}

#: surface_properties docs carry a slab structure per facet (~53 kB/doc), so
#: they are paged smaller to keep single responses modest.
PAGE_SIZES: dict[str, int] = {"surface_properties": 100}


class RateLimited(RuntimeError):
    """The API signalled throttling; stop rather than push through it."""


def load_dotenv(path: Path = DOTENV_PATH) -> None:
    """Populate os.environ from the repo .env without overriding real env."""

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_key() -> str:
    load_dotenv()
    key = os.environ.get("MP_API_KEY") or os.environ.get("MAPI_KEY")
    if not key:
        raise SystemExit(
            "set MP_API_KEY (or legacy MAPI_KEY) in the environment or .env"
        )
    return key


def build_url(family: str, *, skip: int, limit: int) -> str:
    """Query URL for one page. The key is a header, so this URL is loggable."""

    fields = FAMILIES[family]
    query = urlencode(
        {"_skip": skip, "_limit": limit, "_fields": ",".join(fields)}
    )
    return f"{BASE}/materials/{family}/?{query}"


def _fetch_json(url: str, key: str, *, attempts: int = 6, timeout: int = 600) -> dict:
    request = Request(
        url, headers={"X-API-KEY": key, "User-Agent": USER_AGENT}
    )
    last_error: Exception | None = None
    throttles = 0
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            last_error = error
            if error.code in (403, 429):
                throttles += 1
                if throttles >= 2:
                    raise RateLimited(
                        f"HTTP {error.code} twice from {url}: the Materials "
                        "Project is rate limiting or refusing this client. "
                        "Stopping; rerun later to resume."
                    ) from error
                headers = error.headers or {}
                retry_after = str(headers.get("Retry-After") or "")
                time.sleep(
                    min(300, int(retry_after)) if retry_after.isdigit() else 60
                )
                continue
            if error.code < 500:
                raise
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            last_error = error
        if attempt + 1 < attempts:
            time.sleep(min(120, 2 ** (attempt + 1)))
    assert last_error is not None
    raise last_error


def _write_page(directory: Path, *, offset: int, payload: dict) -> Path:
    target = directory / f"page-{offset:09d}.json.gz"
    building = target.with_name(target.name + ".part")
    with gzip.open(building, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    building.replace(target)
    return target


def _read_page(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def completed_offsets(directory: Path) -> set[int]:
    """Offsets whose page AND receipt are both on disk."""

    pattern = re.compile(r"^page-(\d{9})\.json\.gz$")
    offsets: set[int] = set()
    if not directory.exists():
        return offsets
    for path in directory.iterdir():
        match = pattern.match(path.name)
        if match and path.with_name(path.name + ".receipt.json").exists():
            offsets.add(int(match.group(1)))
    return offsets


def _write_manifest(directory: Path, payload: dict) -> Path:
    files: dict[str, dict] = {}
    for receipt in sorted(directory.glob("page-*.json.gz.receipt.json")):
        entry = json.loads(receipt.read_text(encoding="utf-8"))
        files[receipt.name[: -len(".receipt.json")]] = {
            "bytes": entry["bytes"],
            "sha256": entry["sha256"],
        }
    manifest = dict(payload)
    manifest["files"] = files
    manifest["total_bytes"] = sum(item["bytes"] for item in files.values())
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    target = directory / "manifest.json"
    building = target.with_name(target.name + ".part")
    building.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    building.replace(target)
    return target


def export_family(
    *,
    family: str,
    output_dir: Path,
    key: str,
    page_size: int | None = None,
    request_delay: float = 0.3,
    data_root: Path | None = None,
    fetch_json: Callable[[str, str], dict] | None = None,
) -> Path:
    """Page one property family into gzip pages with per-page receipts."""

    if family not in FAMILIES:
        raise SystemExit(f"unknown family {family!r}; choose from {sorted(FAMILIES)}")
    size = page_size or PAGE_SIZES.get(family, MAX_PAGE_SIZE)
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise ValueError("page size must be between 1 and the API maximum of 1000")
    fetch = fetch_json or _fetch_json
    root = data_root or default_data_root()
    output_dir.mkdir(parents=True, exist_ok=True)
    done = completed_offsets(output_dir)

    first_url = build_url(family, skip=0, limit=size)
    first_path = output_dir / "page-000000000.json.gz"
    if 0 in done:
        first = _read_page(first_path)
    else:
        first = fetch(first_url, key)
        _write_page(output_dir, offset=0, payload=first)
        write_receipt(first_path, data_root=root, source_id=SOURCE_ID, url=first_url)
        done.add(0)

    total = int(first.get("meta", {}).get("total_doc") or 0)
    if total <= 0:
        raise RuntimeError(f"{family}: response carried no positive meta.total_doc")
    print(f"[{family}] {total:,} documents, page size {size}", flush=True)

    downloaded = 0
    offsets: list[int] = []
    started = datetime.now(timezone.utc).isoformat()
    for offset in range(0, total, size):
        url = build_url(family, skip=offset, limit=size)
        path = output_dir / f"page-{offset:09d}.json.gz"
        if offset == 0:
            payload = first
        elif offset in done:
            payload = _read_page(path)
        else:
            if request_delay:
                time.sleep(request_delay)
            payload = fetch(url, key)
            _write_page(output_dir, offset=offset, payload=payload)
            write_receipt(path, data_root=root, source_id=SOURCE_ID, url=url)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise RuntimeError(f"{family}: invalid data payload at offset {offset}")
        downloaded += len(rows)
        offsets.append(offset)
        _write_manifest(
            output_dir,
            {
                "source": f"Materials Project {family} API",
                "source_id": SOURCE_ID,
                "endpoint": f"{BASE}/materials/{family}/",
                "family": family,
                "fields": list(FAMILIES[family]),
                "example_query": first_url,
                "api_version": first.get("meta", {}).get("api_version"),
                "database_version": (rows[0].get("builder_meta") or {}).get(
                    "database_version"
                ) if rows and isinstance(rows[0], dict) else None,
                "auth": "X-API-KEY header (never in the URL)",
                "user_agent": USER_AGENT,
                "page_size": size,
                "total_documents": total,
                "downloaded_documents": downloaded,
                "page_offsets": offsets,
                "complete": downloaded >= total,
                "started_at": started,
            },
        )
        if offset % (size * 20) == 0:
            print(
                f"[{family}] {downloaded:,}/{total:,} documents", flush=True
            )

    if downloaded != total:
        raise RuntimeError(
            f"{family}: downloaded {downloaded} documents, expected {total}"
        )
    print(f"[{family}] complete: {downloaded:,} documents", flush=True)
    return output_dir / "manifest.json"


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--family",
        required=True,
        help="one of " + ", ".join(sorted(FAMILIES)) + ", or 'all'",
    )
    parser.add_argument("--page-size", type=int)
    parser.add_argument("--request-delay", type=float, default=0.3)
    parser.add_argument("--snapshot", default=SNAPSHOT)
    parser.add_argument("--output", type=Path, help="override the snapshot directory")
    args = parser.parse_args()

    families = sorted(FAMILIES) if args.family == "all" else [args.family]
    key = api_key()
    root = default_data_root()
    for family in families:
        output = args.output or (
            root / "raw" / "acquired" / SOURCE_ID / f"{family}-{args.snapshot}"
        )
        print(
            export_family(
                family=family,
                output_dir=output,
                key=key,
                page_size=args.page_size,
                request_delay=args.request_delay,
                data_root=root,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
