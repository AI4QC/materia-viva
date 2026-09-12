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


def test_archive_export_retries_then_records_entries_without_an_archive(tmp_path):
    _write_complete_catalog(tmp_path)
    build_selection(tmp_path)
    calls: list[list[str]] = []

    def fetch(path, payload):
        ids = payload["query"]["entry_id:any"]
        calls.append(list(ids))
        # NOMAD lists e3 but has no Archive for it: it never comes back.
        return {"data": [{"entry_id": e, "archive": {}} for e in ids if e != "e3"]}

    manifest_path = export_archives(
        tmp_path, kind="structures", batch_size=2, reserve_bytes=0, fetch_json=fetch
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert calls == [["e2", "e3"], ["e3"]]  # the missing id was retried once, alone
    assert manifest["complete"] is True
    assert manifest["downloaded_documents"] == 1 and manifest["missing_documents"] == 1
    assert manifest["pages"][0]["rows"] == 1
    assert manifest["pages"][0]["missing_entry_ids"] == ["e3"]
    missing_log = tmp_path / "archive" / "structures" / "missing-entry-ids.txt"
    assert missing_log.read_text(encoding="utf-8") == "e3\n"
    report = status(tmp_path)["phases"]["archive:structures"]
    assert report["missing"] == 1 and report["complete"] is True


def test_archive_export_still_fails_closed_when_most_of_a_batch_is_missing(tmp_path):
    _write_catalog_with_entries(tmp_path, 40)
    build_selection(tmp_path)

    with pytest.raises(RuntimeError, match="missing after retry"):
        export_archives(
            tmp_path,
            kind="properties",
            batch_size=40,
            reserve_bytes=0,
            fetch_json=lambda path, payload: {"data": []},
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
    assert "{probe,catalog,select,archive,archive-multi,download,status}" in result.stdout


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


# --- entry_id sharding -------------------------------------------------------

import hashlib  # noqa: E402

from scripts.datasets.nomad import export_archives_parallel, shard_of  # noqa: E402


def _write_catalog_with_entries(output_dir: Path, count: int) -> list[str]:
    """A complete catalog whose entries all carry a DOS, one material each."""
    _write_snapshot(output_dir)
    ids = [f"entry-{index:03d}" for index in range(count)]
    rows = [
        {
            "entry_id": entry_id,
            "results": {
                "material": {"material_id": f"mat-{entry_id}"},
                "properties": {"available_properties": ["dos_electronic"]},
            },
        }
        for entry_id in ids
    ]
    page_path = output_dir / "catalog" / "page-0000000.json.gz"
    _write_gzip_json(page_path, {"data": rows, "pagination": {"total": count}})
    _write_json(
        output_dir / "catalog" / "manifest.json",
        {
            "phase": "catalog",
            "complete": True,
            "downloaded_documents": count,
            "total_documents": count,
            "pages": [
                {
                    "path": "catalog/page-0000000.json.gz",
                    "sha256": hashlib.sha256(page_path.read_bytes()).hexdigest(),
                }
            ],
        },
    )
    return ids


def _echo_archive(calls: list[list[str]]):
    def fetch(path, payload):
        assert path == "/entries/archive/query"
        ids = payload["query"]["entry_id:any"]
        calls.append(list(ids))
        return {"data": [{"entry_id": entry_id, "archive": {}} for entry_id in ids]}

    return fetch


def test_shard_of_is_deterministic_and_in_range():
    assert shard_of("entry-001", 8) == shard_of("entry-001", 8)
    assert all(0 <= shard_of(f"e{i}", 5) < 5 for i in range(1000))
    assert len({shard_of(f"e{i}", 4) for i in range(1000)}) == 4


def test_sharded_archive_export_partitions_entries_exactly_once(tmp_path):
    ids = _write_catalog_with_entries(tmp_path, 40)
    build_selection(tmp_path)
    calls: list[list[str]] = []
    shards = 4

    manifests = [
        export_archives(
            tmp_path,
            kind="properties",
            batch_size=3,
            reserve_bytes=0,
            fetch_json=_echo_archive(calls),
            shards=shards,
            shard=shard,
        )
        for shard in range(shards)
    ]

    fetched = [entry_id for batch in calls for entry_id in batch]
    assert sorted(fetched) == ids  # every entry exactly once across shards
    for shard, path in enumerate(manifests):
        assert path == tmp_path / "archive" / "properties" / f"shard-{shard:02d}-of-04" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest["complete"] is True
        assert manifest["shards"] == shards and manifest["shard"] == shard
        expected = [entry_id for entry_id in ids if shard_of(entry_id, shards) == shard]
        assert manifest["total_documents"] == len(expected)
        assert manifest["downloaded_documents"] == len(expected)
        for page in manifest["pages"]:
            assert shard_of(page["first_entry_id"], shards) == shard
    # The unsharded layout is untouched, so a legacy sequential run can coexist.
    assert not (tmp_path / "archive" / "properties" / "manifest.json").exists()


def test_sharded_archive_export_resumes_and_rejects_shard_mismatch(tmp_path):
    ids = _write_catalog_with_entries(tmp_path, 40)
    build_selection(tmp_path)
    calls: list[list[str]] = []
    fetch = _echo_archive(calls)
    kwargs = dict(kind="properties", batch_size=2, reserve_bytes=0, fetch_json=fetch)

    path = export_archives(tmp_path, max_pages=1, shards=2, shard=1, **kwargs)
    partial = json.loads(path.read_text(encoding="utf-8"))
    assert partial["complete"] is False
    assert partial["downloaded_documents"] == 2

    export_archives(tmp_path, shards=2, shard=1, **kwargs)
    complete = json.loads(path.read_text(encoding="utf-8"))
    assert complete["complete"] is True
    expected = [entry_id for entry_id in ids if shard_of(entry_id, 2) == 1]
    assert [e for batch in calls for e in batch] == expected

    # A manifest written for shard 1 of 2 must not be resumed as another shard.
    (tmp_path / "archive" / "properties" / "shard-00-of-02").mkdir(parents=True)
    (tmp_path / "archive" / "properties" / "shard-00-of-02" / "manifest.json").write_text(
        path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="cannot resume archive:properties"):
        export_archives(tmp_path, shards=2, shard=0, **kwargs)


def test_parallel_archive_export_runs_every_shard_and_status_aggregates(tmp_path):
    ids = _write_catalog_with_entries(tmp_path, 40)
    build_selection(tmp_path)
    calls: list[list[str]] = []

    paths = export_archives_parallel(
        tmp_path,
        kind="properties",
        batch_size=3,
        workers=4,
        reserve_bytes=0,
        fetch_json=_echo_archive(calls),
    )

    assert len(paths) == 4
    assert sorted(e for batch in calls for e in batch) == ids
    assert all(json.loads(p.read_text(encoding="utf-8"))["complete"] for p in paths)

    report = status(tmp_path, verify=True)
    aggregate = report["phases"]["archive:properties:sharded"]
    assert aggregate["shards"] == 4 and aggregate["shards_seen"] == 4
    assert aggregate["downloaded"] == 40 and aggregate["total"] == 40
    assert aggregate["complete"] is True
    assert all(row["verification_errors"] == [] for row in aggregate["per_shard"].values())
    assert "archive:properties" not in report["phases"]


def test_parallel_archive_export_propagates_failure_and_stops_other_shards(tmp_path):
    _write_catalog_with_entries(tmp_path, 40)
    build_selection(tmp_path)
    poison = "entry-007"

    def fetch(path, payload):
        ids = payload["query"]["entry_id:any"]
        if poison in ids:
            raise RuntimeError("simulated NOMAD outage")
        return {"data": [{"entry_id": entry_id, "archive": {}} for entry_id in ids]}

    with pytest.raises(RuntimeError, match="simulated NOMAD outage"):
        export_archives_parallel(
            tmp_path,
            kind="properties",
            batch_size=1,
            workers=4,
            reserve_bytes=0,
            fetch_json=fetch,
        )

    poisoned = shard_of(poison, 4)
    manifest = json.loads(
        (tmp_path / "archive" / "properties" / f"shard-{poisoned:02d}-of-04" / "manifest.json")
        .read_text(encoding="utf-8")
    )
    assert manifest["complete"] is False  # failed shard stays resumable
    # Every committed page is intact, so the whole run can simply be re-issued.
    report = status(tmp_path, verify=True)
    assert all(
        row["verification_errors"] == []
        for row in report["phases"]["archive:properties:sharded"]["per_shard"].values()
    )


def test_download_all_supports_property_workers(tmp_path):
    _write_snapshot(tmp_path)

    def fetch(path, payload):
        if path == "/entries/query":
            return {
                "data": [
                    {
                        "entry_id": "e1",
                        "results": {
                            "material": {"material_id": "m1"},
                            "properties": {"available_properties": ["dos_electronic"]},
                        },
                    }
                ],
                "pagination": {"total": 1, "next_page_after_value": None},
            }
        if path == "/entries/archive/query":
            return {"data": [{"entry_id": e, "archive": {}} for e in payload["query"]["entry_id:any"]]}
        raise AssertionError(path)

    result = download_all(
        tmp_path,
        catalog_page_size=1,
        structure_batch_size=1,
        property_batch_size=1,
        reserve_bytes=0,
        fetch_json=fetch,
        property_workers=2,
    )

    assert isinstance(result["structures"], Path)
    assert isinstance(result["properties"], list) and len(result["properties"]) == 2
    totals = [json.loads(p.read_text(encoding="utf-8")) for p in result["properties"]]
    assert all(m["complete"] for m in totals)  # an empty shard completes immediately
    assert sum(m["downloaded_documents"] for m in totals) == 1


def test_cli_parses_shard_and_worker_options():
    parser = build_parser()
    args = parser.parse_args(["archive", "--kind", "properties", "--shards", "8", "--shard", "3"])
    assert (args.shards, args.shard, args.workers) == (8, 3, 1)
    args = parser.parse_args(["archive", "--kind", "properties", "--workers", "8"])
    assert args.workers == 8
    args = parser.parse_args(["download", "--property-workers", "8"])
    assert (args.structure_workers, args.property_workers) == (1, 8)
    with pytest.raises(SystemExit):
        parser.parse_args(["archive", "--kind", "properties", "--shards", "x"])


def test_retry_delay_backs_off_hard_on_429_and_honours_retry_after(monkeypatch):
    from scripts.datasets import nomad

    assert nomad.retry_delay(0) == 1.0 and nomad.retry_delay(3) == 8.0
    assert nomad.retry_delay(20) == 120.0
    assert nomad.retry_delay(0, status=503, retry_after="42") == 42.0
    jittered = nomad.retry_delay(0, status=429)
    assert 15.0 <= jittered <= 15.0 * 1.25
    monkeypatch.setattr(nomad.random, "uniform", lambda low, high: 0.0)
    assert [nomad.retry_delay(a, status=429) for a in range(6)] == [15, 30, 60, 120, 240, 300]


def test_adaptive_limiter_shrinks_on_throttle_and_recovers_slowly():
    from scripts.datasets.nomad import AdaptiveLimiter

    limiter = AdaptiveLimiter(4, recovery=3)
    with limiter:
        assert limiter.inflight == 1
        with limiter:
            assert limiter.inflight == 2
    assert limiter.inflight == 0
    limiter.throttled()
    limiter.throttled()
    assert limiter.capacity == 2
    assert not limiter.probe_due()  # no successes yet
    for _ in range(3):
        limiter.succeeded()
    assert limiter.probe_due() and not limiter.probe_due()  # one probe at a time
    limiter.probe_result(True)
    assert limiter.capacity == 3
    for _ in range(10):
        limiter.throttled()
    assert limiter.capacity == 1  # never below the floor
    for _ in range(30):
        limiter.succeeded()
    assert limiter.capacity == 1  # successes alone never grow the cap any more
    limiter.probe_due(); limiter.probe_result(False, cooldown=10.0)
    assert limiter.capacity == 1 and limiter.wait_seconds() > 9.0
    limiter = AdaptiveLimiter(4, recovery=1)
    limiter.succeeded(); limiter.probe_due(); limiter.probe_result(True)
    assert limiter.capacity == 4 and not limiter.probe_due()  # at the ceiling: no probes


def test_adaptive_limiter_blocks_when_full():
    import threading

    from scripts.datasets.nomad import AdaptiveLimiter

    limiter = AdaptiveLimiter(1)
    entered = threading.Event()
    release = threading.Event()

    def hold():
        with limiter:
            entered.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold)
    holder.start()
    assert entered.wait(timeout=5)
    waiter_done = threading.Event()

    def wait_for_slot():
        with limiter:
            waiter_done.set()

    waiter = threading.Thread(target=wait_for_slot)
    waiter.start()
    assert not waiter_done.wait(timeout=0.2)  # blocked while the slot is held
    release.set()
    assert waiter_done.wait(timeout=5)
    holder.join(timeout=5)
    waiter.join(timeout=5)


def test_client_from_args_attaches_limiter_only_for_parallel_runs():
    from scripts.datasets.nomad import _client_from_args, build_parser

    parser = build_parser()
    single = _client_from_args(parser.parse_args(["archive", "--kind", "properties"]))
    assert single.limiter is not None and single.limiter.ceiling == 1  # pacing applies everywhere
    parallel = _client_from_args(
        parser.parse_args(["--min-interval", "20", "--throttle-base", "90", "archive", "--kind", "properties", "--workers", "4"])
    )
    assert parallel.limiter is not None and parallel.limiter.ceiling == 4
    assert parallel.limiter.min_interval == 20.0 and parallel.throttle_base == 90.0
    download = _client_from_args(parser.parse_args(["download", "--property-workers", "3"]))
    assert download.limiter is not None and download.limiter.ceiling == 3


# --- throttling behaviour ----------------------------------------------------

import email.message  # noqa: E402
import io  # noqa: E402
from urllib.error import HTTPError  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")
        self.headers = email.message.Message()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None


def _http_429(retry_after: str = "1") -> HTTPError:
    headers = email.message.Message()
    headers["Retry-After"] = retry_after
    return HTTPError("https://x/entries/archive/query", 429, "Too Many Requests", headers, io.BytesIO(b""))


class _StubLimiter:
    """Duck-typed limiter that records calls without real-time cooldowns."""

    def __init__(self):
        self.capacity = 4
        self.consecutive_throttles = 0
        self.cooldowns: list[float] = []
        self.successes = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def slot(self, priority: int = 0):
        return self

    def probe_due(self) -> bool:
        return False

    def throttled(self, cooldown: float = 0.0) -> None:
        self.capacity = max(1, self.capacity - 1)
        self.consecutive_throttles += 1
        self.cooldowns.append(cooldown)

    def succeeded(self) -> None:
        self.consecutive_throttles = 0
        self.successes += 1


def _fake_urlopen(script: list):
    """Return a urlopen stand-in that raises or returns the scripted items in order."""

    def urlopen(request, timeout):
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return urlopen


def test_client_waits_out_429_without_burning_attempts(monkeypatch):
    from scripts.datasets import nomad

    script = [_http_429("1"), _http_429("5"), _http_429("1"), _FakeResponse({"ok": True})]
    sleeps: list[float] = []
    monkeypatch.setattr(nomad, "urlopen", _fake_urlopen(script))
    monkeypatch.setattr(nomad.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(nomad.random, "uniform", lambda low, high: 0.0)

    limiter = _StubLimiter()
    client = nomad.NomadClient(attempts=2, limiter=limiter)
    assert client.request_json("/entries/archive/query", {"q": 1}) == {"ok": True}
    # Three 429s did not exhaust attempts=2; every wait ignored the tiny Retry-After,
    # escalated from the 60 s base along the limiter's consecutive count, and was
    # pushed to the shared limiter so all threads pause together.
    assert sleeps == [60.0, 120.0, 240.0]
    assert limiter.cooldowns == [60.0, 120.0, 240.0]
    assert limiter.capacity == 1 and limiter.successes == 1


def test_client_gives_up_when_throttled_beyond_patience(monkeypatch):
    from scripts.datasets import nomad

    sleeps: list[float] = []
    monkeypatch.setattr(nomad, "urlopen", _fake_urlopen([_http_429("2")] * 10))
    monkeypatch.setattr(nomad.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(nomad.random, "uniform", lambda low, high: 0.0)

    client = nomad.NomadClient(attempts=8, throttle_patience=100.0, throttle_base=15.0)
    with pytest.raises(RuntimeError, match="kept throttling"):
        client.request_json("/entries/archive/query", {"q": 1})
    assert sleeps == [15.0, 30.0]  # the third wait would push the total past 100 s


def test_throttle_cooldown_is_capped_and_honours_a_longer_retry_after(monkeypatch):
    from scripts.datasets import nomad

    monkeypatch.setattr(nomad.random, "uniform", lambda low, high: 0.0)
    client = nomad.NomadClient(throttle_base=60.0, throttle_cap=600.0)
    assert [client.throttle_cooldown(k, None) for k in range(6)] == [60, 120, 240, 480, 600, 600]
    assert client.throttle_cooldown(0, "5") == 60.0  # a short Retry-After never shortens the wait
    assert client.throttle_cooldown(0, "900") == 900.0


def test_archive_batch_size_may_change_on_resume(tmp_path, capsys):
    ids = _write_catalog_with_entries(tmp_path, 40)
    build_selection(tmp_path)
    calls: list[list[str]] = []
    fetch = _echo_archive(calls)

    path = export_archives(tmp_path, kind="properties", batch_size=3, max_pages=2, reserve_bytes=0, fetch_json=fetch)
    export_archives(tmp_path, kind="properties", batch_size=10, reserve_bytes=0, fetch_json=fetch)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True and manifest["page_size"] == 10
    assert [len(batch) for batch in calls] == [3, 3, 10, 10, 10, 4]
    assert [e for batch in calls for e in batch] == ids
    assert "batch size 3 -> 10 on resume" in capsys.readouterr().out
    with pytest.raises(ValueError, match="batch_size"):
        export_archives(tmp_path, kind="structures", batch_size=5001, reserve_bytes=0, fetch_json=fetch)


def test_limiter_cooldown_pauses_everyone_and_spaces_request_starts(monkeypatch):
    from scripts.datasets import nomad

    clock = {"now": 1000.0}
    monkeypatch.setattr(nomad.time, "monotonic", lambda: clock["now"])
    limiter = nomad.AdaptiveLimiter(4, min_interval=2.0)
    assert limiter.wait_seconds() == 0.0
    limiter.throttled(30.0)
    assert limiter.wait_seconds() == 30.0 and limiter.consecutive_throttles == 1
    limiter.throttled(10.0)  # a shorter cooldown never brings the resume time forward
    assert limiter.wait_seconds() == 30.0 and limiter.consecutive_throttles == 2
    clock["now"] += 30.0
    assert limiter.wait_seconds() == 0.0
    with limiter:
        pass
    assert limiter.wait_seconds() == 2.0  # spacing after a request start
    clock["now"] += 2.0
    assert limiter.wait_seconds() == 0.0
    limiter.succeeded()
    assert limiter.consecutive_throttles == 0


def test_limiter_spacing_really_blocks():
    import time

    from scripts.datasets.nomad import AdaptiveLimiter

    limiter = AdaptiveLimiter(2, min_interval=0.2)
    started = time.monotonic()
    with limiter:
        pass
    with limiter:
        pass
    assert time.monotonic() - started >= 0.2


# --- multi-kind export through one request budget ------------------------------

def test_limiter_gives_the_slot_to_urgent_callers_first():
    import threading
    import time

    from scripts.datasets.nomad import AdaptiveLimiter

    limiter = AdaptiveLimiter(1, min_interval=0.0)
    order: list[str] = []
    holder_release = threading.Event()
    holder_in = threading.Event()

    def holder():
        with limiter.slot(1):
            holder_in.set()
            holder_release.wait(timeout=5)

    def low():
        with limiter.slot(1):
            order.append("low")

    def urgent():
        with limiter.slot(0):
            order.append("urgent")

    threading.Thread(target=holder).start()
    assert holder_in.wait(timeout=5)
    low_thread = threading.Thread(target=low)
    low_thread.start()
    time.sleep(0.1)  # low is now waiting on the held slot
    urgent_thread = threading.Thread(target=urgent)
    urgent_thread.start()
    time.sleep(0.1)  # urgent is waiting too
    holder_release.set()
    urgent_thread.join(timeout=5)
    low_thread.join(timeout=5)
    assert order == ["urgent", "low"]


def test_archive_plan_parsing():
    from scripts.datasets.nomad import ArchivePlan, build_parser

    plan = ArchivePlan.parse("properties:500:4:1")
    assert (plan.kind, plan.batch_size, plan.workers, plan.priority) == ("properties", 500, 4, 1)
    default = ArchivePlan.parse("structures:2000")
    assert (default.workers, default.priority) == (1, 0)
    with pytest.raises(ValueError):
        ArchivePlan.parse("nonsense:1")
    with pytest.raises(ValueError):
        ArchivePlan.parse("structures")
    args = build_parser().parse_args(
        ["archive-multi", "--plan", "structures:500:1:0", "--plan", "properties:500:4:1", "--capacity", "2"]
    )
    assert [repr(p) for p in args.plan] == ["structures:500:1:0", "properties:500:4:1"]
    assert args.capacity == 2


def test_export_archives_multi_runs_both_kinds_with_their_priorities(tmp_path):
    from scripts.datasets.nomad import ArchivePlan, export_archives_multi

    ids = _write_catalog_with_entries(tmp_path, 40)
    build_selection(tmp_path)
    seen: list[tuple[str, int]] = []

    def request(path, payload, priority):
        assert path == "/entries/archive/query"
        entry_ids = payload["query"]["entry_id:any"]
        kind = "structures" if payload["required"]["run"].get("system[-1]") else "properties"
        seen.append((kind, priority))
        return {"data": [{"entry_id": e, "archive": {}} for e in entry_ids]}

    result = export_archives_multi(
        tmp_path,
        [ArchivePlan("structures", 7, 1, 0), ArchivePlan("properties", 5, 4, 1)],
        request=request,
        reserve_bytes=0,
    )

    assert len(result["structures"]) == 1 and len(result["properties"]) == 4
    for path in result["structures"] + result["properties"]:
        assert json.loads(path.read_text(encoding="utf-8"))["complete"] is True
    assert {priority for kind, priority in seen if kind == "structures"} == {0}
    assert {priority for kind, priority in seen if kind == "properties"} == {1}
    structures_manifest = json.loads(result["structures"][0].read_text(encoding="utf-8"))
    assert structures_manifest["downloaded_documents"] == len(ids)
    assert sum(
        json.loads(p.read_text(encoding="utf-8"))["downloaded_documents"] for p in result["properties"]
    ) == len(ids)
    with pytest.raises(ValueError, match="one plan only"):
        export_archives_multi(tmp_path, [ArchivePlan("dos", 5), ArchivePlan("dos", 5)], request=request)


def test_client_from_args_caps_multi_run_at_requested_capacity():
    from scripts.datasets.nomad import _client_from_args, build_parser

    parser = build_parser()
    client = _client_from_args(parser.parse_args(
        ["archive-multi", "--plan", "structures:500:1:0", "--plan", "properties:500:4:1", "--capacity", "1", "--recovery", "60"]
    ))
    assert client.limiter.capacity == 1 and client.limiter.ceiling == 5  # starts at 1, may grow to 5
    assert client.limiter.recovery == 60
    client = _client_from_args(parser.parse_args(
        ["archive-multi", "--plan", "structures:500:1:0", "--plan", "properties:500:4:1", "--capacity", "9"]
    ))
    assert client.limiter.capacity == 5 and client.limiter.ceiling == 5  # never more than the thread count


def test_limiter_initial_capacity_grows_towards_the_ceiling():
    from scripts.datasets.nomad import AdaptiveLimiter

    limiter = AdaptiveLimiter(5, initial=1, recovery=3)
    assert limiter.capacity == 1 and limiter.ceiling == 5
    for _ in range(3):
        limiter.succeeded()
    assert limiter.probe_due()
    limiter.probe_result(True)
    assert limiter.capacity == 2
    with pytest.raises(ValueError):
        AdaptiveLimiter(2, initial=3)


def test_limiter_reserved_slots_keep_non_urgent_work_out_until_capacity_grows():
    from scripts.datasets.nomad import AdaptiveLimiter

    limiter = AdaptiveLimiter(2, min_interval=0.0)
    limiter.reserve(+1)
    assert limiter.wait_seconds() == 0.0
    with limiter.slot(1):  # one spare slot above the reservation
        assert limiter.inflight == 1
    limiter.throttled(0.0)  # capacity 2 -> 1: nothing left for non-urgent callers
    import threading

    entered = threading.Event()

    def low():
        with limiter.slot(1):
            entered.set()

    thread = threading.Thread(target=low)
    thread.start()
    assert not entered.wait(timeout=0.3)
    limiter.reserve(-1)  # the urgent stream finished
    assert entered.wait(timeout=5)
    thread.join(timeout=5)


def test_export_archives_multi_serialises_structures_before_properties_at_capacity_one(tmp_path):
    from scripts.datasets.nomad import AdaptiveLimiter, ArchivePlan, export_archives_multi

    ids = _write_catalog_with_entries(tmp_path, 30)
    build_selection(tmp_path)
    limiter = AdaptiveLimiter(1, min_interval=0.0)
    order: list[str] = []

    def request(path, payload, priority):
        entry_ids = payload["query"]["entry_id:any"]
        kind = "structures" if payload["required"]["run"].get("system[-1]") else "properties"
        with limiter.slot(priority):
            order.append(kind)
        return {"data": [{"entry_id": e, "archive": {}} for e in entry_ids]}

    export_archives_multi(
        tmp_path,
        [ArchivePlan("structures", 5, 1, 0), ArchivePlan("properties", 5, 2, 1)],
        request=request,
        reserve_bytes=0,
        limiter=limiter,
    )
    first_property = order.index("properties")
    assert order[:first_property] == ["structures"] * (len(ids) // 5)
    shard_sizes = [sum(1 for e in ids if shard_of(e, 2) == k) for k in range(2)]
    assert order.count("properties") == sum(-(-n // 5) for n in shard_sizes)


def test_client_probes_concurrency_with_a_tiny_request_while_one_is_in_flight(monkeypatch):
    from scripts.datasets import nomad

    calls: list[str] = []

    def urlopen(request, timeout):
        body = json.loads(request.data)
        if body == nomad.NomadClient.PROBE_PAYLOAD:
            calls.append("probe")
            if calls.count("probe") == 1:
                raise _http_429("5")
            return _FakeResponse({"data": []})
        calls.append("real")
        return _FakeResponse({"ok": True})

    class SyncTimer:
        def __init__(self, delay, fn):
            self.fn = fn
            self.daemon = False

        def start(self):
            self.fn()

    monkeypatch.setattr(nomad, "urlopen", urlopen)
    monkeypatch.setattr(nomad.threading, "Timer", SyncTimer)
    monkeypatch.setattr(nomad.time, "sleep", lambda seconds: None)
    limiter = nomad.AdaptiveLimiter(3, initial=1, recovery=2, min_interval=0.0)
    client = nomad.NomadClient(limiter=limiter)
    client.probe_reject_cooldown = 0.0  # keep the test free of real waiting

    client.request_json("/entries/archive/query", {"q": 1})
    client.request_json("/entries/archive/query", {"q": 2})
    assert calls == ["real", "real"]  # no probe before `recovery` successes
    client.request_json("/entries/archive/query", {"q": 3})
    assert calls[-2:] == ["probe", "real"] and limiter.capacity == 1  # rejected probe: cap stays
    client.request_json("/entries/archive/query", {"q": 4})
    assert calls[-1] == "real" and limiter.capacity == 1  # counting successes again
    client.request_json("/entries/archive/query", {"q": 5})
    assert calls[-2:] == ["probe", "real"] and limiter.capacity == 2  # accepted probe grows the cap
    client.request_json("/entries/archive/query", {"q": 6})
    assert calls[-1] == "real" and calls.count("probe") == 2  # no probe until successes accrue again


def test_client_retries_when_the_response_is_cut_off_mid_stream(monkeypatch):
    from http.client import IncompleteRead

    from scripts.datasets import nomad

    class Truncated(_FakeResponse):
        def read(self):
            raise IncompleteRead(b"partial")

    script = [Truncated({}), _FakeResponse({"ok": True})]
    sleeps: list[float] = []
    monkeypatch.setattr(nomad, "urlopen", _fake_urlopen(script))
    monkeypatch.setattr(nomad.time, "sleep", lambda seconds: sleeps.append(seconds))

    client = nomad.NomadClient(attempts=3)
    assert client.request_json("/entries/archive/query", {"q": 1}) == {"ok": True}
    assert sleeps == [1.0]  # one ordinary retry, not a crash


def test_client_rides_out_a_long_network_outage(monkeypatch):
    """A multi-minute outage must not end the run: retries are bounded by time."""
    from scripts.datasets import nomad

    outage = [ConnectionResetError(104, "Connection reset by peer")] * 20
    script = outage + [_FakeResponse({"ok": True})]
    sleeps: list[float] = []
    monkeypatch.setattr(nomad, "urlopen", _fake_urlopen(script))
    monkeypatch.setattr(nomad.time, "sleep", lambda seconds: sleeps.append(seconds))

    client = nomad.NomadClient(attempts=8, network_patience=1800.0)
    assert client.request_json("/entries/archive/query", {"q": 1}) == {"ok": True}
    assert len(sleeps) == 20          # every failure was retried, not just 8
    assert sum(sleeps) > 1500         # it kept trying for well over 20 minutes
    assert max(sleeps) == 120.0       # backoff still capped


def test_client_gives_up_once_the_network_budget_is_spent(monkeypatch):
    from scripts.datasets import nomad

    monkeypatch.setattr(nomad, "urlopen", _fake_urlopen([ConnectionResetError()] * 500))
    monkeypatch.setattr(nomad.time, "sleep", lambda seconds: None)

    client = nomad.NomadClient(attempts=3, network_patience=60.0)
    with pytest.raises(RuntimeError, match="failed after .* attempts over"):
        client.request_json("/entries/archive/query", {"q": 1})


def test_network_patience_is_wired_to_the_cli():
    from scripts.datasets.nomad import _client_from_args, build_parser

    args = build_parser().parse_args(["--network-patience", "900", "archive", "--kind", "properties"])
    assert _client_from_args(args).network_patience == 900.0
