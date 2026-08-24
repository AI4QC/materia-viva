"""Running a role: two ways to execute one, and the parts neither gives you.

Execution has two backends. `SdkExecutor` runs the agent loop in this process
through `claude_agent_sdk`, which reports what the run cost; `CliExecutor` shells
out to `claude -p` and needs nothing installed. The SDK is a 93 MB
platform-specific wheel, so it is an optional dependency the harness prefers when
it is importable rather than something the repository requires.

Around either, the harness adds what makes a run safe to repeat:

* **a workspace outside the repository** per run, so a proposal cannot land in the
  working tree and a bad run is undone by deleting a folder;
* **the gate, run by the harness.** A role that proposes a catalog change is told
  to check itself; instructing is not checking;
* **a record** — role, task, backend, attempts, cost, turns, gate verdict — because
  otherwise a run's reasoning lives in a terminal that gets closed;
* **a timeout and bounded retries**, retrying only what is worth retrying: a
  transport failure, never a role that ran and reached a conclusion.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from src.agents.base import Role
from src.agents.tokens import Usage, from_anthropic_model_usage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE = PROJECT_ROOT / "scripts" / "datasets" / "verify_catalog_change.py"
CATALOG = PROJECT_ROOT / "scripts" / "datasets" / "sources.json"

PROPOSAL_NAME = "proposal.json"
DEFAULT_TIMEOUT = 1800.0
DEFAULT_ATTEMPTS = 2
#: Retrying a role that ran and concluded just spends tokens on the same answer.
#: These are the failures where the role never got to run.
RETRYABLE = ("timed out", "connection", "CLINotFound", "ProcessError")


@dataclass(frozen=True)
class Outcome:
    """What an executor got back, independent of which backend produced it.

    `usage` is provider-neutral on purpose: an executor maps whatever its vendor
    reports into `Usage`, so the budget, the trace and the records never learn
    who ran the work.
    """

    ok: bool
    text: str
    usage: Usage = field(default_factory=Usage)
    turns: int | None = None
    duration_ms: int | None = None
    error: str = ""

    @property
    def cost_usd(self) -> float | None:
        return self.usage.cost_usd

    @property
    def retryable(self) -> bool:
        blob = f"{self.error}".lower()
        return not self.ok and any(token.lower() in blob for token in RETRYABLE)


class Executor(Protocol):
    """The provider seam.

    Everything above this line is ours — roles, gates, records, budgets — and
    everything below it belongs to whoever runs the model. A second vendor is a
    third class here, not a change anywhere else, provided it maps what it
    reports into `Usage` and answers with an `Outcome`.
    """

    name: str

    def __call__(self, role: Role, prompt: str, workspace: Path, *,
                 model: str | None, timeout: float) -> Outcome: ...


class CliExecutor:
    """`claude -p`, in a subprocess. Needs nothing installed beyond the CLI."""

    name = "cli"

    def __call__(self, role: Role, prompt: str, workspace: Path, *,
                 model: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> Outcome:
        argv = command(role, prompt, workspace, model=model)
        try:
            done = subprocess.run(argv, cwd=PROJECT_ROOT, capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return Outcome(ok=False, text="", error=f"timed out after {timeout}s")
        except FileNotFoundError as error:
            return Outcome(ok=False, text="", error=f"CLINotFound: {error}")
        text = (done.stdout or "") + (done.stderr or "")
        usage, turns = Usage(), None
        try:  # --output-format json, when the run got far enough to emit it
            payload = json.loads(done.stdout)
            usage = from_anthropic_model_usage(payload.get("modelUsage"),
                                               payload.get("total_cost_usd"))
            turns = payload.get("num_turns")
        except (ValueError, TypeError):
            pass
        return Outcome(ok=done.returncode == 0, text=text, usage=usage, turns=turns,
                       error="" if done.returncode == 0 else f"exit {done.returncode}")


class SdkExecutor:
    """The agent loop in this process, through `claude_agent_sdk`."""

    name = "sdk"

    def __call__(self, role: Role, prompt: str, workspace: Path, *,
                 model: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> Outcome:
        import asyncio

        from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, ResultMessage, query

        options = ClaudeAgentOptions(
            agents={role.name: AgentDefinition(
                description=role.description, prompt=role.prompt, tools=list(role.tools)
            )},
            allowed_tools=list(role.tools),
            cwd=str(PROJECT_ROOT),
            add_dirs=[str(workspace)],
            **({"model": model} if model else {}),
        )

        async def drive() -> Outcome:
            said: list[str] = []
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    return Outcome(
                        ok=not message.is_error,
                        text=message.result or "\n".join(said),
                        usage=from_anthropic_model_usage(message.model_usage,
                                                         message.total_cost_usd),
                        turns=message.num_turns,
                        duration_ms=message.duration_ms,
                        error="" if not message.is_error else str(message.errors or "error"),
                    )
                said.append(str(getattr(message, "content", message))[:4000])
            return Outcome(ok=False, text="\n".join(said), error="no result message")

        try:
            return asyncio.run(asyncio.wait_for(drive(), timeout))
        except TimeoutError:
            return Outcome(ok=False, text="", error=f"timed out after {timeout}s")
        except Exception as error:  # a transport failure is worth retrying; see RETRYABLE
            return Outcome(ok=False, text="", error=f"{type(error).__name__}: {error}")


def default_executor() -> Executor:
    """The SDK when it is importable, the CLI otherwise."""
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return CliExecutor()
    return SdkExecutor()


@dataclass(frozen=True)
class Result:
    role: str
    task: str
    workspace: Path
    backend: str
    outcome: Outcome
    attempts: int
    started_at: str
    gate_returncode: int | None = None
    gate_output: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome.ok

    @property
    def gate_passed(self) -> bool | None:
        return None if self.gate_returncode is None else self.gate_returncode == 0

    def as_record(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "task": self.task,
            "backend": self.backend,
            "started_at": self.started_at,
            "ok": self.ok,
            "attempts": self.attempts,
            "error": self.outcome.error,
            "usage": self.outcome.usage.as_record(),
            "cost_usd": self.outcome.usage.cost_usd,
            "turns": self.outcome.turns,
            "duration_ms": self.outcome.duration_ms,
            "gate_returncode": self.gate_returncode,
            "gate_passed": self.gate_passed,
            "workspace": str(self.workspace),
        }


def agent_json(role: Role) -> str:
    """The role as the CLI's `--agents` expects it."""
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


