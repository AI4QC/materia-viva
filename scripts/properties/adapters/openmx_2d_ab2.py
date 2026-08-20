"""OpenMX 2D-AB2: high-throughput structure map of AB2 monolayers.

2,214 relaxed CIFs in ``cif/`` named ``<A>1<B>2_<phase>.cif`` with phase in
{P, T, H} (2D AB2 prototypes), plus ``table4web.csv``, the 62x62 element grid
behind the web structure map, and ``manifest.jsonl`` from the download.
Everything is OpenMX DFT, none of it experimental, so every record is a
candidate-pool structure. CIF text is passed through verbatim; the files are
P1 supercells written by OpenMX Viewer, so the deposited CIF carries no useful
symmetry of its own and the space group has to come from the CSV.

table4web.csv layout
--------------------
No header; 29 fields per row, 3,844 rows = 62x62 (A index, B index, A symbol,
B symbol, then three phase slots). The three space-group slots are fields
(4,5), (6,7), (8,9) as (H-M symbol, ITA number); a slot reading ``X, 0`` means
no stable structure was found for that phase. Slot order is **P, T, H** in the
filename's phase letters.

That ordering was not documented upstream, so it was established empirically:
for all 3,844 rows x 3 slots (11,532 checks), "slot is not X" agrees with "the
matching ``cif/<A>1<B>2_<phase>.cif`` exists" with **zero** errors under
(P, T, H) and with 1,188-2,212 errors under each of the other five
permutations. The non-X slot counts (805 / 750 / 659) likewise equal the file
counts per phase exactly (P 805, T 750, H 659).

The table's own phase letters are offset from the filenames' (table H = file T,
table T = file P, table P = file H), which is why the slot order reads (P, T, H)
here but (T, H, P) in the table's vocabulary. That offset is what makes the
result look physically inverted at a glance -- e.g. O1Cr2 gets 187 (P-6m2, the
1H prototype) on its ``_T`` file and 164 (P-3m1, the 1T prototype) on its ``_P``
file. It is not inverted: the letters simply do not mean the same thing on both
sides. Two single-stable-phase rows pin this down with no counting at all --
Li1Cl2 has one stable phase, in slot 2, and exactly one file, ``_H``; Li1In2 has
one stable phase, in slot 1, and exactly one file, ``_T``.

Two traps in that CSV, both confirmed and both worked around here:

* The nine lattice fields (10..18, three groups of a / b / gamma) are
  cyclically rotated by one slot relative to the space-group fields: the cell
  of ``_P`` matches lattice group 2, ``_T`` matches group 0, ``_H`` matches
  group 1. Matching file cells against the table reproduces this for all 1,052
  files that match to 2 decimals, with zero cross-slot matches, and it
  correctly predicts that no single-phase row can ever match (its one lattice
  group always lands on a slot marked ``--``) -- which is exactly what is
  observed (0 of 574). The lattice fields are therefore not used at all.
* Field 22 (e.g. "HTX", "PTH", "PXX") is an energy ranking, not a per-slot
  phase label -- cross-tabulating it against the lattice-verified slots gives
  no correlation -- so it is ignored too.

56 of the 2,214 slots carry an out-of-range ITA number (231, 232 or 233) next
to a perfectly ordinary H-M symbol (Cmmm, P6/mmm, Pmmn, P6mm, P2/c, Cmme).
Those numbers are upstream corruption; the range guard drops them rather than
guessing, leaving 2,158 records with a space group.
"""

from __future__ import annotations

import csv
import os
import re
from typing import Iterator

from scripts.properties.base import PropertyValue, SourceAdapter, SourceRecord

_METHOD = "OpenMX DFT (2D AB2)"

#: filename phase letter -> space-group slot index in table4web.csv
_PHASE_SLOT = {"P": 0, "T": 1, "H": 2}

_RE_NAME = re.compile(r"^([A-Z][a-z]?)1([A-Z][a-z]?)2_([PTH])$")


class Openmx2dAb2Adapter(SourceAdapter):
    source_key = "openmx-2d-ab2"
    always_hash = False
    properties_only = False

    def _space_groups(self) -> dict[tuple[str, str], list[int | None]]:
        """(A, B) -> ITA number per phase slot, None where absent/invalid."""

        table: dict[tuple[str, str], list[int | None]] = {}
        with open(self.root / "table4web.csv", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if len(row) < 10:
                    continue
                slots: list[int | None] = []
                for slot in range(3):
                    symbol = row[4 + 2 * slot].strip()
                    raw = row[5 + 2 * slot].strip()
                    if symbol == "X" or not raw.isdigit():
                        slots.append(None)
                        continue
                    number = int(raw)
                    slots.append(number if 1 <= number <= 230 else None)
                table[(row[2].strip(), row[3].strip())] = slots
        return table

    def iter_records(self, limit: int | None = None) -> Iterator[SourceRecord]:
        table = self._space_groups()
        cif_dir = self.root / "cif"
        count = 0
        for name in sorted(os.listdir(cif_dir)):
            if not name.endswith(".cif"):
                continue
            matched = _RE_NAME.match(name[: -len(".cif")])
            if not matched:
                continue
            if limit is not None and count >= limit:
                return
            element_a, element_b, phase = matched.groups()
            properties = [
                PropertyValue("dimensionality", "2D", None, _METHOD),
            ]
            slots = table.get((element_a, element_b))
            if slots is not None:
                number = slots[_PHASE_SLOT[phase]]
                if number is not None:
                    properties.append(
                        PropertyValue("spacegroup_number", number, None, _METHOD)
                    )
            cif_text = (cif_dir / name).read_text(encoding="utf-8", errors="replace")
            count += 1
            yield SourceRecord(
                native_id=f"openmx2d-{element_a}1{element_b}2-{phase}",
                properties=properties,
                structure=cif_text,
                experimental=False,
            )
