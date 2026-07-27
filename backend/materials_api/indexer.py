"""Streaming index builder for the experimental and 6.12M structure datasets."""

from __future__ import annotations

import csv
import json
import math
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator

from pymatgen.core import Composition

from .blob_store import BlobWriter
from .formula import parse_formula
from .repository import MaterialRepository


csv.field_size_limit(100_000_000)

_NUMBER = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)(?:\(\d+\))?"
_CIF_FIELDS = {
    "lattice_a": re.compile(rf"(?im)^\s*_cell_length_a\s+{_NUMBER}"),
    "lattice_b": re.compile(rf"(?im)^\s*_cell_length_b\s+{_NUMBER}"),
    "lattice_c": re.compile(rf"(?im)^\s*_cell_length_c\s+{_NUMBER}"),
    "lattice_alpha": re.compile(rf"(?im)^\s*_cell_angle_alpha\s+{_NUMBER}"),
    "lattice_beta": re.compile(rf"(?im)^\s*_cell_angle_beta\s+{_NUMBER}"),
    "lattice_gamma": re.compile(rf"(?im)^\s*_cell_angle_gamma\s+{_NUMBER}"),
    "volume": re.compile(rf"(?im)^\s*_cell_volume\s+{_NUMBER}"),
}

_CRYSTAL_SYSTEMS = (
    ("triclinic", 1, 2),
    ("monoclinic", 3, 15),
    ("orthorhombic", 16, 74),
    ("tetragonal", 75, 142),
    ("trigonal", 143, 167),
    ("hexagonal", 168, 194),
    ("cubic", 195, 230),
)


@dataclass(frozen=True)
class IndexConfig:
    experimental_dir: Path
    candidate_dir: Path
    output_dir: Path
    stats_dir: Path | None = None
    limit_per_dataset: int | None = None
    commit_every: int = 5_000
    compression_level: int = 3
    progress_every: int = 100_000
    progress_callback: Callable[[str, int, int], None] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "experimental_dir", Path(self.experimental_dir))
        object.__setattr__(self, "candidate_dir", Path(self.candidate_dir))
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        if self.stats_dir is not None:
            object.__setattr__(self, "stats_dir", Path(self.stats_dir))
        if self.limit_per_dataset is not None and self.limit_per_dataset <= 0:
            raise ValueError("limit_per_dataset must be positive")


