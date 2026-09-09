import csv
import asyncio
import subprocess

import httpx

from materials_api.app import create_app
from materials_api.indexer import IndexConfig, build_index
from materials_api.ovito_renderer import OvitoRenderService


PNG = b"\x89PNG\r\n\x1a\napi-render"
CIF = """data_Li2O
_cell_length_a 5.0
_cell_length_b 5.0
_cell_length_c 5.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_cell_volume 125
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Li1 Li 0 0 0
O1 O 0.5 0.5 0.5
"""


def _write_dataset(path, rows):
    path.mkdir(parents=True)
    for split in ("train", "val"):
        with (path / f"{split}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("index", "material_id", "cif", "pbes_gap"))
            writer.writeheader()
            if split == "train":
                writer.writerows(rows)


def _app(tmp_path):
    experimental = tmp_path / "experimental"
    candidate = tmp_path / "candidate"
    runtime = tmp_path / "runtime"
    _write_dataset(experimental, [{
        "index": 1, "material_id": "Li2O", "cif": CIF, "pbes_gap": 4.2,
    }])
    _write_dataset(candidate, [{
        "index": 2, "material_id": "Fe2O3", "cif": CIF.replace("Li2O", "Fe2O3"),
        "pbes_gap": 2.2,
    }])
    build_index(IndexConfig(experimental, candidate, runtime))

    def runner(command, **kwargs):
        # the service makes two kinds of call: an availability probe, and a render
        if "-c" in command:
            return subprocess.CompletedProcess(command, 0, "", "")
        output = command[command.index("--output") + 1]
        with open(output, "wb") as handle:
            handle.write(PNG)
        return subprocess.CompletedProcess(command, 0, "", "")

    renderer = OvitoRenderService(runtime / "renders", runner=runner)
    app = create_app(
        database_path=runtime / "materials.sqlite",
        blob_path=runtime / "structures.blob",
        renderer=renderer,
        frontend_dir=None,
    )
    return app


def _request(app, path, *, params=None):
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, params=params)

    return asyncio.run(send())


def test_stats_and_material_search_endpoints(tmp_path):
    app = _app(tmp_path)
    stats = _request(app, "/api/stats")
    result = _request(app, "/api/materials", params={
        "elements": "Li,O", "element_mode": "exact", "page_size": 10,
    })

    assert stats.status_code == 200
    assert stats.json()["total"] == 2
    assert stats.json()["datasets"] == {"candidate": 1, "experimental": 1}
    # the frontend decides which viewer to open from this; it must reflect the probe
    assert stats.json()["ovito_available"] is True
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["material_id"] == "exp-train-1"


def test_openapi_uses_crystal_material_universe_brand(tmp_path):
    app = _app(tmp_path)
    response = _request(app, "/api/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "MateriaViva API"


def test_detail_structure_and_cif_endpoints(tmp_path):
    app = _app(tmp_path)
    detail = _request(app, "/api/materials/exp-train-1")
    structure = _request(app, "/api/materials/exp-train-1/structure")
    cif = _request(app, "/api/materials/exp-train-1/cif")

    assert detail.status_code == 200
    assert detail.json()["elements"] == ["Li", "O"]
    assert structure.status_code == 200
    assert structure.json()["site_count"] == 2
    assert len(structure.json()["lattice"]["matrix"]) == 3
    assert cif.status_code == 200
    assert cif.headers["content-type"].startswith("chemical/x-cif")
    assert "exp-train-1.cif" in cif.headers["content-disposition"]


def test_cached_ovito_render_endpoint(tmp_path):
    app = _app(tmp_path)
    response = _request(app, "/api/materials/exp-train-1/render", params={
        "view": "top", "representation": "spacefill", "show_cell": "true",
    })

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == PNG
    assert response.headers["cache-control"].startswith("public")


def test_api_returns_structured_not_found_and_validation_errors(tmp_path):
    app = _app(tmp_path)
    missing = _request(app, "/api/materials/does-not-exist")
    invalid_element = _request(app, "/api/materials", params={"elements": "Hh"})
    invalid_range = _request(app, "/api/materials", params={"gap_min": 4, "gap_max": 1})

    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "material_not_found"
    assert invalid_element.status_code == 422
    assert invalid_element.json()["detail"]["code"] == "invalid_query"
    assert invalid_range.status_code == 422
