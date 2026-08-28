from materials_api.repository import MaterialRepository, SearchQuery


def _record(
    material_id,
    formula,
    elements,
    *,
    dataset="candidate",
    gap=None,
    n_atoms=1,
    density=None,
    spacegroup_number=None,
    crystal_system=None,
    **properties,
):
    record = {
        "material_id": material_id,
        "formula": formula,
        "chemical_system": "-".join(sorted(elements)),
        "elements": tuple(elements),
        "dataset": dataset,
        "is_experimental": dataset == "experimental",
        "source_split": "train",
        "source_index": material_id,
        "n_elements": len(elements),
        "n_atoms": n_atoms,
        "pbes_gap": gap,
        "density": density,
        "spacegroup_number": spacegroup_number,
        "crystal_system": crystal_system,
        "blob_offset": 0,
        "blob_length": 1,
    }
    record.update(properties)
    return record


def _repository(tmp_path):
    repo = MaterialRepository.create(tmp_path / "materials.sqlite", tmp_path / "structures.blob")
    repo.add_material(_record(
        "exp-1", "LiFePO4", ("Li", "Fe", "P", "O"), dataset="experimental",
        gap=2.1, n_atoms=7, density=3.6, spacegroup_number=62,
        crystal_system="orthorhombic",
        volume=300, formation_energy_per_atom=-2.4, energy_above_hull=0.03,
        is_stable=True, is_metal=False, magnetic_ordering="NM",
        total_magnetization=0.1, bulk_modulus=110, shear_modulus=52,
    ))
    repo.add_material(_record(
        "pool-2", "Li2O", ("Li", "O"), gap=4.0, n_atoms=3, density=2.0,
        spacegroup_number=225, crystal_system="cubic",
    ))
    repo.add_material(_record(
        "exp-3", "Fe2O3", ("Fe", "O"), dataset="experimental", gap=2.2,
        n_atoms=5, density=5.2, spacegroup_number=167, crystal_system="trigonal",
    ))
    repo.add_material(_record("pool-4", "Si", ("Si",), gap=1.1, density=2.3))
    repo.add_material(_record("pool-5", "NaCl", ("Na", "Cl"), gap=5.0, density=2.16))
    return repo


def _ids(result):
    return [item["material_id"] for item in result.items]


def test_search_requires_all_selected_elements(tmp_path):
    with _repository(tmp_path) as repo:
        result = repo.search(SearchQuery(include_elements=("Li", "O"), element_mode="all"))

    assert set(_ids(result)) == {"exp-1", "pool-2"}
    assert result.total == 2
    assert result.facets["datasets"] == {"candidate": 1, "experimental": 1}


def test_search_supports_any_and_exact_element_modes(tmp_path):
    with _repository(tmp_path) as repo:
        any_result = repo.search(SearchQuery(include_elements=("Li", "Si"), element_mode="any"))
        exact_result = repo.search(SearchQuery(include_elements=("Li", "O"), element_mode="exact"))

    assert set(_ids(any_result)) == {"exp-1", "pool-2", "pool-4"}
    assert _ids(exact_result) == ["pool-2"]


def test_search_excludes_elements_and_filters_dataset_and_formula(tmp_path):
    with _repository(tmp_path) as repo:
        without_fe = repo.search(SearchQuery(include_elements=("O",), exclude_elements=("Fe",)))
        experimental_fe = repo.search(SearchQuery(
            datasets=("experimental",), formula="Fe2O3",
        ))

    assert _ids(without_fe) == ["pool-2"]
    assert _ids(experimental_fe) == ["exp-3"]


def test_search_filters_numeric_and_crystallographic_ranges(tmp_path):
    with _repository(tmp_path) as repo:
        result = repo.search(SearchQuery(
            gap_min=2.15,
            gap_max=4.1,
            density_min=1.9,
            crystal_systems=("cubic", "trigonal"),
            sort="pbes_gap",
            direction="asc",
        ))

    assert _ids(result) == ["exp-3", "pool-2"]


def test_search_paginates_with_stable_sorting(tmp_path):
    with _repository(tmp_path) as repo:
        first = repo.search(SearchQuery(sort="formula", direction="asc", page=1, page_size=2))
        second = repo.search(SearchQuery(sort="formula", direction="asc", page=2, page_size=2))

    assert first.total == 5
    assert first.pages == 3
    # Fe2O3, then LiFePO4 before Li2O: Li1 precedes Li2. Sorting the stored text
    # put Li2O first, because '2' sorts below 'F'.
    assert _ids(first) == ["exp-3", "exp-1"]
    assert _ids(second) == ["pool-2", "pool-5"]


