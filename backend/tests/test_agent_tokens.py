import json

import pytest

from src.agents.tokens import Budget, Usage, from_anthropic_model_usage, report, total, trace


def test_cache_reads_count_toward_the_total_and_not_toward_billable():
    # cache reads are cheap, not free; leaving them out of the total is how a loop
    # that looks affordable per turn stops being affordable per sweep
    usage = Usage(input=100, output=50, cache_read=9000, cache_write=200)
    assert usage.total == 9350
    assert usage.billable == 350


def test_usage_adds_up_across_runs():
    first = Usage(input=10, output=5, cost_usd=0.1, models=(("m", "anthropic"),))
    second = Usage(input=1, cache_read=7, cost_usd=0.2, models=(("m", "anthropic"),))
    combined = first + second
    assert combined.input == 11 and combined.cache_read == 7
    assert combined.cost_usd == pytest.approx(0.3)
    # the same model twice is still one model
    assert combined.models == (("m", "anthropic"),)


def test_a_provider_report_is_mapped_rather_than_stored_as_it_arrives():
    # claude_agent_sdk reports camelCase per model; another backend will not, and
    # nothing above the executor should have to know either shape
    usage = from_anthropic_model_usage(
        {"claude-opus-5": {"inputTokens": 1000, "outputTokens": 500,
                           "cacheReadInputTokens": 8000, "cacheCreationInputTokens": 200,
                           "provider": "anthropic"}},
        1.25,
    )
    assert (usage.input, usage.output, usage.cache_read, usage.cache_write) == (1000, 500, 8000, 200)
    assert usage.cost_usd == 1.25
    assert usage.models == (("claude-opus-5", "anthropic"),)


def test_a_provider_that_reports_nothing_still_yields_a_usable_zero():
    assert from_anthropic_model_usage(None).total == 0
    assert from_anthropic_model_usage(None, 0.5).cost_usd == 0.5


def test_a_budget_is_exhausted_before_it_is_exceeded():
    budget = Budget(tokens=1000)
    budget.record(Usage(input=600))
    assert not budget.exhausted and budget.remaining_tokens == 400
    budget.record(Usage(input=600))
    assert budget.exhausted and budget.remaining_tokens == 0
    assert "token budget of 1,000 is spent" in budget.why()


def test_no_budget_never_stops_anything():
    budget = Budget()
    budget.record(Usage(input=10**9, cost_usd=10**6))
    assert not budget.exhausted and budget.why() == ""


def _record(root, run_id, role, usage, started="2026-08-24T09:00:00+00:00", backend="sdk"):
    workspace = root / run_id / role
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "run.json").write_text(json.dumps({
        "role": role, "backend": backend, "started_at": started, "usage": usage.as_record(),
    }), encoding="utf-8")


def test_the_trace_groups_what_was_spent(tmp_path):
    _record(tmp_path, "r1", "explorer", Usage(input=1000, cost_usd=1.0))
    _record(tmp_path, "r1", "challenger", Usage(input=2000, cost_usd=2.0))
    _record(tmp_path, "r2", "explorer", Usage(input=500, cost_usd=0.5),
            started="2026-08-25T09:00:00+00:00")

    by_role = trace(tmp_path, by="role")
    assert by_role["explorer"].total == 1500 and by_role["challenger"].total == 2000
    by_day = trace(tmp_path, by="day")
    assert set(by_day) == {"2026-08-24", "2026-08-25"}
    assert total(tmp_path).total == 3500


def test_a_malformed_record_does_not_break_the_trace(tmp_path):
    _record(tmp_path, "r1", "explorer", Usage(input=100))
    bad = tmp_path / "r1" / "broken"
    bad.mkdir(parents=True)
    (bad / "run.json").write_text("{not json", encoding="utf-8")
    assert total(tmp_path).total == 100


def test_the_report_says_so_when_nothing_has_run(tmp_path):
    assert "no runs recorded" in report(tmp_path)[0]
