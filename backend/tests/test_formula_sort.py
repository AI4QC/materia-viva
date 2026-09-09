import re

import pytest

from materials_api.formula import sort_key


def test_the_pair_that_started_this():
    """Plain text order put Al12P12O48 first: '2' sorts below 'A'."""
    assert sorted(["Al12P12O48", "Al1As1"]) == ["Al12P12O48", "Al1As1"]
    assert sorted(["Al12P12O48", "Al1As1"], key=sort_key) == ["Al1As1", "Al12P12O48"]


@pytest.mark.parametrize("pair", [
    ("B2N2", "B24O36"),
    ("Ba1Al1Si1H1", "Ba10Re6O32"),
    ("Cd1As2O6", "Cd12As4Cl12"),
])
def test_a_narrow_count_sorts_before_a_wide_one(pair):
    first, second = pair
    assert sort_key(first) < sort_key(second)


def test_the_ordering_within_one_element_is_numeric():
    formulas = ["O100", "O2", "O10", "O1"]
    assert sorted(formulas, key=sort_key) == ["O1", "O2", "O10", "O100"]


def test_an_implicit_count_is_the_same_as_an_explicit_one():
    # the index spells counts out, but a key must not depend on that
    assert sort_key("CdS") == sort_key("Cd1S1")


def test_a_fractional_occupancy_keeps_its_place():
    assert sort_key("Fe0.5Ni0.5") < sort_key("Fe1Ni1")
    assert sort_key("Fe0.5") < sort_key("Fe0.9")


def test_anything_unreadable_comes_back_unchanged_rather_than_raising():
    # one odd row must not be able to stop an index build
    for odd in ["", "   ", "not a formula", "123", "Al-2"]:
        assert sort_key(odd) == odd.strip()


def test_the_key_never_loses_an_element():
    for formula in ["Al12P12O48", "Cd1S1", "Sr12P24O100", "Fe0.5Ni0.5"]:
        assert re.findall(r"[A-Z][a-z]?", formula) == re.findall(r"[A-Z][a-z]?", sort_key(formula))


def test_the_slice_orders_the_way_a_chemist_reads_it():
    """Fifteen adjacent pairs in the development slice were misordered."""
    import sqlite3
    from pathlib import Path

    index = Path(__file__).resolve().parents[2] / "data" / "slice" / "materials.sqlite"
    if not index.is_file():
        pytest.skip("development slice not present")

    formulas = sorted({row[0] for row in sqlite3.connect(index).execute("SELECT formula FROM materials")})
    by_key = sorted(formulas, key=sort_key)

    def chemical(formula):
        return [(el, float(n)) for el, n in re.findall(r"([A-Z][a-z]?)(\d+(?:\.\d+)?)", formula)]

    wrong = [(a, b) for a, b in zip(by_key, by_key[1:]) if chemical(a) > chemical(b)]
    assert wrong == [], f"{len(wrong)} pairs still out of order"
