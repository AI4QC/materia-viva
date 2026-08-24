import json
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

from scripts.properties.load import FINGERPRINT_UNRELIABLE
from scripts.snapshot_meta import describe, diff_snapshots, fingerprint_identity


def _index(path, sources, materials, refs, properties, metadata=None):
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);"
        "CREATE TABLE source_defs (id INTEGER PRIMARY KEY, key TEXT, name TEXT,"
        " license TEXT, url TEXT);"
        "CREATE TABLE materials (pk INTEGER PRIMARY KEY, is_experimental INTEGER);"
        "CREATE TABLE material_source_refs (material_pk INTEGER, source_id INTEGER,"
        " native_id TEXT, match_via TEXT);"
        "CREATE TABLE material_properties (material_pk INTEGER, property_id INTEGER,"
        " source_id INTEGER, native_id TEXT, value_num REAL, value_text TEXT, method TEXT);"
    )
    db.executemany("INSERT INTO source_defs VALUES (?, ?, ?, ?, ?)", sources)
    db.executemany("INSERT INTO materials VALUES (?, ?)", materials)
    db.executemany("INSERT INTO material_source_refs VALUES (?, ?, ?, ?)", refs)
    db.executemany(
        "INSERT INTO material_properties VALUES (?, ?, ?, ?, ?, ?, ?)", properties
    )
    db.executemany("INSERT INTO metadata VALUES (?, ?)", (metadata or {}).items())
    db.commit()
    db.close()
    return path


def _catalog(path, entries):
    path.write_text(json.dumps({"schema_version": 2, "sources": entries}), encoding="utf-8")
    return path


def test_describe_reads_counts_licences_and_the_upstream_token(tmp_path):
    index = _index(
        tmp_path / "i.sqlite",
        sources=[(1, "cod", "COD", "CC0", "https://x"), (2, "icsd", "ICSD", "FIZ licence", "https://y")],
        materials=[(1, 1), (2, 0), (3, 0)],
        refs=[(1, 1, "c1", "hash"), (2, 1, "c2", "hash"), (3, 2, "i1", "id:icsd")],
        properties=[(1, 1, 1, "c1", 1.0, None, "experiment"), (3, 1, 2, "i1", 2.0, None, "experiment")],
        metadata={"schema_version": "3", "property_row_count": "2", "curve_count": "7"},
    )
    catalog = _catalog(
        tmp_path / "sources.json",
        [
            {"id": "cod", "license": "CC0", "state": "integrated"},
            {"id": "icsd", "license": "FIZ licence", "state": "integrated"},
        ],
    )
    probe = tmp_path / "seen.json"
    probe.write_text(json.dumps({"probes": {"cod": {"seen": "tok-1", "checked_at": "2026-08-24"}}}),
                     encoding="utf-8")

    snapshot = describe(index, catalog, probe)
    assert snapshot["index"] == {
        "schema_version": "3", "materials": 3, "experimental": 1,
        "computational": 2, "property_rows": 2, "curves": 7,
    }
    by_id = {s["source_id"]: s for s in snapshot["sources"]}
    assert by_id["cod"]["materials"] == 2 and by_id["cod"]["property_rows"] == 1
    assert by_id["cod"]["upstream_seen"] == "tok-1"
    # a source the probe cannot reach simply has no token
    assert by_id["icsd"]["upstream_seen"] is None
    assert by_id["icsd"]["licence_in_index"] == "FIZ licence"


def test_describe_survives_an_index_without_a_schema_version(tmp_path):
    # the published slice has no schema_version row; that must not be fatal
    index = _index(tmp_path / "i.sqlite", [(1, "cod", "COD", "CC0", "u")], [(1, 0)], [], [])
    snapshot = describe(index, _catalog(tmp_path / "s.json", [{"id": "cod"}]), None)
    assert snapshot["index"]["schema_version"] is None
    assert snapshot["index"]["property_rows"] == 0


