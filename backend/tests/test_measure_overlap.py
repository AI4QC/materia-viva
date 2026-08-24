import gzip
import json
import sqlite3

import pytest

from scripts.properties.measure_overlap import main, measure, read_fingerprints


def _match_map(path, hash_rows, id_rows):
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE hash_map (hash TEXT NOT NULL, material_id TEXT NOT NULL);"
        "CREATE TABLE id_map (source TEXT NOT NULL, native_id TEXT NOT NULL,"
        " material_id TEXT NOT NULL);"
    )
    db.executemany("INSERT INTO hash_map VALUES (?, ?)", hash_rows)
    db.executemany("INSERT INTO id_map VALUES (?, ?, ?)", id_rows)
    db.commit()
    db.close()


def _hashes_file(path, rows, gzipped=False):
    body = "native_id\tn_sites\tformula\tbawl_hash\n" + "".join(
        f"{native}\t{n}\tX\t{h}\n" for native, n, h in rows
    )
    if gzipped:
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(body)
    else:
        path.write_text(body, encoding="utf-8")
    return path


def test_failures_are_tallied_by_reason_and_never_counted_as_structures(tmp_path):
    path = _hashes_file(
        tmp_path / "h.tsv",
        [
            ("a", 10, "hash-1"),
            ("b", 900, "FAIL:TOO_LARGE"),
            ("c", 12, "FAIL:DISORDERED"),
            ("d", 800, "FAIL:TOO_LARGE"),
            ("e", 4, "hash-2"),
        ],
    )
    fingerprints, failures = read_fingerprints(path)
    assert fingerprints == ["hash-1", "hash-2"]
    assert dict(failures) == {"TOO_LARGE": 2, "DISORDERED": 1}


def test_a_failure_reason_keeps_only_its_leading_token(tmp_path):
    # hashing.py writes FAIL:<reason>:<repr of the exception>
    path = _hashes_file(tmp_path / "h.tsv", [("a", 1, "FAIL:BAD_ROW:ValueError('x: y')")])
    _, failures = read_fingerprints(path)
    assert dict(failures) == {"BAD_ROW": 1}


def test_gzipped_and_plain_files_read_the_same(tmp_path):
    rows = [("a", 1, "hash-1"), ("b", 2, "FAIL:TOO_LARGE")]
    plain = read_fingerprints(_hashes_file(tmp_path / "h.tsv", rows))
    packed = read_fingerprints(_hashes_file(tmp_path / "h.tsv.gz", rows, gzipped=True))
    assert plain == packed


def test_a_file_without_the_fingerprint_column_is_refused(tmp_path):
    path = tmp_path / "h.tsv"
    path.write_text("native_id\tn_sites\n a\t1\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no bawl_hash column"):
        read_fingerprints(path)


def test_overlap_counts_unique_structures_and_names_the_sources_holding_them(tmp_path):
    match_map = tmp_path / "map.sqlite"
    _match_map(
        match_map,
        [("hash-1", "mv-1"), ("hash-2", "mv-2")],
        [("cod", "c1", "mv-1"), ("icsd", "i1", "mv-1"), ("cod", "c2", "mv-2")],
    )
    # hash-1 twice: a candidate repeating a structure must not inflate the count
    result = measure(["hash-1", "hash-1", "hash-2", "hash-9"], match_map)
    assert result["rows_with_a_fingerprint"] == 4
    assert result["unique_fingerprints"] == 3
    assert result["already_in_the_pool"] == 2
    assert result["new_to_the_pool"] == 1
    assert result["new_fraction_of_unique"] == pytest.approx(1 / 3, abs=1e-4)
    assert result["overlap_by_existing_source"] == [
        {"source": "cod", "materials": 2},
        {"source": "icsd", "materials": 1},
    ]


def test_a_candidate_the_pool_already_holds_entirely_reports_nothing_new(tmp_path):
    # the open-materials-db shape: everything in it comes from a source we have
    match_map = tmp_path / "map.sqlite"
    _match_map(match_map, [("h1", "mv-1"), ("h2", "mv-2")], [("cod", "c1", "mv-1"), ("cod", "c2", "mv-2")])
    result = measure(["h1", "h2"], match_map)
    assert result["new_to_the_pool"] == 0
    assert result["new_fraction_of_unique"] == 0.0


def test_the_pool_map_is_opened_read_only(tmp_path):
    match_map = tmp_path / "map.sqlite"
    _match_map(match_map, [("h1", "mv-1")], [("cod", "c1", "mv-1")])
    before = match_map.read_bytes()
    measure(["h1", "h2"], match_map)
    assert match_map.read_bytes() == before


def test_end_to_end_writes_a_report(tmp_path):
    match_map = tmp_path / "map.sqlite"
    _match_map(match_map, [("h1", "mv-1")], [("cod", "c1", "mv-1")])
    hashes = _hashes_file(tmp_path / "h.tsv", [("a", 1, "h1"), ("b", 2, "h2"), ("c", 3, "FAIL:TOO_LARGE")])
    out = tmp_path / "report.json"
    assert main(["--hashes", str(hashes), "--match-map", str(match_map),
                 "--source", "example", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["rows_read"] == 3
    assert report["parse_failures"] == 1
    assert report["new_to_the_pool"] == 1
    assert report["already_in_the_pool"] == 1
    assert report["parse_failure_fraction"] == pytest.approx(1 / 3, abs=1e-4)


def test_a_missing_pool_map_says_how_to_build_it(tmp_path):
    hashes = _hashes_file(tmp_path / "h.tsv", [("a", 1, "h1")])
    with pytest.raises(SystemExit):
        main(["--hashes", str(hashes), "--match-map", str(tmp_path / "absent.sqlite")])
