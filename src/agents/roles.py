"""The agent roles, as definitions the harness can run and code can check.

Each role is one markdown file with YAML-ish frontmatter (`name`, `description`,
`tools`) followed by the system prompt. That is the harness's own format, so a
definition here is executable rather than a description of one.

This module exists so the definitions can be checked, and so the deterministic
half of a role's work — see `detectors` — lives in code rather than in a prompt. Their containment
properties — that none of them can edit a file, that the ones producing a
proposal end by running it through the gate, that the reviewer cannot reach the
network — are the reason the roles are safe to run, and a property stated only in
prose is one nobody is holding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROLE_ROOT = Path(__file__).resolve().parent

#: Tools no role may hold: editing a tracked file is not a proposal's to do, and
#: removing the ergonomic path to it is the part of the containment rule that
#: does not rely on the agent choosing to comply.
FORBIDDEN_TOOLS = {"Edit", "Write", "NotebookEdit"}


@dataclass(frozen=True)
class Role:
    name: str
    description: str
    tools: tuple[str, ...]
    body: str
    path: Path


def _parse(path: Path) -> Role:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not match:
        raise ValueError(f"{path.name} has no frontmatter block")
    front, body = match.groups()
    fields: dict[str, str] = {}
    for line in front.splitlines():
        key, _, value = line.partition(":")
        if _:
            fields[key.strip()] = value.strip()
    missing = {"name", "description", "tools"} - fields.keys()
    if missing:
        raise ValueError(f"{path.name} is missing {sorted(missing)}")
    tools = tuple(t.strip() for t in fields["tools"].split(",") if t.strip())
    return Role(fields["name"], fields["description"], tools, body, path)


def load_roles() -> dict[str, Role]:
    return {
        role.name: role
        for role in (_parse(p) for p in sorted(ROLE_ROOT.glob("*.md")) if p.name != "README.md")
    }
