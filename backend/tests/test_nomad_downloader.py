import gzip
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.datasets.nomad import (
    CATALOG_BASE_FIELDS,
    DEFAULT_RESERVE_BYTES,
    SNAPSHOT_TIME_FIELD,
    build_archive_request,
    build_catalog_request,
    build_parser,
    build_selection,
    discover_scalar_fields,
    download_all,
    export_archives,
    export_catalog,
    status,
)


CUTOFF = "2026-08-18T12:00:00+00:00"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_gzip_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _write_snapshot(output_dir: Path) -> None:
    _write_json(
        output_dir / "snapshot.json",
        {
            "cutoff": CUTOFF,
            "cutoff_field": SNAPSHOT_TIME_FIELD,
            "catalog_fields": [
                "entry_id",
                "results.material.material_id",
                "results.properties.available_properties",
            ],
        },
    )


def _write_complete_catalog(output_dir: Path) -> None:
    _write_snapshot(output_dir)
    page_path = output_dir / "catalog" / "page-0000000.json.gz"
    rows = [
        {
            "entry_id": "e1",
            "results": {
                "material": {"material_id": "m1"},
                "properties": {
                    "available_properties": ["band_structure_electronic"]
                },
            },
        },
        {
            "entry_id": "e2",
            "results": {
                "material": {"material_id": "m1"},
                "properties": {
                    "available_properties": [
                        "structure_optimized",
                        "dos_electronic_new",
                    ]
                },
            },
        },
        {
            "entry_id": "e3",
            "results": {
                "material": {"material_id": "m2"},
                "properties": {"available_properties": []},
            },
        },
    ]
    _write_gzip_json(page_path, {"data": rows, "pagination": {"total": 3}})
    _write_json(
        output_dir / "catalog" / "manifest.json",
        {
            "phase": "catalog",
            "complete": True,
            "downloaded_documents": 3,
            "total_documents": 3,
            "pages": [{"path": "catalog/page-0000000.json.gz"}],
        },
    )


def test_scalar_discovery_keeps_scalars_and_required_catalog_fields():
    schema = [
        {
            "quantity": "results.properties.electronic.band_gap.value",
            "dtype": "float",
            "shape": [],
        },
        {
            "quantity": "results.properties.structures.structure_original",
            "dtype": "reference",
            "shape": [],
        },
        {
            "quantity": "results.properties.electronic.dos.energies",
            "dtype": "float",
            "shape": ["*"]
        },
        {"quantity": "metadata.optimade.formula", "dtype": "string", "shape": []},
    ]

    fields, returned_schema = discover_scalar_fields(lambda path, payload: schema)

    assert returned_schema == schema
    assert set(CATALOG_BASE_FIELDS) <= set(fields)
    assert "results.properties.electronic.band_gap.value" in fields
    assert "results.properties.structures.structure_original" not in fields
    assert "results.properties.electronic.dos.energies" not in fields
    assert "metadata.optimade.formula" not in fields


def test_catalog_request_freezes_cutoff_and_uses_cursor():
    request = build_catalog_request(
        cutoff=CUTOFF,
        fields=["entry_id", "results.material.material_id"],
        page_size=250,
        cursor="entry-0249",
    )

    assert request["owner"] == "public"
    assert request["query"] == {"entry_create_time:lte": CUTOFF}
    assert request["pagination"]["page_after_value"] == "entry-0249"
    assert request["pagination"]["order_by"] == "entry_id"
    assert request["required"]["include"] == [
        "entry_id",
        "results.material.material_id",
    ]