def build_index(config: IndexConfig) -> dict[str, Any]:
    """Build an index into temporary files, then replace the active pair."""

    started = time.time()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    database_path = config.output_dir / "materials.sqlite"
    blob_path = config.output_dir / "structures.blob"
    temp_database = config.output_dir / "materials.sqlite.building"
    temp_blob = config.output_dir / "structures.blob.building"
    for path in (temp_database, temp_blob):
        if path.exists():
            path.unlink()

    spg_maps = {
        "experimental": _load_spacegroups(config.stats_dir / "exp_spg.tsv") if config.stats_dir else {},
        "candidate": _load_spacegroups(config.stats_dir / "pool_spg.tsv") if config.stats_dir else {},
    }
    report: dict[str, Any] = {
        "indexed": {"experimental": 0, "candidate": 0},
        "skipped": {"invalid_formula": 0, "missing_cif": 0, "other": 0},
        "inputs": {
            "experimental": str(config.experimental_dir),
            "candidate": str(config.candidate_dir),
        },
    }
    property_counts = {
        "spacegroup": 0,
        "pbes_gap": 0,
        "density": 0,
        "formation_energy": 0,
        "energy_above_hull": 0,
        "magnetism": 0,
        "elasticity": 0,
    }

    repository = MaterialRepository.create(temp_database, temp_blob)
    try:
        with BlobWriter(temp_blob, compression_level=config.compression_level) as blobs:
            for dataset, source_dir in (
                ("experimental", config.experimental_dir),
                ("candidate", config.candidate_dir),
            ):
                for split, row in _iter_rows(source_dir, config.limit_per_dataset):
                    cif = row.get("cif", "")
                    if not cif:
                        report["skipped"]["missing_cif"] += 1
                        continue
                    try:
                        info = parse_formula(row.get("material_id", ""))
                        fields = _extract_cif_fields(cif)
                        source_index = str(row.get("index", report["indexed"][dataset]))
                        spg = spg_maps[dataset].get(source_index)
                        reference = blobs.append(cif)
                        record = {
                            "material_id": f"{'exp' if dataset == 'experimental' else 'pool'}-{split}-{source_index}",
                            "formula": info.formula,
                            "chemical_system": info.chemical_system,
                            "elements": info.elements,
                            "dataset": dataset,
                            "is_experimental": dataset == "experimental",
                            "source_split": split,
                            "source_index": source_index,
                            "n_elements": info.n_elements,
                            "n_atoms": info.n_atoms,
                            "pbes_gap": _optional_float(row.get("pbes_gap")),
                            "density": _density(info.formula, fields.get("volume")),
                            "spacegroup_number": spg,
                            "spacegroup_symbol": _spacegroup_symbol(spg),
                            "crystal_system": crystal_system(spg),
                            "formation_energy_per_atom": _optional_float(_first(
                                row, "formation_energy_per_atom", "formation_energy", "e_form"
                            )),
                            "energy_above_hull": _optional_float(_first(
                                row, "energy_above_hull", "e_above_hull", "e_hull"
                            )),
                            "is_stable": _optional_bool(_first(row, "is_stable", "stable")),
                            "is_metal": _optional_bool(_first(row, "is_metal", "metallic")),
                            "magnetic_ordering": _optional_text(_first(
                                row, "magnetic_ordering", "ordering"
                            )),
                            "total_magnetization": _optional_float(_first(
                                row, "total_magnetization", "magnetization"
                            )),
                            "bulk_modulus": _optional_float(_first(
                                row, "bulk_modulus", "k_vrh", "bulk_modulus_vrh"
                            )),
                            "shear_modulus": _optional_float(_first(
                                row, "shear_modulus", "g_vrh", "shear_modulus_vrh"
                            )),
                            "poisson_ratio": _optional_float(_first(
                                row, "poisson_ratio", "poisson"
                            )),
                            "blob_offset": reference.offset,
                            "blob_length": reference.length,
                            **fields,
                        }
                        repository.add_material(record, commit=False)
                        report["indexed"][dataset] += 1
                        property_counts["spacegroup"] += record["spacegroup_number"] is not None
                        property_counts["pbes_gap"] += record["pbes_gap"] is not None
                        property_counts["density"] += record["density"] is not None
                        property_counts["formation_energy"] += (
                            record["formation_energy_per_atom"] is not None
                        )
                        property_counts["energy_above_hull"] += (
                            record["energy_above_hull"] is not None
                        )
                        property_counts["magnetism"] += (
                            record["magnetic_ordering"] is not None
                            or record["total_magnetization"] is not None
                        )
                        property_counts["elasticity"] += (
                            record["bulk_modulus"] is not None
                            or record["shear_modulus"] is not None
                        )
                        indexed_total = sum(report["indexed"].values())
                        if indexed_total % config.commit_every == 0:
                            repository.connection.commit()
                        if (
                            config.progress_callback is not None
                            and config.progress_every > 0
                            and indexed_total % config.progress_every == 0
                        ):
                            config.progress_callback(
                                dataset, report["indexed"][dataset], indexed_total
                            )
                    except ValueError:
                        report["skipped"]["invalid_formula"] += 1
                    except Exception:
                        report["skipped"]["other"] += 1
                repository.connection.commit()
        for key, value in {
            "schema_version": "2",
            "experimental_count": str(report["indexed"]["experimental"]),
            "candidate_count": str(report["indexed"]["candidate"]),
            "property_counts": json.dumps(property_counts, sort_keys=True),
            "build_report": json.dumps(report, sort_keys=True),
        }.items():
            repository.connection.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value)
            )
        repository.connection.commit()
        repository.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        repository.close()
        for path in (temp_database, temp_blob):
            if path.exists():
                path.unlink()
        raise
    else:
        repository.close()

    os.replace(temp_blob, blob_path)
    os.replace(temp_database, database_path)
    report["elapsed_seconds"] = round(time.time() - started, 3)
    (config.output_dir / "build-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def _iter_rows(source_dir: Path, limit: int | None) -> Iterator[tuple[str, dict[str, str]]]:
    yielded = 0
    for split in ("train", "val"):
        path = source_dir / f"{split}.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if limit is not None and yielded >= limit:
                    return
                yield split, row
                yielded += 1


def _load_spacegroups(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    result: dict[str, int] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                source_index, number = line.rstrip("\n").split("\t", 1)
                parsed = int(number)
                if 1 <= parsed <= 230:
                    result[source_index] = parsed
            except (ValueError, TypeError):
                continue
    return result


def _extract_cif_fields(cif: str) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for name, pattern in _CIF_FIELDS.items():
        match = pattern.search(cif)
        result[name] = _optional_float(match.group(1)) if match else None
    return result


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() in {"", "?", "."}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _first(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() not in {"", "?", "."}:
            return value
    return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized not in {"", "?", "."} else None


def _density(formula: str, volume: float | None) -> float | None:
    if volume is None or volume <= 0:
        return None
    try:
        mass_amu = float(Composition(formula).weight)
    except Exception:
        return None
    return mass_amu * 1.66053906660 / volume


def crystal_system(spacegroup_number: int | None) -> str | None:
    if spacegroup_number is None:
        return None
    for name, lower, upper in _CRYSTAL_SYSTEMS:
        if lower <= spacegroup_number <= upper:
            return name
    return None


@lru_cache(maxsize=231)
def _spacegroup_symbol(number: int | None) -> str | None:
    if number is None:
        return None
    try:
        from pymatgen.symmetry.groups import SpaceGroup

        return SpaceGroup.from_int_number(number).symbol
    except Exception:
        return None
