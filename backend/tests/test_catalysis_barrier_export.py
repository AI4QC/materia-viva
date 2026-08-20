import math

from scripts.datasets import catalysis_barriers as barriers


class _Atoms:
    def __init__(self, formula):
        self.formula = formula

    def get_chemical_formula(self):
        return self.formula


def test_parse_oc20neb_name_preserves_signed_miller_indices():
    parsed = barriers.parse_oc20neb_trajectory_name(
        "transfer_ood_242_4786_11_2-1-1-2_neb1.0.traj"
    )

    assert parsed == {
        "reaction_class": "transfer",
        "domain": "ood",
        "task_id": 242,
        "bulk_index": 4786,
        "reaction_index": 11,
        "facet": "2-1-1",
        "shift": 2,
    }


def test_oc20neb_records_restore_material_reaction_and_quality_flags():
    mappings = {
        "dissociation": [
            {
                "trajectory_name": "dissociation_id_18_1_0_111-5_neb1.0.traj",
                "neb_id": "18_1_0_111-5_neb1",
                "barrier_height": 2.3,
                "E_rxn": 1.2,
                "converged": True,
                "barrierless": False,
                "E_raw_initial": -10.0,
                "E_raw_final": -8.8,
                "E_raw_TS": -7.7,
                "domain": "id",
                "Ea": 2.3,
            },
            {
                "trajectory_name": "dissociation_ood_19_1_0_111-6_neb1.0.traj",
                "neb_id": "19_1_0_111-6_neb1",
                "barrier_height": 456.0,
                "E_rxn": 0.4,
                "converged": True,
                "barrierless": False,
                "E_raw_initial": -456.0,
                "E_raw_final": -455.6,
                "E_raw_TS": 0.0,
                "domain": "ood",
                "Ea": 456.0,
            },
        ]
    }
    reaction_databases = {
        "dissociation": [{"reaction": "*OH -> *O + *H"}]
    }
    bulks = [{}, {"src_id": "mp-123", "atoms": _Atoms("Pt3Ni")}]
    archive_names = {"dissociation_id_18_1_0_111-5_neb1.0.traj"}

    rows = barriers.build_oc20neb_records(
        mappings,
        reaction_databases=reaction_databases,
        bulks=bulks,
        archive_names=archive_names,
    )

    good, bad = rows
    assert good["reaction_equation"] == "*OH -> *O + *H"
    assert good["material_id"] == "mp-123"
    assert good["material_formula"] == "Pt3Ni"
    assert good["facet"] == "111"
    assert good["barrier_eV"] == 2.3
    assert good["label_kind"] == "dft_neb_explicit_barrier"
    assert good["label_quality"] == "high"
    assert good["has_structure"] is True

    assert bad["label_quality"] == "invalid"
    assert "raw_ts_zero" in bad["quality_flags"]
    assert bad["has_structure"] is False


def test_catapp_classification_keeps_every_label_but_quarantines_proxies():
    explicit = barriers.build_catapp_record(
        {
            "reaction_energy": -0.3,
            "activation_energy": 0.8,
            "surface": "Pt(111)",
            "ab": "CO*",
            "a": "CO",
            "b": "*",
            "reference": "PCCP 2011",
            "url": "https://example.test/paper",
            "dataset": "DACAPO, RPBE",
        },
        row_number=7,
    )
    bep = barriers.build_catapp_record(
        {
            "reaction_energy": 0.2,
            "activation_energy": 0.5,
            "surface": "Pt(111)",
            "ab": "CO*",
            "a": "CO",
            "b": "*",
            "reference": "CatApp BEP",
            "url": "https://example.test/bep",
            "dataset": "BEP+DACAPO",
        },
        row_number=8,
    )
    placeholder = barriers.build_catapp_record(
        {
            "reaction_energy": 1.2,
            "activation_energy": 1.2,
            "surface": "Pt3Ni(111)",
            "ab": "CO*",
            "a": "CO",
            "b": "*",
            "reference": "J. Catal. 293 (2012) 51-60",
            "url": "https://example.test/alloys",
            "dataset": "SUNCAT alloys, DACAPO/RPBE",
        },
        row_number=9,
    )

    assert explicit["material_formula"] == "Pt"
    assert explicit["facet"] == "111"
    assert explicit["label_kind"] == "reported_activation_energy"
    assert explicit["label_quality"] == "high"
    assert bep["label_kind"] == "bep_estimate"
    assert bep["label_quality"] == "low"
    assert placeholder["label_kind"] == "reaction_energy_proxy"
    assert "known_catapp_alloy_proxy" in placeholder["quality_flags"]


