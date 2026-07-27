from materials_api.structure import parse_cif_structure


def _two_hydrogen_cif(second_x: float) -> str:
    return f"""data_H2
_cell_length_a 10
_cell_length_b 10
_cell_length_c 10
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
H1 H 0.02 0.5 0.5
H2 H {second_x} 0.5 0.5
"""


def test_interactive_bonds_do_not_draw_across_periodic_cell_boundaries():
    structure = parse_cif_structure(_two_hydrogen_cif(0.98))

    assert structure["bonds"] == []


def test_interactive_bonds_keep_close_atoms_inside_the_displayed_cell():
    structure = parse_cif_structure(_two_hydrogen_cif(0.07))

    assert len(structure["bonds"]) == 1
    assert round(structure["bonds"][0]["distance"], 8) == 0.5
