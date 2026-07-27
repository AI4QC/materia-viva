import pytest

from materials_api.formula import parse_formula


def test_parse_formula_extracts_canonical_elements_and_counts_atoms():
    info = parse_formula("Li2FePO4")

    assert info.elements == ("Fe", "Li", "O", "P")
    assert info.chemical_system == "Fe-Li-O-P"
    assert info.n_elements == 4
    assert info.n_atoms == 8


def test_parse_formula_supports_parenthesized_compositions():
    info = parse_formula("Ca3(PO4)2")

    assert info.elements == ("Ca", "O", "P")
    assert info.n_atoms == 13


@pytest.mark.parametrize("formula", ["", "not-a-formula", "Xx2O", "Li(-1)O"])
def test_parse_formula_rejects_invalid_input(formula):
    with pytest.raises(ValueError):
        parse_formula(formula)
