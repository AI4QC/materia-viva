"""MC2D: Materials Cloud two-dimensional crystals database.

``structure_2d.json`` lists 3,078 monolayers exfoliated from bulk parents;
the CIF files live in ``optimized_2d_structures.zip`` (member
``optimized_2d_structures/optimized_structures_new/<uuid>.cif``) with the
as-extracted CIF as fallback. CIF text is passed through verbatim. Some
uuids only ship .xsf files — those records go out without a structure.

The recorded 3D parents (ICSD/COD/MP ids) are *bulk* structures, not the
monolayer, so no match_ids are emitted; the monolayer itself is a new
2D structure (always_hash=False, plain fingerprint path).

``space_group`` is written either as "P-6m2 (187)" or as the bare symbol; the
1,201 bare ones go through the shared symbol->number lookup, which resolves
every distinct symbol in the file and agrees with the parenthesised number on
all 1,549 records that carry both. 328 records name no space group at all.

Interlayer binding energies (`binding_energy_per_substructure_per_unit_area`)
carry no units field in the JSON; magnitudes (0.0002..0.22, with the MC2D
paper's exfoliability thresholds appearing at 0.03 and 0.12) match the
paper's 30 / 120 meV/Å² cutoffs, i.e. the stored values are eV/Å².
"""

from __future__ import annotations

import json
import re
import zipfile
from typing import Iterator

from scripts.properties.adapters._util import (
    safe_float,
    safe_text,
    spacegroup_number_from_symbol,
)
from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_SPG_RE = re.compile(r"\((\d+)\)\s*$")


class Mc2dAdapter(SourceAdapter):
    source_key = "mc2d"
    always_hash = False

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        with open(self.root / "structure_2d.json", encoding="utf-8") as handle:
            records = json.load(handle)

        with zipfile.ZipFile(
            self.root / "optimized_2d_structures.zip"
        ) as optimized, zipfile.ZipFile(
            self.root / "as_extracted_2d_structures.zip"
        ) as extracted:
            opt_members = {
                name.rsplit("/", 1)[-1][:-4]: name
                for name in optimized.namelist()
                if name.endswith(".cif")
            }
            ext_members = {
                name.rsplit("/", 1)[-1][:-4]: name
                for name in extracted.namelist()
                if name.endswith(".cif")
            }
            for count, row in enumerate(records):
                if limit is not None and count >= limit:
                    return
                yield self._build(
                    row, optimized, opt_members, extracted, ext_members
                )

    def _build(self, row, optimized, opt_members, extracted, ext_members):
        opt_uuid = safe_text(row.get("optimized_2D_structure_uuid"))
        ext_uuid = safe_text(row.get("as_extracted_2D_structure_uuid"))
        formula = (
            safe_text(row.get("formula"))
            or safe_text(row.get("initial_3D_formula"))
            or "unknown"
        )
        native_id = f"{formula}:{opt_uuid or ext_uuid}"

        structure = None
        if opt_uuid and opt_uuid in opt_members:
            structure = optimized.read(opt_members[opt_uuid]).decode("utf-8")
        elif ext_uuid and ext_uuid in ext_members:
            structure = extracted.read(ext_members[ext_uuid]).decode("utf-8")

        properties = [PropertyValue("dimensionality", "2D", None, "PBE (MC2D)")]
        gap_entry = row.get("band_gap")
        if isinstance(gap_entry, dict):
            gap = safe_float(gap_entry.get("value"))
            if gap is not None:
                properties.append(
                    PropertyValue("band_gap", gap, "eV", "PBE (MC2D)")
                )
        for key, method in (
            ("binding_energy_per_substructure_per_unit_area_df2", "DF2-C09"),
            ("binding_energy_per_substructure_per_unit_area_rvv10", "rVV10"),
        ):
            entry = row.get(key)
            if isinstance(entry, dict):
                binding = safe_float(entry.get("value"))
                if binding is not None:
                    properties.append(
                        PropertyValue(
                            "interlayer_binding_energy", binding, "eV/Å²",
                            method,
                        )
                    )
        spacegroup = safe_text(row.get("space_group"))
        if spacegroup:
            match = _SPG_RE.search(spacegroup)
            number = (
                int(match.group(1))
                if match
                else spacegroup_number_from_symbol(spacegroup)
            )
            if number is not None and 1 <= number <= 230:
                properties.append(
                    PropertyValue(
                        "spacegroup_number", number, None, "PBE (MC2D)"
                    )
                )

        return SourceRecord(
            native_id=native_id,
            properties=properties,
            structure=structure,
            match_ids=[],
        )
