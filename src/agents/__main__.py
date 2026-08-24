"""`python -m src.agents render` — write the harness's copy of the definitions.

The harness discovers agents by reading markdown from a directory. That markdown
is generated here rather than maintained, so there is one definition and it is the
Python: edit a role, re-render, and what the harness runs cannot drift from what
the tests check.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.agents import ROLES

DEFAULT_OUT = Path(__file__).resolve().parents[2] / ".claude" / "agents"


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
    parser.add_argument("command", choices=["render"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    for path in render(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
