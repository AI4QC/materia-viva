import json
from datetime import datetime, timezone

import pytest

from src.agents import ROLES
from src.agents.tokens import Usage
from scripts.datasets import verify_catalog_change
from src.agents.harness import (
    CATALOG,
    GATE_REFUSED,
    PROPOSAL_NAME,
    CliExecutor,
    Outcome,
    SdkExecutor,
    agent_json,
    brief,
    command,
    default_executor,
    run,
)

WHEN = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)


class _FakeExecutor:
    """An executor whose answers the test dictates."""

    name = "fake"

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes) or [Outcome(ok=True, text="done", usage=Usage(input=100, output=50, cost_usd=0.5), turns=3)]
        self.calls = []

    def __call__(self, role, prompt, workspace, *, model=None, timeout=None):
        self.calls.append((role.name, prompt, workspace))
        return self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]


def _gate_runner(returncode=0):
    def runner(argv, cwd):
        return type("Done", (), {"returncode": returncode, "stdout": "gate said so", "stderr": ""})()
    return runner


def test_only_a_failure_the_role_never_survived_is_retried():
    # retrying a role that ran and concluded just spends tokens on the same answer
    assert Outcome(ok=False, text="", error="timed out after 5s").retryable
    assert Outcome(ok=False, text="", error="CLINotFound: no claude").retryable
    assert not Outcome(ok=False, text="", error="exit 1").retryable
    assert not Outcome(ok=True, text="fine").retryable


def test_the_role_is_what_the_cli_consumes():
    payload = json.loads(agent_json(ROLES["explorer"]))
    assert payload["explorer"]["prompt"] == ROLES["explorer"].prompt
    assert payload["explorer"]["tools"] == list(ROLES["explorer"].tools)


def test_the_command_restricts_tools_and_opens_only_the_workspace(tmp_path):
    argv = command(ROLES["cleaner"], "look for redundancy", tmp_path)
    assert argv[argv.index("--allowedTools") + 1] == " ".join(ROLES["cleaner"].tools)
    assert argv[argv.index("--add-dir") + 1] == str(tmp_path)
    assert argv[argv.index("--agent") + 1] == "cleaner"


def test_the_backend_is_the_sdk_when_it_is_importable():
    # a 93 MB platform-specific wheel, so it is preferred when present rather
    # than required; without it the CLI backend needs nothing installed
    assert isinstance(default_executor(), (SdkExecutor, CliExecutor))


def test_the_brief_tells_the_role_where_it_may_write(tmp_path):
    text = brief("find sources", tmp_path)
    assert str(tmp_path) in text and PROPOSAL_NAME in text
    assert "Write nothing anywhere else" in text


def test_the_harness_gates_a_proposal_rather_than_trusting_the_role_to(tmp_path):
    (tmp_path / PROPOSAL_NAME).write_text("{}", encoding="utf-8")
    result = run(ROLES["explorer"], "find", workspace=tmp_path, executor=_FakeExecutor(),
                 gate_runner=_gate_runner(), now=WHEN)
    assert result.gate_passed is True
    assert (tmp_path / "gate.txt").read_text(encoding="utf-8") == "gate said so"


def test_a_role_that_proposes_nothing_is_not_gated(tmp_path):
    result = run(ROLES["cleaner"], "audit", workspace=tmp_path, executor=_FakeExecutor(),
                 now=WHEN)
    assert result.gate_passed is None
    assert not (tmp_path / "gate.txt").exists()


def test_a_proposing_role_that_left_nothing_behind_does_not_pass_the_gate(tmp_path):
    # it proposed a catalog change and nothing checked it, which is not "no gate applies"
    result = run(ROLES["updater"], "upgrade", workspace=tmp_path, executor=_FakeExecutor(),
                 now=WHEN)
    assert result.gate_status == "no-proposal"
    assert result.gate_passed is False and PROPOSAL_NAME in result.gate_output


def test_a_gate_that_could_not_run_is_not_read_as_a_refusal(tmp_path):
    (tmp_path / PROPOSAL_NAME).write_text("{}", encoding="utf-8")
    result = run(ROLES["explorer"], "find", workspace=tmp_path, executor=_FakeExecutor(),
                 gate_runner=_gate_runner(1), now=WHEN)
    assert result.gate_status == "did-not-run"
    assert result.gate_passed is False


def test_the_refusal_code_is_the_one_the_gate_actually_exits_with():
    # two files, one number: if the gate renumbers, the harness stops understanding it
    assert GATE_REFUSED == verify_catalog_change.REFUSED


@pytest.mark.parametrize("proposal,expected", [
    ("unchanged", "passed"),
    ("bad", "refused"),
])
def test_the_real_gate_runs_from_the_harness(tmp_path, monkeypatch, proposal, expected):
    """No fake runner. A gate that cannot even import is the bug this pins.

    The harness invokes the gate as a subprocess, and the gate imports
    `scripts.datasets.*`. Every test above supplies a fake runner, so nothing
    exercised the one call that has to work.
    """
    # the caller is not obliged to have set this; the harness is
    monkeypatch.delenv("PYTHONPATH", raising=False)

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if proposal == "bad":
        catalog["sources"].append(
            {"id": "zzz-not-a-source", "name": "T", "access": "open",
             "official_url": "https://example.org", "license": "CC-BY-4.0",
             "data_path": "/absolute/and/therefore/unsafe", "status": "candidate",
             "downloads": []}
        )
    (tmp_path / PROPOSAL_NAME).write_text(json.dumps(catalog), encoding="utf-8")

    result = run(ROLES["explorer"], "find", workspace=tmp_path, executor=_FakeExecutor(),
                 now=WHEN)
    assert result.gate_status == expected, result.gate_output
    assert "ModuleNotFoundError" not in result.gate_output


def test_a_retryable_failure_is_retried_and_a_conclusive_one_is_not(tmp_path):
    slept = []
    flaky = _FakeExecutor(Outcome(ok=False, text="", error="connection reset"),
                          Outcome(ok=True, text="second time", usage=Usage(cost_usd=0.2)))
    result = run(ROLES["cleaner"], "audit", workspace=tmp_path, executor=flaky,
                 attempts=3, sleep=slept.append, now=WHEN)
    assert result.ok and result.attempts == 2 and slept

    stubborn = _FakeExecutor(Outcome(ok=False, text="", error="exit 1"))
    result = run(ROLES["cleaner"], "audit", workspace=tmp_path, executor=stubborn,
                 attempts=3, sleep=slept.append, now=WHEN)
    assert not result.ok and result.attempts == 1


def test_the_record_carries_what_the_run_cost(tmp_path):
    # without it there is no way to know whether a monthly sweep is affordable
    run(ROLES["cleaner"], "audit", workspace=tmp_path,
        executor=_FakeExecutor(Outcome(ok=True, text="x", turns=7, duration_ms=9000,
                                       usage=Usage(input=2000, output=800, cache_read=9000,
                                                   cost_usd=1.25))),
        now=WHEN)
    record = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert record["cost_usd"] == 1.25 and record["turns"] == 7
    # tokens, not just dollars: they are what still compares after a provider change
    assert record["usage"]["input"] == 2000 and record["usage"]["cache_read"] == 9000
    assert record["usage"]["total"] == 11800 and record["usage"]["billable"] == 2800
    assert record["backend"] == "fake" and record["attempts"] == 1
    assert record["started_at"].startswith("2026-08-24")
