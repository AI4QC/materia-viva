import base64
import gzip
import hashlib
import json
from datetime import date

import pytest

from scripts.datasets import catalysis_hub as cathub
from scripts.datasets.catalysis_hub import (
    ENDPOINT,
    TABLE_SPECS,
    build_page_request,
    decode_relay_id,
    default_output_dir,
    export_all,
    export_table,
    main,
    validate_export,
)


class _FakeClock:
    def __init__(self, value=1_000.0):
        self.value = value
        self.sleeps = []

    def time(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


def test_page_request_keeps_api_key_in_header_and_uses_graphql_variables():
    request = build_page_request(
        table="reactions",
        api_key="secret-value",
        page_size=200,
        after="cursor-1",
        max_id=340_225,
    )

    assert request.full_url == ENDPOINT
    assert request.headers["X-api-key"] == "secret-value"
    assert "secret-value" not in request.full_url
    assert "secret-value" not in request.data.decode("utf-8")

    payload = json.loads(request.data)
    assert payload["variables"] == {
        "first": 200,
        "after": "cursor-1",
        "maxId": 340_225,
    }
    assert "order: \"id\"" in payload["query"]
    assert "op: \"<=\"" in payload["query"]


def test_request_governor_paces_attempts_and_persists_rolling_daily_budget(tmp_path):
    clock = _FakeClock()
    ledger = tmp_path / "request-ledger.json"
    governor = cathub.RequestGovernor(
        ledger,
        minimum_interval=6.1,
        requests_per_24_hours=2,
        clock=clock.time,
        sleep=clock.sleep,
    )

    governor.acquire()
    governor.acquire()

    assert clock.sleeps == [pytest.approx(6.1)]
    persisted = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(persisted["request_timestamps"]) == 2
    assert "secret" not in ledger.read_text(encoding="utf-8").lower()

    restarted = cathub.RequestGovernor(
        ledger,
        minimum_interval=6.1,
        requests_per_24_hours=2,
        clock=clock.time,
        sleep=clock.sleep,
    )
    with pytest.raises(RuntimeError, match="24-hour request budget exhausted"):
        restarted.acquire()


def test_governed_fetcher_counts_and_paces_every_retry_attempt(tmp_path):
    clock = _FakeClock()
    governor = cathub.RequestGovernor(
        tmp_path / "request-ledger.json",
        minimum_interval=6.1,
        requests_per_24_hours=5,
        clock=clock.time,
        sleep=clock.sleep,
    )
    attempts = []

    def fetch_once(request):
        attempts.append(request)
        if len(attempts) < 3:
            raise OSError("temporary network failure")
        return {"data": {"ok": True}}

    fetch = cathub.GovernedFetcher(governor, fetch_once=fetch_once, attempts=3)
    request = build_page_request(
        table="reactions",
        api_key="secret-value",
        page_size=5_000,
        after=None,
        max_id=10,
    )

    assert fetch(request) == {"data": {"ok": True}}
    assert len(attempts) == 3
    assert clock.sleeps == [pytest.approx(6.1), pytest.approx(6.1)]
    ledger = json.loads(
        (tmp_path / "request-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["requests_in_rolling_24_hours"] == 3


def test_export_table_accepts_large_page_size_to_minimize_api_requests(tmp_path):
    def fetch(request):
        payload = json.loads(request.data)
        assert "HighWatermark" in payload["query"]
        return {"data": {"reactions": {"totalCount": 0, "edges": []}}}

    manifest_path = export_table(
        output_dir=tmp_path,
        table="reactions",
        api_key="secret-value",
        page_size=5_000,
        fetch_json=fetch,
        request_delay=0,
    )

    assert json.loads(manifest_path.read_text(encoding="utf-8"))["page_size"] == 5_000


def test_table_specs_preserve_reaction_system_links_and_bulk_metadata():
    reactions = TABLE_SPECS["reactions"].selection
    relations = TABLE_SPECS["reaction_systems"].selection
    systems = TABLE_SPECS["systems"].selection

    assert "reactionSystems" in reactions
    assert "aseId" in reactions
    assert TABLE_SPECS["reaction_systems"].graphql_name == "reactionSystems"
    assert "reactions { id }" in relations
    assert "systems { id uniqueId }" in relations
    assert "keyValuePairs" in systems
    assert "numbers" in systems
    assert "positions" in systems
    assert "cell" in systems



def test_barrier_request_filters_positive_values_and_inlines_role_structures():
    request = cathub.build_barrier_page_request(
        api_key="secret-value",
        page_size=100,
        after="cursor-100",
        minimum_activation_energy=0.0,
    )

    payload = json.loads(request.data)
    assert payload["variables"] == {
        "first": 100,
        "after": "cursor-100",
        "minimumActivationEnergy": 0.0,
    }
    assert 'activationEnergy: $minimumActivationEnergy' in payload["query"]
    assert 'op: ">"' in payload["query"]
    assert "reactionSystems" in payload["query"]
    assert "systems {" in payload["query"]
    assert "numbers" in payload["query"]
    assert "positions" in payload["query"]
    assert "cell" in payload["query"]
    assert "keyValuePairs" in payload["query"]
    assert request.headers["X-api-key"] == "secret-value"
    assert "secret-value" not in request.data.decode("utf-8")


def test_relay_id_decoder_returns_type_and_integer_primary_key():
    encoded = base64.b64encode(b"Reaction:938").decode("ascii")

    assert decode_relay_id(encoded) == ("Reaction", 938)


def _relay(type_name, value):
    return base64.b64encode(f"{type_name}:{value}".encode("ascii")).decode("ascii")


def _watermark_payload(table_name, type_name, total, maximum):
    return {
        "data": {
            table_name: {
                "totalCount": total,
                "edges": [{"node": {"id": _relay(type_name, maximum)}}],
            }
        }
    }


def _page_payload(table_name, nodes, *, has_next, end_cursor, total):
    return {
        "data": {
            table_name: {
                "totalCount": total,
                "pageInfo": {
                    "hasNextPage": has_next,
                    "endCursor": end_cursor,
                },
                "edges": [
                    {"cursor": f"edge-{index}", "node": node}
                    for index, node in enumerate(nodes)
                ],
            }
        }
    }


def test_export_table_follows_page_info_and_writes_atomic_secret_free_pages(tmp_path):
    calls = []
    progress = []

    def fetch(request):
        payload = json.loads(request.data)
        calls.append(payload)
        if "HighWatermark" in payload["query"]:
            return _watermark_payload("reactions", "Reaction", 2, 2)
        after = payload["variables"]["after"]
        if after is None:
            return _page_payload(
                "reactions",
                [{"id": _relay("Reaction", 1), "activationEnergy": 0.5}],
                has_next=True,
                end_cursor="cursor-1",
                total=2,
            )
        return _page_payload(
            "reactions",
            [{"id": _relay("Reaction", 2), "activationEnergy": 0.8}],
            has_next=False,
            end_cursor="cursor-2",
            total=2,
        )

    manifest_path = export_table(
        output_dir=tmp_path,
        table="reactions",
        api_key="secret-value",
        page_size=2,
        fetch_json=fetch,
        request_delay=0,
        progress=progress.append,
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["complete"] is True
    assert manifest["downloaded_documents"] == 2
    assert manifest["bounded_total_documents"] == 2
    assert manifest["max_id"] == 2
    assert [page["records"] for page in manifest["pages"]] == [1, 1]
    assert len(calls) == 3
    assert progress == ["reactions: 1/2", "reactions: 2/2"]
    assert "secret-value" not in manifest_text

    pages = sorted((tmp_path / "reactions").glob("page-*.json.gz"))
    assert [page.name for page in pages] == ["page-000000.json.gz", "page-000001.json.gz"]
    assert not list((tmp_path / "reactions").glob("*.building"))
    with gzip.open(pages[0], "rt", encoding="utf-8") as handle:
        assert json.load(handle)["data"]["reactions"]["edges"][0]["node"]["activationEnergy"] == 0.5


def test_export_barriers_uses_one_filtered_cursor_crawl_without_watermark(tmp_path):
    calls = []

    def fetch(request):
        payload = json.loads(request.data)
        calls.append(payload)
        assert "HighWatermark" not in payload["query"]
        after = payload["variables"]["after"]
        if after is None:
            return _page_payload(
                "reactions",
                [
                    {
                        "id": _relay("Reaction", 1),
                        "activationEnergy": 0.5,
                        "reactionSystems": [],
                    }
                ],
                has_next=True,
                end_cursor="barrier-1",
                total=2,
            )
        return _page_payload(
            "reactions",
            [
                {
                    "id": _relay("Reaction", 2),
                    "activationEnergy": 0.8,
                    "reactionSystems": [],
                }
            ],
            has_next=False,
            end_cursor="barrier-2",
            total=2,
        )

    manifest_path = cathub.export_barriers(
        output_dir=tmp_path,
        api_key="secret-value",
        page_size=100,
        fetch_json=fetch,
        request_delay=0,
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert len(calls) == 2
    assert manifest["complete"] is True
    assert manifest["downloaded_documents"] == 2
    assert manifest["bounded_total_documents"] == 2
    assert [page["records"] for page in manifest["pages"]] == [1, 1]
    assert "secret-value" not in manifest_text


def test_main_barriers_only_uses_large_pages_and_rate_safe_defaults(
    tmp_path, monkeypatch
):
    captured = {}
    manifest_path = tmp_path / "barriers" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text('{"complete": true}\n', encoding="utf-8")

    def fake_export_barriers(**kwargs):
        captured.update(kwargs)
        return manifest_path

    monkeypatch.setattr(cathub, "export_barriers", fake_export_barriers)

    result = cathub.main(
        ["--output", str(tmp_path), "--barriers-only"],
        environ={"CATHUB_API_KEY": "secret-value"},
    )

    assert result == 0
    assert captured["page_size"] == cathub.MAX_PAGE_SIZE
    assert captured["request_delay"] == 6.1
    assert captured["minimum_activation_energy"] == 0.0


def test_export_table_resumes_from_manifest_cursor_without_restarting(tmp_path):
    first_calls = []

    def interrupted_fetch(request):
        payload = json.loads(request.data)
        first_calls.append(payload)
        if "HighWatermark" in payload["query"]:
            return _watermark_payload("reactionSystems", "ReactionSystem", 2, 12)
        if payload["variables"]["after"] is None:
            return _page_payload(
                "reactionSystems",
                [{"id": _relay("ReactionSystem", 11)}],
                has_next=True,
                end_cursor="cursor-11",
                total=2,
            )
        raise RuntimeError("simulated interruption")

    try:
        export_table(
            output_dir=tmp_path,
            table="reaction_systems",
            api_key="secret-value",
            page_size=2,
            fetch_json=interrupted_fetch,
            request_delay=0,
        )
    except RuntimeError as error:
        assert str(error) == "simulated interruption"
    else:
        raise AssertionError("expected the simulated interruption")

    partial = json.loads(
        (tmp_path / "reaction_systems" / "manifest.json").read_text(encoding="utf-8")
    )
    assert partial["complete"] is False
    assert partial["downloaded_documents"] == 1
    assert partial["next_cursor"] == "cursor-11"

    resumed_calls = []

    def resumed_fetch(request):
        payload = json.loads(request.data)
        resumed_calls.append(payload)
        assert "HighWatermark" not in payload["query"]
        assert payload["variables"]["after"] == "cursor-11"
        return _page_payload(
            "reactionSystems",
            [{"id": _relay("ReactionSystem", 12)}],
            has_next=False,
            end_cursor="cursor-12",
            total=2,
        )

    manifest_path = export_table(
        output_dir=tmp_path,
        table="reaction_systems",
        api_key="secret-value",
        page_size=2,
        fetch_json=resumed_fetch,
        request_delay=0,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["downloaded_documents"] == 2
    assert len(manifest["pages"]) == 2
    assert len(resumed_calls) == 1


def _write_complete_table(root, local_name, graphql_name, nodes):
    directory = root / local_name
    directory.mkdir(parents=True)
    payload = {
        "data": {
            graphql_name: {
                "totalCount": len(nodes),
                "pageInfo": {"hasNextPage": False, "endCursor": "done"},
                "edges": [
                    {"cursor": f"cursor-{index}", "node": node}
                    for index, node in enumerate(nodes)
                ],
            }
        }
    }
    page = directory / "page-00000.json.gz"
    with gzip.open(page, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    digest = hashlib.sha256(page.read_bytes()).hexdigest()
    manifest = {
        "table": local_name,
        "graphql_name": graphql_name,
        "complete": True,
        "downloaded_documents": len(nodes),
        "bounded_total_documents": len(nodes),
        "pages": [
            {
                "filename": page.name,
                "records": len(nodes),
                "bytes": page.stat().st_size,
                "sha256": digest,
            }
        ],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_validate_export_reports_barrier_link_and_explicit_bulk_id_coverage(tmp_path):
    reaction_1 = _relay("Reaction", 1)
    reaction_2 = _relay("Reaction", 2)
    reaction_3 = _relay("Reaction", 3)
    system_11 = _relay("System", 11)
    system_12 = _relay("System", 12)
    system_13 = _relay("System", 13)
    relation_101 = _relay("ReactionSystem", 101)
    relation_102 = _relay("ReactionSystem", 102)
    relation_103 = _relay("ReactionSystem", 103)
    relation_104 = _relay("ReactionSystem", 104)

    _write_complete_table(
        tmp_path,
        "reactions",
        "reactions",
        [
            {
                "id": reaction_1,
                "activationEnergy": 0.5,
                "reactionSystems": [
                    {"id": relation_101},
                    {"id": relation_102},
                    {"id": relation_103},
                ],
            },
            {"id": reaction_2, "activationEnergy": 0.8, "reactionSystems": []},
            {
                "id": reaction_3,
                "activationEnergy": None,
                "reactionSystems": [{"id": relation_104}],
            },
        ],
    )
    _write_complete_table(
        tmp_path,
        "reaction_systems",
        "reactionSystems",
        [
            {
                "id": relation_101,
                "name": "transition_state",
                "aseId": "11",
                "reactions": {"id": reaction_1},
                "systems": {"id": system_11, "uniqueId": "system-11"},
            },
            {
                "id": relation_102,
                "name": "reactant",
                "aseId": "12",
                "reactions": {"id": reaction_1},
                "systems": {"id": system_12, "uniqueId": "system-12"},
            },
            {
                "id": relation_103,
                "name": "product",
                "aseId": "13",
                "reactions": {"id": reaction_1},
                "systems": {"id": system_13, "uniqueId": "system-13"},
            },
            {
                "id": relation_104,
                "name": "reactant",
                "aseId": "12",
                "reactions": {"id": reaction_3},
                "systems": {"id": system_12, "uniqueId": "system-12"},
            },
        ],
    )
    _write_complete_table(
        tmp_path,
        "systems",
        "systems",
        [
            {
                "id": system_11,
                "uniqueId": "system-11",
                "keyValuePairs": '{"bulk_id": 93, "pub_id": "Example2026"}',
            },
            {"id": system_12, "uniqueId": "system-12", "keyValuePairs": "{}"},
            {"id": system_13, "uniqueId": "system-13", "keyValuePairs": "{}"},
        ],
    )

    report_path = validate_export(tmp_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["relationally_valid"] is True
    assert report["reaction_rows"] == 3
    assert report["barrier_reactions"] == 2
    assert report["reaction_system_rows"] == 4
    assert report["system_rows"] == 3
    assert report["reactions_with_links"] == 2
    assert report["barrier_reactions_with_links"] == 1
    assert report["barrier_reactions_with_transition_state_link"] == 1
    assert report["barrier_reactions_with_is_ts_fs_links"] == 1
    assert report["reactions_with_explicit_bulk_link"] == 1
    assert report["linked_systems"] == 3
    assert report["linked_systems_with_explicit_bulk_id"] == 1
    assert report["relation_roles"] == {
        "product": 1,
        "reactant": 2,
        "transition_state": 1,
    }
    assert report["nested_relation_ids_missing_from_relation_table"] == []
    assert report["relation_ids_missing_from_reaction_nesting"] == []
    assert report["orphan_reaction_ids"] == []
    assert report["orphan_system_ids"] == []


def test_validate_export_rejects_duplicate_ids_and_orphan_relations(tmp_path):
    reaction = _relay("Reaction", 1)
    system = _relay("System", 11)
    missing_reaction = _relay("Reaction", 99)
    missing_system = _relay("System", 88)
    _write_complete_table(
        tmp_path,
        "reactions",
        "reactions",
        [{"id": reaction, "activationEnergy": 0.5}],
    )
    _write_complete_table(
        tmp_path,
        "reaction_systems",
        "reactionSystems",
        [
            {
                "id": _relay("ReactionSystem", 101),
                "name": "product",
                "aseId": "88",
                "reactions": {"id": missing_reaction},
                "systems": {"id": missing_system, "uniqueId": "missing"},
            }
        ],
    )
    _write_complete_table(
        tmp_path,
        "systems",
        "systems",
        [
            {"id": system, "uniqueId": "duplicate", "keyValuePairs": "{}"},
            {"id": system, "uniqueId": "duplicate", "keyValuePairs": "{}"},
        ],
    )

    report = json.loads(validate_export(tmp_path).read_text(encoding="utf-8"))

    assert report["relationally_valid"] is False
    assert report["duplicate_system_ids"] == [11]
    assert report["orphan_reaction_ids"] == [99]
    assert report["orphan_system_ids"] == [88]


def test_default_output_uses_additive_dated_snapshot_directory(tmp_path):
    assert default_output_dir(data_root=tmp_path, snapshot=date(2026, 8, 18)) == (
        tmp_path / "raw" / "acquired" / "catalysis-hub" / "relational-2026-08-18"
    )


def test_cli_requires_personal_api_key_for_export(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main(["--output", str(tmp_path)], environ={})

    assert error.value.code == 2
    assert "CATALYSIS_HUB_API_KEY" in capsys.readouterr().err


def test_cli_validate_only_does_not_require_api_key(tmp_path):
    _write_complete_table(tmp_path, "reactions", "reactions", [])
    _write_complete_table(tmp_path, "reaction_systems", "reactionSystems", [])
    _write_complete_table(tmp_path, "systems", "systems", [])

    assert main(["--output", str(tmp_path), "--validate-only"], environ={}) == 0
    assert (tmp_path / "relational-integrity.json").is_file()


def test_export_all_freezes_relation_table_before_endpoint_tables(tmp_path):
    watermark_order = []

    def fetch(request):
        payload = json.loads(request.data)
        query = payload["query"]
        assert "HighWatermark" in query
        if "reactionSystems(" in query:
            graphql_name = "reactionSystems"
        elif "reactions(" in query:
            graphql_name = "reactions"
        else:
            graphql_name = "systems"
        watermark_order.append(graphql_name)
        return {"data": {graphql_name: {"totalCount": 0, "edges": []}}}

    report_path = export_all(
        output_dir=tmp_path,
        api_key="secret-value",
        page_size=2,
        request_delay=0,
        fetch_json=fetch,
    )

    assert watermark_order == ["reactionSystems", "reactions", "systems"]
    assert json.loads(report_path.read_text(encoding="utf-8"))["relationally_valid"]
