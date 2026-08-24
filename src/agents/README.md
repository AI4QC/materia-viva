# The agents

Five roles, each a Python object rather than a document. The markdown the harness reads is rendered
from them, so the definition and what runs cannot drift.

| Module | Role | Section |
|---|---|---|
| `explorer.py` | find databases the catalog does not have | 1.4, output one |
| `challenger.py` | try to reject what the explorer proposed | 1.3 |
| `updater.py` | work out what to pull when an upstream moved | 1.4, output two |
| `reviewer.py` | assemble and advise at a human gate | 1.6 |
| `cleaner.py` | find redundancy and error in what we already hold | 1.6, 6.3 |

```bash
python -m src.agents render     # writes .claude/agents/*.md for the harness
```

## Why Python and not markdown

**Constraints are enforced where a role is constructed.** `base.Role` refuses to build a role that
holds a tool able to edit a file, that can fetch without being told to use the shared HTTP client,
or that proposes a catalog change without running the gate on itself. A definition that violates the
containment rule does not come into existence, rather than being caught later by something reading
its prose.

**The parts every role repeats are written once.** The containment rule, the politeness rule, the
discipline of separating fact from claim, and the closing question — five copies of those in five
markdown files is five things that drift apart.

**The object is what the CLI consumes.** `claude --agents` takes exactly the JSON a `Role`
serialises to, so nothing is transcribed by hand between the definition, the tests and the
invocation.

## What the harness adds

`harness.py` wraps a run with the three things `claude -p` does not do:

- **a workspace outside the repository** per run, so a proposal cannot land in the working tree and a
  bad run is undone by deleting a folder;
- **the gate, run by the harness.** A role that proposes a catalog change is told to check itself;
  instructing is not checking, so the harness runs the gate on what came back and records the
  verdict beside it;
- **a record of the run** — role, task, time, command, gate outcome — because otherwise a run's
  reasoning lives in a terminal that gets closed, and the next run cannot know what the last one
  already declined.

## What is still missing

Two roles are absent on purpose: drafting an adapter, and independently authoring its golden sample.
Both wait on the golden sample framework, and section 1.8's rule is verification before the producer.

There is no orchestration yet — nothing that decides to run the explorer, then the challenger on its
output, then the reviewer on what survived. The fan-out shape belongs in a script, and that script
does not exist.