def test_catalysis_hub_nodes_are_standardized_without_claiming_structures():
    row = barriers.build_catalysis_hub_record(
        {
            "id": "UmVhY3Rpb246MQ==",
            "Equation": "CO* -> CO(g) + *",
            "surfaceComposition": "Pt",
            "chemicalComposition": "Pt36CO",
            "facet": "111",
            "sites": '{"CO": "top"}',
            "activationEnergy": 1.1,
            "reactionEnergy": 0.7,
            "pubId": "Example2020",
            "dftCode": "VASP",
            "dftFunctional": "RPBE",
        }
    )

    assert row["barrier_eV"] == 1.1
    assert row["material_formula"] == "Pt"
    assert row["has_structure"] is False
    assert row["label_quality"] == "medium"
    assert row["equation_canonical"] == "co*->co+*"


def test_barrier_filters_separate_raw_positive_and_high_confidence():
    rows = [
        {"barrier_eV": 1.0, "label_quality": "high"},
        {"barrier_eV": 2.0, "label_quality": "low"},
        {"barrier_eV": math.nan, "label_quality": "high"},
        {"barrier_eV": -0.1, "label_quality": "high"},
    ]

    positive, high = barriers.curated_layers(rows)

    assert positive == rows[:2]
    assert high == rows[:1]


def test_training_candidates_require_identity_and_medium_or_high_quality():
    high = {
        "barrier_eV": 1.0,
        "label_quality": "high",
        "reaction_equation": "A* -> B*",
        "material_formula": "Pt",
        "facet": "111",
    }
    medium_without_facet = {
        **high,
        "label_quality": "medium",
        "facet": "",
    }
    low = {**high, "label_quality": "low"}
    anonymous = {**high, "label_quality": "medium", "material_formula": ""}

    candidates, identity_complete = barriers.training_candidate_layers(
        [high, medium_without_facet, low, anonymous]
    )

    assert candidates == [high, medium_without_facet]
    assert identity_complete == [high]


def test_structure_training_candidates_are_usable_and_structure_linked():
    usable = {
        "barrier_eV": 1.0,
        "label_quality": "medium",
        "reaction_equation": "A* -> B*",
        "material_formula": "Pt",
        "facet": "111",
        "has_structure": True,
    }
    no_structure = {**usable, "has_structure": False}
    low_quality = {**usable, "label_quality": "low"}

    assert barriers.structure_training_candidates(
        [usable, no_structure, low_quality]
    ) == [usable]


def test_meo_ci_neb_record_keeps_mechanism_and_site_identity():
    row = barriers.build_meo_methane_record(
        {
            "reaction_id": "8_8_1",
            "mechanism": "heterolytic",
            "ch4_cation_idx": "8",
            "ch4_cation": "Zn",
            "ch3_site_idx": "8",
            "ch3_site": "Zn",
            "h_site_idx": "1",
            "h_site": "O(Cu)",
            "Ea_eV": "1.10",
        }
    )

    assert row["barrier_eV"] == 1.1
    assert row["reaction_class"] == "methane_dissociation_heterolytic"
    assert row["material_formula"] == "Mg0.25Zn0.25Ni0.25Cu0.25O"
    assert row["facet"] == "100"
    assert row["label_kind"] == "dft_ci_neb_explicit_barrier"
    assert row["label_quality"] == "high"
    assert "CH4@Zn[8]" in row["site"]


def test_deduplication_prefers_high_quality_record_for_same_physical_key():
    low = {
        "source": "catapp",
        "record_id": "low",
        "reaction_equation": "CO* -> CO(g) + *",
        "material_formula": "Pt",
        "facet": "111",
        "barrier_eV": 1.2,
        "reaction_energy_eV": 0.8,
        "label_quality": "low",
    }
    high = {
        **low,
        "source": "explicit_neb",
        "record_id": "high",
        "label_quality": "high",
    }
    rows = [low, high]
    barriers.annotate_duplicates(rows)

    selected = barriers.deduplicate_records(rows)

    assert [row["record_id"] for row in selected] == ["high"]
    assert high["duplicate_count"] == 2
    assert high["duplicate_sources"] == "catapp;explicit_neb"


