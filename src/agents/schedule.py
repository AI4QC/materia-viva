"""When each job is next due, so cron does not have to know.

The alternative is a crontab line per job, which puts the policy somewhere
nobody reviews: a cadence living in one person's crontab cannot be read in a
diff, does not travel with the repository, and drifts from what the documents
say without anything noticing. So cron gets **one** dumb line, and the decision
about how often each job should run is a table here.

Cadence is deliberately conservative:

* the probe is cheap and deterministic — 38 HTTP requests through the polite
  poller — so it runs weekly;
* `audit` is one agent over what we already hold, so it runs monthly;
* `discovery-sweep` is **manual**. `agent-framework.md` says nothing should put
  it on a timer until a sweep has run unattended once and been read, and none
  has. Changing that is one word in this table, once someone has read one;
* `upgrade` is manual because it cannot be scheduled at all: it needs to be told
  which source moved, which is what the probe's output is for.

A job that has never run is due immediately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE = PROJECT_ROOT / "data" / "agent-runs" / "schedule.json"


@dataclass(frozen=True)
class Job:
    name: str
    #: None means this job is never due on its own; a person starts it
    every_days: int | None
    what: str

    @property
    def manual(self) -> bool:
        return self.every_days is None


CADENCE: tuple[Job, ...] = (
    Job("probe", 7, "read-only upstream change detection over the catalogued sources"),
    Job("audit", 30, "the cleaner over the catalog and the adapters"),
    Job("discovery-sweep", None, "look for sources the catalog lacks — costs ~300k tokens"),
    Job("upgrade", None, "needs a source id; start it from what the probe reported"),
)

JOBS: dict[str, Job] = {job.name: job for job in CADENCE}


def load_state(path: Path = DEFAULT_STATE) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:  # a truncated write should not stop the schedule for ever
        return {}


def mark(name: str, *, path: Path = DEFAULT_STATE, now: datetime | None = None) -> None:
    state = load_state(path)
    state[name] = (now or datetime.now(timezone.utc)).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def due(*, path: Path = DEFAULT_STATE, now: datetime | None = None) -> list[Job]:
    """The jobs whose cadence has elapsed. Manual jobs are never in it."""
    when = now or datetime.now(timezone.utc)
    state = load_state(path)
    ready = []
    for job in CADENCE:
        if job.manual:
            continue
        last = state.get(job.name)
        if last is None:
            ready.append(job)
            continue
        try:
            seen = datetime.fromisoformat(last)
        except ValueError:
            ready.append(job)
            continue
        if when - seen >= timedelta(days=job.every_days):
            ready.append(job)
    return ready


def crontab_line(python: str = "python") -> str:
    """The one line cron needs. Printed, never installed — that is the user's crontab."""
    return (
        f"0 4 * * *  cd {PROJECT_ROOT} && PYTHONPATH=backend:. {python} -m src.agents due --run "
        f">> {PROJECT_ROOT / 'data' / 'agent-runs' / 'schedule.log'} 2>&1"
    )


def run_due(
    *,
    path: Path = DEFAULT_STATE,
    now: datetime | None = None,
    runners: dict[str, Callable[[], None]] | None = None,
) -> list[tuple[str, str]]:
    """Run what is due, and record that it ran. Returns (job, outcome) per job.

    A job that raises is reported and **not** marked, so the next tick tries it
    again rather than treating a failure as a completed run.
    """
    # `is None`, not `or`: an empty mapping means "no runners", and treating it as
    # "use the defaults" is how a test asking for nothing ran the real probe.
    runners = _default_runners() if runners is None else runners
    done = []
    for job in due(path=path, now=now):
        runner = runners.get(job.name)
        if runner is None:
            done.append((job.name, "no runner"))
            continue
        try:
            runner()
        except Exception as error:  # noqa: BLE001 - reported, and the job stays due
            done.append((job.name, f"failed: {type(error).__name__}: {error}"))
            continue
        mark(job.name, path=path, now=now)
        done.append((job.name, "ran"))
    return done


def _default_runners() -> dict[str, Callable[[], None]]:
    def probe() -> None:
        from scripts.datasets.probe_upstream import main as probe_main

        probe_main([])

    def audit() -> None:
        from src.agents.pipelines import AUDIT, run_pipeline

        run_pipeline(AUDIT, root=DEFAULT_STATE.parent)

    return {"probe": probe, "audit": audit}
