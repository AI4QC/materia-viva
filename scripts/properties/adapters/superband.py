"""SuperBand: DFT band structures for SuperCon-curated superconductors.

Raw data is one HDF5 file (0724.hdf5) with 2,474 groups keyed by an integer
id. Each group carries attrs Tc / formula / SG_num / volume plus the crystal
structure (atoms symbols, cartesian positions, cell). The heavy per-group
band/DOS/Fermi-surface arrays are never read. The companion SuperBand-main
zip ships superband.csv whose header row is broken; columns are mapped by
position (id, formula, Tc, year, doi, cif-id, system, SG symbol, volume,
density, a, b, c, alpha, beta, gamma) to join the publication year on id.

Tc == 0 rows (1,111 of 2,474) are SuperCon's documented non-superconductors:
the record and its structure are kept (always_hash pool candidates) but no
``tc_superconducting`` value is emitted, because 0 K would read as a real
transition temperature once merged with other sources.

The csv also carries structure-less SuperCon Tc rows (mostly doped variants)
whose ``cif`` column points at the parent structure's group id. Rows absent
from the HDF5 whose parent pointer is a valid group id become properties-only
records (``csvrow-<id>``, structure=None) that id-match onto the parent's
pool material through the match map's ``superband`` source; the doped formula
is preserved in the method string. Rows without a valid parent pointer, or
without a positive Tc, are skipped.
"""

from __future__ import annotations

import csv
import io
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import safe_float, safe_text
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_CSV_MEMBER = "SuperBand-main/superband.csv"
_METHOD_MAX = 80
_CSV_METHOD_MAX = 60


class SuperbandAdapter(SourceAdapter):
    source_key = "superband"
    always_hash = True
    properties_only = False

    def _year_by_id(self) -> dict[str, str]:
        """id -> publication year from superband.csv (broken header: by position)."""

        years: dict[str, str] = {}
        archive = self.root / "SuperBand-main.zip"
        try:
            with zipfile.ZipFile(archive) as bundle:
                with bundle.open(_CSV_MEMBER) as handle:
                    text = io.TextIOWrapper(handle, encoding="utf-8", newline="")
                    reader = csv.reader(text)
                    next(reader, None)  # broken header row
                    for row in reader:
                        if len(row) < 4:
                            continue
                        native = safe_text(row[0])
                        year = safe_text(row[3])
                        if native and year and year.isdigit():
                            years[native] = year
        except (OSError, KeyError, zipfile.BadZipFile):
            return {}
        return years

    def _csv_rows(self) -> list[list[str]]:
        """Raw superband.csv rows (broken header: columns by position)."""

        rows: list[list[str]] = []
        archive = self.root / "SuperBand-main.zip"
        try:
            with zipfile.ZipFile(archive) as bundle:
                with bundle.open(_CSV_MEMBER) as handle:
                    text = io.TextIOWrapper(handle, encoding="utf-8", newline="")
                    reader = csv.reader(text)
                    next(reader, None)  # broken header row
                    for row in reader:
                        if len(row) < 6:
                            continue
                        rows.append(row)
        except (OSError, KeyError, zipfile.BadZipFile):
            return []
        return rows

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        import h5py
        from pymatgen.io.ase import AseAtomsAdaptor

        try:
            from ase import Atoms
        except ImportError:  # pragma: no cover
            Atoms = None

        years = self._year_by_id()
        count = 0
        group_ids: set[str] = set()
        with h5py.File(self.root / "0724.hdf5", "r") as bundle:
            for native_id in bundle:
                group_ids.add(str(native_id))
                if limit is not None and count >= limit:
                    return
                group = bundle[native_id]
                properties = []
                year = years.get(str(native_id))
                method = "SuperCon curated"
                if year:
                    method = f"SuperCon curated; reported {year}"[:_METHOD_MAX]
                tc = safe_float(group.attrs.get("Tc"))
                if tc is not None and tc > 0:
                    properties.append(
                        PropertyValue("tc_superconducting", tc, "K", method)
                    )
                spacegroup = safe_float(group.attrs.get("SG_num"))
                if spacegroup:
                    properties.append(
                        PropertyValue(
                            "spacegroup_number", int(spacegroup),
                            None, "SuperCon curated",
                        )
                    )
                structure = None
                if Atoms is not None:
                    try:
                        symbols = [
                            s.decode() if isinstance(s, bytes) else str(s)
                            for s in group["atoms"][()]
                        ]
                        atoms = Atoms(
                            symbols=symbols,
                            positions=group["position"][()],
                            cell=group["cell"][()],
                            pbc=True,
                        )
                        structure = AseAtomsAdaptor.get_structure(atoms)
                    except Exception:  # noqa: BLE001 - keep the property record
                        structure = None
                count += 1
                yield SourceRecord(
                    native_id=str(native_id),
                    properties=properties,
                    structure=structure,
                )

        # structure-less SuperCon Tc rows: csv entries absent from the HDF5
        # whose cif column names a parent group id (see module docstring)
        for row in self._csv_rows():
            if limit is not None and count >= limit:
                return
            native = safe_text(row[0])
            if not native or native in group_ids:
                continue
            parent = safe_text(row[5])
            if not parent or parent not in group_ids:
                continue
            tc = safe_float(row[2])
            if tc is None or tc <= 0:
                continue
            formula = safe_text(row[1]) or ""
            method = f"SuperCon curated; doped formula {formula}"[:_CSV_METHOD_MAX]
            count += 1
            yield SourceRecord(
                native_id=f"csvrow-{native}",
                properties=[
                    PropertyValue("tc_superconducting", tc, "K", method)
                ],
                structure=None,
                match_ids=[("superband", parent)],
            )
