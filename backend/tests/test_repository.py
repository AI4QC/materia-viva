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
    assert _ids(first) == ["exp-3", "pool-2"]
    assert _ids(second) == ["exp-1", "pool-5"]


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
