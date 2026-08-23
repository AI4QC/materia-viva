import json
from pathlib import Path

from scripts.datasets.acquire import load_catalog
from scripts.datasets.probe_upstream import (
    diff_against,
    merge_probes,
    plan_probe,
    plan_probes,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG = REPO_ROOT / "scripts" / "datasets" / "sources.json"


def _plans():
    return plan_probes(load_catalog(CATALOG))


def test_every_catalog_source_gets_a_plan():
    catalog = load_catalog(CATALOG)
    plans = _plans()
    assert set(plans) == {source["id"] for source in catalog["sources"]}


def test_invenio_records_probe_the_latest_sibling_version():
    plans = _plans()
    # zenodo, and materials cloud in both its `/api/records/` and `/records/` forms
    for source_id, host in [
        ("core-mof", "zenodo.org"),
        ("mc2d", "archive.materialscloud.org"),
        ("mad-static", "archive.materialscloud.org"),
    ]:
        probe = plans[source_id]
        assert probe.kind == "invenio-latest", source_id
        assert probe.endpoint.startswith(f"https://{host}/api/records/")
        assert probe.endpoint.endswith("/versions/latest")
        assert probe.known


def test_hf_and_github_sources_probe_a_revision():
    plans = _plans()
    assert plans["elementa"].kind == "hf-revision"
    assert (
        plans["elementa"].endpoint
        == "https://huggingface.co/api/datasets/kairosmaterial/ELEMENTA"
    )
    obelix = plans["obelix"]
    assert obelix.kind == "git-commit"
    assert "NRC-Mila/OBELiX/commits" in obelix.endpoint
    # path-scoped, so an unrelated commit elsewhere in the repository is not a change
    assert "path=data/downloads/" in obelix.endpoint


def test_figshare_and_endpointless_sources_are_reported_as_unprobeable():
    plans = _plans()
    # figshare stores an immutable file id, so a new article version is invisible
    for source_id in ("aflow", "c2db", "2dmatpedia"):
        probe = plans[source_id]
        assert probe.kind == "manual"
        assert probe.note == "figshare-file-id-is-not-version-addressable"
    # licensed and browse-only sources have no download endpoint at all
    assert plans["icsd"].note == "no-download-endpoint"
    assert plans["magndata"].note == "no-download-endpoint"


def test_probeable_share_of_the_catalog_is_reported_honestly():
    plans = _plans()
    probeable = [p for p in plans.values() if p.kind != "manual"]
    # automated detection covers a minority of the catalog by design; this guards
    # against a regex regression silently shrinking the covered set
    assert len(probeable) >= 30
    assert len(probeable) < len(plans) / 2


def test_plan_probe_prefers_the_first_recognised_url():
    source = {
        "id": "example",
        "downloads": [
            {"url": "https://example.org/whatever.zip"},
            {"url": "https://zenodo.org/api/records/1234/files/a.zip/content"},
        ],
    }
    # an unrecognised first URL must not shadow a version-addressable later one
    assert plan_probe(source).kind == "invenio-latest"


def test_diff_against_classifies_each_outcome():
    previous = {
        "probes": {
            "stable": {"kind": "hf-revision", "seen": "aaa"},
            "moved": {"kind": "hf-revision", "seen": "aaa"},
            "was-blank": {"kind": "http-head", "seen": None},
        }
    }
    current = {
        "stable": {"kind": "hf-revision", "seen": "aaa"},
        "moved": {"kind": "hf-revision", "seen": "bbb"},
        "was-blank": {"kind": "http-head", "seen": "etag"},
        "fresh": {"kind": "git-commit", "seen": "ccc"},
        "broken": {"kind": "git-commit", "seen": None, "error": "http-404"},
        "hand-checked": {"kind": "manual", "seen": None},
    }
    verdict = diff_against(previous, current)
    assert verdict["unchanged"] == ["stable"]
    assert verdict["changed"] == ["moved"]
    assert sorted(verdict["first-seen"]) == ["fresh", "was-blank"]
    assert verdict["failed"] == ["broken"]
    assert verdict["unprobeable"] == ["hand-checked"]


def test_a_partial_run_keeps_the_sources_it_did_not_probe():
    previous = {"probes": {"kept": {"seen": "old"}, "reprobed": {"seen": "old"}, "gone": {}}}
    results = {"reprobed": {"seen": "new"}}
    merged = merge_probes(previous, results, {"kept", "reprobed"})
    assert merged == {"kept": {"seen": "old"}, "reprobed": {"seen": "new"}}


def test_written_probe_file_is_json_with_one_entry_per_source():
    out = REPO_ROOT / "data" / "probe" / "seen.json"
    if not out.exists():
        return  # the probe has not been run on this machine
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload["probes"]) == set(_plans())
