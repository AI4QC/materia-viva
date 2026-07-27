"""SQLite repository and strictly parameterized material search."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .blob_store import BlobReader


SORT_COLUMNS = {
    "material_id": "m.material_id",
    "formula": "m.formula COLLATE NOCASE",
    "pbes_gap": "m.pbes_gap",
    "density": "m.density",
    "n_atoms": "m.n_atoms",
    "n_elements": "m.n_elements",
    "spacegroup_number": "m.spacegroup_number",
    "volume": "m.volume",
    "formation_energy_per_atom": "m.formation_energy_per_atom",
    "energy_above_hull": "m.energy_above_hull",
    "bulk_modulus": "m.bulk_modulus",
}

PROPERTY_FILTERS = {
    "band_gap": "m.pbes_gap IS NOT NULL",
    "density": "m.density IS NOT NULL",
    "spacegroup": "m.spacegroup_number IS NOT NULL",
    "formation_energy": "m.formation_energy_per_atom IS NOT NULL",
    "energy_above_hull": "m.energy_above_hull IS NOT NULL",
    "magnetism": "(m.magnetic_ordering IS NOT NULL OR m.total_magnetization IS NOT NULL)",
    "elasticity": "(m.bulk_modulus IS NOT NULL OR m.shear_modulus IS NOT NULL)",
}

PUBLIC_COLUMNS = (
    "material_id", "formula", "chemical_system", "dataset", "is_experimental",
    "source_split", "source_index", "n_elements", "n_atoms", "pbes_gap",
    "density", "volume", "spacegroup_number", "spacegroup_symbol",
    "crystal_system", "lattice_a", "lattice_b", "lattice_c", "lattice_alpha",
    "lattice_beta", "lattice_gamma", "formation_energy_per_atom",
    "energy_above_hull", "is_stable", "is_metal", "magnetic_ordering",
    "total_magnetization", "bulk_modulus", "shear_modulus", "poisson_ratio",
)

INSERT_COLUMNS = PUBLIC_COLUMNS + ("blob_offset", "blob_length")


@dataclass(frozen=True)
class SearchQuery:
    include_elements: tuple[str, ...] = ()
    exclude_elements: tuple[str, ...] = ()
    element_mode: str = "all"
    datasets: tuple[str, ...] = ()
    formula: str | None = None
    gap_min: float | None = None
    gap_max: float | None = None
    density_min: float | None = None
    density_max: float | None = None
    volume_min: float | None = None
    volume_max: float | None = None
    n_atoms_min: float | None = None
    n_atoms_max: float | None = None
    n_elements_min: int | None = None
    n_elements_max: int | None = None
    spacegroup_numbers: tuple[int, ...] = ()
    crystal_systems: tuple[str, ...] = ()
    formation_energy_min: float | None = None
    formation_energy_max: float | None = None
    e_hull_min: float | None = None
    e_hull_max: float | None = None
    stability: str | None = None
    metallicity: str | None = None
    magnetic_orderings: tuple[str, ...] = ()
    magnetization_min: float | None = None
    magnetization_max: float | None = None
    bulk_modulus_min: float | None = None
    bulk_modulus_max: float | None = None
    shear_modulus_min: float | None = None
    shear_modulus_max: float | None = None
    has_properties: tuple[str, ...] = ()
    page: int = 1
    page_size: int = 24
    sort: str = "material_id"
    direction: str = "asc"


@dataclass(frozen=True)
class SearchResult:
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    pages: int
    facets: dict[str, Any] = field(default_factory=dict)


class MaterialRepository:
    def __init__(self, database_path: str | Path, blob_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.blob_path = Path(blob_path)
        self.connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def create(cls, database_path: str | Path, blob_path: str | Path) -> "MaterialRepository":
        database_path = Path(database_path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        connection = sqlite3.connect(database_path)
        try:
            connection.executescript(schema)
            connection.commit()
        finally:
            connection.close()
        return cls(database_path, blob_path)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MaterialRepository":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def add_material(self, record: Mapping[str, Any], *, commit: bool = True) -> int:
        missing = {"material_id", "formula", "chemical_system", "dataset", "elements"} - record.keys()
        if missing:
            raise ValueError(f"missing material fields: {', '.join(sorted(missing))}")
        values = [record.get(column) for column in INSERT_COLUMNS]
        placeholders = ", ".join("?" for _ in INSERT_COLUMNS)
        cursor = self.connection.execute(
            f"INSERT INTO materials ({', '.join(INSERT_COLUMNS)}) VALUES ({placeholders})",
            values,
        )
        material_pk = int(cursor.lastrowid)
        self.connection.executemany(
            "INSERT INTO material_elements (material_pk, element) VALUES (?, ?)",
            ((material_pk, element) for element in sorted(set(record["elements"]))),
        )
        if commit:
            self.connection.commit()
        return material_pk

    def add_materials(self, records: Iterable[Mapping[str, Any]]) -> int:
        count = 0
        with self.connection:
            for record in records:
                self.add_material(record, commit=False)
                count += 1
        return count

    def get(self, material_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            f"SELECT {', '.join(PUBLIC_COLUMNS)}, blob_offset, blob_length "
            "FROM materials WHERE material_id = ?",
            (material_id,),
        ).fetchone()
        if row is None:
            return None
        result = self._row_to_public(row, include_blob=True)
        result["elements"] = [item[0] for item in self.connection.execute(
            "SELECT element FROM material_elements "
            "WHERE material_pk = (SELECT pk FROM materials WHERE material_id = ?) "
            "ORDER BY element",
            (material_id,),
        ).fetchall()]
        return result

    def read_cif(self, material_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT blob_offset, blob_length FROM materials WHERE material_id = ?",
            (material_id,),
        ).fetchone()
        if row is None:
            return None
        with BlobReader(self.blob_path) as reader:
            return reader.read(int(row["blob_offset"]), int(row["blob_length"]))

    def search(self, query: SearchQuery) -> SearchResult:
        where, params = self._build_where(query)
        if query.sort not in SORT_COLUMNS:
            raise ValueError(f"unknown sort key: {query.sort}")
        direction = query.direction.lower()
        if direction not in {"asc", "desc"}:
            raise ValueError("sort direction must be 'asc' or 'desc'")
        if query.page < 1 or not 1 <= query.page_size <= 100:
            raise ValueError("page must be positive and page_size must be between 1 and 100")

        where_sql = " AND ".join(where) if where else "1 = 1"
        if where:
            total, facets = self._filtered_counts(where_sql, params)
        else:
            facets = self._precomputed_dataset_counts()
            if facets is None:
                total, facets = self._filtered_counts(where_sql, params)
            else:
                total = sum(facets.values())
        offset = (query.page - 1) * query.page_size
        rows = self.connection.execute(
            f"SELECT {', '.join('m.' + column for column in PUBLIC_COLUMNS)} "
            f"FROM materials m WHERE {where_sql} "
            f"ORDER BY {SORT_COLUMNS[query.sort]} {direction.upper()}, m.pk ASC "
            "LIMIT ? OFFSET ?",
            (*params, query.page_size, offset),
        ).fetchall()
        return SearchResult(
            items=[self._row_to_public(row) for row in rows],
            total=total,
            page=query.page,
            page_size=query.page_size,
            pages=math.ceil(total / query.page_size) if total else 0,
            facets={"datasets": facets},
        )

    def stats(self) -> dict[str, Any]:
        metadata = dict(self.connection.execute(
            "SELECT key, value FROM metadata WHERE key IN "
            "('experimental_count', 'candidate_count', 'property_counts')"
        ).fetchall())
        if all(key in metadata for key in (
            "experimental_count", "candidate_count", "property_counts",
        )):
            try:
                datasets = self._precomputed_dataset_counts()
                if datasets is None:
                    raise ValueError("invalid dataset metadata")
                property_counts = {
                    key: int(value)
                    for key, value in json.loads(metadata["property_counts"]).items()
                }
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            else:
                return {
                    "total": sum(datasets.values()),
                    "datasets": datasets,
                    "property_counts": property_counts,
                }

        rows = self.connection.execute(
            "SELECT dataset, COUNT(*) AS count FROM materials GROUP BY dataset ORDER BY dataset"
        ).fetchall()
        available = self.connection.execute(
            "SELECT COUNT(spacegroup_number) AS spacegroup, COUNT(pbes_gap) AS pbes_gap, "
            "COUNT(density) AS density, COUNT(formation_energy_per_atom) AS formation_energy, "
            "COUNT(energy_above_hull) AS energy_above_hull, "
            "COUNT(CASE WHEN magnetic_ordering IS NOT NULL OR total_magnetization IS NOT NULL "
            "THEN 1 END) AS magnetism, "
            "COUNT(CASE WHEN bulk_modulus IS NOT NULL OR shear_modulus IS NOT NULL THEN 1 END) "
            "AS elasticity FROM materials"
        ).fetchone()
        datasets = {row["dataset"]: row["count"] for row in rows}
        return {
            "total": sum(datasets.values()),
            "datasets": datasets,
            "property_counts": dict(available),
        }

    def _build_where(self, query: SearchQuery) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        include = tuple(dict.fromkeys(query.include_elements))
        exclude = tuple(dict.fromkeys(query.exclude_elements))
        if query.element_mode not in {"all", "any", "exact"}:
            raise ValueError("element_mode must be all, any, or exact")
        if include:
            placeholders = ", ".join("?" for _ in include)
            if query.element_mode == "any":
                where.append(
                    f"m.pk IN (SELECT material_pk FROM material_elements WHERE element IN ({placeholders}))"
                )
                params.extend(include)
            else:
                where.append(
                    "m.pk IN (SELECT material_pk FROM material_elements "
                    f"WHERE element IN ({placeholders}) GROUP BY material_pk HAVING COUNT(*) = ?)"
                )
                params.extend(include)
                params.append(len(include))
                if query.element_mode == "exact":
                    where.append("m.n_elements = ?")
                    params.append(len(include))
        if exclude:
            placeholders = ", ".join("?" for _ in exclude)
            where.append(
                "NOT EXISTS (SELECT 1 FROM material_elements excluded "
                f"WHERE excluded.material_pk = m.pk AND excluded.element IN ({placeholders}))"
            )
            params.extend(exclude)
        if query.datasets:
            unknown = set(query.datasets) - {"experimental", "candidate"}
            if unknown:
                raise ValueError(f"unknown datasets: {', '.join(sorted(unknown))}")
            placeholders = ", ".join("?" for _ in query.datasets)
            where.append(f"m.dataset IN ({placeholders})")
            params.extend(query.datasets)
        if query.formula:
            term = query.formula.strip()
            if term.startswith(("exp-", "pool-")):
                where.append("m.material_id = ?")
                params.append(term)
            elif "-" in term:
                chemical_system = "-".join(sorted(
                    component.strip().capitalize()
                    for component in term.split("-")
                    if component.strip()
                ))
                where.append("m.chemical_system = ?")
                params.append(chemical_system)
            else:
                where.append("m.formula = ? COLLATE NOCASE")
                params.append(term)
        self._add_range(where, params, "m.pbes_gap", query.gap_min, query.gap_max, "gap")
        self._add_range(where, params, "m.density", query.density_min, query.density_max, "density")
        self._add_range(where, params, "m.volume", query.volume_min, query.volume_max, "volume")
        self._add_range(where, params, "m.n_atoms", query.n_atoms_min, query.n_atoms_max, "n_atoms")
        self._add_range(where, params, "m.n_elements", query.n_elements_min, query.n_elements_max, "n_elements")
        self._add_range(
            where, params, "m.formation_energy_per_atom",
            query.formation_energy_min, query.formation_energy_max, "formation_energy",
        )
        self._add_range(
            where, params, "m.energy_above_hull", query.e_hull_min, query.e_hull_max, "e_hull",
        )
        self._add_range(
            where, params, "m.total_magnetization",
            query.magnetization_min, query.magnetization_max, "magnetization",
        )
        self._add_range(
            where, params, "m.bulk_modulus",
            query.bulk_modulus_min, query.bulk_modulus_max, "bulk_modulus",
        )
        self._add_range(
            where, params, "m.shear_modulus",
            query.shear_modulus_min, query.shear_modulus_max, "shear_modulus",
        )
        if query.spacegroup_numbers:
            if any(number < 1 or number > 230 for number in query.spacegroup_numbers):
                raise ValueError("space-group numbers must be between 1 and 230")
            placeholders = ", ".join("?" for _ in query.spacegroup_numbers)
            where.append(f"m.spacegroup_number IN ({placeholders})")
            params.extend(query.spacegroup_numbers)
        if query.crystal_systems:
            placeholders = ", ".join("?" for _ in query.crystal_systems)
            where.append(f"m.crystal_system IN ({placeholders})")
            params.extend(query.crystal_systems)
        for value, column in ((query.stability, "m.is_stable"), (query.metallicity, "m.is_metal")):
            if value is None:
                continue
            allowed = {"stable", "unstable"} if column == "m.is_stable" else {"metal", "nonmetal"}
            if value not in allowed:
                raise ValueError(f"invalid property state: {value}")
            where.append(f"{column} = ?")
            params.append(1 if value in {"stable", "metal"} else 0)
        if query.magnetic_orderings:
            placeholders = ", ".join("?" for _ in query.magnetic_orderings)
            where.append(f"m.magnetic_ordering IN ({placeholders})")
            params.extend(query.magnetic_orderings)
        for property_name in dict.fromkeys(query.has_properties):
            try:
                where.append(PROPERTY_FILTERS[property_name])
            except KeyError as exc:
                raise ValueError(f"unknown property filter: {property_name}") from exc
        return where, params

    @staticmethod
    def _add_range(where, params, column, minimum, maximum, label) -> None:
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError(f"{label} minimum cannot exceed maximum")
        if minimum is not None:
            where.append(f"{column} >= ?")
            params.append(minimum)
        if maximum is not None:
            where.append(f"{column} <= ?")
            params.append(maximum)

    def _precomputed_dataset_counts(self) -> dict[str, int] | None:
        rows = dict(self.connection.execute(
            "SELECT key, value FROM metadata WHERE key IN "
            "('experimental_count', 'candidate_count')"
        ).fetchall())
        if "experimental_count" not in rows or "candidate_count" not in rows:
            return None
        try:
            return {
                "candidate": int(rows["candidate_count"]),
                "experimental": int(rows["experimental_count"]),
            }
        except (TypeError, ValueError):
            return None

    def _filtered_counts(
        self, where_sql: str, params: Sequence[Any]
    ) -> tuple[int, dict[str, int]]:
        row = self.connection.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(CASE WHEN m.dataset = 'candidate' THEN 1 END) AS candidate, "
            "COUNT(CASE WHEN m.dataset = 'experimental' THEN 1 END) AS experimental "
            f"FROM materials m WHERE {where_sql}",
            params,
        ).fetchone()
        facets = {
            dataset: int(row[dataset])
            for dataset in ("candidate", "experimental")
            if int(row[dataset]) > 0
        }
        return int(row["total"]), facets

    @staticmethod
    def _row_to_public(row: sqlite3.Row, *, include_blob: bool = False) -> dict[str, Any]:
        result = dict(row)
        result["is_experimental"] = bool(result["is_experimental"])
        for key in ("is_stable", "is_metal"):
            if result.get(key) is not None:
                result[key] = bool(result[key])
        if not include_blob:
            result.pop("blob_offset", None)
            result.pop("blob_length", None)
        return result
