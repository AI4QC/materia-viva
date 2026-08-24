"""The self-evolving loop's agents: their definitions, and the code they lean on.

A role is a markdown definition the harness executes plus whatever part of its
work is deterministic. Keeping the second part here rather than in the prompt is
the same rule the loop applies everywhere: judgement to the agent, everything
checkable to code.
"""

from src.agents.roles import FORBIDDEN_TOOLS, ROLE_ROOT, Role, load_roles

__all__ = ["FORBIDDEN_TOOLS", "ROLE_ROOT", "Role", "load_roles"]
