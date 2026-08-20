"""HADB: hard-coating alloy elastic properties (funmat-ii.se).

One gzipped JSON per material, scraped detail pages. Each record ships its own
CIF (passed through verbatim) plus a 'table_rows' listing of computed elastic
moduli. Structures are HADB's own supercells, so always_hash with no id
matches. Tensor / strength tables are skipped; only the four VRH scalars are
ingested with method '<DFT|MLIP> <T>K'.
"""

from __future__ import annotations

import ast
import gzip
import json
from typing import Any, Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

# table label -> (canonical name, unit)
_ROW_MAP = {
    "Bulk modulus, Voigt-Reuss-Hill": ("bulk_modulus_vrh", "GPa"),
    "Shear modulus, Voigt-Reuss-Hill": ("shear_modulus_vrh", "GPa"),
    "Young's modulus, Voigt-Reuss-Hill": ("youngs_modulus", "GPa"),
    "Poisson's ratio, Voigt-Reuss-Hill": ("poisson_ratio", None),
}


def _table_rows(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _cell_number(text: Any, unit: str | None) -> float | None:
    """Parse '199 GPa' / '0.32' cells, dropping a trailing unit token."""

    cell = safe_text(text)
    if cell is None:
        return None
    if unit and cell.endswith(unit):
        cell = cell[: -len(unit)].strip()
    return safe_float(cell)


class HadbAdapter(SourceAdapter):
    source_key = "hadb"
    always_hash = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        files = sorted((self.root / "records").glob("material-*.json.gz"))
        count = 0
        for path in files:
            if limit is not None and count >= limit:
                return
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                rec = json.load(handle)
            material_id = safe_text(rec.get("material_id"))
            if not material_id:
                continue
            method = safe_text(rec.get("method")) or "DFT"
            temperature = safe_float(rec.get("temperature"))
            if temperature is not None:
                if temperature == int(temperature):
                    method = f"{method} {int(temperature)}K"
                else:
                    method = f"{method} {temperature}K"
            properties = []
            for row in _table_rows(rec.get("table_rows")):
                if not isinstance(row, list) or len(row) < 2:
                    continue
                label = safe_text(row[0])
                if label not in _ROW_MAP:
                    continue
                name, unit = _ROW_MAP[label]
                value = _cell_number(row[1], unit)
                if value is not None:
                    properties.append(PropertyValue(name, value, unit, method))
            structure = rec.get("cif") if isinstance(rec.get("cif"), str) else None
            if not properties and structure is None:
                continue
            count += 1
            yield SourceRecord(
                native_id=material_id,
                properties=properties,
                structure=structure,
            )
