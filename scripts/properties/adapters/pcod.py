"""PCOD: Predicted Crystallography Open Database (GRINSP snapshot, 2008-04-01).

A historical rsync mirror of the PCOD CIF tree: 110,230 files laid out as
``cif/<first-digit>/<pcod-id>.cif`` (the ``cif/`` directory also holds two
Windows helper binaries, a zip and the rsync log, all ignored). 110,121 of the
files are GRINSP (Le Bail) predictions; the remaining 109 are the Simperler et
al. hypothetical binodal zeolitic frameworks (Acta Cryst. B61 (2005) 263-279),
which carry no GRINSP payload at all and therefore no properties below. Nothing
here is experimental and the whole corpus joins the candidate pool. The
chemistry is mixed -- silicates, phosphates, borates, vanadates, aluminates --
so no SOURCE_FAMILY label is claimed; these are emphatically not all zeolites.

Guard on the 8,000,000 block
----------------------------
Native ids are ``pcod-<stem>``, which collides with two sources already in the
pool: deem-zeolites ships its hypothetical zeolites under ids like
``pcod-8029697``, and mofx-db's PCOD-syn subset draws from the same block. This
snapshot contains zero files whose stem starts with '8' (surveyed: 1:6,808
2:468 3:23,412 4:20,908 5:25,998 6:22,362 7:10,272 9:2, and an empty ``cif/8``
directory), but the guard is kept unconditionally so that a refreshed mirror
can never double-admit those ids.

Spacegroup: still skipped
-------------------------
110,115 of the 110,230 files write ``_symmetry_space_group_name_H-M "P 1"``
(2,642 of them spelled ``"P1"``) and list all sites explicitly. 107,469 of them
also carry an active ``_symmetry_Int_Tables_number``, and it is **1 in every
single one of them** (2,761 files omit the tag entirely). GRINSP's guess at the
real symmetry lives only in the free-text ``_publ_section_title`` ("Probable
space group: P 6/M M M") and in a *commented-out* trailer at the end::

    #_symmetry_space_group_name_H-M  P 6/M M M
    #_symmetry_Int_Tables_number  191

Those 107,469 commented values are not CIF data items -- they are a suggestion
the depositor deliberately disabled, and the deposited coordinates are the P1
expansion regardless. Mapping them onto ``spacegroup_number`` would assert a
symmetry the file itself declines to assert, so the property stays skipped and
nothing below starts emitting it.

The 115 files that are *not* P1 do assert a symmetry, and deposit only the
asymmetric unit: 107 of the Simperler entries, plus eight GRINSP files,
PCOD1300001 to PCOD1300008 ("P 21/m", "I 41/A", ...), which additionally spell
the operators out in a ``_symmetry_equiv_pos_as_xyz`` loop. None of the 115
carries an ``_symmetry_Int_Tables_number``, so reading them would mean
resolving H-M symbols rather than reading a tag; they are left to the pool's
own symmetry analysis along with everything else.

Properties: the two GRINSP scalars
----------------------------------
Read independently, so a file carrying only one of them still yields it.

``framework_density`` -- the commented last line of the trailer, T atoms per
1000 Å³ in the IZA convention the registry and deem-zeolites already use::

    #_framework_density   18.95

107,469 files carry it, spanning 5.09 to 37.75. This is the same quantity
deem-zeolites parses out of its own GULP trailer, so name and unit transfer
unchanged.

``structure_prediction_r_factor`` -- GRINSP's agreement factor, written into
the free-text ``_publ_section_title`` block, where it always ends the line::

    SiO2 - PCOD1000000 - EDI - R =  0.0044
    V2PO7          PCOD4000001 R =  0.0136

110,119 files carry it, spanning 0.0001 to 0.0500. The 107,469 files that also
have the coordination-sequence trailer repeat the value there, followed by the
probable space-group number ("# PCOD4000001 V2PO7  R =  0.0136  198"). The two
copies never disagree anywhere in the corpus, so anchoring on end-of-line reads
the title copy and still covers the 2,650 files that have no trailer at all.

Why not ``r_factor``
~~~~~~~~~~~~~~~~~~~~
registry.py documents ``r_factor`` as the crystallographic refinement residual
R1, and open-framework-aluminophosphate stages exactly that from published
refinements. GRINSP's R is a different quantity that merely shares a letter: it
is the cost function of the geometric restraint search, the disagreement
between the framework's realised distances and angles and the ideal target
values fed to the optimiser. No PCOD entry was ever measured, so nothing here
was refined against an observation.

Sharing the name would be unrecoverable rather than just imprecise. Both are
dimensionless, both improve downwards, and their ranges interleave (0.0001 to
0.0500 here against 0.022 to 0.078 for the AlPO refinements), so no numeric
filter could separate them afterwards. pcod would also contribute ~17.2k rows
against that source's <=312, leaving ~98% of ``r_factor`` meaning
"geometrically self-consistent guess" rather than "refined against data" -- a
method string cannot rescue a name whose dominant population contradicts its
own definition. A distinct name keeps ``r_factor`` honest; the loader registers
this one on the fly, and with no CANONICAL_PROPERTIES entry it defaults to
exactly what is wanted, a unitless numeric property.

Method strings
--------------
Base method is "GRINSP structure prediction", which can never be misread as a
measurement, and the R value spells out "geometric restraint residual" on top
of that. Both methods then name the PCOD entry the value came from, because
hash matching fans many frameworks onto one pool material: the worst case
absorbs 814 distinct pcod ids carrying 115 distinct R values and 530 distinct
framework densities. A constant method would leave those hundreds of rows
indistinguishable on (material, property).
"""

