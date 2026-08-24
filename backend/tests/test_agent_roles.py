import re

import pytest

from src.agents import FORBIDDEN_TOOLS, NETWORK_TOOLS, ROLES
from src.agents.base import Role


def test_every_role_is_registered_under_its_own_name():
    assert set(ROLES) == {"explorer", "challenger", "updater", "reviewer", "cleaner"}
    for name, role in ROLES.items():
        assert role.name == name
        assert role.description.strip() and role.prompt.strip()


@pytest.mark.parametrize("name", sorted(ROLES))
def test_no_role_can_edit_a_file(name):
    """The half of the containment rule that does not rely on compliance.

    Telling an agent not to modify tracked files is an instruction; withholding
    the tools is a property. A shell can still write, which is why the gate
    compares against HEAD regardless — but the ergonomic path is gone.
    """
    assert not (set(ROLES[name].tools) & FORBIDDEN_TOOLS)


def test_a_role_that_edits_files_cannot_be_constructed():
    with pytest.raises(ValueError, match="may not edit a file"):
        Role(name="bad", description="d", tools=("Read", "Edit"), prompt="p")


def test_a_role_that_fetches_without_the_shared_client_cannot_be_constructed():
    # section 4's spacing, the stop on 429 and the run cap all live in
    # PolitePoller; a role building its own requests inherits none of them
    with pytest.raises(ValueError, match="PolitePoller"):
        Role(name="bad", description="d", tools=("WebFetch",), prompt="fetch away")


def test_a_role_proposing_a_catalog_change_must_run_the_gate_on_itself():
    with pytest.raises(ValueError, match="without running the gate"):
        Role(name="bad", description="d", tools=("Read",), prompt="p",
             proposes_catalog_change=True)


def _flat(text: str) -> str:
    """Prompts are wrapped prose; a check should not depend on where the wrap falls."""
    return " ".join(text.split())


@pytest.mark.parametrize("name", sorted(n for n in ROLES if set(ROLES[n].tools) & NETWORK_TOOLS))
def test_every_fetching_role_carries_the_politeness_block(name):
    prompt = _flat(ROLES[name].prompt)
    assert "PolitePoller" in prompt
    assert "Never bypass a login, a paywall or a bot check" in prompt


@pytest.mark.parametrize("name", sorted(ROLES))
def test_every_role_carries_the_containment_rule_and_closes_the_same_way(name):
    prompt = _flat(ROLES[name].prompt)
    assert "you may propose anything, and nothing enters on your word" in prompt
    assert "Do not modify any tracked file" in prompt
    assert "What you did not do, and why" in prompt


@pytest.mark.parametrize("name", sorted(ROLES))
def test_a_role_renders_to_frontmatter_the_harness_can_read(name):
    role = ROLES[name]
    rendered = role.to_markdown()
    match = re.match(r"^---\n(.*?)\n---\n", rendered, re.S)
    assert match, "no frontmatter"
    front = dict(
        (k.strip(), v.strip())
        for k, _, v in (line.partition(":") for line in match.group(1).splitlines())
    )
    assert front["name"] == role.name
    assert front["description"] == role.description
    assert front["tools"] == ", ".join(role.tools)
    # the file is an artifact, and says so, so nobody edits it and loses the edit
    assert "Generated from src/agents/" in rendered