def test_ckinetics_pmutt_restores_forward_and_reverse_dft_barriers():
    document = {
        "project": "example_project",
        "filename": "Rh_Al2O3_110.xlsx",
        "file_type": "pMuttExcels",
        "species": {
            "data": {
                "0": {"name": "Name of the species", "potentialenergy": "help"},
                "1": {"name": "IS", "potentialenergy": -10.0},
                "2": {"name": "TS", "potentialenergy": -8.5},
                "3": {"name": "FS", "potentialenergy": -9.4},
            }
        },
        "refs": {"data": {}},
        "reactions": {
            "data": {
                "0": {"reaction_str": "Reaction string"},
                "1": {
                    "reaction_str": "IS = TS = FS",
                    "is_adsorption": False,
                    "beta": 1,
                },
                "2": {
                    "reaction_str": "IS = FS",
                    "is_adsorption": True,
                    "beta": 0,
                },
            }
        },
    }

    rows = barriers.build_ckineticsdb_records([document])

    assert len(rows) == 2
    forward, reverse = rows
    assert forward["reaction_equation"] == "IS -> FS"
    assert forward["barrier_eV"] == 1.5
    assert forward["reaction_energy_eV"] == 0.6
    assert reverse["reaction_equation"] == "FS -> IS"
    assert reverse["barrier_eV"] == 0.9
    assert reverse["reaction_energy_eV"] == -0.6
    assert forward["material_formula"] == "Rh/Al2O3"
    assert forward["facet"] == "110"
    assert forward["label_kind"] == "dft_ts_energy_difference"
    assert forward["label_quality"] == "high"


def test_ckinetics_pmutt_converts_manual_kcal_barrier_and_recovers_reverse():
    document = {
        "project": "Light_alkane_hydrogenolysis_on_Ru",
        "filename": "Input_Data_Ru_c2.xlsx",
        "file_type": "pMuttExcels",
        "species": {
            "data": {
                "1": {"name": "A(S)", "potentialenergy": -1.0},
                "2": {"name": "B(S)", "potentialenergy": -0.8},
            }
        },
        "refs": {"data": {}},
        "reactions": {
            "data": {
                "1": {
                    "reaction_str": "A(S) + Ru(S) = B(S) + Ru(B)",
                    "is_adsorption": False,
                    "notes": 23.060548867,
                }
            }
        },
    }

    forward, reverse = barriers.build_ckineticsdb_records([document])

    assert forward["barrier_eV"] == 1.0
    assert forward["reaction_energy_eV"] == 0.2
    assert reverse["barrier_eV"] == 0.8
    assert forward["material_formula"] == "Ru"
    assert forward["facet"] == "0001"
    assert forward["label_kind"] == "reported_activation_energy_kcal_mol"
    assert forward["label_quality"] == "medium"


def test_uar_values_are_retained_but_not_misrepresented_as_identified_reactions():
    row = barriers.build_uar_record(
        {
            "datapoint": 92,
            "original [eV]": 0.64,
            "RFR [eV]": 0.70,
            "SVR [eV]": 0.45,
            "GBR [eV]": 0.62,
        }
    )

    assert row["barrier_eV"] == 0.64
    assert row["reaction_equation"] == ""
    assert row["material_formula"] == ""
    assert row["label_quality"] == "unusable"
    assert "missing_reaction_and_surface_identity" in row["quality_flags"]
    assert row["license"] == "CC BY-NC 4.0"


