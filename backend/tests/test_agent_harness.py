import json
from datetime import datetime, timezone
from pathlib import Path

from src.agents import ROLES
from src.agents.harness import PROPOSAL_NAME, agent_json, brief, command, run, workspace_for

WHEN = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)


class _FakeRun:
    """Stands in for subprocess.run, recording what was executed."""

    def __init__(self, gate_returncode=0):
        self.calls = []
        self.gate_returncode = gate_returncode

    def __call__(self, argv, cwd):
        self.calls.append(list(argv))
        is_gate = any("verify_catalog_change.py" in part for part in argv)
        code = self.gate_returncode if is_gate else 0
        return type("Done", (), {"returncode": code, "stdout": "output", "stderr": ""})()


def test_the_role_is_what_the_cli_consumes():
    # --agents takes exactly the JSON a Role serialises to, so nothing is
    # transcribed by hand between the definition and the invocation
    payload = json.loads(agent_json(ROLES["explorer"]))
    assert set(payload) == {"explorer"}
    assert payload["explorer"]["prompt"] == ROLES["explorer"].prompt
    assert payload["explorer"]["tools"] == list(ROLES["explorer"].tools)


def test_the_command_restricts_tools_and_opens_only_the_workspace(tmp_path):
    argv = command(ROLES["cleaner"], "look for redundancy", tmp_path)
    assert argv[:3] == ["claude", "-p", "look for redundancy"]
    assert argv[argv.index("--allowedTools") + 1] == " ".join(ROLES["cleaner"].tools)
    assert argv[argv.index("--add-dir") + 1] == str(tmp_path)
    assert argv[argv.index("--agent") + 1] == "cleaner"


def test_each_run_gets_its_own_workspace(tmp_path):
    first = workspace_for(ROLES["explorer"], tmp_path, now=WHEN)
    assert first.is_dir() and first.name == "20260824T090000Z-explorer"
    assert workspace_for(ROLES["cleaner"], tmp_path, now=WHEN) != first


def test_the_brief_tells_the_role_where_it_may_write(tmp_path):
    text = brief(ROLES["explorer"], "find sources", tmp_path)
    assert str(tmp_path) in text and PROPOSAL_NAME in text
    assert "Write nothing anywhere else" in text


def test_the_harness_gates_a_proposal_rather_than_trusting_the_role_to(tmp_path):
    # the role is told to check itself; instructing is not checking
    fake = _FakeRun()
    workspace = tmp_path / "20260824T090000Z-explorer"
    workspace.mkdir(parents=True)
    (workspace / PROPOSAL_NAME).write_text("{}", encoding="utf-8")

    result = run(ROLES["explorer"], "find sources", root=tmp_path, runner=fake, now=WHEN)
    assert result.gate_passed is True
    assert any("verify_catalog_change.py" in " ".join(call) for call in fake.calls)


def test_a_role_that_proposes_nothing_is_not_gated(tmp_path):
    fake = _FakeRun()
    result = run(ROLES["cleaner"], "audit", root=tmp_path, runner=fake, now=WHEN)
    assert result.gate_passed is None
    assert not any("verify_catalog_change.py" in " ".join(call) for call in fake.calls)


def test_a_proposing_role_that_left_nothing_behind_is_reported_as_such(tmp_path):
    result = run(ROLES["updater"], "upgrade core-mof", root=tmp_path, runner=_FakeRun(), now=WHEN)
    assert result.gate_passed is None
    assert PROPOSAL_NAME in result.gate_output


def test_every_run_leaves_a_record(tmp_path):
    # without one, a run's reasoning lives in a terminal that gets closed, and
    # the next run cannot know what the last one already declined
    result = run(ROLES["cleaner"], "audit the adapters", root=tmp_path, runner=_FakeRun(), now=WHEN)
    record = json.loads((result.workspace / "run.json").read_text(encoding="utf-8"))
    assert record["role"] == "cleaner"
    assert record["task"] == "audit the adapters"
    assert record["started_at"].startswith("2026-08-24")
    assert (result.workspace / "report.txt").read_text(encoding="utf-8") == "output"


def test_a_failing_gate_is_recorded_not_swallowed(tmp_path):
    workspace = tmp_path / "20260824T090000Z-explorer"
    workspace.mkdir(parents=True)
    (workspace / PROPOSAL_NAME).write_text("{}", encoding="utf-8")
    result = run(ROLES["explorer"], "find", root=tmp_path, runner=_FakeRun(gate_returncode=1),
                 now=WHEN)
    assert result.gate_passed is False
    assert json.loads((result.workspace / "run.json").read_text())["gate_passed"] is False