def test_search_rejects_unknown_sort_key(tmp_path):
    with _repository(tmp_path) as repo:
        try:
            repo.search(SearchQuery(sort="DROP TABLE materials"))
        except ValueError as exc:
            assert "sort" in str(exc)
        else:
            raise AssertionError("unknown sort keys must be rejected")


def test_search_supports_mp_style_property_availability_and_state_filters(tmp_path):
    with _repository(tmp_path) as repo:
        result = repo.search(SearchQuery(
            formation_energy_max=-2.0,
            e_hull_max=0.05,
            stability="stable",
            metallicity="nonmetal",
            magnetic_orderings=("NM",),
            bulk_modulus_min=100,
            has_properties=("formation_energy", "elasticity"),
        ))

    assert _ids(result) == ["exp-1"]


def test_formula_search_also_accepts_material_ids(tmp_path):
    with _repository(tmp_path) as repo:
        result = repo.search(SearchQuery(formula="pool-2"))
        chemical_system = repo.search(SearchQuery(formula="O-Fe"))

    assert _ids(result) == ["pool-2"]
    assert _ids(chemical_system) == ["exp-3"]


def test_stats_falls_back_to_material_rows_without_build_metadata(tmp_path):
    with _repository(tmp_path) as repo:
        stats = repo.stats()

    assert stats["total"] == 5
    assert stats["datasets"] == {"candidate": 3, "experimental": 2}
    assert stats["property_counts"] == {
        "spacegroup": 3,
        "pbes_gap": 5,
        "density": 5,
        "formation_energy": 1,
        "energy_above_hull": 1,
        "magnetism": 1,
        "elasticity": 1,
    }
    # Absent metadata must degrade to "unknown", never to a live COUNT(*):
    # material_properties runs to nine figures and /api/stats is on the landing
    # page's critical path.
    assert stats["property_rows"] is None
    assert stats["curve_count"] is None


def test_stats_reports_cached_property_and_curve_counts(tmp_path):
    with _repository(tmp_path) as repo:
        repo.connection.executemany(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            (("property_row_count", "121106364"), ("curve_count", "1198897")),
        )
        repo.connection.commit()
        stats = repo.stats()

    assert stats["property_rows"] == 121_106_364
    assert stats["curve_count"] == 1_198_897


def test_stats_ignores_unparsable_cached_counts(tmp_path):
    with _repository(tmp_path) as repo:
        repo.connection.executemany(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            (("property_row_count", "not-a-number"), ("curve_count", "")),
        )
        repo.connection.commit()
        stats = repo.stats()

    assert stats["property_rows"] is None
    assert stats["curve_count"] is None


def test_unfiltered_search_uses_precomputed_dataset_counts(tmp_path):
    with _repository(tmp_path) as repo:
        repo.connection.executemany(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            (("candidate_count", "30"), ("experimental_count", "20")),
        )
        repo.connection.commit()
        result = repo.search(SearchQuery(page_size=2))

    assert result.total == 50
    assert result.pages == 25
    assert result.facets["datasets"] == {"candidate": 30, "experimental": 20}
    assert len(result.items) == 2


def test_search_filters_material_family_including_bulk(tmp_path):
    with _repository(tmp_path) as repo:
        repo.add_material(_record(
            "pool-6", "C2H8N2O4Zn", ("Zn", "O", "C", "H", "N"),
            material_family="mof",
        ))
        mofs = repo.search(SearchQuery(material_families=("mof",)))
        bulk = repo.search(SearchQuery(material_families=("bulk",)))
        both = repo.search(SearchQuery(material_families=("mof", "bulk")))

    assert _ids(mofs) == ["pool-6"]
    assert "pool-6" not in _ids(bulk)
    assert len(_ids(bulk)) == 5
    assert len(_ids(both)) == 6


def test_search_rejects_unknown_material_family(tmp_path):
    import pytest

    with _repository(tmp_path) as repo:
        with pytest.raises(ValueError):
            repo.search(SearchQuery(material_families=("perovskite",)))