def test_the_fingerprint_identity_carries_the_composite_key_sources():
    identity = fingerprint_identity()
    assert identity["max_sites"] == 500 and identity["max_primitive_sites"] == 300
    # part of the algorithm's definition: rebuilding without it merges differently
    assert identity["fingerprint_unreliable_sources"] == sorted(FINGERPRINT_UNRELIABLE)
    # the composite-key admissions have no constant to import, so the scripts
    # that implement them are what this list is pinned to
    assert identity["composite_key_admissions"] == ["deem-zeolites", "hmof"]
    properties_dir = REPO_ROOT / "scripts" / "properties"
    assert (properties_dir / "deem_zeolite_admit.py").exists()
    assert (properties_dir / "hmof_composite_admit.py").exists()


def _snapshot(sources, index=None, fingerprint=None):
    return {
        "index": index or {"schema_version": "3", "materials": 10, "experimental": 4,
                           "computational": 6, "property_rows": 100, "curves": 0},
        "fingerprint": fingerprint or fingerprint_identity(),
        "sources": sources,
    }


def _source(sid, materials=1, rows=1, licence="CC BY 4.0", state="integrated", reason=None):
    return {"source_id": sid, "name": sid, "licence_in_index": licence,
            "licence_in_catalog": licence, "state": state, "reason": reason,
            "materials": materials, "property_rows": rows,
            "upstream_seen": None, "upstream_checked_at": None}


def test_two_reports_of_the_same_snapshot_differ_in_nothing():
    snapshot = _snapshot([_source("cod"), _source("icsd")])
    report = diff_snapshots(snapshot, json.loads(json.dumps(snapshot)))
    assert report["sources_added"] == [] and report["sources_removed"] == []
    assert report["moved"] == [] and report["licence_changes"] == []
    assert report["state_changes"] == []
    assert all(v["delta"] == 0 for v in report["totals"].values())
    assert "fingerprint_changed" not in report


def test_a_licence_that_only_changed_punctuation_is_not_reported():
    before = _snapshot([_source("cod", licence="CC BY 4.0")])
    after = _snapshot([_source("cod", licence="cc-by-4.0")])
    assert diff_snapshots(before, after)["licence_changes"] == []


def test_the_report_names_what_moved(tmp_path):
    before = _snapshot([_source("cod", materials=5, rows=50), _source("gone")])
    after = _snapshot(
        [
            _source("cod", materials=7, rows=48, licence="CC BY-NC 4.0"),
            _source("fresh", state="acquired"),
        ],
        index={"schema_version": "4", "materials": 12, "experimental": 4,
               "computational": 8, "property_rows": 98, "curves": 0},
    )
    report = diff_snapshots(before, after)
    assert report["sources_added"] == [{"source_id": "fresh", "state": "acquired", "reason": None}]
    assert report["sources_removed"] == [{"source_id": "gone", "state": "integrated", "reason": None}]
    assert report["moved"] == [{"source_id": "cod", "materials": 2, "property_rows": -2}]
    # a real licence change survives normalising and must be surfaced
    assert report["licence_changes"] == [
        {"source_id": "cod", "before": "CC BY 4.0", "after": "CC BY-NC 4.0"}
    ]
    assert report["totals"]["materials"]["delta"] == 2
    assert report["schema_version_changed"] == {"before": "3", "after": "4"}


def test_a_changed_fingerprint_is_reported_as_a_renumbering_event():
    before = _snapshot([_source("cod")])
    moved = dict(fingerprint_identity(), max_primitive_sites=400)
    report = diff_snapshots(before, _snapshot([_source("cod")], fingerprint=moved))
    assert "old_id to new_id" in report["fingerprint_changed"]["consequence"]


def test_a_state_change_is_reported_with_its_reason():
    before = _snapshot([_source("catalysis-hub", state="acquired")])
    after = _snapshot([_source("catalysis-hub", state="rejected", reason="join-key-missing")])
    assert diff_snapshots(before, after)["state_changes"] == [
        {"source_id": "catalysis-hub", "before": ["acquired", None],
         "after": ["rejected", "join-key-missing"]}
    ]
