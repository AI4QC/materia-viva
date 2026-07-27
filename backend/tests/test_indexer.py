import csv

from materials_api.indexer import IndexConfig, build_index
from materials_api.repository import MaterialRepository, SearchQuery


CIF = """data_{formula}
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_cell_volume 125
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
{element} 0 0 0
"""


def _write_dataset(path, rows):
    path.mkdir(parents=True)
    for split in ("train", "val"):
        with (path / f"{split}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=(
                "index", "material_id", "cif", "pbes_gap",
                "formation_energy_per_atom", "energy_above_hull", "is_stable", "is_metal",
            ))
            writer.writeheader()
            for row in rows if split == "train" else ():
                writer.writerow(row)


def test_build_index_streams_both_datasets_and_persists_random_access_cif(tmp_path):
    experimental = tmp_path / "experimental"
    candidate = tmp_path / "candidate"
    output = tmp_path / "index"
    stats = tmp_path / "stats"
    stats.mkdir()
    _write_dataset(experimental, [{
        "index": "17", "material_id": "Li2O",
        "cif": CIF.format(formula="Li2O", element="Li"), "pbes_gap": "4.2",
        "formation_energy_per_atom": "-2.31", "energy_above_hull": "0.04",
        "is_stable": "true", "is_metal": "false",
    }])
    _write_dataset(candidate, [{
        "index": "23", "material_id": "Si",
        "cif": CIF.format(formula="Si", element="Si"), "pbes_gap": "1.1",
    }])
    (stats / "exp_spg.tsv").write_text("17\t225\n", encoding="utf-8")
    (stats / "pool_spg.tsv").write_text("23\t227\n", encoding="utf-8")

    report = build_index(IndexConfig(
        experimental_dir=experimental,
        candidate_dir=candidate,
        output_dir=output,
        stats_dir=stats,
    ))

    assert report["indexed"] == {"experimental": 1, "candidate": 1}
    with MaterialRepository(output / "materials.sqlite", output / "structures.blob") as repo:
        metadata = dict(repo.connection.execute(
            "SELECT key, value FROM metadata WHERE key IN "
            "('experimental_count', 'candidate_count', 'property_counts')"
        ).fetchall())
        assert set(metadata) == {"experimental_count", "candidate_count", "property_counts"}
        assert repo.stats() == {
            "total": 2,
            "datasets": {"candidate": 1, "experimental": 1},
            "property_counts": {
                "spacegroup": 2,
                "pbes_gap": 2,
                "density": 2,
                "formation_energy": 1,
                "energy_above_hull": 1,
                "magnetism": 0,
                "elasticity": 0,
            },
        }
        result = repo.search(SearchQuery(include_elements=("Li",)))
        assert [item["material_id"] for item in result.items] == ["exp-train-17"]
        detail = repo.get("exp-train-17")
        assert detail["spacegroup_number"] == 225
        assert detail["crystal_system"] == "cubic"
        assert detail["lattice_a"] == 5.0
        assert detail["density"] > 0
        assert detail["formation_energy_per_atom"] == -2.31
        assert detail["energy_above_hull"] == 0.04
        assert detail["is_stable"] is True
        assert detail["is_metal"] is False
        assert repo.read_cif("pool-train-23").startswith("data_Si")
