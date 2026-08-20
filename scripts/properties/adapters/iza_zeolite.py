"""IZA-SC: the 268 approved zeolite framework types.

One CIF per framework in ``cif/framework_<NNN>.cif``; the three-letter IZA code
is the data block name, which is also the only place it appears, so the code is
read from ``data_<CODE>``. Codes include the interrupted-framework ('-HOS',
'-IFU', '-IRY', ...) and the '*-SSO' spellings verbatim. Native id is
``iza:<CODE>``. Nothing in the pool references these ids, so no match_ids.

Not experimental
----------------
IZA states in every file header that "the atom coordinates and the cell
parameters were optimized with DLS76 assuming a pure SiO2 composition". These
are therefore idealised distance-least-squares geometries of a hypothetical
pure-silica end member, not refined coordinates from a diffraction experiment
on a real, as-synthesised (usually aluminosilicate, usually with template and
extra-framework cations) material. The framework *topologies* are experimental
facts; the deposited *structures* are models. Records are consequently emitted
with ``experimental=False`` so they join the candidate pool rather than
claiming to be measured structures.

Why the CIF text is not passed through
--------------------------------------
These files declare the full space group and list only the asymmetric unit, so
the symmetry operators have to be applied to build the cell -- and pymatgen's
default ``site_tolerance`` (1e-4 A) is too tight to merge the images that
symmetry generates on top of atoms sitting on special positions. At the default
tolerance 20 of the 268 frameworks come out with pairs of atoms 0.001-0.005 A
apart, silently inflating the cell: CHA parses as Si36O96 (132 sites) instead
of Si36O72 (108 sites), LTN as Si768O1584 instead of Si768O1536, LOS as
Si24O58 instead of Si24O48, and so on. Judged by SiO2 stoichiometry the damage
touches 38 of 268 files at the default tolerance.

Parsing with ``site_tolerance=1e-3`` fixes it: all 268 files parse, no
structure is left with an interatomic distance below 0.8 A, and the only site
counts that change are those same 20 broken ones. ``occupancy_tolerance`` is
left at its default -- every file is fully ordered and none needed it. The
parsed Structure is yielded directly, so the loader re-serialises a clean P1
cell rather than re-running the broken expansion.

20 frameworks still have Si:O != 1:2 after the fix (CHI, CLO, EWT, -HOS, IFT,
-IFU, ION, -IRT, -IRY, -ITV, LIT, PAR, RON, *-SSO, SVR, -SYT, WEN, IVY, -ERS,
-JSI). That is real chemistry -- interrupted frameworks carry terminal
oxygens -- not a parsing artefact, and it is left alone.

Properties: the framework code as ``structure_prototype``, and
``spacegroup_number`` from ``_symmetry_Int_Tables_number`` (265 files) or the
``_space_group_IT_number`` spelling used by IVY and KLW. UTL declares neither
and simply gets no space group.
"""

from __future__ import annotations

import os
import re
from typing import Iterator

from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_METHOD = "IZA Structure Commission"

#: loose enough to merge symmetry images on special positions, tight enough to
#: leave every genuinely distinct site alone (see module docstring)
_SITE_TOLERANCE = 1e-3

_RE_CODE = re.compile(r"^data_(\S+)", re.M)
_RE_SPACEGROUP = re.compile(
    r"^[ \t]*_(?:symmetry_Int_Tables_number|space_group_IT_number)[ \t]+(\d+)", re.M
)


class IzaZeoliteAdapter(SourceAdapter):
    source_key = "iza-zeolite"
    always_hash = False
    properties_only = False

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        from pymatgen.io.cif import CifParser

        cif_dir = self.root / "cif"
        count = 0
        for name in sorted(os.listdir(cif_dir)):
            if not name.endswith(".cif"):
                continue
            if limit is not None and count >= limit:
                return
            path = cif_dir / name
            text = path.read_text(encoding="utf-8", errors="replace")
            code_match = _RE_CODE.search(text)
            if not code_match:
                continue
            code = code_match.group(1)
            try:
                structures = CifParser(
                    str(path), site_tolerance=_SITE_TOLERANCE
                ).parse_structures(primitive=False)
            except Exception:
                continue
            if not structures:
                continue
            structure = structures[0]
            # The asymmetric-unit labels (T1, O1, ...) repeat once symmetry has
            # been applied, and CifWriter warns loudly about the duplicates on
            # every serialisation. Renumbering keeps the CIF spec-compliant and
            # the logs readable; nothing else about the structure changes.
            structure.relabel_sites()
            properties = [
                PropertyValue("structure_prototype", code, None, _METHOD),
            ]
            spacegroup_match = _RE_SPACEGROUP.search(text)
            if spacegroup_match:
                number = int(spacegroup_match.group(1))
                if 1 <= number <= 230:
                    properties.append(
                        PropertyValue("spacegroup_number", number, None, _METHOD)
                    )
            count += 1
            yield SourceRecord(
                native_id=f"iza:{code}",
                properties=properties,
                structure=structure,
                experimental=False,
            )
