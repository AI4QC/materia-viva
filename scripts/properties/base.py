"""Adapter protocol shared by every property-source ingester."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACQUIRED_ROOT = PROJECT_ROOT / "data" / "raw" / "acquired"
WORK_ROOT = PROJECT_ROOT / "data" / "props_work"


def default_nproc() -> int:
    """Workers for a CPU-bound stage on whatever machine this is.

    Honours CPU affinity where the platform exposes it, so a cgroup- or
    taskset-limited run does not oversubscribe the cores it was actually
    given. The pipeline stages were originally pinned to 28, the core count
    of the machine they were built on.
    """

    if hasattr(os, "sched_getaffinity"):
        return max(1, len(os.sched_getaffinity(0)))
    return max(1, os.cpu_count() or 1)


_ID_PATTERNS = {
    "materials-project": re.compile(r"^mp-\d+$"),
    "oqmd": re.compile(r"^oqmd-\d+$"),
    "alexandria": re.compile(r"^agm\d+$"),
    "icsd": re.compile(r"^icsd-\d+$"),
    "cod": re.compile(r"^cod-\d+$"),
}


def normalize_match_id(source: str, value: Any) -> tuple[str, str] | None:
    """Return a (source, id) pair in pool notation, or None if unusable.

    Pool notation follows the ids stored in the merge metadata:
    mp-123, oqmd-123, agm000000123, icsd-123, cod-1234567.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None
    if source == "materials-project":
        if text.startswith(("mvc-", "mp-")):
            pass
        elif text.isdigit():
            text = f"mp-{text}"
    elif source == "oqmd" and text.isdigit():
        text = f"oqmd-{text}"
    elif source == "icsd":
        text = re.sub(r"(?i)^icsd[-_ ]?0*", "", text)
        if not text.isdigit():
            return None
        text = f"icsd-{int(text)}"
    elif source == "cod":
        text = re.sub(r"(?i)^cod[-_ ]?", "", text)
        if not text.isdigit():
            return None
        text = f"cod-{int(text)}"
    pattern = _ID_PATTERNS.get(source)
    if pattern is not None and not pattern.match(text):
        return None
    return source, text


@dataclass
class PropertyValue:
    """One property of one source record; source tagging happens per record."""

    name: str
    value: float | int | bool | str | None
    unit: str | None = None
    method: str | None = None

    def as_row(self) -> tuple[float | None, str | None]:
        """Split into (value_num, value_text) for the staging TSV."""

        value = self.value
        if value is None:
            return None, None
        if isinstance(value, bool):
            return (1.0 if value else 0.0), None
        if isinstance(value, (int, float)):
            number = float(value)
            return (number, None) if math.isfinite(number) else (None, None)
        text = str(value).strip()
        return None, (text or None)


@dataclass
class SourceRecord:
    """One record of a source database, before matching.

    ``structure`` may be a CIF string, a pymatgen Structure, or None when the
    source publishes properties without redistributable structures (matching
    then relies on ``match_ids`` alone).

    ``match_ids`` are cross-database ids this record is *authoritative* for:
    the record's structure is the referenced entry of that database. They are
    tried before any hashing. ``experimental`` selects which pool a brand-new
    structure joins.
    """

    native_id: str
    properties: list[PropertyValue] = field(default_factory=list)
    structure: Any | None = None
    match_ids: list[tuple[str, str]] = field(default_factory=list)
    experimental: bool = False

    def structure_cif(self) -> str | None:
        if self.structure is None:
            return None
        if isinstance(self.structure, str):
            return self.structure
        # pymatgen Structure (imported lazily by adapters)
        return self.structure.to(fmt="cif")


class SourceAdapter:
    """Base class: subclasses stream SourceRecords out of one raw source."""

    #: id in scripts/datasets/sources.json; also the provenance tag
    source_key: str = ""
    #: True when every record without a pool match should be dropped instead of
    #: ingested as a new structure (e.g. licence forbids structure reuse, or
    #: the source's structures are non-periodic / out of scope).
    properties_only: bool = False
    #: True when records should be fingerprinted even after an id match hits.
    #: Use for sources whose match_ids point at a *related* database entry
    #: (e.g. the ICSD parent) while the record's own structure may still be a
    #: distinct pool candidate. Sources whose id match means "this record IS
    #: that pool structure" (e.g. Alexandria agm ids) keep the default False
    #: and skip hashing entirely on a hit.
    always_hash: bool = False

    def __init__(self, root: Path | None = None) -> None:
        if not self.source_key:
            raise ValueError(f"{type(self).__name__} does not define source_key")
        self.root = Path(root) if root else ACQUIRED_ROOT / self.source_key

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        raise NotImplementedError
