"""The self-evolving loop's agents.

A role is a Python object (`base.Role`) carrying its description, its tools and
its prompt, built under constraints that are checked where it is constructed. The
markdown the harness reads is rendered from it — `python -m src.agents render` —
so the Python is the definition and the file is an artifact.

`harness` runs one; `detectors` is the deterministic half of the cleaner's work.
"""

from __future__ import annotations

from src.agents import challenger, cleaner, explorer, reviewer, updater
from src.agents.base import FORBIDDEN_TOOLS, NETWORK_TOOLS, Role

ROLES: dict[str, Role] = {
    role.name: role
    for role in (explorer.ROLE, challenger.ROLE, updater.ROLE, reviewer.ROLE, cleaner.ROLE)
}

__all__ = ["ROLES", "Role", "FORBIDDEN_TOOLS", "NETWORK_TOOLS"]
