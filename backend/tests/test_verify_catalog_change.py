import pytest

from scripts.datasets.verify_catalog_change import (
    check_candidate_urls,
    check_urls,
    duplicate_candidates,
    proposed_sources,
    data_path_collisions,
    proposed_downloads,
    stale_prose,
    verify,
)


class _StubPoller:
    def __init__(self, headers=None, raises=None, status=200):
        self._headers = headers or {}
        self._raises = raises
        self._status = status

    def head(self, url):
        if self._raises:
            raise self._raises
        return self._headers

    def status(self, url):
        if self._raises:
            raise self._raises
        return self._status


def _catalog(*sources):
    return {"schema_version": 2, "sources": list(sources)}


def _source(sid="cod", downloads=(), **extra):
    return {
        "id": sid, "name": sid, "access": "open",
        "official_url": "https://example.org", "license": "CC0",
        "data_path": f"raw/acquired/{sid}", "downloads": list(downloads), **extra,
    }


def _dl(name, url, size=10):
    return {"filename": name, "url": url, "bytes": size}


def test_only_added_or_altered_entries_count_as_proposed():
    kept = _dl("a.csv", "https://h/records/1/files/a.csv/content")
    before = _catalog(_source(downloads=[kept]))
    after = _catalog(_source(downloads=[kept, _dl("b.csv", "https://h/records/1/files/b.csv/content")]))
    proposed = proposed_downloads(before, after)
    assert [p["filename"] for p in proposed] == ["b.csv"]
    # an unchanged catalog proposes nothing
    assert proposed_downloads(before, before) == []
    # a changed byte count on an existing entry is a proposal too
    altered = _catalog(_source(downloads=[{**kept, "bytes": 99}]))
    assert [p["bytes"] for p in proposed_downloads(before, altered)] == [99]


def test_two_sources_cannot_claim_one_data_path():
    clash = _catalog(_source("cod"), {**_source("icsd"), "data_path": "raw/acquired/cod"})
    assert len(data_path_collisions(clash)) == 1
    assert data_path_collisions(_catalog(_source("cod"), _source("icsd"))) == []


def test_prose_naming_a_replaced_upstream_id_is_a_problem():
    old = _dl("a.csv", "https://zenodo.org/api/records/3677685/files/a.csv/content")
    new = _dl("b.csv", "https://zenodo.org/api/records/14184621/files/b.csv/content")
    before = _catalog(_source(downloads=[old]))
    after = _catalog(_source(downloads=[new], notes="taken from record 3677685"))
    problems = stale_prose(before, after)
    assert len(problems) == 1 and "3677685" in problems[0]

    # silent when the prose was updated with the plan
    fixed = _catalog(_source(downloads=[new], notes="taken from record 14184621"))
    assert stale_prose(before, fixed) == []
    # silent when the id is still in use by a remaining entry
    both = _catalog(_source(downloads=[old, new], notes="record 3677685"))
    assert stale_prose(before, both) == []
    # silent when the plan drops nothing
    assert stale_prose(before, _catalog(_source(downloads=[old], notes="record 3677685"))) == []


def test_a_url_is_ok_only_when_it_resolves_at_the_size_claimed():
    entry = [{"source_id": "cod", "filename": "a.csv",
              "url": "https://h/a.csv", "bytes": 10}]
    assert check_urls(entry, _StubPoller({"content-length": "10"}))[0]["verdict"] == "ok"
    assert "size mismatch" in check_urls(entry, _StubPoller({"content-length": "11"}))[0]["verdict"]
    assert "no content-length" in check_urls(entry, _StubPoller({}))[0]["verdict"]
    assert check_urls(entry, _StubPoller(raises=TimeoutError("slow")))[0]["verdict"].startswith(
        "TimeoutError"
    )
    # a plan that claims no size cannot be contradicted, and says so
    sizeless = [{"source_id": "cod", "filename": "a.csv", "url": "https://h/a.csv"}]
    assert "claims no size" in check_urls(sizeless, _StubPoller({"content-length": "10"}))[0]["verdict"]


def test_an_invalid_catalog_stops_before_any_request_is_made():
    before = _catalog(_source())
    broken = _catalog(_source(downloads=[_dl("a.csv", "http://insecure/a.csv")]))
    poller = _StubPoller(raises=AssertionError("must not be called"))
    report = verify(before, broken, poller, free_bytes=10**12)
    assert len(report["problems"]) == 1
    assert "does not validate" in report["problems"][0]
    assert report["proposed"] == []


