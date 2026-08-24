import json
from datetime import datetime, timezone
from pathlib import Path

from src.agents.harness import PROPOSAL_NAME
from src.agents.pipelines import DISCOVERY_SWEEP, PIPELINES, plan, run_pipeline

WHEN = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)


class _FakeRun:
    def __init__(self, gate_fails_for=(), exit_for=()):
        self.calls = []
        self.gate_fails_for = set(gate_fails_for)
        self.exit_for = set(exit_for)
        self.current = None

    def __call__(self, argv, cwd):
        # keyed on argv[0], not on the text: a role's prompt contains the gate
        # command it is told to run, so searching the whole argv classifies the
        # agent invocation itself as a gate call
        self.calls.append(list(argv))
        if argv[0] == "claude":
            self.current = argv[argv.index("--agent") + 1]
            code = 1 if self.current in self.exit_for else 0
        else:
            code = 1 if self.current in self.gate_fails_for else 0
        return type("Done", (), {"returncode": code, "stdout": "out", "stderr": ""})()


def _seed_proposal(root, role, when=WHEN):
    workspace = root / f"{when.strftime('%Y%m%dT%H%M%SZ')}-{role}"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / PROPOSAL_NAME).write_text("{}", encoding="utf-8")


def test_every_pipeline_names_roles_that_exist():
    from src.agents import ROLES

    for pipeline in PIPELINES.values():
        assert pipeline.steps and pipeline.purpose.strip()
        for role in pipeline.roles:
            assert role in ROLES


def test_the_challenger_is_handed_the_artifact_and_never_the_report():
    """Section 1.3's blindness, made a property rather than a discipline.

    A step builds its task from a mapping of role name to the file that role left
    behind. There is no route from there to a report, so the caller cannot leak
    one by forgetting not to.
    """
    steps = dict(plan(DISCOVERY_SWEEP, Path("/runs")))
    assert PROPOSAL_NAME in steps["challenger"]
    assert "report" not in steps["challenger"].lower()
    assert "That file is all you get" in steps["challenger"]


def test_a_step_runs_with_the_previous_steps_artifact(tmp_path):
    fake = _FakeRun()
    for role in ("explorer", "challenger", "reviewer"):
        _seed_proposal(tmp_path, role)
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, runner=fake, now=WHEN)
    assert [r.role for r in record.results] == ["explorer", "challenger", "reviewer"]
    challenger_task = [c for c in fake.calls if "--agent" in c and c[c.index("--agent") + 1] == "challenger"]
    assert str(tmp_path) in challenger_task[0][2]


def test_a_refused_gate_stops_the_pipeline(tmp_path):
    # carrying on would spend an agent reasoning about an artifact already known
    # to be unsound
    _seed_proposal(tmp_path, "explorer")
    fake = _FakeRun(gate_fails_for={"explorer"})
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, runner=fake, now=WHEN)
    assert [r.role for r in record.results] == ["explorer"]
    assert record.stopped_after == "explorer"
    assert "gate refused" in record.stopped_because


def test_a_role_exiting_nonzero_stops_the_pipeline(tmp_path):
    fake = _FakeRun(exit_for={"explorer"})
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, runner=fake, now=WHEN)
    assert record.stopped_after == "explorer"
    assert "exited 1" in record.stopped_because


def test_the_whole_run_is_recorded_not_just_each_step(tmp_path):
    for role in ("cleaner",):
        _seed_proposal(tmp_path, role)
    run_pipeline(PIPELINES["audit"], root=tmp_path, runner=_FakeRun(), now=WHEN)
    record = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert record["pipeline"] == "audit"
    assert [s["role"] for s in record["steps"]] == ["cleaner"]
    assert record["stopped_after"] is None


def test_what_a_run_is_about_reaches_every_step(tmp_path):
    fake = _FakeRun()
    run_pipeline(PIPELINES["upgrade"], root=tmp_path, prefix="source: core-mof",
                 runner=fake, now=WHEN)
    agent_calls = [c for c in fake.calls if "--agent" in c]
    assert all("source: core-mof" in c[2] for c in agent_calls)
