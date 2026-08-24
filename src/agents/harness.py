"""Running a role, and the three things the harness adds around the run.

`claude -p --agents <json>` already runs an agent. What it does not do is any of
the parts that make a run safe to repeat, and those are what this module is:

* **a workspace outside the repository.** Every run gets its own directory and is
  told to write there, so a proposal cannot land in the working tree by accident
  and a bad run is undone by deleting a folder.
* **the gate, run by the harness rather than by the agent.** A role that proposes
  a catalog change is instructed to check itself; instructing is not the same as
  checking, so the harness runs the gate on whatever came back and records the
  verdict next to it.
* **a record of the run.** Which role, on what task, when, with which command,
  what the gate said. Without it a run's reasoning lives in a terminal that gets
  closed, and the next run cannot know what the last one already declined.

The role object is what the CLI consumes: `--agents` takes exactly the JSON a
`Role` serialises to, so nothing is transcribed by hand between the definition and
the invocation.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from src.agents.base import Role

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE = PROJECT_ROOT / "scripts" / "datasets" / "verify_catalog_change.py"
CATALOG = PROJECT_ROOT / "scripts" / "datasets" / "sources.json"

#: What a role that proposes a catalog change is expected to leave behind.
PROPOSAL_NAME = "proposal.json"


@dataclass(frozen=True)
class Result:
    role: str
    task: str
    workspace: Path
    command: tuple[str, ...]
    returncode: int
    report: str
    gate_returncode: int | None = None
    gate_output: str = ""
    started_at: str = ""

    @property
    def gate_passed(self) -> bool | None:
        return None if self.gate_returncode is None else self.gate_returncode == 0

    def as_record(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "task": self.task,
            "started_at": self.started_at,
            "command": list(self.command),
            "returncode": self.returncode,
            "gate_returncode": self.gate_returncode,
            "gate_passed": self.gate_passed,
            "workspace": str(self.workspace),
        }


def agent_json(role: Role) -> str:
    """The role as `--agents` expects it."""
    return json.dumps(
        {role.name: {"description": role.description, "prompt": role.prompt,
                     "tools": list(role.tools)}}
    )


def command(role: Role, task: str, workspace: Path, *, model: str | None = None) -> list[str]:
    argv = [
        "claude", "-p", task,
        "--agents", agent_json(role),
        "--agent", role.name,
        "--allowedTools", " ".join(role.tools),
        "--output-format", "json",
        "--add-dir", str(workspace),
    ]
    if model:
        argv += ["--model", model]
    return argv


def workspace_for(role: Role, root: Path, *, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{stamp}-{role.name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def brief(role: Role, task: str, workspace: Path) -> str:
    """The task, with the one thing every run has to be told: where to write."""
    return (
        f"{task}\n\n"
        f"Write anything you produce to {workspace}. A proposal goes in "
        f"{workspace / PROPOSAL_NAME}. Write nothing anywhere else."
    )


def _run(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True)


def check_proposal(workspace: Path, runner: Callable[..., Any] = _run) -> tuple[int | None, str]:
    """Run the gate on whatever the role left behind."""
    proposal = workspace / PROPOSAL_NAME
    if not proposal.exists():
        return None, f"no {PROPOSAL_NAME} in {workspace}"
    done = runner(
        ["python", str(GATE), "--catalog", str(proposal), "--before", str(CATALOG)],
        PROJECT_ROOT,
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def run(
    role: Role,
    task: str,
    *,
    root: Path,
    model: str | None = None,
    runner: Callable[..., Any] = _run,
    now: datetime | None = None,
) -> Result:
    """Run a role, gate what it produced, and record both."""
    started = (now or datetime.now(timezone.utc)).isoformat()
    workspace = workspace_for(role, root, now=now)
    argv = command(role, brief(role, task, workspace), workspace, model=model)

    done = runner(argv, PROJECT_ROOT)
    report = (done.stdout or "") + (done.stderr or "")
    (workspace / "report.txt").write_text(report, encoding="utf-8")

    gate_code, gate_output = (None, "")
    if role.proposes_catalog_change:
        gate_code, gate_output = check_proposal(workspace, runner=runner)
        (workspace / "gate.txt").write_text(gate_output, encoding="utf-8")

    result = Result(
        role=role.name, task=task, workspace=workspace, command=tuple(argv),
        returncode=done.returncode, report=report,
        gate_returncode=gate_code, gate_output=gate_output, started_at=started,
    )
    (workspace / "run.json").write_text(
        json.dumps(result.as_record(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
