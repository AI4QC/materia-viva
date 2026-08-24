from scripts.datasets.plan_upgrade import (
    _normalise_licence,
    derive,
    recorded_for,
    route_for,
    upstream_files,
)
from scripts.datasets.probe_upstream import Probe

ZENODO = Probe("x", "invenio-latest", endpoint="https://zenodo.org/api/records/1/versions/latest", known="1")


class _StubPoller:
    def __init__(self, payload):
        self._payload = payload

    def json(self, url):
        return self._payload

    def head(self, url):
        return {"content-length": "10"}


def test_route_follows_how_much_of_the_recorded_list_survives():
    assert route_for(["a", "b"], ["a", "b"]) == "mechanical"
    assert route_for(["a"], ["a", "b"]) == "delta"
    assert route_for([], ["a", "b"]) == "restructured"
    assert route_for([], []) == "nothing-recorded"


def test_licences_compare_by_content_not_punctuation():
    # upstream says cc-by-4.0 where the catalog says CC BY 4.0
    assert _normalise_licence("CC BY 4.0") == _normalise_licence("cc-by-4.0")
    assert _normalise_licence("CC BY-NC 4.0") == _normalise_licence({"id": "cc-by-nc-4.0"})
    # but a genuinely different licence must still differ
    assert _normalise_licence("CC BY 4.0") != _normalise_licence("cc-by-nc-4.0")


def test_only_the_probed_hosts_files_are_compared():
    # carolina mirrors one archive from zenodo and two parquet files from a
    # Hugging Face dataset; comparing all three against zenodo's file list
    # reported the Hugging Face pair as vanished
    source = {
        "downloads": [
            {"filename": "bulk/z/carolina_matdb.zip",
             "url": "https://zenodo.org/api/records/8381476/files/carolina_matdb.zip/content"},
            {"filename": "bulk/hf/co_0.parquet",
             "url": "https://huggingface.co/datasets/colabfit/C/resolve/main/co/co_0.parquet"},
            {"filename": "bulk/hf/ds.parquet",
             "url": "https://huggingface.co/datasets/colabfit/C/resolve/main/ds.parquet"},
        ]
    }
    probe = Probe("carolina", "invenio-latest", endpoint="https://zenodo.org/x", known="8381476")
    mine, others = recorded_for(probe, source)
    assert mine == ["bulk/z/carolina_matdb.zip"]
    assert others == 2


def test_upstream_files_reads_both_invenio_shapes_and_figshare():
    # zenodo answers with a list
    legacy = upstream_files(ZENODO, {"id": 99, "files": [{"key": "a.csv", "size": 5}]})
    assert legacy == [
        {"name": "a.csv", "bytes": 5,
         "url": "https://zenodo.org/api/records/99/files/a.csv/content"}
    ]
    # InvenioRDM keys its files by name
    rdm_probe = Probe("y", "invenio-latest", endpoint="https://archive.materialscloud.org/x", known="p")
    rdm = upstream_files(rdm_probe, {"id": "abc-1", "files": {"entries": {"b.zip": {"key": "b.zip", "size": 7}}}})
    assert rdm[0]["url"] == "https://archive.materialscloud.org/api/records/abc-1/files/b.zip/content"
    # figshare hands over the download URL itself
    fig = Probe("z", "figshare-article", endpoint="https://api.figshare.com/v2/articles/5")
    assert upstream_files(fig, {"files": [{"name": "c.zip", "size": 9, "download_url": "https://n/1"}]}) == [
        {"name": "c.zip", "bytes": 9, "url": "https://n/1"}
    ]


def test_a_mechanical_upgrade_proposes_the_new_urls_and_keeps_local_paths():
    source = {
        "license": "CC BY 4.0",
        "downloads": [{"filename": "bulk/old-1/a.csv",
                       "url": "https://zenodo.org/api/records/1/files/a.csv/content"}],
    }
    payload = {"id": 2, "files": [{"key": "a.csv", "size": 11}],
               "metadata": {"license": {"id": "cc-by-4.0"}}}
    plan = derive(source, ZENODO, _StubPoller(payload))
    assert plan["route"] == "mechanical"
    # the local destination is preserved; only the URL moves to the new record
    assert plan["proposed_downloads"] == [
        {"filename": "bulk/old-1/a.csv",
         "url": "https://zenodo.org/api/records/2/files/a.csv/content", "bytes": 11}
    ]
    assert plan["licence"]["verdict"] == "same"
    # the old record id is still written into the local path, which is a human call
    assert plan["local_paths_name_the_old_record"] == ["bulk/old-1/a.csv"]


def test_a_changed_licence_is_sent_back_to_the_gate():
    source = {"license": "CC BY 4.0",
              "downloads": [{"filename": "a.csv",
                             "url": "https://zenodo.org/api/records/1/files/a.csv/content"}]}
    payload = {"id": 1, "files": [{"key": "a.csv", "size": 1}],
               "metadata": {"license": {"id": "cc-by-nc-4.0"}}}
    plan = derive(source, ZENODO, _StubPoller(payload))
    assert plan["licence"]["verdict"] == "differs-return-to-the-licence-gate"


def test_sources_whose_urls_do_not_move_are_left_alone():
    # a new Hugging Face revision or git commit arrives at the same address, so
    # the recorded plan still applies and nothing needs deriving
    for kind in ("hf-revision", "git-commit", "http-head", "manual"):
        plan = derive({}, Probe("x", kind, endpoint="https://x"), _StubPoller({}))
        assert plan["route"] == "urls-unchanged", kind
