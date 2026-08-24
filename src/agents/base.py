"""What a role is, and the constraints every role is built under.

A role is a Python object, not a document. The markdown the harness reads is
rendered from it, which means the constraints can be enforced where the role is
constructed rather than checked afterwards by reading its prose: a role that
holds a tool able to edit a file, or that fetches without being told to use the
shared client, does not come into existence.

It also means the parts every role repeats — the containment rule, the politeness
rule, the discipline of separating fact from claim — are written once here rather
than copied into five prompts that then drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

#: No role may hold these. Withholding the tool is the half of the containment
#: rule that does not depend on the agent choosing to comply; a shell can still
#: write, which is why the gate compares against HEAD regardless.
FORBIDDEN_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
NETWORK_TOOLS = frozenset({"WebFetch", "WebSearch"})

CONTAINMENT = """\
The rule that governs everything you do (section 1.2): **you may propose anything, and nothing
enters on your word.** Every claim you make has to reduce to a check that does not depend on you —
a file exists, an id matches, a diff is empty. A claim that cannot be reduced that way queues for a
human gate; it does not pass because you were confident."""

NO_EDITS = """\
- **Do not modify any tracked file.** You have no `Edit` or `Write` tool; do not work around that
  with a shell. No git add, commit or branch."""

POLITENESS = """\
- **HTTP goes through the shared client**: `from scripts.datasets.probe_upstream import
  PolitePoller`. It spaces one request per host per second, stops contacting a host entirely once it
  answers 429 or 503, and caps the run. Build your own requests and you inherit none of that.
- **Never bypass a login, a paywall or a bot check**, and download no data files — metadata and
  public pages only. A zip's file list can be read from its central directory with a range request
  if you need one."""

FACT_AND_CLAIM = """\
Keep fact and claim apart, and label them. What a machine settled is a fact; what a proposal's notes
assert is that proposal's claim until something outside it agrees; what you concluded is your
judgement. A reader has to be able to discount the last two without discarding the first."""

GATE_SELF_CHECK = """\
## Self-check before reporting

```
PYTHONPATH=backend:. python scripts/datasets/verify_catalog_change.py \\
  --catalog <your file> --before scripts/datasets/sources.json
```

Paste its full output into your report. If it fails, fix the proposal or explain why you cannot."""

CLOSING = """\
- **What you did not do, and why.** Including anything you could have checked and chose not to."""


def reading(*sections: str) -> str:
    """The opening every role shares: what to read, and the rule it works under."""
    return (
        "Read `docs/self-evolving-loop.md` sections "
        + ", ".join(sections)
        + " before starting.\n\n"
        + CONTAINMENT
    )


@dataclass(frozen=True)
class Role:
    """One agent role: what the harness runs, and what it is allowed to run with."""

    name: str
    description: str
    tools: tuple[str, ...]
    prompt: str
    #: True when the role's output is a change to the catalog, which the gate reads
    proposes_catalog_change: bool = False

    def __post_init__(self) -> None:
        held = set(self.tools)
        if held & FORBIDDEN_TOOLS:
            raise ValueError(
                f"{self.name} holds {sorted(held & FORBIDDEN_TOOLS)}; a role may not edit a file"
            )
        if held & NETWORK_TOOLS and "PolitePoller" not in self.prompt:
            raise ValueError(
                f"{self.name} can fetch but is not told to use PolitePoller, so it would inherit "
                "neither the spacing nor the stop on 429"
            )
        if self.proposes_catalog_change and "verify_catalog_change.py" not in self.prompt:
            raise ValueError(
                f"{self.name} proposes a catalog change without running the gate on itself"
            )
        if not self.description.strip() or not self.prompt.strip():
            raise ValueError(f"{self.name} needs a description and a prompt")

    def to_markdown(self) -> str:
        """The harness's own format, rendered from this object."""
        return (
            "---\n"
            f"name: {self.name}\n"
            f"description: {self.description}\n"
            f"tools: {', '.join(self.tools)}\n"
            "---\n\n"
            "<!-- Generated from src/agents/. Edit the Python, then re-render:\n"
            "     python -m src.agents render -->\n\n"
            f"{self.prompt.strip()}\n"
        )
