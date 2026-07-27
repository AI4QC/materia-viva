import csv
import json

import pytest

from materials_api.data_contract import (
    CRYSTAL_RECORD_FIELDS,
    DataContractError,
    validate_source_dataset,
    write_manifest,
)


def _write_split(path, rows, *, fields=CRYSTAL_RECORD_FIELDS):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _record(index="0", *, cif="data_Li2O\n_cell_length_a 3", pbes_gap="1.2"):
    return {
        "index": index,
        "material_id": "Li2O",
        "cif": cif,
        "pbes_gap": pbes_gap,
    }


def test_validate_source_dataset_emits_crystal_record_v1_manifest(tmp_path):
    _write_split(tmp_path / "train.csv", [_record("0"), _record("1")])
    _write_split(tmp_path / "val.csv", [_record("2")])

    report = validate_source_dataset(tmp_path, role="experimental")
    manifest = report.to_manifest()

    assert manifest["schema"] == "crystal-record-v1"
    assert manifest["role"] == "experimental"
    assert manifest["fields"] == list(CRYSTAL_RECORD_FIELDS)
    assert manifest["splits"] == {"train": 2, "val": 1}
    assert manifest["total_records"] == 3
    assert json.loads(json.dumps(manifest)) == manifest


def test_write_manifest_atomically_persists_validation_report(tmp_path):
    _write_split(tmp_path / "train.csv", [_record("0")])
    _write_split(tmp_path / "val.csv", [_record("1")])
    report = validate_source_dataset(tmp_path, role="candidate")
    destination = tmp_path / "manifests" / "candidate.json"

    result = write_manifest(report, destination)

    assert result == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == report.to_manifest()
    assert not destination.with_suffix(".json.building").exists()


def test_validate_source_dataset_rejects_noncanonical_column_order(tmp_path):
    fields = ("material_id", "index", "cif", "pbes_gap")
    _write_split(tmp_path / "train.csv", [_record()], fields=fields)
    _write_split(tmp_path / "val.csv", [_record("1")])

    with pytest.raises(DataContractError, match="column order"):
        validate_source_dataset(tmp_path, role="candidate")


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (_record(cif=""), "non-empty CIF"),
        (_record(index="-1"), "non-negative integer"),
        (_record(pbes_gap="unknown"), "numeric pbes_gap"),
    ],
)
def test_validate_source_dataset_rejects_invalid_records(tmp_path, row, message):
    _write_split(tmp_path / "train.csv", [row])
    _write_split(tmp_path / "val.csv", [_record("1")])

    with pytest.raises(DataContractError, match=message):
        validate_source_dataset(tmp_path, role="candidate")