def brief(task: str, workspace: Path) -> str:
    """The task, with the one thing every run has to be told: where to write."""
    return (
        f"{task}\n\n"
        f"Write anything you produce to {workspace}. A proposal goes in "
        f"{workspace / PROPOSAL_NAME}. Write nothing anywhere else."
    )


def _gate(workspace: Path, runner: Callable[..., Any]) -> tuple[int | None, str]:
    proposal = workspace / PROPOSAL_NAME
    if not proposal.exists():
        return None, f"no {PROPOSAL_NAME} in {workspace}"
    done = runner(
        ["python", str(GATE), "--catalog", str(proposal), "--before", str(CATALOG)],
        PROJECT_ROOT,
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _subprocess(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True)


def run(
    role: Role,
    task: str,
    *,
    workspace: Path,
    executor: Executor | None = None,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    attempts: int = DEFAULT_ATTEMPTS,
    gate_runner: Callable[..., Any] = _subprocess,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    """Run a role, gate what it produced, and record both."""
    executor = executor or default_executor()
    workspace.mkdir(parents=True, exist_ok=True)
    started = (now or datetime.now(timezone.utc)).isoformat()
    prompt = brief(task, workspace)

    used = 0
    outcome = Outcome(ok=False, text="", error="never ran")
    for attempt in range(1, attempts + 1):
        used = attempt
        outcome = executor(role, prompt, workspace, model=model, timeout=timeout)
        if outcome.ok or not outcome.retryable:
            break
        sleep(min(30.0, 2.0 ** attempt))

    (workspace / "report.txt").write_text(outcome.text, encoding="utf-8")

    gate_code, gate_output = (None, "")
    if role.proposes_catalog_change:
        gate_code, gate_output = _gate(workspace, gate_runner)
        (workspace / "gate.txt").write_text(gate_output, encoding="utf-8")

    result = Result(
        role=role.name, task=task, workspace=workspace, backend=executor.name,
        outcome=outcome, attempts=used, started_at=started,
        gate_returncode=gate_code, gate_output=gate_output,
    )
    (workspace / "run.json").write_text(
        json.dumps(result.as_record(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
