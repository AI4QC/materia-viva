import json
from pathlib import Path

import pytest

from scripts.properties.base import PropertyValue, SourceRecord
from scripts.properties.golden import (
    GOLDEN_ROOT,
    adapter_class,
    check,
    diff,
    golden_dir,
    serialise,
    unit_violations,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted(p.name for p in GOLDEN_ROOT.iterdir() if p.is_dir()) if GOLDEN_ROOT.is_dir() else []


@pytest.mark.parametrize("source_key", SOURCES)
def test_every_golden_sample_still_matches_its_adapter(source_key):
    directory = golden_dir(source_key)
    assert (directory / "expected.json").exists(), f"{source_key} has a fixture but no expected.json"
    problems = check(source_key)
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize("source_key", SOURCES)
def test_every_golden_sample_declares_who_wrote_the_expectation(source_key):
    # a zero diff means nothing unless it is known whether the expectation was
    # recorded from the adapter or written independently of it
    golden = json.loads((golden_dir(source_key) / "expected.json").read_text(encoding="utf-8"))
    assert golden["authored_by"] in {"recorded-from-adapter", "independent"}
    assert golden["source_key"] == source_key


def test_the_obelix_sample_covers_the_branches_its_readme_claims():
    # 8 rows in, 5 records out: no-property, blank-id and zero-conductivity rows
    # are each dropped for a different reason
    golden = json.loads((golden_dir("obelix") / "expected.json").read_text(encoding="utf-8"))
    assert [r["native_id"] for r in golden["records"]] == ["A1", "A2", "A3", "A7", "A8"]
    by_id = {r["native_id"]: r for r in golden["records"]}
    # both provenance patterns recover an ICSD match where the id column is empty
    assert by_id["A2"]["match_ids"] == [["icsd", "icsd-155951"]]
    assert by_id["A3"]["match_ids"] == [["icsd", "icsd-111757"]]
    # a non-integer ICSD id yields none
    assert by_id["A7"]["match_ids"] == []


def test_adapter_class_finds_the_one_adapter_for_a_source():
    assert adapter_class("obelix").source_key == "obelix"
    with pytest.raises(ModuleNotFoundError):
        adapter_class("not-a-source")


def test_units_are_checked_against_the_registry():
    good = [{"native_id": "a", "properties": [
        {"name": "ionic_conductivity", "value": 1.0, "unit": "S/cm", "method": "x"}]}]
    assert unit_violations(good) == []
    # the failure a golden sample exists to catch: right number, wrong unit
    bad = [{"native_id": "a", "properties": [
        {"name": "ionic_conductivity", "value": 1.0, "unit": "S/m", "method": "x"}]}]
    assert len(unit_violations(bad)) == 1
    assert "registry says 'S/cm'" in unit_violations(bad)[0]
    # a source-specific name the registry does not fix is left alone
    novel = [{"native_id": "a", "properties": [
        {"name": "some_source_specific_thing", "value": 1.0, "unit": "furlongs", "method": None}]}]
    assert unit_violations(novel) == []


def test_diff_names_the_field_that_moved():
    want = [{"native_id": "a", "experimental": False, "match_ids": [], "structure": None,
             "properties": [{"name": "band_gap", "value": 1.0, "unit": "eV", "method": "PBE"}]}]
    got = [{"native_id": "a", "experimental": False, "match_ids": [], "structure": None,
            "properties": [{"name": "band_gap", "value": 2.0, "unit": "eV", "method": "PBE"}]}]
    lines = diff(want, got)
    assert len(lines) == 1 and "properties differ" in lines[0]
    assert diff(want, want) == []
    assert "record count" in diff(want, [])[0]


def test_serialise_is_order_independent_and_digests_the_structure():
    first = SourceRecord(
        native_id="a",
        properties=[PropertyValue("band_gap", 1.0, "eV", "PBE"),
                    PropertyValue("is_metal", False, None, "PBE")],
        structure="data_x\n_cell_length_a 1\n",
    )
    second = SourceRecord(
        native_id="a",
        properties=list(reversed(first.properties)),
        structure="data_x\n_cell_length_a 1\n",
    )
    assert serialise(first) == serialise(second)
    assert serialise(first)["structure"].startswith("sha256:")
    # a different structure must not share the digest
    other = SourceRecord(native_id="a", structure="data_y\n")
    assert serialise(other)["structure"] != serialise(first)["structure"]


# Units an adapter emits for a canonical property but which disagree with the
# registry. Each is a real disagreement awaiting a decision, not a false alarm:
# the first five put the magnetisation normalisation in the unit where the
# registry keeps it neutral and expects it in the method string, and mc2d looks
# like a factor-of-1000 error — the registry declares meV/Å² and the adapter
# passes the value through labelled eV/Å², with no conversion of the kind
# 2dmatpedia does for exfoliation energy.
KNOWN_UNIT_DEVIATIONS = {
    ("2dmatpedia", "total_magnetization", "μB/cell"),
    ("alexandria", "total_magnetization", "μB/cell"),
    ("elementa", "total_magnetization", "μB/cell"),
    ("materials_project", "total_magnetization", "μB/cell"),
    ("materials_project", "total_magnetization", "μB/f.u."),
    ("novomag", "total_magnetization", "μB/cell"),
    ("mc2d", "interlayer_binding_energy", "eV/Å²"),
}


def test_no_adapter_grows_a_new_unit_that_the_registry_does_not_declare():
    """Static audit over every adapter; needs no fixture.

    Catches the failure a golden sample cannot: an adapter with no fixture yet
    emitting a canonical property under the wrong unit.
    """
    import ast

    from scripts.properties.registry import CANONICAL_PROPERTIES

    directory = REPO_ROOT / "scripts" / "properties" / "adapters"
    found = set()
    for path in sorted(directory.glob("*.py")):
        if path.stem in {"__init__", "_util"}:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "PropertyValue"):
                continue
            args = node.args
            if len(args) < 3 or not isinstance(args[0], ast.Constant):
                continue
            name = args[0].value
            canonical = CANONICAL_PROPERTIES.get(name)
            if canonical is None or not isinstance(args[2], ast.Constant):
                continue
            if args[2].value != canonical[0]:
                found.add((path.stem, name, args[2].value))

    assert found == KNOWN_UNIT_DEVIATIONS, (
        "unit disagreements changed:\n"
        f"  new: {sorted(found - KNOWN_UNIT_DEVIATIONS)}\n"
        f"  gone: {sorted(KNOWN_UNIT_DEVIATIONS - found)}"
    )
