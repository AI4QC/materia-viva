import json
import subprocess
from pathlib import Path

import pytest

from scripts.datasets.aflow import build_url as build_aflow_url
from scripts.datasets.aflow import export_all as export_all_aflow
from scripts.datasets.aflow import parse_total as parse_aflow_total
from scripts.datasets.acquire import (
    CapacityError,
    build_curl_command,
    default_data_root,
    ensure_capacity,
    expand_source_downloads,
    extract_index_downloads,
    load_catalog,
    run_curl_resumable,
    validate_catalog,
    write_receipt,
)
from scripts.datasets.materials_project import (
    build_request,
    completed_offsets,
    export_all,
    write_page,
)
from scripts.datasets.mp_properties import (
    FAMILIES,
    RateLimited,
    build_url as build_mp_property_url,
    completed_offsets as mp_property_offsets,
    export_family,
)
from scripts.datasets.sacada import build_structure_downloads
from scripts.datasets.ec_mof import build_candidate_stems
from scripts.datasets.optimade_export import (
    build_url as build_optimade_url,
    export_all as export_all_optimade,
)
from scripts.datasets.tcod import extract_tcod_links
from scripts.datasets.hadb import extract_embedded_cif, select_static_materials
from scripts.datasets.ccpnc_magres import latest_file_items
from scripts.datasets.bincstrdb import extract_cif_text, extract_entry_ids


REPO_ROOT = Path(__file__).resolve().parents[2]
def test_catalog_is_broad_valid_and_contains_no_credentials():
    catalog_path = REPO_ROOT / "scripts" / "datasets" / "sources.json"

    catalog = load_catalog(catalog_path)
    validate_catalog(catalog)

    ids = {source["id"] for source in catalog["sources"]}
    assert len(ids) >= 45
    assert {
        "materials-project",
        "oqmd",
        "aflow",
        "nomad",
        "alexandria",
        "gnome",
        "jarvis-dft",
        "c2db",
        "2dmatpedia",
        "omdb-organic",
        "mpds",
        "csd",
        "atomwork-adv",
        "fair-mofs",
        "mofx-db",
        "phonix",
        "novomag",
        "pcod",
        "magndata",
        "iza-zeolite",
        "topomat",
        "sacada",
        "deem-zeolites",
        "arc-mof",
        "jarvis-specialized-structures",
        "rruff",
        "mpod",
        "ec-mof",
        "aflow-prototypes",
        "matterverse",
        "odbx",
        "tcod",
        "mpdd",
        "materials-cloud-specialized",
        "materials-cloud-archive-static",
        "materials-cloud-li-ion-trajectories",
        "mofdb-ml",
        "adaq",
        "amdb",
        "hadb",
        "ccpnc-magres",
        "cmr-static",
        "mad-static",
        "shiftml2-static",
        "matcloud",
        "atomly",
        "matcraft",
        "mof-carbon-capture",
        "nlr-matdb",
        "matgen",
        "obelix",
        "atomwork-open",
        "hybrid-perovskite-2d",
        "openmx-2d-ab2",
        "hex-high-pressure",
        "hpcsd",
        "hofsyn",
        "open-framework-aluminophosphate",
        "opxrd",
        "simpod",
        "spse",
        "superband",
        "qpod",
        "catalysis-hub",
        "matnavi",
        "b-incstrdb",
        "mincryst",
        "webmineral",
        "powbase",
        "nist-crystal-data",
        "nist-surface-structure",
        "phonondb",
    } <= ids
    serialized = json.dumps(catalog).lower()
    assert "api_key=" not in serialized
    assert "mp_api_key=" not in serialized

    sources = {source["id"]: source for source in catalog["sources"]}
    assert sources["matcloud"]["downloads"] == []
    assert sources["atomly"]["downloads"] == []
    assert sources["matcraft"]["downloads"] == []
    assert "user-action-required" in sources["matcloud"]["status"]
    # atomly moved from user-action-required to an in-progress API mirror
    assert (
        "user-action-required" in sources["atomly"]["status"]
        or "in-progress" in sources["atomly"]["status"]
        or "downloaded" in sources["atomly"]["status"]
    )
    assert "user-action-required" in sources["matcraft"]["status"]
    assert "912-full-and-1267-partial" in sources["opxrd"]["status"]


