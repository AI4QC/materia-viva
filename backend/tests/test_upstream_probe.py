from pathlib import Path

from scripts.datasets.acquire import load_catalog
from scripts.datasets.probe_upstream import (
    Probe,
    diff_against,
    merge_probes,
    plan_probe,
    plan_probes,
    run_probe,
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
    # figshare stores an immutable file id, so without the article id a new
    # version of the dataset is invisible
    for source_id in ("aflow", "c2db", "2dmatpedia"):
        probe = plans[source_id]
        assert probe.kind == "manual"
        assert probe.note == "figshare-article-id-unknown"
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


class _StubPoller:
    """Stands in for the network: canned payloads, or an exception to raise."""

    def __init__(self, payload=None, headers=None, raises=None):
        self._payload = payload
        self._headers = headers or {}
        self._raises = raises

    def json(self, url):
        if self._raises:
            raise self._raises
        return self._payload

    def head(self, url):
        if self._raises:
            raise self._raises
        return self._headers


def test_github_release_archive_urls_probe_a_commit():
    # github.com/<owner>/<repo>/archive/refs/heads/<branch>.zip is a fourth github
    # form; before it was recognised, superband fell back to a HEAD on a mirror
    source = {
        "id": "example",
        "downloads": [
            {"url": "https://github.com/ljcj007/SuperBand/archive/refs/heads/main.zip"}
        ],
    }
    probe = plan_probe(source)
    assert probe.kind == "git-commit"
    assert "ljcj007/SuperBand/commits?sha=main" in probe.endpoint


def test_invenio_payload_reports_the_superseding_record():
    probe = Probe("core-mof", "invenio-latest", endpoint="https://zenodo.org/x", known="3677685")
    payload = {"id": 14184621, "metadata": {"version": "2.0.1"}}
    result = run_probe(probe, _StubPoller(payload))
    assert result["seen"] == "14184621:2.0.1"
    assert result["latest_version"] == "2.0.1"
    # the headline output: the catalog still points at the record we ingested
    assert result["catalog_points_at_older_record"] == "3677685"


def test_invenio_payload_at_the_latest_record_reports_no_lag():
    probe = Probe("deem", "invenio-latest", endpoint="https://zenodo.org/x", known="8035241")
    result = run_probe(probe, _StubPoller({"id": 8035241, "metadata": {"version": "2.1"}}))
    assert result["seen"] == "8035241:2.1"
    assert "catalog_points_at_older_record" not in result


def test_each_probe_kind_extracts_its_own_token():
    hf = run_probe(
        Probe("elementa", "hf-revision", endpoint="https://hf/x"), _StubPoller({"sha": "abc123"})
    )
    assert hf["seen"] == "abc123"

    git = run_probe(
        Probe("obelix", "git-commit", endpoint="https://api.github.com/x"),
        _StubPoller([{"sha": "def456"}]),
    )
    assert git["seen"] == "def456"

    head = run_probe(
        Probe("oqmd", "http-head", endpoint="https://static/x"),
        _StubPoller(headers={"etag": '"a90506cf"'}),
    )
    assert head["seen"] == '"a90506cf"'

    manual = run_probe(Probe("icsd", "manual", note="no-download-endpoint"), _StubPoller())
    assert manual["seen"] is None
    assert manual["note"] == "no-download-endpoint"


def test_a_host_that_sends_no_validator_is_named_as_such():
    result = run_probe(Probe("sacada", "http-head", endpoint="https://x"), _StubPoller(headers={}))
    assert result["seen"] is None
    assert result["note"] == "host-sends-no-etag-or-last-modified"


def test_an_empty_commit_list_is_not_mistaken_for_a_token():
    result = run_probe(Probe("x", "git-commit", endpoint="https://x"), _StubPoller([]))
    assert result["seen"] is None
    assert result["note"] == "no-commit-touches-the-stored-path"


def test_one_failing_host_is_recorded_and_does_not_raise():
    result = run_probe(
        Probe("x", "hf-revision", endpoint="https://x"), _StubPoller(raises=TimeoutError("slow"))
    )
    assert result["seen"] is None
    assert result["error"].startswith("TimeoutError")


def test_a_failed_probe_does_not_erase_the_token_it_already_had():
    # one transient failure must not demote the next genuine change to first-seen
    previous = {"probes": {"core-mof": {"seen": "14184621:2.0.1", "kind": "invenio-latest"}}}
    failed = {"core-mof": {"kind": "invenio-latest", "seen": None, "error": "http-503"}}
    merged = merge_probes(previous, failed, {"core-mof"})
    assert merged["core-mof"]["seen"] == "14184621:2.0.1"
    assert merged["core-mof"]["seen_carried_over"] is True
    assert merged["core-mof"]["error"] == "http-503"
    # and the carried token still classifies a later real change as changed
    verdict = diff_against({"probes": merged}, {"core-mof": {"kind": "invenio-latest", "seen": "9:3.0"}})
    assert verdict["changed"] == ["core-mof"]


def test_figshare_article_id_comes_from_official_url_when_it_is_there():
    plans = _plans()
    for source_id in ("hmof", "matbench-discovery", "hofsyn"):
        probe = plans[source_id]
        assert probe.kind == "figshare-article", source_id
        assert probe.endpoint.startswith("https://api.figshare.com/v2/articles/")
    # the id is the last number in the path, not the first, so a title carrying
    # digits does not shadow it
    source = {
        "id": "example",
        "official_url": "https://figshare.com/articles/dataset/Matbench_Discovery_v1_0_0/22715158",
        "downloads": [{"url": "https://ndownloader.figshare.com/files/40344436"}],
    }
    assert plan_probe(source).endpoint.endswith("/22715158")


def test_a_recorded_article_id_beats_the_official_url():
    # hex-high-pressure's official_url is a *collection*, whose id is not the
    # article id, so the looked-up value has to win
    source = {
        "id": "hex",
        "official_url": "https://springernature.figshare.com/collections/HEX/7119778",
        "figshare_article": 25403968,
        "downloads": [{"url": "https://ndownloader.figshare.com/files/45020533"}],
    }
    probe = plan_probe(source)
    assert probe.kind == "figshare-article"
    assert probe.endpoint.endswith("/25403968")

    # and without the recorded id, a collection URL is not mistaken for an article
    del source["figshare_article"]
    assert plan_probe(source).kind == "manual"


def test_a_figshare_article_reports_its_version_as_the_token():
    probe = Probe("hmof", "figshare-article", endpoint="https://api.figshare.com/v2/articles/1")
    assert run_probe(probe, _StubPoller({"version": 2}))["seen"] == "2"
