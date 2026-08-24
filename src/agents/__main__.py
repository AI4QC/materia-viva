"""`python -m src.agents` — render the definitions, or run a pipeline.

    render                 write .claude/agents/*.md for the harness
    list                   the pipelines and the roles each runs
    plan <pipeline>        what would run, and what each step would be told
    run <pipeline>         run it, gating and recording each step

The markdown is generated rather than maintained, so there is one definition and
it is the Python: edit a role, re-render, and what the harness runs cannot drift
from what the tests check.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.agents import ROLES
from src.agents.pipelines import PIPELINES, plan, run_pipeline

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
    for name in ("plan", "run"):
        node = sub.add_parser(name)
        node.add_argument("pipeline", choices=sorted(PIPELINES))
        node.add_argument("--root", type=Path, default=DEFAULT_RUNS)
        if name == "run":
            node.add_argument("--about", default="", help="what this run is about, e.g. a source id")
    args = parser.parse_args(argv)

    if args.command == "render":
        for path in render(args.out):
            print(f"wrote {path}")
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

    record = run_pipeline(pipeline, root=args.root, prefix=args.about)
    for result in record.results:
        gate = "" if result.gate_passed is None else f"  gate={'ok' if result.gate_passed else 'refused'}"
        print(f"  {result.role:11s} exit={result.returncode}{gate}  {result.workspace}")
    if record.stopped_after:
        print(f"\nstopped after {record.stopped_after}: {record.stopped_because}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
