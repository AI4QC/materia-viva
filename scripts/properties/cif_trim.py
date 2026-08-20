#!/usr/bin/env python3
"""Drop non-structural payloads from a CIF before it is persisted.

COD publishes the as-measured CIF: a 33,486-file byte census found 60.0% of
all bytes in ``_shelx_*`` (whole SHELX ``.res``/``.hkl`` instrument files
embedded as ``;``-delimited text), 7.4% in ``_geom_*`` (bond/angle/torsion
tables that are pure functions of the coordinates) and 0.7% in
bibliography tags.  One 16.7 MB entry carried ~11 KB of actual structure.
The pool stores crystal structures, so this module removes those families
and keeps everything needed to rebuild the cell.

Design notes
------------

* The trimmer is a real CIF tokenizer, not a line filter: the SHELX payloads
  are ``;``-delimited multi-line text fields whose content routinely starts
  lines with ``_``, ``loop_`` or ``#``, so a line filter corrupts the file.
* Output is assembled from *slices of the input*, never re-serialised, so
  kept text is byte-identical to the source.  A CIF with none of the dropped
  families is returned unchanged (``trim_cif(x) is x``), which keeps every
  other source's pymatgen-written CIF untouched.
* Trimming is idempotent: ``trim_cif(trim_cif(x)) == trim_cif(x)``.
* Trimming is fingerprint-preserving.  Nothing removed here is read by
  pymatgen's ``CifParser`` or by ``materials_api.indexer._extract_cif_fields``
  (which only regexes ``_cell_length_*``/``_cell_angle_*``/``_cell_volume``).
  ``cif_trim_verify.py`` checks that over 1,100 random COD CIFs drawn from
  ten row groups: composition, site count, lattice and fractional
  coordinates all identical to 1e-6, and 320 primitive-reduced BAWL hashes
  identical, at 96.3% fewer bytes (240.4 KB -> 8.8 KB mean).
"""

from __future__ import annotations

TRIM_MARKER = "# MateriaViva: non-structural loops (_shelx/_geom/_publ/...) removed"

#: Tag families removed.  Instrument dumps, refinement bookkeeping,
#: bibliography, and quantities that are derived from the coordinates.
DROP_PREFIXES: tuple[str, ...] = (
    "_shelx",  # also _shelxl_version_number: SHELX .res/.hkl dumps + version
    "_geom",  # bond/angle/torsion/hbond tables, derived from coordinates
    "_publ",
    "_citation",
    "_journal",
    "_diffrn",
    "_refine",
    "_exptl",
    "_computing",
    "_audit",
    "_reflns",
    "_cell_measurement",
    "_atom_sites_solution",
    "_atom_site_aniso",  # anisotropic displacement parameters
)

#: Two more families, added after measuring what survived the list above.
#: Same character as ``_shelx_*`` -- raw instrument output and refinement
#: instructions -- and together the two largest remaining blocks of bytes
#: (``_refln_*`` 2.7% and ``_iucr_refine_instructions_details`` 1.4% of all
#: sampled COD bytes; dropping them takes the sample from 92.3% to 96.3%
#: smaller).  Note ``_refln_*`` (singular) is the measured reflection table,
#: a CIF-loop spelling of the ``.hkl`` file, not ``_reflns_*`` summary stats.
#: Delete this tuple to fall back to exactly the families listed above.
EXTRA_DROP_PREFIXES: tuple[str, ...] = (
    "_refln",  # subsumes _reflns_*
    "_iucr_refine",  # _iucr_refine_instructions_details: embedded SHELX .ins
)

_DROP: tuple[str, ...] = DROP_PREFIXES + EXTRA_DROP_PREFIXES

#: Structurally load-bearing families.  Only consulted to out-rank a shorter
#: drop prefix; unlisted tags are kept by default, so this is a guard rail,
#: not a whitelist.
KEEP_PREFIXES: tuple[str, ...] = (
    "_cell_",
    "_symmetry",
    "_space_group",
    "_atom_site",
    "_atom_type",
    "_chemical_formula",
    "_chemical_name",
    "_cod_database_code",
    "_cod_",
    "_database_code",
    "_[local]_cod",
)

_WHITESPACE = " \t\r\n\f\v"

_TAG = "tag"
_VALUE = "value"
_LOOP = "loop"
_BLOCK = "block"


def _longest_prefix(tag: str, prefixes: tuple[str, ...]) -> int:
    best = 0
    for prefix in prefixes:
        if len(prefix) > best and tag.startswith(prefix):
            best = len(prefix)
    return best


def is_dropped_tag(tag: str) -> bool:
    """True when ``tag`` belongs to a removed family (longest prefix wins)."""

    tag = tag.lower()
    return _longest_prefix(tag, _DROP) > _longest_prefix(tag, KEEP_PREFIXES)


def _field_end(text: str, start: int) -> int:
    """End of a ``;``-delimited text field opened at ``start`` (column 0).

    Terminates on the next ``;`` that itself sits in column 0, matching
    pymatgen's ``line.startswith(";")`` rule.
    """

    cursor = start + 1
    size = len(text)
    while True:
        close = text.find(";", cursor)
        if close < 0:
            return size
        if text[close - 1] in "\n\r":
            return close + 1
        cursor = close + 1


