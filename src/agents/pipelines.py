"""The fan-out shape, in code rather than decided per run.

Section 1.3 puts judgement in the agents and control flow in a script, and this is
the script. What runs, in what order, and what each step is told are the same
every time and reviewable as a diff — a manager agent deciding it instead would
add a way to get the shape wrong with no upside.

One design rule becomes a property here rather than a discipline. The challenger
must not see the explorer's report: it forms its own view from the artifact. So a
step builds its task from `Artifacts`, a mapping of role name to the file that
role left behind, and there is no route from there to a report. Blindness is not
something the caller has to remember.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from src.agents import ROLES
from src.agents.base import Role
from src.agents.harness import PROPOSAL_NAME, Executor, Result, run
from src.agents.tokens import Budget, Usage

#: role name -> the proposal that role produced. Deliberately not its report.
Artifacts = Mapping[str, Path]


@dataclass(frozen=True)
class Step:
    role: Role
    task: Callable[[Artifacts], str]


@dataclass(frozen=True)
class Pipeline:
    name: str
    purpose: str
    steps: tuple[Step, ...]

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(step.role.name for step in self.steps)


@dataclass
class PipelineRun:
    pipeline: str
    run_id: str
    started_at: str
    results: list[Result]
    resumed: tuple[str, ...] = ()
    stopped_after: str | None = None
    stopped_because: str = ""

    @property
    def usage(self) -> Usage:
        spent = Usage()
        for result in self.results:
            spent = spent + result.outcome.usage
        return spent

    @property
    def cost_usd(self) -> float | None:
        return self.usage.cost_usd

    def as_record(self) -> dict:
        return {
            "pipeline": self.pipeline,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "usage": self.usage.as_record(),
            "cost_usd": self.cost_usd,
            "resumed": list(self.resumed),
            "steps": [r.as_record() for r in self.results],
            "stopped_after": self.stopped_after,
            "stopped_because": self.stopped_because,
        }


DISCOVERY_SWEEP = Pipeline(
    name="discovery-sweep",
    purpose="Look for sources the catalog lacks, attack what turns up, and prepare the survivors.",
    steps=(
        Step(
            role=ROLES["explorer"],
            task=lambda _artifacts: (
                "Search for crystal-structure or materials-property databases that "
                "scripts/datasets/sources.json does not already hold, and propose them."
            ),
        ),
        Step(
            role=ROLES["challenger"],
            task=lambda artifacts: (
                "Try to reject every candidate in "
                f"{artifacts['explorer']}. That file is all you get: form your own view of each "
                "candidate from it and your own research."
            ),
        ),
        Step(
            role=ROLES["reviewer"],
            task=lambda artifacts: (
                f"Assemble the licence-gate packet for the candidates in {artifacts['explorer']}. "
                "Read the challenger's verdicts in its workspace alongside them."
            ),
        ),
    ),
)

UPGRADE = Pipeline(
    name="upgrade",
    purpose="Work out what to pull for a source whose upstream has moved, and prepare the decision.",
    steps=(
        Step(
            role=ROLES["updater"],
            task=lambda _artifacts: (
                "The probe reports this source is behind its upstream. Work out what to pull. "
                "The source id is in the task you were given by the caller."
            ),
        ),
        Step(
            role=ROLES["reviewer"],
            task=lambda artifacts: (
                f"Assemble the admission packet for the plan in {artifacts['updater']}."
            ),
        ),
    ),
)

AUDIT = Pipeline(
    name="audit",
    purpose="Go over what is already held, looking for redundancy and error.",
    steps=(
        Step(
            role=ROLES["cleaner"],
            task=lambda _artifacts: (
                "Run every detector in src/agents/detectors.py over the catalog and the adapters, "
                "and report what needs judging."
            ),
        ),
    ),
)

PIPELINES: dict[str, Pipeline] = {p.name: p for p in (DISCOVERY_SWEEP, UPGRADE, AUDIT)}


def plan(pipeline: Pipeline, root: Path) -> list[tuple[str, str]]:
    """What would run, without running it. Paths are illustrative."""
    artifacts: dict[str, Path] = {}
    out = []
    for step in pipeline.steps:
        name = step.role.name
        out.append((name, step.task(artifacts)))
        artifacts[name] = root / f"<{name} workspace>" / PROPOSAL_NAME
    return out


def _finished(workspace: Path) -> bool:
    record = workspace / "run.json"
    if not record.exists():
        return False
    try:
        return bool(json.loads(record.read_text(encoding="utf-8")).get("ok"))
    except ValueError:
        return False


def run_pipeline(
    pipeline: Pipeline,
    *,
    root: Path,
    run_id: str | None = None,
    prefix: str = "",
    resume: bool = False,
    budget: Budget | None = None,
    executor: Executor | None = None,
    now: datetime | None = None,
    **run_kwargs,
) -> PipelineRun:
    """Run every step, stopping at the first whose gate refused what it produced.

    A proposal the gate refuses is not something the next step should reason
    about; carrying on would spend an agent on an artifact already known to be
    unsound.

    `resume` reuses a step that finished in a previous attempt at the same
    `run_id` rather than paying for it again. A step is only skipped if its own
    record says it succeeded — a half-written workspace is redone.

    `budget` is checked **before** a step, not after: a ceiling you discover you
    have crossed is a report, not a ceiling. The step that would have broken it
    is named as where the run stopped.
    """
    when = now or datetime.now(timezone.utc)
    run_id = run_id or when.strftime("%Y%m%dT%H%M%SZ")
    record = PipelineRun(pipeline=pipeline.name, run_id=run_id,
                         started_at=when.isoformat(), results=[])
    artifacts: dict[str, Path] = {}
    resumed: list[str] = []

    for step in pipeline.steps:
        workspace = root / run_id / step.role.name
        if resume and _finished(workspace):
            resumed.append(step.role.name)
            artifacts[step.role.name] = workspace / PROPOSAL_NAME
            continue

        if budget is not None and budget.exhausted:
            record.stopped_after = step.role.name
            record.stopped_because = budget.why()
            break

        task = step.task(artifacts)
        if prefix:
            task = f"{prefix}\n\n{task}"
        result = run(step.role, task, workspace=workspace, executor=executor,
                     now=when, **run_kwargs)
        record.results.append(result)
        artifacts[step.role.name] = workspace / PROPOSAL_NAME
        if budget is not None:
            budget.record(result.outcome.usage)

        if result.gate_passed is False:
            record.stopped_after = step.role.name
            record.stopped_because = "the gate refused what it produced"
            break
        if not result.ok:
            record.stopped_after = step.role.name
            record.stopped_because = result.outcome.error or "the role did not succeed"
            break

    record.resumed = tuple(resumed)
    (root / run_id).mkdir(parents=True, exist_ok=True)
    (root / run_id / "pipeline.json").write_text(
        json.dumps(record.as_record(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record
