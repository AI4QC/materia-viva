"""Canonical source-data contract for Crystal Material Universe datasets."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "crystal-record-v1"
CRYSTAL_RECORD_FIELDS = ("index", "material_id", "cif", "pbes_gap")
SOURCE_ROLES = frozenset({"experimental", "candidate"})

csv.field_size_limit(sys.maxsize)


class DataContractError(ValueError):
    """Raised when a source split violates Crystal Record v1."""


@dataclass(frozen=True)
class SourceValidation:
    role: str
    root: Path
    splits: dict[str, int]

    @property
    def total_records(self) -> int:
        return sum(self.splits.values())

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "role": self.role,
            "fields": list(CRYSTAL_RECORD_FIELDS),
            "splits": self.splits,
            "total_records": self.total_records,
        }


def _validate_row(row: dict[str | None, str | list[str] | None], source: str) -> None:
    if None in row:
        raise DataContractError(f"{source}: record has more than four columns")

    index = str(row.get("index") or "")
    try:
        parsed_index = int(index)
    except ValueError as exc:
        raise DataContractError(f"{source}: index must be a non-negative integer") from exc
    if parsed_index < 0 or str(parsed_index) != index.strip():
        raise DataContractError(f"{source}: index must be a non-negative integer")

    if not str(row.get("material_id") or "").strip():
        raise DataContractError(f"{source}: material_id must be non-empty")
    if not str(row.get("cif") or "").strip():
        raise DataContractError(f"{source}: record must contain a non-empty CIF")

    pbes_gap = str(row.get("pbes_gap") or "").strip()
    if pbes_gap:
        try:
            float(pbes_gap)
        except ValueError as exc:
            raise DataContractError(f"{source}: record must contain a numeric pbes_gap") from exc


def _validate_split(path: Path) -> int:
    if not path.is_file():
        raise DataContractError(f"missing source split: {path}")

    count = 0
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CRYSTAL_RECORD_FIELDS:
            raise DataContractError(
                f"{path}: expected column order {CRYSTAL_RECORD_FIELDS}, "
                f"got {tuple(reader.fieldnames or ())}"
            )
        for line_number, row in enumerate(reader, start=2):
            _validate_row(row, f"{path}:{line_number}")
            count += 1
    return count


def validate_source_dataset(root: str | Path, *, role: str) -> SourceValidation:
    """Stream both CSV splits and return a Crystal Record v1 manifest."""

    if role not in SOURCE_ROLES:
        raise DataContractError(f"unsupported dataset role: {role}")
    source_root = Path(root)
    splits = {
        split: _validate_split(source_root / f"{split}.csv")
        for split in ("train", "val")
    }
    return SourceValidation(role=role, root=source_root, splits=splits)


def write_manifest(report: SourceValidation, destination: str | Path) -> Path:
    """Atomically persist a validation report as UTF-8 JSON."""

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".building")
    temporary.write_text(
        json.dumps(report.to_manifest(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path