def test_catalog_export_is_resumable_and_writes_portable_manifest(tmp_path):
    _write_snapshot(tmp_path)
    calls = []

    def fetch(path, payload):
        calls.append((path, payload))
        cursor = payload["pagination"].get("page_after_value")
        if cursor is None:
            return {
                "data": [{"entry_id": "a"}, {"entry_id": "b"}],
                "pagination": {"total": 3, "next_page_after_value": "b"},
            }
        assert cursor == "b"
        return {
            "data": [{"entry_id": "c"}],
            "pagination": {"total": 3, "next_page_after_value": None},
        }

    manifest_path = export_catalog(
        tmp_path,
        page_size=2,
        max_pages=1,
        reserve_bytes=0,
        fetch_json=fetch,
    )
    first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert first_manifest["complete"] is False
    assert first_manifest["downloaded_documents"] == 2

    export_catalog(
        tmp_path,
        page_size=2,
        max_pages=1,
        reserve_bytes=0,
        fetch_json=fetch,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["downloaded_documents"] == 3
    assert len(manifest["pages"]) == 2
    assert all("absolute_path" not in page for page in manifest["pages"])
    assert calls[1][1]["pagination"]["page_after_value"] == "b"

    verified = status(tmp_path, verify=True)
    assert verified["phases"]["catalog"]["verification_errors"] == []


def test_selection_deduplicates_materials_and_builds_property_queues(tmp_path):
    _write_complete_catalog(tmp_path)

    manifest_path = build_selection(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["complete"] is True
    assert manifest["counts"] == {
        "materials": 2,
        "entries_with_material": 3,
        "properties": 2,
        "band": 1,
        "dos": 1,
        "phonon-band": 0,
        "phonon-dos": 0,
        "spectra": 0,
    }
    with sqlite3.connect(tmp_path / "selection.sqlite") as db:
        representative = db.execute(
            "SELECT representative_entry_id FROM materials WHERE material_id = 'm1'"
        ).fetchone()[0]
    assert representative == "e2"

    # Re-running selection must not count or insert a completed page twice.
    second_manifest = json.loads(
        build_selection(tmp_path).read_text(encoding="utf-8")
    )
    assert second_manifest["counts"] == manifest["counts"]


def test_archive_requests_cover_resolved_and_legacy_curve_branches():
    band = build_archive_request(entry_ids=["e1"], kind="band")
    dos = build_archive_request(entry_ids=["e2"], kind="dos")

    assert band["query"] == {"entry_id:any": ["e1"]}
    assert (
        band["required"]["results"]["properties"]["electronic"]
        ["band_structure_electronic"]
        == "include-resolved"
    )
    assert (
        band["required"]["run"]["calculation"]["band_structure_electronic"]
        == "*"
    )
    assert (
        dos["required"]["results"]["properties"]["electronic"]
        ["dos_electronic_new"]
        == "include-resolved"
    )
    assert dos["required"]["run"]["calculation"]["dos_electronic"] == "*"


def test_archive_export_validates_ids_and_resumes_from_selection(tmp_path):
    _write_complete_catalog(tmp_path)
    build_selection(tmp_path)
    calls = []

    def fetch(path, payload):
        assert path == "/entries/archive/query"
        ids = payload["query"]["entry_id:any"]
        calls.append(ids)
        return {"data": [{"entry_id": entry_id, "archive": {}} for entry_id in ids]}

    manifest_path = export_archives(
        tmp_path,
        kind="structures",
        batch_size=1,
        max_pages=1,
        reserve_bytes=0,
        fetch_json=fetch,
    )
    first = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert first["complete"] is False
    assert first["downloaded_documents"] == 1

    export_archives(
        tmp_path,
        kind="structures",
        batch_size=1,
        reserve_bytes=0,
        fetch_json=fetch,
    )
    complete = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert complete["complete"] is True
    assert complete["downloaded_documents"] == 2
    assert calls == [["e2"], ["e3"]]


def test_archive_export_fails_closed_on_missing_entry(tmp_path):
    _write_complete_catalog(tmp_path)
    build_selection(tmp_path)

    with pytest.raises(RuntimeError, match="Archive batch mismatch"):
        export_archives(
            tmp_path,
            kind="structures",
            batch_size=2,
            reserve_bytes=0,
            fetch_json=lambda path, payload: {"data": [{"entry_id": "e2"}]},
        )


def test_archive_export_fails_closed_on_duplicate_entry(tmp_path):
    _write_complete_catalog(tmp_path)
    build_selection(tmp_path)

    with pytest.raises(RuntimeError, match="Archive batch mismatch"):
        export_archives(
            tmp_path,
            kind="structures",
            batch_size=2,
            reserve_bytes=0,
            fetch_json=lambda path, payload: {
                "data": [{"entry_id": "e2"}, {"entry_id": "e2"}]
            },
        )


def test_cli_converts_reserve_gib_to_bytes():
    parser = build_parser()

    defaults = parser.parse_args(["catalog"])
    custom = parser.parse_args(["catalog", "--reserve-gib", "1.5"])

    assert defaults.reserve_bytes == DEFAULT_RESERVE_BYTES
    assert custom.reserve_bytes == int(1.5 * 1024**3)


def test_script_supports_direct_cli_invocation():
    result = subprocess.run(
        [sys.executable, "scripts/datasets/nomad.py", "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "{probe,catalog,select,archive,download,status}" in result.stdout


def test_download_all_is_the_single_user_facing_workflow(tmp_path):
    _write_snapshot(tmp_path)
    calls = []

    def fetch(path, payload):
        calls.append(path)
        if path == "/entries/query":
            if "required" in payload:
                return {
                    "data": [
                        {
                            "entry_id": "e1",
                            "results": {
                                "material": {"material_id": "m1"},
                                "properties": {
                                    "available_properties": [
                                        "structure_optimized",
                                        "band_structure_electronic",
                                    ]
                                },
                            },
                        }
                    ],
                    "pagination": {"total": 1, "next_page_after_value": None},
                }
            raise AssertionError("download_all should reuse the prepared snapshot")
        if path == "/entries/archive/query":
            return {"data": [{"entry_id": "e1", "archive": {}}]}
        raise AssertionError(path)

    result = download_all(
        tmp_path,
        catalog_page_size=1,
        structure_batch_size=1,
        property_batch_size=1,
        reserve_bytes=0,
        fetch_json=fetch,
    )

    assert set(result) == {"snapshot", "catalog", "selection", "structures", "properties"}
    assert json.loads(result["catalog"].read_text())["complete"] is True
    assert json.loads(result["structures"].read_text())["complete"] is True
    assert json.loads(result["properties"].read_text())["complete"] is True
    assert calls.count("/entries/query") == 1
    assert calls.count("/entries/archive/query") == 2
