from pathlib import Path

from materials_api.layout import RepositoryLayout


def test_repository_layout_uses_standalone_root_and_canonical_data_paths(tmp_path):
    layout = RepositoryLayout.from_root(tmp_path)

    assert layout.root == tmp_path
    assert layout.backend == tmp_path / "backend"
    assert layout.frontend_static == tmp_path / "backend" / "static"
    assert layout.experimental_source == tmp_path / "data" / "sources" / "experimental"
    assert layout.candidate_source == tmp_path / "data" / "sources" / "candidate"
    assert layout.stats == tmp_path / "data" / "raw" / "external_structs" / "work" / "stats"
    assert layout.index == tmp_path / "data" / "index"
    assert "CSAgent" not in str(layout)
    assert "materials_web" not in str(layout)


def test_repository_layout_discovers_root_from_script_path(tmp_path):
    script = tmp_path / "scripts" / "serve.py"

    layout = RepositoryLayout.from_anchor(script)

    assert layout.root == Path(tmp_path)
