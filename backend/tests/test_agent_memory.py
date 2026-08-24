from datetime import datetime, timezone

import pytest

from src.agents.memory import Rejection, briefing, load, remember

WHEN = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)


def test_a_refusal_survives_to_be_read_back(tmp_path):
    store = tmp_path / "rejected.json"
    remember("camd", "https://camd.example", "already ingested inside odbx",
             run_id="20260824T090000Z", path=store, now=WHEN)
    rows = load(store)
    assert rows == [Rejection(id="camd", url="https://camd.example",
                              why="already ingested inside odbx", when="2026-08-24",
                              run_id="20260824T090000Z")]


def test_looking_at_the_same_candidate_twice_replaces_rather_than_duplicates(tmp_path):
    # two rows saying different things about one id is the drift this module prevents
    store = tmp_path / "rejected.json"
    remember("camd", "https://camd.example", "looks redundant", path=store, now=WHEN)
    remember("camd", "https://camd.example", "already ingested inside odbx", path=store, now=WHEN)
    rows = load(store)
    assert len(rows) == 1 and rows[0].why == "already ingested inside odbx"


def test_a_refusal_without_a_reason_is_refused(tmp_path):
    with pytest.raises(ValueError, match="needs a reason"):
        remember("camd", "https://camd.example", "   ", path=tmp_path / "rejected.json")


def test_the_first_sweep_is_not_handed_an_empty_lecture(tmp_path):
    assert briefing(tmp_path / "nothing.json") == ""


def test_the_briefing_names_every_refusal_and_leaves_a_way_back_in(tmp_path):
    store = tmp_path / "rejected.json"
    remember("camd", "https://camd.example", "already inside odbx", path=store, now=WHEN)
    remember("zzz", "https://zzz.example", "licence would not clear", path=store, now=WHEN)
    text = briefing(store)
    assert "camd" in text and "zzz" in text
    assert "already inside odbx" in text
    # a refusal is not a life sentence: the reason can stop holding
    assert "unless you have evidence the reason no longer holds" in text


def test_a_long_memory_is_summarised_rather_than_pasted(tmp_path):
    store = tmp_path / "rejected.json"
    for i in range(45):
        remember(f"cand-{i:03d}", f"https://{i}.example", "redundant", path=store, now=WHEN)
    text = briefing(store, limit=40)
    assert "…and 5 more" in text


def test_the_sweep_carries_what_was_refused_into_the_explorers_task(tmp_path, monkeypatch):
    """The wiring, not just the module: a refusal has to reach the next sweep."""
    from pathlib import Path

    import src.agents.memory as memory
    from src.agents.pipelines import DISCOVERY_SWEEP, plan

    store = tmp_path / "rejected.json"
    remember("camd", "https://camd.example", "already inside odbx", path=store, now=WHEN)
    monkeypatch.setattr(memory, "REJECTED", store)

    explorer_task = dict(plan(DISCOVERY_SWEEP, Path("/runs")))["explorer"]
    assert "camd" in explorer_task and "already inside odbx" in explorer_task