from __future__ import annotations

import os
import re
from typing import Iterator

from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

#: PCOD ids beginning with this digit belong to deem-zeolites / mofx-db PCOD-syn
_RESERVED_BLOCK = "8"

#: Prefix shared by both methods; the per-entry suffix is appended below.
_METHOD = "GRINSP structure prediction"

#: "restraint", never "refinement" -- see the docstring on why this value must
#: not be confusable with an experimental R1.
_R_METHOD = f"{_METHOD}, geometric restraint residual"

#: The ``_publ_section_title`` copy of the agreement factor. The comment
#: lookahead and the end-of-line anchor each independently exclude the
#: commented trailer copy, which is followed by the probable space-group
#: number; the lookahead tolerates indentation so it keeps meaning "not a
#: comment" if the mirror is ever reformatted.
#:
#: Every file in the snapshot is CRLF, and only ``read_text``'s universal
#: newline translation hides that here. ``\r`` is allowed before the anchor so
#: that reading the bytes directly -- as the tar-member adapters in this
#: package do -- cannot silently drop all 110,119 values instead of failing.
_RE_R_FACTOR = re.compile(
    r"^(?![ \t]*#).*\bR\s*=\s*([0-9]*\.?[0-9]+)[ \t\r]*$", re.M
)

#: Commented out like the whole trailer, so no CIF parser ever sees it.
#: ``[ \t]+`` rather than ``\s+`` keeps the value on the label's own line, and
#: the anchor refuses a partial parse: an exponent form has to be dropped, not
#: silently truncated to its mantissa, which would still pass the guard below.
_RE_FRAMEWORK_DENSITY = re.compile(
    r"^#_framework_density[ \t]+([0-9]*\.?[0-9]+)[ \t\r]*$", re.M
)


def _scalar(pattern: re.Pattern[str], text: str) -> float | None:
    """First capture of ``pattern`` as a float, or None when the line is absent.

    Both patterns capture at least one digit, so the conversion cannot fail.
    """

    match = pattern.search(text)
    return float(match.group(1)) if match is not None else None


class PcodAdapter(SourceAdapter):
    source_key = "pcod"
    always_hash = False
    properties_only = False

    def _properties(self, stem: str, cif_text: str) -> list[PropertyValue]:
        """Both trailer scalars, each optional and each guarded on its own."""

        properties: list[PropertyValue] = []
        density = _scalar(_RE_FRAMEWORK_DENSITY, cif_text)
        # bound matches open-framework-aluminophosphate's guard on the same
        # property; the observed corpus sits well inside it at 5.09 to 37.75
        if density is not None and 0 < density < 100:
            properties.append(
                PropertyValue(
                    "framework_density", density, "T/1000 Å³",
                    f"{_METHOD} (PCOD{stem})",
                )
            )
        r_factor = _scalar(_RE_R_FACTOR, cif_text)
        # stored as a fraction like the registry's r_factor, not per cent
        if r_factor is not None and 0 < r_factor <= 1:
            properties.append(
                PropertyValue(
                    "structure_prediction_r_factor", r_factor, None,
                    f"{_R_METHOD} (PCOD{stem})",
                )
            )
        return properties

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        cif_root = self.root / "cif"
        count = 0
        for bucket in sorted(
            entry for entry in os.listdir(cif_root)
            if (cif_root / entry).is_dir()
        ):
            bucket_dir = cif_root / bucket
            for name in sorted(os.listdir(bucket_dir)):
                if not name.endswith(".cif"):
                    continue
                stem = name[: -len(".cif")]
                if not stem or stem.startswith(_RESERVED_BLOCK):
                    # 8-block ids are owned by deem-zeolites / mofx-db PCOD-syn
                    continue
                if limit is not None and count >= limit:
                    return
                cif_text = (bucket_dir / name).read_text(
                    encoding="utf-8", errors="replace"
                )
                count += 1
                yield SourceRecord(
                    native_id=f"pcod-{stem}",
                    properties=self._properties(stem, cif_text),
                    structure=cif_text,
                    experimental=False,
                )