def test_optimade_url_requests_complete_structure_and_selected_properties():
    url = build_optimade_url(
        endpoint="https://optimade-misc.odbx.science/v1/structures",
        offset=500,
        page_size=500,
        fields=("id", "lattice_vectors", "cartesian_site_positions", "_odbx_formation_energy"),
    )

    assert "page_limit=500" in url
    assert "page_offset=500" in url
    assert "lattice_vectors" in url
    assert "cartesian_site_positions" in url
    assert "_odbx_formation_energy" in url


def test_optimade_url_can_request_provider_default_fields_without_empty_parameter():
    url = build_optimade_url(
        endpoint="https://optimade.materialscloud.org/main/2dtopo/v1/structures",
        offset=0,
        page_size=500,
        fields=(),
    )

    assert "response_fields" not in url


def test_optimade_export_is_compressed_resumable_and_counts_rows(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        offset = int(url.split("page_offset=")[1].split("&")[0])
        rows = [{"id": str(index)} for index in range(offset, min(offset + 2, 3))]
        return {"data": rows, "meta": {"data_available": 3}}

    manifest_path = export_all_optimade(
        output_dir=tmp_path,
        endpoint="https://example.org/v1/structures",
        fields=("id", "lattice_vectors", "cartesian_site_positions"),
        page_size=2,
        fetch_json=fetch,
        request_delay=0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["total_documents"] == 3
    assert manifest["downloaded_documents"] == 3
    assert manifest["page_offsets"] == [0, 2]
    assert len(calls) == 2
    assert sorted(path.name for path in tmp_path.glob("page-*.json.gz")) == [
        "page-000000000.json.gz",
        "page-000000002.json.gz",
    ]


def test_tcod_index_parser_only_returns_safe_subdirectories_and_cifs():
    html = """
      <a href="../">Parent Directory</a>
      <a href="00/">00/</a>
      <a href="10000000.cif">10000000.cif</a>
      <a href="10000000.hkl">10000000.hkl</a>
      <a href="https://example.org/escape.cif">external</a>
      <a href="?C=N;O=D">sort</a>
    """

    directories, cifs = extract_tcod_links(
        "https://www.crystallography.net/tcod/cif/10/", html
    )

    assert directories == ["https://www.crystallography.net/tcod/cif/10/00/"]
    assert cifs == ["https://www.crystallography.net/tcod/cif/10/10000000.cif"]


def test_hadb_selection_excludes_aimd_but_keeps_dft_and_static_mlip_entries():
    html = """
    <table><tbody>
      <tr><td>1</td><td><a href="search_page?material_id=10&q=">TiN</a></td><td>0</td><td>DFT</td></tr>
      <tr><td>2</td><td><a href="search_page?material_id=11&q=">VN</a></td><td>900</td><td>AIMD</td></tr>
      <tr><td>3</td><td><a href="search_page?material_id=12&q=">ZrN</a></td><td>0</td><td>MLIP</td></tr>
    </tbody></table>
    """

    rows = select_static_materials(html)

    assert [row["material_id"] for row in rows] == [10, 12]
    assert [row["method"] for row in rows] == ["DFT", "MLIP"]


def test_hadb_embedded_cif_is_json_decoded_and_html_unescaped():
    html = r'''<script>viewer.addModel("data_TiN\n_symmetry_name &#x27;P 1&#x27;\n", "cif");</script>'''

    cif = extract_embedded_cif(html)

    assert cif == "data_TiN\n_symmetry_name 'P 1'\n"


def test_ccpnc_download_items_keep_only_each_records_latest_static_magres_file():
    rows = [
        {
            "immutable_id": "0000001",
            "version_count": 2,
            "last_version": {"magresFilesID": "file-b"},
        },
        {
            "immutable_id": "0000002",
            "version_count": 1,
            "last_version": {"magresFilesID": "file-c"},
        },
    ]

    items = latest_file_items(rows)

    assert [(item["fileID"], item["filename"], item["version"]) for item in items] == [
        ("file-b", "MRD0000001", 1),
        ("file-c", "MRD0000002", 0),
    ]


def test_trajectory_datasets_are_explicitly_excluded_from_downloads():
    catalog = load_catalog(REPO_ROOT / "scripts" / "datasets" / "sources.json")
    sources = {source["id"]: source for source in catalog["sources"]}

    assert sources["mptrj"]["status"] == "excluded-by-scope-trajectory-dataset"
    assert sources["mptrj"]["downloads"] == []
    assert (
        sources["omat24"]["status"]
        == "excluded-by-scope-existing-legacy-trajectory-data-not-ingested"
    )
    assert sources["omat24"]["downloads"] == []
    assert "migration-path-arrays-excluded" in sources["spse"]["status"]
    assert sources["spse"]["excluded_structure_fields"] == [
        "hierarchical_calculation_data.json:paths"
    ]


def test_bincstrdb_parser_returns_unique_ids_and_exact_mscif_text():
    index_html = """
      <a href="/bincstrdb/view/?incid=12Ees1le">entry</a>
      <a href="/bincstrdb/create/?incid=12Ees1le">CIF</a>
      <a href="/bincstrdb/create/?incid=92ETsjWb">CIF</a>
      <a href="https://example.org/?incid=escape">external</a>
    """
    cif_html = """
      <textarea id="other">ignore</textarea>
      <textarea class="lined" id="cif-text" name="cif-text">#\\#CIF_1.1
data_demo
_chemical_formula_sum 'Na Cl'
</textarea>
    """

    assert extract_entry_ids(index_html) == ["12Ees1le", "92ETsjWb"]
    assert extract_cif_text(cif_html) == (
        "#\\#CIF_1.1\ndata_demo\n_chemical_formula_sum 'Na Cl'\n"
    )


def test_sacada_structure_downloads_are_unique_ordered_endpoint_archives():
    payload = {
        "data": [
            {"id": "12", "topology": "abc"},
            {"id": "2", "topology": "dia"},
        ]
    }

    downloads = build_structure_downloads(payload)

    assert downloads == [
        {
            "filename": "structures/000002.zip",
            "url": "https://www.sacada.info/download/2.zip",
        },
        {
            "filename": "structures/000012.zip",
            "url": "https://www.sacada.info/download/12.zip",
        },
    ]


def test_ec_mof_candidate_stems_match_the_official_selector_space():
    stems = build_candidate_stems()

    assert len(stems) == 1072
    assert len(set(stems)) == len(stems)
    assert "CoHAT_Bulk" in stems
    assert "CuHIB_Mono" in stems
    assert "FeOIPcZn_Bulk" in stems


def test_default_data_root_resolves_the_selected_repositories_data_link(tmp_path, monkeypatch):
    monkeypatch.delenv("MV_DATA_ROOT", raising=False)

    assert default_data_root(tmp_path) == (tmp_path / "data").resolve()


def test_default_data_root_honors_an_external_storage_override(tmp_path, monkeypatch):
    external = tmp_path / "external-data"
    monkeypatch.setenv("MV_DATA_ROOT", str(external))

    assert default_data_root(tmp_path) == external.resolve()


def test_catalog_rejects_parent_traversal_destination():
    catalog = {
        "schema_version": 1,
        "sources": [
            {
                "id": "bad",
                "name": "bad",
                "access": "open",
                "official_url": "https://example.org",
                "license": "unknown",
                "data_path": "../outside",
                "downloads": [],
            }
        ],
    }

    with pytest.raises(ValueError, match="safe relative path"):
        validate_catalog(catalog)


def test_capacity_guard_keeps_fifty_gibibytes_free():
    gib = 1024**3
    ensure_capacity(available_bytes=80 * gib, expected_bytes=20 * gib)

    with pytest.raises(CapacityError, match="50 GiB reserve"):
        ensure_capacity(available_bytes=60 * gib, expected_bytes=20 * gib)


def test_static_download_command_is_resumable_and_writes_a_part_file(tmp_path):
    part = tmp_path / "archive.zip.part"

    command = build_curl_command("https://example.org/archive.zip", part)

    assert command[:2] == ["curl", "--fail"]
    assert ["--continue-at", "-"] == command[command.index("--continue-at") : command.index("--continue-at") + 2]
    assert command[command.index("--output") + 1] == str(part)
    assert command[-1] == "https://example.org/archive.zip"


def test_static_download_command_disables_curl_internal_retries(tmp_path):
    command = build_curl_command(
        "https://example.org/missing.zip", tmp_path / "missing.zip.part"
    )

    assert command[command.index("--retry") + 1] == "0"
    assert "--retry-all-errors" not in command


def test_outer_retry_preserves_part_bytes_before_resuming(tmp_path):
    part = tmp_path / "archive.zip.part"
    part.write_bytes(b"existing")
    snapshots = []
    sleeps = []

    def fake_run(command, *, check):
        assert check is True
        snapshots.append((command, part.read_bytes()))
        if len(snapshots) == 1:
            with part.open("ab") as handle:
                handle.write(b"-downloaded")
            raise subprocess.CalledProcessError(56, command)

    run_curl_resumable(
        "https://example.org/archive.zip",
        part,
        retries=1,
        run_command=fake_run,
        sleep=sleeps.append,
    )

    assert [snapshot for _, snapshot in snapshots] == [
        b"existing",
        b"existing-downloaded",
    ]
    assert sleeps == [1]
    for command, _ in snapshots:
        assert command[command.index("--retry") + 1] == "0"
        assert command[command.index("--continue-at") + 1] == "-"


def test_apache_index_expansion_selects_dataset_files_and_ignores_parent_links():
    html = """
      <a href="../">../</a>
      <a href="alexandria_00000.json.bz2">part 0</a>
      <a href="notes.txt">notes</a>
      <a href="alexandria_00001.json.bz2">part 1</a>
    """

    items = extract_index_downloads(
        "https://example.org/data/", html, suffixes=(".json.bz2",)
    )

    assert items == [
        {
            "filename": "alexandria_00000.json.bz2",
            "url": "https://example.org/data/alexandria_00000.json.bz2",
        },
        {
            "filename": "alexandria_00001.json.bz2",
            "url": "https://example.org/data/alexandria_00001.json.bz2",
        },
    ]


def test_source_index_expansion_preserves_a_safe_dataset_subdirectory():
    source = {
        "downloads": [{"filename": "fixed.json", "url": "https://example.org/fixed.json"}],
        "indexes": [
            {
                "url": "https://example.org/pbe/",
                "destination": "pbe-3d",
                "suffixes": [".json.bz2"],
            }
        ],
    }

    items = expand_source_downloads(
        source,
        fetch_text=lambda _url: '<a href="alexandria_00000.json.bz2">part</a>',
    )

    assert items == [
        {"filename": "fixed.json", "url": "https://example.org/fixed.json"},
        {
            "filename": "pbe-3d/alexandria_00000.json.bz2",
            "url": "https://example.org/pbe/alexandria_00000.json.bz2",
        },
    ]


def test_receipt_contains_sha256_and_relative_ssd_path(tmp_path):
    data_root = tmp_path / "data"
    archive = data_root / "raw" / "acquired" / "demo" / "archive.bin"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"crystal-data")

    receipt = write_receipt(
        archive,
        data_root=data_root,
        source_id="demo",
        url="https://example.org/archive.bin",
    )

    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["path"] == "raw/acquired/demo/archive.bin"
    assert payload["bytes"] == 12
    assert payload["sha256"] == "61c7b8cef766101723efddcdb994fe6c1ce6e9a758dcb42d2219ef899a929700"
    assert payload["url"] == "https://example.org/archive.bin"


def test_materials_project_request_keeps_key_in_header_not_url():
    request = build_request(skip=2000, limit=1000, api_key="secret-value")

    assert "secret-value" not in request.full_url
    assert request.headers["X-api-key"] == "secret-value"
    assert "_skip=2000" in request.full_url
    assert "_limit=1000" in request.full_url


def test_materials_project_pages_are_compressed_atomic_and_resumable(tmp_path):
    page = write_page(
        tmp_path,
        offset=1000,
        payload={"data": [{"material_id": "mp-1"}], "meta": {"total_doc": 1}},
    )

    assert page.name == "page-000001000.json.gz"
    assert not page.with_suffix(page.suffix + ".building").exists()
    assert completed_offsets(tmp_path) == {1000}


def test_materials_project_export_fetches_all_pages_and_writes_secret_free_manifest(tmp_path):
    calls = []

    def fetch(request):
        calls.append(request)
        skip = int(request.full_url.split("_skip=")[1].split("&")[0])
        rows = [{"material_id": f"mp-{index}"} for index in range(skip, min(skip + 2, 3))]
        return {"data": rows, "meta": {"total_doc": 3, "api_version": "test"}}

    manifest_path = export_all(
        output_dir=tmp_path,
        api_key="secret-value",
        page_size=2,
        fetch_json=fetch,
        request_delay=0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["total_documents"] == 3
    assert manifest["downloaded_documents"] == 3
    assert manifest["page_offsets"] == [0, 2]
    assert len(calls) == 2
    assert all("secret-value" not in request.full_url for request in calls)
    assert "secret-value" not in manifest_path.read_text(encoding="utf-8")


def test_mp_property_url_restricts_fields_and_carries_no_key():
    url = build_mp_property_url("insertion_electrodes", skip=2000, limit=1000)

    assert url.startswith(
        "https://api.materialsproject.org/materials/insertion_electrodes/?"
    )
    assert "_skip=2000" in url and "_limit=1000" in url
    assert "_all_fields" not in url
    assert "average_voltage" in url
    # the key travels in the X-API-KEY header, so no query parameter names it
    assert "api_key" not in url.lower() and "key=" not in url.lower()


def test_every_mp_property_family_requests_an_explicit_field_list():
    for family, fields in FAMILIES.items():
        assert fields, f"{family} must restrict its fields"
        # every family needs the column the property adapter joins on
        assert {"material_id", "material_ids", "task_id"} & set(fields), family


def test_mp_property_export_writes_receipts_and_a_secret_free_manifest(tmp_path):
    calls = []

    def fetch(url, key):
        calls.append((url, key))
        skip = int(url.split("_skip=")[1].split("&")[0])
        rows = [
            {"material_id": f"mp-{index}"} for index in range(skip, min(skip + 2, 3))
        ]
        return {"data": rows, "meta": {"total_doc": 3, "api_version": "test"}}

    manifest_path = export_family(
        family="grain_boundaries",
        output_dir=tmp_path,
        key="secret-value",
        page_size=2,
        request_delay=0,
        data_root=tmp_path,
        fetch_json=fetch,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["downloaded_documents"] == 3
    assert manifest["page_offsets"] == [0, 2]
    assert set(manifest["files"]) == {
        "page-000000000.json.gz",
        "page-000000002.json.gz",
    }
    assert all(entry["sha256"] for entry in manifest["files"].values())
    assert "secret-value" not in manifest_path.read_text(encoding="utf-8")
    assert all("secret-value" not in url for url, _ in calls)

    receipt = json.loads(
        (tmp_path / "page-000000000.json.gz.receipt.json").read_text(encoding="utf-8")
    )
    assert "secret-value" not in receipt["url"]
    assert receipt["source_id"] == "materials-project"

    # a completed page is one whose receipt exists too, so the run resumes
    assert mp_property_offsets(tmp_path) == {0, 2}
    calls.clear()
    export_family(
        family="grain_boundaries",
        output_dir=tmp_path,
        key="secret-value",
        page_size=2,
        request_delay=0,
        data_root=tmp_path,
        fetch_json=fetch,
    )
    assert calls == []


def test_mp_property_export_stops_when_the_api_signals_throttling(tmp_path):
    def fetch(url, key):
        raise RateLimited("HTTP 429 twice")

    with pytest.raises(RateLimited):
        export_family(
            family="eos",
            output_dir=tmp_path,
            key="secret-value",
            request_delay=0,
            data_root=tmp_path,
            fetch_json=fetch,
        )


def test_aflow_url_requests_structure_and_property_fields_with_bounded_paging():
    url = build_aflow_url(page=3, page_size=1000)

    assert "paging(3,1000)" in url
    assert "geometry" in url
    assert "positions_fractional" in url
    assert "species" in url
    assert "enthalpy_formation_atom" in url
    assert "Egap" in url


def test_aflow_total_is_parsed_from_aflux_page_labels():
    assert parse_aflow_total({"1 of 2981853": {"auid": "aflow:test"}}) == 2_981_853

    with pytest.raises(RuntimeError, match="total"):
        parse_aflow_total({})


def test_aflow_export_is_paged_and_resumable(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        if "paging(1,2)" in url:
            return {"1 of 3": {"auid": "aflow:1"}, "2 of 3": {"auid": "aflow:2"}}
        return {"3 of 3": {"auid": "aflow:3"}}

    manifest_path = export_all_aflow(
        output_dir=tmp_path,
        page_size=2,
        fetch_json=fetch,
        request_delay=0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["total_documents"] == 3
    assert manifest["downloaded_documents"] == 3
    assert manifest["pages"] == [1, 2]
    assert len(calls) == 2


def test_the_acquisition_notes_state_the_number_of_sources_the_catalog_holds():
    """This count drifted to three different values across two files before.

    English said 102, Chinese said 100, the catalog held 106. The prose is
    maintained by hand; the catalog is the fact, so the fact is asserted here.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    catalog = json.loads(
        (root / "scripts" / "datasets" / "sources.json").read_text(encoding="utf-8")
    )
    total = len(catalog["sources"])

    for name, claim in (("dataset-acquisition.md", f"{total} sources"),
                        ("dataset-acquisition.zh-CN.md", f"{total} 个来源")):
        text = (root / "docs" / name).read_text(encoding="utf-8")
        assert claim in text, f"{name} does not say the catalog holds {total}"
        for stale in range(total - 10, total):
            assert f"{stale} sources" not in text and f"{stale} 个来源" not in text