def _tokenize(text: str) -> list[tuple[str, int, int, str]]:
    """Return ``(kind, start, end, tag_or_empty)`` for every CIF token.

    Handles ``;``-delimited text fields (only a ``;`` in column 0 opens or
    closes one), ``'``/``"`` quoting with the CIF 1.1 rule that a closing
    quote must be followed by whitespace (so ``'O'Brien'`` stays one token),
    and ``#`` comments outside of values.
    """

    size = len(text)
    tokens: list[tuple[str, int, int, str]] = []
    index = 0
    line_start = True
    while index < size:
        char = text[index]
        if char in _WHITESPACE:
            line_start = char in "\n\r"
            index += 1
            continue
        if char == "#":
            newline = text.find("\n", index)
            index = size if newline < 0 else newline
            line_start = False
            continue
        if char == ";" and line_start:
            end = _field_end(text, index)
            tokens.append((_VALUE, index, end, ""))
            index = end
            line_start = False
            continue
        if char in "'\"":
            # A quoted value never spans a line break, so an unterminated
            # quote can only ever swallow the rest of its own line.
            newline = text.find("\n", index)
            limit = size if newline < 0 else newline
            cursor = index + 1
            end = limit
            while cursor < limit:
                close = text.find(char, cursor, limit)
                if close < 0:
                    break
                if close + 1 >= size or text[close + 1] in _WHITESPACE:
                    end = close + 1
                    break
                cursor = close + 1
            tokens.append((_VALUE, index, end, ""))
            index = end
            line_start = False
            continue
        cursor = index
        while cursor < size and text[cursor] not in _WHITESPACE:
            cursor += 1
        word = text[index:cursor]
        lowered = word.lower()
        if word.startswith("_"):
            kind, tag = _TAG, lowered
        elif lowered == "loop_":
            kind, tag = _LOOP, ""
        elif (
            lowered.startswith("data_")
            or lowered.startswith("save_")
            or lowered in {"global_", "stop_"}
        ):
            kind, tag = _BLOCK, ""
        else:
            kind, tag = _VALUE, ""
        tokens.append((kind, index, cursor, tag))
        index = cursor
        line_start = False
    return tokens


def _units(text: str) -> list[tuple[int, int, bool, str]]:
    """Group tokens into ``(start, end, keep, first_tag)`` CIF items.

    An item is a block header, a ``tag value`` pair, or a whole ``loop_``
    (header tags plus every row).  A loop is dropped only when *all* of its
    declared tags are in a dropped family, so a mixed loop survives intact.
    """

    tokens = _tokenize(text)
    units: list[tuple[int, int, bool, str]] = []
    index = 0
    total = len(tokens)
    while index < total:
        kind, start, end, tag = tokens[index]
        if kind == _BLOCK:
            units.append((start, end, True, ""))
            index += 1
        elif kind == _TAG:
            keep = not is_dropped_tag(tag)
            index += 1
            if index < total and tokens[index][0] == _VALUE:
                end = tokens[index][2]
                index += 1
            units.append((start, end, keep, tag))
        elif kind == _LOOP:
            index += 1
            tags: list[str] = []
            while index < total and tokens[index][0] == _TAG:
                tags.append(tokens[index][3])
                end = tokens[index][2]
                index += 1
            while index < total and tokens[index][0] == _VALUE:
                end = tokens[index][2]
                index += 1
            keep = not (tags and all(is_dropped_tag(name) for name in tags))
            units.append((start, end, keep, tags[0] if tags else ""))
        else:  # stray value: malformed input, never our call to discard
            units.append((start, end, True, ""))
            index += 1
    return units


def trim_cif(text: str) -> str:
    """Return ``text`` without its non-structural tags and loops.

    Byte-identical to the input when nothing matches a dropped family.
    """

    if not text:
        return text
    units = _units(text)
    if all(unit[2] for unit in units):
        return text
    parts: list[str] = [TRIM_MARKER, "\n"]
    cursor = 0
    previous_dropped = False
    for start, end, keep, _tag in units:
        if keep:
            # A dropped neighbour must never pull a kept item off column 0:
            # ";" only opens a text field there.
            if previous_dropped and cursor and "\n" not in text[cursor:start]:
                parts.append("\n")
            parts.append(text[cursor:end])
        previous_dropped = not keep
        cursor = end
    parts.append(text[cursor:])
    trimmed = "".join(parts)
    if not trimmed.endswith("\n"):
        trimmed += "\n"
    return trimmed


def dropped_bytes(text: str) -> dict[str, int]:
    """Bytes removed per dropped tag family; for reporting and verification."""

    census: dict[str, int] = {}
    cursor = 0
    for _start, end, keep, tag in _units(text):
        if not keep:
            census[tag] = census.get(tag, 0) + (end - cursor)
        cursor = end
    return census


if __name__ == "__main__":  # pragma: no cover - manual spot check
    import sys

    sys.stdout.write(trim_cif(sys.stdin.read()))
