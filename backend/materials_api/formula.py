"""Chemical-formula normalization shared by indexing and query validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import isclose

from pymatgen.core import Composition


@dataclass(frozen=True)
class FormulaInfo:
    formula: str
    elements: tuple[str, ...]
    chemical_system: str
    n_elements: int
    n_atoms: int | float


def parse_formula(formula: str) -> FormulaInfo:
    """Parse a formula and return stable search metadata.

    Elements are alphabetized to match Materials Project chemical-system
    notation. Integer atom totals stay integers so API output remains clean.
    """

    value = formula.strip() if isinstance(formula, str) else ""
    if not value:
        raise ValueError("formula must not be empty")
    try:
        composition = Composition(value, strict=True)
    except Exception as exc:
        raise ValueError(f"invalid chemical formula: {formula!r}") from exc
    if not composition or any(amount <= 0 for amount in composition.values()):
        raise ValueError(f"invalid chemical formula: {formula!r}")

    elements = tuple(sorted(element.symbol for element in composition.elements))
    total = float(composition.num_atoms)
    n_atoms: int | float = round(total) if isclose(total, round(total)) else total
    return FormulaInfo(
        formula=value,
        elements=elements,
        chemical_system="-".join(elements),
        n_elements=len(elements),
        n_atoms=n_atoms,
    )

#: Enough digits for any count a unit cell realistically carries; the largest in
#: the published index is three. Counts wider than this still sort correctly
#: among themselves, just not against narrower ones — an accepted bound rather
#: than an unbounded key.
_SORT_WIDTH = 6

_TERM = re.compile(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)?")


def sort_key(formula: str) -> str:
    """A formula rewritten so that sorting it as text sorts it as chemistry.

    Formulas are stored with every count spelled out, so plain text ordering put
    `Al12P12O48` before `Al1As1`: comparison reaches `'2'` against `'A'`, and a
    digit sorts below a letter. Zero-padding each count makes the two orders
    agree — `Al000012...` now follows `Al000001...`.

    Cheap and total on purpose. It runs over every row of a thirteen-million row
    index, and anything it cannot read is returned unchanged rather than raising,
    so one odd formula cannot stop a build.
    """
    value = (formula or "").strip()
    matched = list(_TERM.finditer(value))
    if not matched or "".join(m.group(0) for m in matched) != value:
        return value

    parts = []
    for element, count in ((m.group(1), m.group(2)) for m in matched):
        whole, _, fraction = (count or "1").partition(".")
        padded = whole.rjust(_SORT_WIDTH, "0")
        parts.append(element + padded + ("." + fraction if fraction else ""))
    return "".join(parts)
