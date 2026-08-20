"""Open-framework aluminophosphate (AlPO) database: 312 synthesized AlPOs.

One zip of per-material CIFs (verbatim passthrough) plus one xlsx whose
sheet1 carries the curated metadata. openpyxl is unavailable, so the sheet is
parsed by hand from xl/worksheets/sheet1.xml + xl/sharedStrings.xml; cells are
addressed by their explicit column letter (rows are sparse, so positional
alignment would be wrong). All entries are published synthesized materials
(experimental pool); Index_Code is the native id, no cross-database ids, and
always_hash so the structures are fingerprinted into the pool.

Staged sheet columns: IZA_Code, Dimension, Space-Group_Number, plus
Framework_Density (T atoms per 1000 Å³, the IZA convention: 6.9-20 across the
file), R_Factor (the published refinement residual, stored as a fraction -
2.2E-2, 7.8E-2 - so values above 0.5 are rejected as mis-scaled) and
Material_Name (the published name, e.g. "AlPO-CJ8") as chemical_name. The
per-site coordination-environment counters, coordination sequences, vertex
symbols, XRD peak/d lists and atomic coordinates are not scalar properties
and stay out.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

_DIMENSION_MAP = {"3": "3D", "2": "2D", "1": "1D", "0": "0D"}


def _cell_value(cell: ET.Element, shared: list[str]) -> str | None:
    value = cell.find(_NS + "v")
    if cell.get("t") == "s":
        return shared[int(value.text)] if value is not None else None
    if cell.get("t") == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(_NS + "t"))
    return value.text if value is not None else None


def _column_letter(cell: ET.Element) -> str:
    return "".join(ch for ch in (cell.get("r") or "") if ch.isalpha())


class OpenFrameworkAluminophosphateAdapter(SourceAdapter):
    source_key = "open-framework-aluminophosphate"
    always_hash = True
    properties_only = False

    def _sheet_rows(self) -> list[dict[str, str]]:
        """Parse sheet1 into per-row {header: value} dicts keyed by column."""

        with zipfile.ZipFile(self.root / "alpo-312-200219.xlsx") as book:
            shared_root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            shared = [
                "".join(t.text or "" for t in si.iter(_NS + "t"))
                for si in shared_root.findall(_NS + "si")
            ]
            sheet_root = ET.fromstring(book.read("xl/worksheets/sheet1.xml"))
        rows = sheet_root.find(_NS + "sheetData").findall(_NS + "row")
        header: dict[str, str] = {}
        for cell in rows[0].findall(_NS + "c"):
            name = _cell_value(cell, shared)
            if name:
                header[_column_letter(cell)] = name.strip()
        parsed = []
        for row in rows[1:]:
            entry: dict[str, str] = {}
            for cell in row.findall(_NS + "c"):
                column = _column_letter(cell)
                if column not in header:
                    continue
                value = _cell_value(cell, shared)
                if value is not None:
                    entry[header[column]] = value
            if entry.get("Index_Code"):
                parsed.append(entry)
        return parsed

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        cif_archive = zipfile.ZipFile(self.root / "alpo-cif.zip")
        cif_names = {
            name.rsplit("/", 1)[-1][: -len(".cif")]: name
            for name in cif_archive.namelist()
            if name.endswith(".cif")
        }
        for count, row in enumerate(self._sheet_rows()):
            if limit is not None and count >= limit:
                return
            index_code = row["Index_Code"].strip()
            properties = []
            iza = safe_text(row.get("IZA_Code"))
            if iza:
                properties.append(
                    PropertyValue(
                        "structure_prototype", iza, None,
                        "IZA framework assignment",
                    )
                )
            dimension = safe_text(row.get("Dimension"))
            if dimension in _DIMENSION_MAP:
                properties.append(
                    PropertyValue(
                        "dimensionality", _DIMENSION_MAP[dimension],
                        None, "experiment",
                    )
                )
            spacegroup = safe_float(row.get("Space-Group_Number"))
            if spacegroup and 1 <= spacegroup <= 230:
                properties.append(
                    PropertyValue(
                        "spacegroup_number", int(spacegroup), None, "experiment"
                    )
                )
            name = safe_text(row.get("Material_Name"))
            if name:
                properties.append(
                    PropertyValue("chemical_name", name, None, "experiment")
                )
            framework_density = safe_float(row.get("Framework_Density"))
            if framework_density is not None and 0 < framework_density < 100:
                properties.append(
                    PropertyValue(
                        "framework_density", framework_density, "T/1000 Å³",
                        "framework topology analysis",
                    )
                )
            r_factor = safe_float(row.get("R_Factor"))
            if r_factor is not None and 0 < r_factor <= 0.5:
                properties.append(
                    PropertyValue(
                        "r_factor", r_factor, None,
                        "experiment (published refinement residual)",
                    )
                )
            structure = None
            member = cif_names.get(index_code)
            if member is not None:
                structure = cif_archive.read(member).decode(
                    "utf-8", errors="replace"
                )
            yield SourceRecord(
                native_id=index_code,
                properties=properties,
                structure=structure,
                experimental=True,
            )