def test_mo2c_fts_table_yields_forward_and_reverse_free_energy_barriers(tmp_path):
    table = tmp_path / "mo2c.dat"
    table.write_text(
        "Gibbs Energies for 35 steps\n"
        "Elementary Step \tName\tinitial G (eV)\tTS G(eV)\tfinal G (eV)\t"
        "barrier (eV)\tErxn (eV)\treverse barrier (eV)\n"
        "1\tNEB_CO_C_O\t-209.04\t-207.54\t-210.07\t1.51\t-1.02\t2.53\n",
        encoding="utf-8",
    )

    forward, reverse = barriers.load_mo2c_fts_records(table)

    assert forward["reaction_equation"] == "CO* -> C* + O*"
    assert forward["barrier_eV"] == 1.51
    assert forward["reaction_energy_eV"] == -1.02
    assert reverse["reaction_equation"] == "C* + O* -> CO*"
    assert reverse["barrier_eV"] == 2.53
    assert reverse["reaction_energy_eV"] == 1.02
    assert forward["material_formula"] == "Mo2C"
    assert forward["label_kind"] == "dft_gibbs_activation_free_energy"
    assert forward["label_quality"] == "high"
    assert forward["record_id"] == "mo2c_fts_35:1:forward"
    assert reverse["record_id"] == "mo2c_fts_35:1:reverse"


def test_catalysis_hub_reader_deduplicates_overlapping_pages_by_graphql_id(
    tmp_path,
):
    import gzip
    import json

    reactions = tmp_path / "reactions"
    reactions.mkdir()
    repeated = {"id": "reaction-1", "activationEnergy": 0.7}
    for page_number, nodes in enumerate(
        ([repeated], [repeated, {"id": "reaction-2", "activationEnergy": 0.8}]),
        start=1,
    ):
        payload = {
            "data": {"reactions": {"edges": [{"node": node} for node in nodes]}}
        }
        with gzip.open(reactions / f"page-{page_number:06d}.json.gz", "wt") as handle:
            json.dump(payload, handle)

    rows = list(barriers._iter_catalysis_hub_nodes(reactions))

    assert [row["id"] for row in rows] == ["reaction-1", "reaction-2"]


def test_sbh17_benchmark_is_complete_and_keeps_submerged_barriers():
    rows = barriers.build_sbh17_records()

    assert len(rows) == 17
    assert {row["material_formula"] for row in rows} >= {
        "Cu",
        "Pt",
        "Ru",
        "Ni",
        "Ag",
        "Ir",
    }
    pt111 = next(
        row
        for row in rows
        if row["material_formula"] == "Pt"
        and row["facet"] == "111"
        and row["reaction_equation"].startswith("H2")
    )
    assert pt111["barrier_eV"] == -0.008
    assert pt111["barrierless"] is True
    assert pt111["label_quality"] == "high"
    assert pt111["license"] == "CC BY 4.0"


def test_game_net_uq_derives_directional_barriers_from_path_linked_states(tmp_path):
    from ase import Atoms
    from ase.db import connect

    database_path = tmp_path / "all.db"
    database = connect(database_path)
    database.write(
        Atoms("Ag2CH2"),
        calc_type="int",
        metal="Ag",
        facet="fcc(111)",
        scaled_energy=-14.0,
        path="/data/int/ag-1201b",
    )
    database.write(
        Atoms("Ag2CH"),
        calc_type="int",
        metal="Ag",
        facet="fcc(111)",
        scaled_energy=-10.0,
        path="/data/int/ag-1101b",
    )
    database.write(
        Atoms("Ag2H"),
        calc_type="int",
        metal="Ag",
        facet="fcc(111)",
        scaled_energy=-3.0,
        path="/data/int/ag-0101b",
    )
    database.write(
        Atoms("Ag2CH2"),
        calc_type="ts",
        metal="Ag",
        facet="fcc(111)",
        scaled_energy=-12.0,
        path="/data/ts/ag-1201-1101",
        rxn_string="CH2 -> CH + H",
        note="1 img_freqs",
        converged="yes",
    )

    forward, reverse = barriers.load_game_net_uq_records(database_path)

    assert forward["reaction_equation"] == "CH2* -> CH* + H*"
    assert forward["barrier_eV"] == 2.0
    assert forward["reaction_energy_eV"] == 1.0
    assert reverse["reaction_equation"] == "CH* + H* -> CH2*"
    assert reverse["barrier_eV"] == 1.0
    assert forward["material_formula"] == "Ag"
    assert forward["facet"] == "111"
    assert forward["label_quality"] == "medium"
    assert forward["has_structure"] is True
    assert "all.db#ts=4" in forward["structure_ref"]