def test_detail_returns_per_source_properties_and_refs(tmp_path):
    with _repository(tmp_path) as repo:
        connection = repo.connection
        connection.execute(
            "INSERT INTO source_defs (key, name, license, url) VALUES "
            "('jarvis-dft', 'JARVIS-DFT', 'NIST terms', 'https://jarvis.nist.gov/')"
        )
        connection.execute(
            "INSERT INTO property_defs (name, unit, kind) VALUES "
            "('band_gap', 'eV', 'num')"
        )
        pk = connection.execute(
            "SELECT pk FROM materials WHERE material_id = 'exp-1'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO material_properties VALUES (?, 1, 1, 'JVASP-7', 2.05, "
            "NULL, 'OptB88vdW')",
            (pk,),
        )
        connection.execute(
            "INSERT INTO material_source_refs VALUES (?, 1, 'JVASP-7', 'hash')",
            (pk,),
        )
        connection.commit()

        detail = repo.get("exp-1")
        other = repo.get("pool-2")

    assert detail is not None
    assert detail["properties"] == [{
        "property": "band_gap", "unit": "eV", "kind": "num",
        "value_num": 2.05, "value_text": None, "method": "OptB88vdW",
        "source": "jarvis-dft", "source_name": "JARVIS-DFT",
        "source_license": "NIST terms", "source_url": "https://jarvis.nist.gov/",
        "native_id": "JVASP-7",
    }]
    assert detail["source_refs"] == [{
        "source": "jarvis-dft", "source_name": "JARVIS-DFT",
        "source_license": "NIST terms", "source_url": "https://jarvis.nist.gov/",
        "native_id": "JVASP-7", "match_via": "hash",
    }]
    assert other is not None
    assert other["properties"] == []
    assert other["source_refs"] == []


def test_a_formula_search_does_not_require_typing_the_ones(tmp_path):
    """Stored formulas spell every count out: CdS is held as `Cd1S1`.

    Searching for `CdS` matched nothing at all, so formula search was unusable
    for any compound with a 1 subscript — which is most of them.
    """
    from materials_api.repository import explicit_and_implicit_counts

    assert explicit_and_implicit_counts("CdS") == {"CdS", "Cd1S1"}
    assert explicit_and_implicit_counts("Cd1S1") == {"CdS", "Cd1S1"}
    assert explicit_and_implicit_counts("Th1O2") == {"ThO2", "Th1O2"}


def test_normalising_a_formula_never_reduces_the_cell():
    """`Ag2I2` is a cell with two formula units and is not the same record as `AgI`."""
    from materials_api.repository import explicit_and_implicit_counts

    assert explicit_and_implicit_counts("Ag2I2") == {"Ag2I2"}
    assert "AgI" not in explicit_and_implicit_counts("Ag2I2")
    assert "Ag2I2" not in explicit_and_implicit_counts("AgI")


def test_a_formula_that_is_not_one_is_left_alone():
    from materials_api.repository import explicit_and_implicit_counts

    # fractional occupancies and unparseable input must not be mangled
    assert explicit_and_implicit_counts("Fe0.5Ni0.5") == {"Fe0.5Ni0.5"}
    assert explicit_and_implicit_counts("not a formula") == {"not a formula"}


def test_sorting_by_formula_reads_counts_as_numbers(tmp_path):
    """`Li2O` used to sort before `LiFePO4` because '2' sorts below 'F'."""
    with _repository(tmp_path) as repo:
        result = repo.search(SearchQuery(sort="formula", direction="asc", page_size=10))
        order = [row["formula"] for row in result.items]

    assert order == ["Fe2O3", "LiFePO4", "Li2O", "NaCl", "Si"]


def test_an_index_built_before_the_sort_key_still_searches(tmp_path):
    """The column arrived after some indexes were built; they must not break."""
    with _repository(tmp_path) as repo:
        # an index from before this change has neither the column nor its index
        repo.connection.execute("DROP INDEX idx_materials_formula_sort")
        repo.connection.execute("ALTER TABLE materials DROP COLUMN formula_sort")
        result = repo.search(SearchQuery(sort="formula", direction="asc", page_size=10))

    # misordered as it was before, but answering rather than failing
    assert [row["formula"] for row in result.items] == ["Fe2O3", "Li2O", "LiFePO4", "NaCl", "Si"]


def test_the_frontend_offers_exactly_the_sort_keys_the_api_accepts():
    """Drift between the two is what let `?sort=garbage` reach the API.

    It came back 422 and the page showed a Retry button that could never work,
    because the key stayed in the query state. The parser validates now, and this
    keeps its list honest.
    """
    import re
    from pathlib import Path

    from materials_api.repository import SORT_COLUMNS

    source = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "query.ts").read_text(
        encoding="utf-8"
    )
    block = re.search(r"SORT_KEYS = \[(.*?)\] as const", source, re.S)
    assert block, "SORT_KEYS is no longer where this test looks for it"
    frontend = set(re.findall(r"'([a-z_]+)'", block.group(1)))

    assert frontend == set(SORT_COLUMNS), (
        f"only in the frontend: {sorted(frontend - set(SORT_COLUMNS))}; "
        f"only in the API: {sorted(set(SORT_COLUMNS) - frontend)}"
    )
