import json
from datetime import datetime, timezone
from pathlib import Path

from src.agents.harness import GATE_REFUSED, PROPOSAL_NAME, Outcome
from src.agents.tokens import Budget, Usage
from src.agents.pipelines import DISCOVERY_SWEEP, PIPELINES, plan, run_pipeline

WHEN = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
RUN_ID = "20260824T090000Z"


class _FakeExecutor:
    name = "fake"

    def __init__(self, fail_for=(), cost=0.5, tokens=1000):
        self.fail_for = set(fail_for)
        self.cost = cost
        self.tokens = tokens
        self.calls = []

    def __call__(self, role, prompt, workspace, *, model=None, timeout=None):
        self.calls.append((role.name, prompt))
        if role.name in self.fail_for:
            return Outcome(ok=False, text="", error="exit 1")
        if role.proposes_catalog_change:  # as a real role would, for the gate to read
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / PROPOSAL_NAME).write_text("{}", encoding="utf-8")
        return Outcome(ok=True, text="done", turns=2,
                       usage=Usage(input=self.tokens, output=0, cost_usd=self.cost))


def _gate(returncode=0):
    def runner(argv, cwd):
        return type("Done", (), {"returncode": returncode, "stdout": "g", "stderr": ""})()
    return runner


def _seed(root, role, ok=True):
    workspace = root / RUN_ID / role
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / PROPOSAL_NAME).write_text("{}", encoding="utf-8")
    (workspace / "run.json").write_text(json.dumps({"role": role, "ok": ok}), encoding="utf-8")
    return workspace


def test_every_pipeline_names_roles_that_exist():
    from src.agents import ROLES

    for pipeline in PIPELINES.values():
        assert pipeline.steps and pipeline.purpose.strip()
        assert all(role in ROLES for role in pipeline.roles)


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


def test_a_step_is_handed_the_previous_steps_artifact(tmp_path):
    fake = _FakeExecutor()
    run_pipeline(DISCOVERY_SWEEP, root=tmp_path, run_id=RUN_ID, executor=fake,
                 gate_runner=_gate(), now=WHEN)
    challenger_prompt = next(p for name, p in fake.calls if name == "challenger")
    assert str(tmp_path / RUN_ID / "explorer" / PROPOSAL_NAME) in challenger_prompt


def test_a_refused_gate_stops_the_pipeline(tmp_path):
    # carrying on would spend an agent reasoning about an artifact already known
    # to be unsound
    (tmp_path / RUN_ID / "explorer").mkdir(parents=True)
    (tmp_path / RUN_ID / "explorer" / PROPOSAL_NAME).write_text("{}", encoding="utf-8")
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, run_id=RUN_ID,
                          executor=_FakeExecutor(), gate_runner=_gate(GATE_REFUSED), now=WHEN)
    assert [r.role for r in record.results] == ["explorer"]
    assert record.stopped_after == "explorer" and "gate refused" in record.stopped_because


class _SilentExecutor(_FakeExecutor):
    """Succeeds, and leaves no proposal — the shape a role failing quietly takes."""

    def __call__(self, role, prompt, workspace, *, model=None, timeout=None):
        self.calls.append((role.name, prompt))
        return Outcome(ok=True, text="done", usage=Usage(input=10, output=0))


def test_a_proposing_role_that_leaves_nothing_stops_the_pipeline(tmp_path):
    # otherwise the next step is handed a path to a file that was never written
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, run_id=RUN_ID,
                          executor=_SilentExecutor(), gate_runner=_gate(), now=WHEN)
    assert record.stopped_after == "explorer"
    assert "no proposal" in record.stopped_because
    assert [r.role for r in record.results] == ["explorer"]


def test_a_role_that_does_not_succeed_stops_the_pipeline(tmp_path):
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, run_id=RUN_ID,
                          executor=_FakeExecutor(fail_for={"explorer"}),
                          gate_runner=_gate(), now=WHEN)
    assert record.stopped_after == "explorer" and record.stopped_because == "exit 1"


def test_resuming_reuses_a_step_that_already_finished(tmp_path):
    # a sweep costs on the order of 300k tokens; redoing a step that succeeded
    # because a later one broke is the expensive way to fail
    _seed(tmp_path, "explorer", ok=True)
    fake = _FakeExecutor()
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, run_id=RUN_ID, resume=True,
                          executor=fake, gate_runner=_gate(), now=WHEN)
    assert record.resumed == ("explorer",)
    assert [name for name, _ in fake.calls] == ["challenger", "reviewer"]


def test_a_step_that_failed_before_is_redone_not_resumed(tmp_path):
    _seed(tmp_path, "explorer", ok=False)
    fake = _FakeExecutor()
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, run_id=RUN_ID, resume=True,
                          executor=fake, gate_runner=_gate(), now=WHEN)
    assert record.resumed == ()
    assert [name for name, _ in fake.calls][0] == "explorer"


def test_the_run_records_what_the_whole_pipeline_cost(tmp_path):
    record = run_pipeline(PIPELINES["audit"], root=tmp_path, run_id=RUN_ID,
                          executor=_FakeExecutor(cost=0.25), now=WHEN)
    assert record.cost_usd == 0.25 and record.usage.total == 1000
    written = json.loads((tmp_path / RUN_ID / "pipeline.json").read_text(encoding="utf-8"))
    assert written["pipeline"] == "audit" and written["cost_usd"] == 0.25
    assert written["run_id"] == RUN_ID


def test_what_a_run_is_about_reaches_every_step(tmp_path):
    fake = _FakeExecutor()
    run_pipeline(PIPELINES["upgrade"], root=tmp_path, run_id=RUN_ID, prefix="source: core-mof",
                 executor=fake, gate_runner=_gate(), now=WHEN)
    assert all("source: core-mof" in prompt for _name, prompt in fake.calls)


def test_a_budget_stops_the_run_before_the_step_that_would_break_it(tmp_path):
    # a ceiling you discover you have crossed is a report, not a ceiling
    budget = Budget(tokens=1500)
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, run_id=RUN_ID,
                          executor=_FakeExecutor(tokens=1000), gate_runner=_gate(),
                          budget=budget, now=WHEN)
    # explorer spends 1000, challenger 1000 and takes it past 1500, reviewer never starts
    assert [r.role for r in record.results] == ["explorer", "challenger"]
    assert record.stopped_after == "reviewer"
    assert "token budget of 1,500 is spent" in record.stopped_because


def test_a_budget_with_room_does_not_interfere(tmp_path):
    budget = Budget(tokens=1_000_000)
    record = run_pipeline(DISCOVERY_SWEEP, root=tmp_path, run_id=RUN_ID,
                          executor=_FakeExecutor(tokens=1000), gate_runner=_gate(),
                          budget=budget, now=WHEN)
    assert record.stopped_after is None
    assert budget.spent.total == 3000 and budget.remaining_tokens == 997_000
