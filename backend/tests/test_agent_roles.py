import pytest

from src.agents import FORBIDDEN_TOOLS, ROLE_ROOT, load_roles

ROLES = load_roles()
NETWORK_TOOLS = {"WebFetch", "WebSearch"}
#: roles whose output is a change to the catalog, and so must pass the gate
PROPOSING = {"explorer", "updater"}


def test_every_definition_parses_and_is_named_after_its_file():
    assert set(ROLES) == {"explorer", "challenger", "updater", "reviewer", "cleaner"}
    for name, role in ROLES.items():
        assert role.path.stem == name
        assert role.description.strip()
        assert role.tools


@pytest.mark.parametrize("name", sorted(ROLES))
def test_no_role_can_edit_a_file(name):
    """The part of the containment rule that does not rely on compliance.

    Section 1.2 forbids an agent from modifying tracked files. Telling it so is
    an instruction; withholding the tools is a property. A shell can still write,
    which is why the gate compares against HEAD regardless — but the ergonomic
    path is gone, and that is worth holding.
    """
    assert not (set(ROLES[name].tools) & FORBIDDEN_TOOLS)


def test_the_reviewer_cannot_reach_the_network():
    # deliberate: attacking a candidate's claims is the challenger's job, and
    # repeating it here would double the requests made of other people's servers
    for name in ("reviewer", "cleaner"):
        assert not (set(ROLES[name].tools) & NETWORK_TOOLS), name
    # while the three that do research upstream keep it
    for name in ("explorer", "challenger", "updater"):
        assert set(ROLES[name].tools) & NETWORK_TOOLS, name


@pytest.mark.parametrize("name", sorted(n for n in ROLES if set(ROLES[n].tools) & NETWORK_TOOLS))
def test_a_role_that_fetches_is_told_to_use_the_polite_client(name):
    # section 4's spacing, the full stop on 429 and the run-wide cap all live in
    # PolitePoller; a role rolling its own requests inherits none of them
    assert "PolitePoller" in ROLES[name].body


@pytest.mark.parametrize("name", sorted(PROPOSING))
def test_a_role_proposing_a_catalog_change_runs_the_gate_on_itself(name):
    assert "verify_catalog_change.py" in ROLES[name].body


@pytest.mark.parametrize("name", sorted(ROLES))
def test_every_role_is_told_not_to_touch_tracked_files(name):
    body = ROLES[name].body.lower()
    assert "tracked file" in body or "change nothing" in body, name


def test_the_readme_lists_every_role():
    readme = (ROLE_ROOT / "README.md").read_text(encoding="utf-8")
    for name in ROLES:
        assert f"{name}.md" in readme, name
