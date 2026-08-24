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
from src.agents.harness import PROPOSAL_NAME, Result, _run, run

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
    started_at: str
    results: list[Result]
    stopped_after: str | None = None
    stopped_because: str = ""

    def as_record(self) -> dict:
        return {
            "pipeline": self.pipeline,
            "started_at": self.started_at,
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


def run_pipeline(
    pipeline: Pipeline,
    *,
    root: Path,
    prefix: str = "",
    runner: Callable[..., object] = _run,
    now: datetime | None = None,
) -> PipelineRun:
    """Run every step, stopping at the first whose gate refused what it produced.

    A proposal the gate refuses is not something the next step should reason
    about; carrying on would spend an agent on an artifact already known to be
    unsound.
    """
    started = (now or datetime.now(timezone.utc)).isoformat()
    record = PipelineRun(pipeline=pipeline.name, started_at=started, results=[])
    artifacts: dict[str, Path] = {}

    for step in pipeline.steps:
        task = step.task(artifacts)
        if prefix:
            task = f"{prefix}\n\n{task}"
        result = run(step.role, task, root=root, runner=runner, now=now)
        record.results.append(result)
        artifacts[step.role.name] = result.workspace / PROPOSAL_NAME

        if result.gate_passed is False:
            record.stopped_after = step.role.name
            record.stopped_because = "the gate refused what it produced"
            break
        if result.returncode != 0:
            record.stopped_after = step.role.name
            record.stopped_because = f"the role exited {result.returncode}"
            break

    root.mkdir(parents=True, exist_ok=True)
    (root / f"{pipeline.name}.json").write_text(
        json.dumps(record.as_record(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record
