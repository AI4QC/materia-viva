import json

from src.agents.detectors import mentions_of, stale_upstream_ids, unit_disagreements
from src.agents.detectors import CATALOG


def test_mentions_of_finds_the_adapter_that_already_ingests_a_name():
    # the deduplication signal the gate cannot see: CAMD was refused as a
    # candidate only because a person read odbx.py and found the word there
    found = mentions_of("CAMD")
    assert any(m.where == "adapters/odbx.py" for m in found)
    # a name nothing ingests finds nothing
    assert mentions_of("definitely-not-a-database-xyz") == []


def test_mentions_of_matches_whole_words_only(tmp_path):
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    (adapters / "a.py").write_text('"""camdenite is a mineral, unrelated."""\n', encoding="utf-8")
    catalog = tmp_path / "sources.json"
    catalog.write_text(json.dumps({"sources": []}), encoding="utf-8")
    assert mentions_of("CAMD", catalog=catalog, adapters=adapters) == []


def test_unit_disagreements_finds_an_adapter_that_contradicts_the_registry(tmp_path):
    # Against a fixture rather than against whichever bug the tree happens to
    # hold: this used to assert mc2d's factor of 1000 was present, so fixing
    # that broke the test for the detector. What is under test is the detector.
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    (adapters / "wrong.py").write_text(
        'PropertyValue("interlayer_binding_energy", x, "eV/Å²", "m")\n', encoding="utf-8"
    )
    (adapters / "right.py").write_text(
        'PropertyValue("interlayer_binding_energy", x, "meV/Å²", "m")\n', encoding="utf-8"
    )
    found = unit_disagreements(adapters=adapters)
    assert found == [("wrong", "interlayer_binding_energy", "eV/Å²", "meV/Å²")]


def test_mc2d_no_longer_contradicts_the_registry():
    # the factor of 1000 this detector was built to find. The golden sample in
    # backend/tests/golden/mc2d holds the conversion itself; this holds the
    # label, which is the half a static pass can see.
    assert not [d for d in unit_disagreements() if d[0] == "mc2d"]


def test_stale_upstream_ids_does_not_mistake_a_count_for_a_record():
    # the first version of this flagged oqmd's byte count, aflow's structure count
    # and carolina's record counts — five hits, none of them real. A check that
    # cries wolf trains people to ignore it.
    assert stale_upstream_ids(json.loads(CATALOG.read_text(encoding="utf-8"))) == []


def test_stale_upstream_ids_fires_when_the_prose_names_a_record_the_urls_left():
    catalog = {
        "sources": [
            {
                "id": "carolina",
                "status": "downloaded-verified-zenodo-8381476-214435-records",
                "downloads": [
                    {"url": "https://zenodo.org/api/records/10768743/files/x/content"}
                ],
            }
        ]
    }
    assert stale_upstream_ids(catalog) == [("carolina", "status", "8381476")]
    # the record count in the same string is not an upstream id and is left alone
    assert all(found[2] != "214435" for found in stale_upstream_ids(catalog))


def test_a_source_with_no_download_urls_is_not_examined():
    catalog = {"sources": [{"id": "icsd", "status": "zenodo-1234567", "downloads": []}]}
    assert stale_upstream_ids(catalog) == []
