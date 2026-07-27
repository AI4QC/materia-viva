"""Chemical-formula normalization shared by indexing and query validation."""

from __future__ import annotations

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
