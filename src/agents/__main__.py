"""`python -m src.agents` — render the definitions, or run a pipeline.

    render                 write .claude/agents/*.md for the harness
    list                   the pipelines and the roles each runs
    plan <pipeline>        what would run, and what each step would be told
    run <pipeline>         run it, gating and recording each step
    tokens                 what has been spent, grouped by role, backend or day
    due [--run|--cron]     which scheduled jobs have come round
    remember <id> <url>    record a candidate that was turned down
    rejected               what has already been looked at and turned down

The markdown is generated rather than maintained, so there is one definition and
it is the Python: edit a role, re-render, and what the harness runs cannot drift
from what the tests check.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.agents import ROLES
from src.agents.memory import REJECTED, load as load_rejected, remember
from src.agents.pipelines import PIPELINES, plan, run_pipeline
from src.agents.schedule import CADENCE, crontab_line, due, run_due
from src.agents.tokens import Budget, report

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RENDER = PROJECT_ROOT / ".claude" / "agents"
DEFAULT_RUNS = PROJECT_ROOT / "data" / "agent-runs"


def render(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for role in ROLES.values():
        path = out / f"{role.name}.md"
        path.write_text(role.to_markdown(), encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rendered = sub.add_parser("render")
    rendered.add_argument("--out", type=Path, default=DEFAULT_RENDER)
    sub.add_parser("list")
    recall = sub.add_parser("remember", help="record a candidate that was turned down")
    recall.add_argument("id")
    recall.add_argument("url")
    recall.add_argument("--why", required=True, help="why it was refused; a person's words")
    recall.add_argument("--run-id", default="", help="the run whose outcome this was read from")

    sub.add_parser("rejected", help="what has already been looked at and turned down")

    when = sub.add_parser("due", help="which scheduled jobs have come round")
    when.add_argument("--run", action="store_true", help="run them, rather than only saying so")
    when.add_argument("--cron", action="store_true", help="print the crontab line and exit")

    spent = sub.add_parser("tokens")
    spent.add_argument("--root", type=Path, default=DEFAULT_RUNS)
    spent.add_argument("--by", choices=["role", "backend", "day"], default="role")
    for name in ("plan", "run"):
        node = sub.add_parser(name)
        node.add_argument("pipeline", choices=sorted(PIPELINES))
        node.add_argument("--root", type=Path, default=DEFAULT_RUNS)
        if name == "run":
            node.add_argument("--about", default="", help="what this run is about, e.g. a source id")
            node.add_argument("--run-id", default=None,
                              help="reuse a run id; with --resume, continue that run")
            node.add_argument("--resume", action="store_true",
                              help="skip steps that already finished under this run id")
            node.add_argument("--backend", choices=["sdk", "cli"], default=None)
            node.add_argument("--max-tokens", type=int, default=None,
                              help="stop before the step that would exceed this")
    args = parser.parse_args(argv)

    if args.command == "render":
        for path in render(args.out):
            print(f"wrote {path}")
        return 0

    if args.command == "tokens":
        for line in report(args.root, by=args.by):
            print(line)
        return 0

    if args.command == "remember":
        entry = remember(args.id, args.url, args.why, run_id=args.run_id)
        print(f"{entry.id} recorded as refused on {entry.when}: {entry.why}")
        print(f"commit {REJECTED.relative_to(PROJECT_ROOT)} so the next sweep inherits it")
        return 0

    if args.command == "rejected":
        rows = load_rejected()
        if not rows:
            print("nothing refused yet")
            return 0
        for row in rows:
            print(f"  {row.when}  {row.id:24s} {row.why}")
        return 0

    if args.command == "due":
        if args.cron:
            print(crontab_line())
            return 0
        if not args.run:
            ready = due()
            for job in CADENCE:
                mark = "due" if job in ready else ("manual" if job.manual else "not yet")
                every = "on request" if job.manual else f"every {job.every_days}d"
                print(f"  {job.name:16s} {every:12s} {mark:8s} {job.what}")
            return 0
        for name, outcome in run_due():
            print(f"  {name}: {outcome}")
        return 0

    if args.command == "list":
        for name, pipeline in sorted(PIPELINES.items()):
            print(f"{name}: {' → '.join(pipeline.roles)}")
            print(f"  {pipeline.purpose}")
        return 0

    pipeline = PIPELINES[args.pipeline]
    if args.command == "plan":
        for role, task in plan(pipeline, args.root):
            print(f"\n[{role}]\n{task}")
        return 0

    executor = None
    if args.backend:
        from src.agents.harness import CliExecutor, SdkExecutor

        executor = SdkExecutor() if args.backend == "sdk" else CliExecutor()

    budget = Budget(tokens=args.max_tokens) if args.max_tokens else None
    record = run_pipeline(pipeline, root=args.root, run_id=args.run_id, prefix=args.about,
                          resume=args.resume, executor=executor, budget=budget)
    for name in record.resumed:
        print(f"  {name:11s} reused from an earlier attempt")
    for result in record.results:
        gate = "" if result.gate_passed is None else f"  gate={result.gate_status}"
        cost = "" if result.outcome.cost_usd is None else f"  ${result.outcome.cost_usd:.2f}"
        print(f"  {result.role:11s} {'ok' if result.ok else 'failed'}{gate}{cost}  "
              f"{result.workspace}")
    spent = record.usage
    money = "" if spent.cost_usd is None else f", ${spent.cost_usd:.2f}"
    print(f"\nrun {record.run_id}: {spent.total:,} tokens "
          f"({spent.billable:,} billable, {spent.cache_read:,} cached){money}")
    if record.stopped_after:
        print(f"stopped after {record.stopped_after}: {record.stopped_because}")
        print(f"resume with: python -m src.agents run {pipeline.name} "
              f"--run-id {record.run_id} --resume")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