def test_a_plan_that_would_eat_the_reserve_is_refused():
    before = _catalog(_source())
    after = _catalog(_source(downloads=[_dl("big.zip", "https://h/big.zip", size=10**12)]))
    report = verify(after=after, before=before, poller=_StubPoller({"content-length": str(10**12)}),
                    free_bytes=10**12)
    assert any("reserve" in p for p in report["problems"])


def test_a_sound_plan_reports_no_problem():
    before = _catalog(_source())
    after = _catalog(_source(downloads=[_dl("a.csv", "https://h/a.csv", size=10)]))
    report = verify(before, after, _StubPoller({"content-length": "10"}), free_bytes=10**12)
    assert report["problems"] == []
    assert report["expected_bytes"] == 10


def test_only_sources_the_diff_adds_count_as_candidates():
    before = _catalog(_source("cod"))
    after = _catalog(_source("cod"), _source("newdb"))
    assert [s["id"] for s in proposed_sources(before, after)] == ["newdb"]
    assert proposed_sources(before, before) == []


def test_a_candidate_the_catalog_already_holds_is_refused():
    before = _catalog({**_source("cod"), "name": "Crystallography Open Database",
                       "official_url": "https://www.crystallography.net/cod/"})
    # the same official_url, trailing slash and case aside
    same_url = [{**_source("cod2"), "name": "Whatever",
                 "official_url": "https://www.crystallography.net/cod"}]
    assert len(duplicate_candidates(before, same_url)) == 1
    # the same name, punctuation and case aside
    same_name = [{**_source("cod3"), "name": "crystallography open database",
                  "official_url": "https://elsewhere.example/"}]
    assert len(duplicate_candidates(before, same_name)) == 1
    # a host only one source uses is that source's own domain
    same_host = [{**_source("codmirror"), "name": "Something else",
                  "official_url": "https://www.crystallography.net/other"}]
    assert len(duplicate_candidates(before, same_host)) == 1
    # genuinely new on every count
    fresh = [{**_source("newdb"), "name": "Some New DB",
              "official_url": "https://newdb.example/"}]
    assert duplicate_candidates(before, fresh) == []


def test_a_shared_platform_host_is_not_evidence_of_duplication():
    # 46 of the catalog's 106 sources sit on 13 shared hosts, figshare.com alone
    # carrying 8, so a shared host must not reject a new figshare-hosted dataset
    before = _catalog(
        {**_source("hmof"), "name": "hMOF",
         "official_url": "https://figshare.com/articles/dataset/15127758"},
        {**_source("snumat"), "name": "SNUMAT",
         "official_url": "https://figshare.com/articles/dataset/21713885"},
    )
    candidate = [{**_source("newdb"), "name": "Some New DB",
                  "official_url": "https://figshare.com/articles/dataset/19601956"}]
    assert duplicate_candidates(before, candidate) == []


def test_a_candidate_reports_its_urls_and_says_when_a_licence_url_is_absent():
    added = [{**_source("newdb"), "official_url": "https://newdb.example/"}]
    check = check_candidate_urls(added, _StubPoller(status=200))[0]
    assert check["official_url"] == "http-200"
    # the catalog has no licence_url field, so absence is reported, not passed over
    assert check["licence_url"] == "not supplied"

    with_licence = [{**added[0], "licence_url": "https://newdb.example/terms"}]
    assert check_candidate_urls(with_licence, _StubPoller(status=200))[0]["licence_url"] == "http-200"
    # an unreachable official_url is recorded rather than raised
    broken = check_candidate_urls(added, _StubPoller(raises=TimeoutError("slow")))[0]
    assert broken["official_url"].startswith("TimeoutError")


def test_a_candidate_whose_official_url_does_not_resolve_is_a_problem():
    before = _catalog(_source("cod"))
    after = _catalog(_source("cod"), {**_source("newdb"), "official_url": "https://newdb.example/"})
    report = verify(before, after, _StubPoller(status=404), free_bytes=10**12)
    assert any("official_url http-404" in p for p in report["problems"])
    # and a resolving one raises no problem, while still being reported
    ok = verify(before, after, _StubPoller(status=200), free_bytes=10**12)
    assert ok["problems"] == []
    assert ok["candidates"][0]["source_id"] == "newdb"
