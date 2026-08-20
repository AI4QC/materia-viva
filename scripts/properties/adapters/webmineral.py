"""Webmineral: mineral-species data sheets (https://webmineral.com/data/).

6,988 mirrored ``.shtml`` species pages. Webmineral publishes no atomic
coordinates, so this source is properties_only with ``structure=None``.

**These are SPECIES-level literature compilations, not measurements on the
matched crystal structure.** Webmineral's physical-property tables are keyed to
the mineral species and are compiled from Anthony, Bideaux, Bladh & Nichols,
*Handbook of Mineralogy* / Roberts, Campbell & Rapp, *Encyclopedia of Minerals*
(2nd ed., 1990) and the sources those works cite. A density or Mohs hardness
attached here therefore describes the species as a whole - a different specimen,
often a different locality and composition - and not the particular ICSD entry
the record matches. Values are ``experimental=True`` because they are measured
mineral data and their pool counterpart is an experimental ICSD structure.

Attachment is by ICSD number only. The Synonym block of a page may carry a bare
``ICSD <code>`` cell (rendered as ``</b></td><td>ICSD 15481</td>``); 2,174 of
the 6,988 pages do, always exactly one code per page. Pages without one yield
nothing at all - no formula matching, no fabricated link. Twelve cells carry a
qualifier after the code; four of those are ambiguous (``ICSD 24-615``,
``ICSD 32-101`` are PDF-style powder-file numbers, ``ICSD 75298/9`` and
``ICSD 22305/6`` name two entries) and are skipped, leaving 2,170 records.

Parsed fields (the pages are one flat ``<b>Label: </b></td><td>value</td>``
table per section):

* ``<title>Foo Mineral Data</title>`` -> mineral_name (present on 100% of
  ICSD-bearing pages)
* ``Density``  "3.21" or "3.31 - 3.57, Average = 3.44" -> density in g/cm3
  (the compilation's specific gravity; the average is taken for ranges).
  Present on 2,005 / 2,174 = 92.2% of ICSD-bearing pages, and every present
  value parses.
* ``Hardness`` "4 - Fluorite", "2-3 - Gypsum-Calcite", "7.5-8" -> mohs_hardness
  (range midpoint; the trailing reference-mineral gloss is dropped). Present on
  1,965 / 2,174 = 90.4%, and every present value parses.
* ``Optical Data`` -> refractive_index, in the four spellings the block uses:
  "Isotropic, n=1.55" (127 pages), "Uniaxial (-), e=1.586, w=1.589, ..."
  (412; the orientation average of a uniaxial indicatrix is (2w+e)/3),
  "Biaxial (+), a=..., b=..., g=..., ..." (1,128; average (a+b+g)/3, or the
  midpoint of a and g on the pages that omit b) and "NCalc= 1.9 - from
  Gladstone-Dale relationship" (130). Each spelling carries its own method
  string so the averaging convention travels with the value; components given
  as a range ("e=1.612-1.63") use the range midpoint. Values outside 1.0-4.5
  are dropped.

Deliberately skipped: Chemical Formula / Empirical Formula / Composition (used
for nothing - matching never touches formulas here), the pleochroism / RL /
X-ray / radioactivity blocks (instrument- and specimen-specific), the optical
block's birefringence and 2V (both strongly orientation- and specimen-
dependent in a species-level compilation), and "Chemical Name", which
duplicates the species name.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterator

from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_METHOD = "Webmineral compilation (species-level)"

# the ICSD code lives in its own table cell, directly after a label cell; a
# trailing '-<digits>' or '/<digits>' means a PDF number or a pair of entries
_ICSD_RE = re.compile(r"</b>\s*</td>\s*<td[^>]*>\s*ICSD\s+(\d+)\s*([^<]*)")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_FIELD_RE = re.compile(
    r"<b>\s*([^<]{1,60}?)\s*:\s*</b>\s*</td>\s*<td[^>]*>(.*?)</td>", re.S
)
_TAG_RE = re.compile(r"<[^>]+>")

_NUMBER = r"\d+(?:\.\d+)?"
_DENSITY_PLAIN_RE = re.compile(rf"^({_NUMBER})$")
_DENSITY_RANGE_RE = re.compile(
    rf"^{_NUMBER}\s*-\s*{_NUMBER}\s*,\s*Average\s*=\s*({_NUMBER})$", re.I
)
_HARDNESS_RANGE_RE = re.compile(rf"^({_NUMBER})\s*-\s*({_NUMBER})$")
_HARDNESS_ONE_RE = re.compile(rf"^({_NUMBER})$")

_DENSITY_MIN, _DENSITY_MAX = 0.5, 25.0
_HARDNESS_MIN, _HARDNESS_MAX = 1.0, 10.0
_INDEX_MIN, _INDEX_MAX = 1.0, 4.5

#: one refractive-index component, possibly given as a low-high range
_COMPONENT = rf"({_NUMBER})(?:\s*-\s*({_NUMBER}))?"
_NCALC_RE = re.compile(rf"NCalc\s*=\s*{_COMPONENT}", re.I)


def _component(raw: str, name: str) -> float | None:
    """'e=1.612-1.63' -> 1.621 (range midpoint); single values pass through."""

    match = re.search(rf"\b{name}\s*=\s*{_COMPONENT}", raw)
    if not match:
        return None
    low = float(match.group(1))
    high = match.group(2)
    return (low + float(high)) / 2 if high else low


def _refractive_index(raw: str | None) -> tuple[float, str] | None:
    """Optical Data block -> (mean index, averaging convention)."""

    if not raw:
        return None
    head = raw.split(",", 1)[0].strip().rstrip(".")
    if head.startswith("Isotropic"):
        value, note = _component(raw, "n"), "isotropic n"
    elif head.startswith("Uniaxial"):
        ordinary = _component(raw, "w")
        extraordinary = _component(raw, "e")
        if ordinary is None or extraordinary is None:
            return None
        value = (2 * ordinary + extraordinary) / 3
        note = "uniaxial mean (2w+e)/3"
    elif head.startswith("Biaxial"):
        alpha = _component(raw, "a")
        beta = _component(raw, "b")
        gamma = _component(raw, "g")
        if alpha is None or gamma is None:
            return None
        if beta is None:
            value, note = (alpha + gamma) / 2, "biaxial mean (a+g)/2"
        else:
            value, note = (alpha + beta + gamma) / 3, "biaxial mean (a+b+g)/3"
    else:
        match = _NCALC_RE.search(raw)
        if not match:
            return None
        low = float(match.group(1))
        high = match.group(2)
        value = (low + float(high)) / 2 if high else low
        note = "Gladstone-Dale N_calc"
    if value is None or not _INDEX_MIN <= value <= _INDEX_MAX:
        return None
    return value, note


def _strip_tags(fragment: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", fragment).replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", text).strip()


def _slug(path: Path) -> str:
    """Filename without .shtml; apostrophe-quoted names are unwrapped."""

    return path.stem.strip().strip("'")


def _density(raw: str | None) -> float | None:
    if not raw:
        return None
    match = _DENSITY_PLAIN_RE.match(raw) or _DENSITY_RANGE_RE.match(raw)
    if not match:
        return None
    value = float(match.group(1))
    return value if _DENSITY_MIN <= value <= _DENSITY_MAX else None


def _mohs(raw: str | None) -> float | None:
    """'2-3 - Gypsum-Calcite' -> 2.5; '4 - Fluorite' -> 4.0; '7.5-8' -> 7.75."""

    if not raw:
        return None
    # drop the reference-mineral gloss, which is always ' - <names>'
    head = re.split(r"\s+-\s+", raw, maxsplit=1)[0].strip()
    match = _HARDNESS_RANGE_RE.match(head)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        value = (low + high) / 2
    else:
        match = _HARDNESS_ONE_RE.match(head)
        if not match:
            return None
        value = float(match.group(1))
    return value if _HARDNESS_MIN <= value <= _HARDNESS_MAX else None


class WebmineralAdapter(SourceAdapter):
    source_key = "webmineral"
    properties_only = True

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        for path in sorted((self.root / "pages").glob("*.shtml")):
            record = self._parse(path)
            if record is None:
                continue
            if limit is not None and count >= limit:
                return
            count += 1
            yield record

    def _parse(self, path: Path) -> SourceRecord | None:
        # the mirror is served as iso-8859-1 and a couple of filenames carry
        # bytes that are not valid utf-8
        text = path.read_text(encoding="latin-1")

        icsd = _ICSD_RE.search(text)
        if not icsd:
            return None
        trailer = icsd.group(2).lstrip()
        if trailer[:1] in {"-", "/"}:
            # 'ICSD 24-615' (a PDF number) or 'ICSD 75298/9' (two entries)
            return None
        pair = normalize_match_id("icsd", icsd.group(1))
        if not pair:
            return None

        fields: dict[str, str] = {}
        for label, value in _FIELD_RE.findall(text):
            fields.setdefault(_strip_tags(label), _strip_tags(value))

        properties = []
        title = _TITLE_RE.search(text)
        name = _strip_tags(title.group(1)) if title else ""
        if name.endswith("Mineral Data"):
            name = name[: -len("Mineral Data")].strip()
        if name:
            properties.append(
                PropertyValue("mineral_name", name, None, _METHOD)
            )

        density = _density(fields.get("Density"))
        if density is not None:
            properties.append(
                PropertyValue("density", density, "g/cm³", _METHOD)
            )

        mohs = _mohs(fields.get("Hardness"))
        if mohs is not None:
            properties.append(
                PropertyValue("mohs_hardness", mohs, None, _METHOD)
            )

        optical = _refractive_index(fields.get("Optical Data"))
        if optical is not None:
            index, note = optical
            properties.append(
                PropertyValue(
                    "refractive_index", index, None, f"{_METHOD}; {note}"
                )
            )

        if not properties:
            return None
        return SourceRecord(
            native_id=f"webmineral-{_slug(path)}",
            properties=properties,
            structure=None,
            match_ids=[pair],
            experimental=True,
        )
