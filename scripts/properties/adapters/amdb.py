"""AMDB: the Anyterial Altermagnets Database (https://altermagnets.anyterial.se/).

Despite the acronym this is *not* a magnetic-anisotropy database: AMDB is a
high-throughput **altermagnetism** screen run over MAGNDATA magnetic structures.
Each of the 180 entries is a magnetic structure that the screen classified as
altermagnetic (every detail page carries an "AM" badge; two entries are also
flagged "FiM"), annotated with its spin-splitting metrics and the Kohn-Sham gap
of the screening calculation.

The acquisition is a mirror of the rendered site: one HTML detail page per
entry under ``records/`` plus the ``search.html`` listing. No structures are
published in a reusable form (the pages embed only base64 band-structure
figures), so this source is properties_only with ``structure=None``; the entry
*is* the referenced ICSD structure, hence ``always_hash=False``.

Attachment is by ICSD number only - the Identity block's "ICSD IDs" <dd>.
105 of the 180 pages carry at least one numeric code (111 distinct; 3 pages
list 2 and 2 pages list 3); the other 75 render the literal "n/a" and yield
``match_ids=[]``, so the properties_only pipeline drops them. That is expected.

Parsed fields (all from ``<div><dt>label</dt><dd>value</dd></div>`` pairs
inside the detail article):

* ``ICSD IDs``                              -> match_ids
* ``KS Gap``            "0.764 eV"          -> band_gap ("n/a eV" = missing)
* ``KS Gap Type``       Metallic /
                        Semiconducting /
                        KS gap unavailable  -> is_metal (third value skipped)
* ``$\\Delta E^{max}_{split}$``  "1.872 eV" -> altermagnetic_splitting_max
* ``$\\Delta E^{avg}_{split}$``  "0.763 eV" -> altermagnetic_splitting_avg
* ``FΔ``                    "34.4%"    -> altermagnetic_split_fraction
* every record additionally gets magnetic_ordering = "altermagnetic"

Skipped: Elements / Space group / Parent space group(s) / MAGNDATA IDs /
References (identity, not properties), Min abundance (a crustal-abundance
scarcity proxy of the elements, not a material property), and the BNS/Laue
symmetry block present on 15 pages.

The site never states the exchange-correlation functional, so the method tag
"PBE+U altermagnet screen (AMDB)" records the project's reading of the screen
rather than a value quoted by the source.
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterator

from scripts.properties.adapters._util import safe_float
from scripts.properties.base import (
    PropertyValue,
    SourceAdapter,
    SourceRecord,
    normalize_match_id,
)

_METHOD = "PBE+U altermagnet screen (AMDB)"

_ARTICLE = '<article class="material-detail">'
# the detail article is followed by a "Figures" section holding multi-hundred-kB
# base64 PNGs; cutting there keeps the dt/dd scan on a few kB of markup
_FIGURE_CUT = "data:image"

_ID_RE = re.compile(r'<strong class="material-id-value">(.*?)</strong>', re.S)
_PAIR_RE = re.compile(
    r"<div(?:\s[^>]*)?>\s*<dt>(.*?)</dt>\s*<dd>(.*?)</dd>\s*</div>", re.S
)
_TAG_RE = re.compile(r"<[^>]+>")

_MAX_SPLIT_LABEL = r"$\Delta E^{\mathrm{max}}_{\mathrm{split}}$"
_AVG_SPLIT_LABEL = r"$\Delta E^{\mathrm{avg}}_{\mathrm{split}}$"
_FRACTION_LABEL = "FΔ"


def _strip_tags(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _label(fragment: str) -> str:
    """<dt> text without the trailing info-dot tooltip span."""

    return _strip_tags(fragment.split("<span", 1)[0])


def _quantity(text: str | None, suffix: str) -> float | None:
    """'0.764 eV' -> 0.764; 'n/a eV' and anything unexpected -> None."""

    if not text:
        return None
    value = text.strip()
    if value.endswith(suffix):
        value = value[: -len(suffix)].strip()
    return safe_float(value)


class AmdbAdapter(SourceAdapter):
    source_key = "amdb"
    properties_only = True
    always_hash = False

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        count = 0
        for path in sorted((self.root / "records").glob("*.html")):
            record = self._parse(path)
            if record is None:
                continue
            if limit is not None and count >= limit:
                return
            count += 1
            yield record

    @staticmethod
    def _fields(path: Path) -> tuple[str | None, dict[str, str]]:
        text = path.read_text(encoding="utf-8")
        start = text.find(_ARTICLE)
        if start < 0:
            return None, {}
        end = text.find(_FIGURE_CUT, start)
        detail = text[start:] if end < 0 else text[start:end]
        native = _ID_RE.search(detail)
        fields: dict[str, str] = {}
        for label, value in _PAIR_RE.findall(detail):
            fields.setdefault(_label(label), _strip_tags(value))
        return (_strip_tags(native.group(1)) if native else None), fields

    def _parse(self, path: Path) -> SourceRecord | None:
        native_id, fields = self._fields(path)
        if not native_id:
            return None

        match_ids = []
        for code in (fields.get("ICSD IDs") or "").split(","):
            pair = normalize_match_id("icsd", code.strip())
            if pair and pair not in match_ids:
                match_ids.append(pair)

        properties = [
            PropertyValue("magnetic_ordering", "altermagnetic", None, _METHOD)
        ]

        gap = _quantity(fields.get("KS Gap"), "eV")
        if gap is not None and gap >= 0:
            properties.append(PropertyValue("band_gap", gap, "eV", _METHOD))

        gap_type = (fields.get("KS Gap Type") or "").strip().lower()
        if gap_type == "metallic":
            properties.append(PropertyValue("is_metal", True, None, _METHOD))
        elif gap_type == "semiconducting":
            properties.append(PropertyValue("is_metal", False, None, _METHOD))

        for label, name in (
            (_MAX_SPLIT_LABEL, "altermagnetic_splitting_max"),
            (_AVG_SPLIT_LABEL, "altermagnetic_splitting_avg"),
        ):
            value = _quantity(fields.get(label), "eV")
            if value is not None:
                properties.append(PropertyValue(name, value, "eV", _METHOD))

        fraction = _quantity(fields.get(_FRACTION_LABEL), "%")
        if fraction is not None and 0 <= fraction <= 100:
            properties.append(
                PropertyValue(
                    "altermagnetic_split_fraction", fraction, "%", _METHOD
                )
            )

        return SourceRecord(
            native_id=native_id,
            properties=properties,
            structure=None,
            match_ids=match_ids,
        )
