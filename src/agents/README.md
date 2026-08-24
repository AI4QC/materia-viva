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
python -m src.agents render          # write .claude/agents/*.md for the harness
python -m src.agents list            # the pipelines and the roles each runs
python -m src.agents plan <name>     # what would run, and what each step is told
python -m src.agents run <name>      # run it, gating and recording each step
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

## The harness

Two backends. `SdkExecutor` runs the agent loop in this process through `claude_agent_sdk` and
reports what the run cost; `CliExecutor` shells out to `claude -p` and needs nothing installed. The
SDK is a 93 MB platform-specific wheel, so it is **optional**: the harness prefers it when it is
importable, and the repository's requirements do not carry it.

```bash
pip install claude-agent-sdk          # optional; without it the CLI backend is used
python -m src.agents run discovery-sweep
python -m src.agents run discovery-sweep --run-id 20260824T090000Z --resume
```

Around either backend it adds what `claude -p` does not:

- **a workspace outside the repository** per run, so a proposal cannot land in the working tree and a
  bad run is undone by deleting a folder;
- **the gate, run by the harness.** A role that proposes a catalog change is told to check itself;
  instructing is not checking, so the harness runs the gate on what came back and records the
  verdict beside it;
- **a record of the run** — role, task, backend, attempts, cost, turns, gate outcome — because
  otherwise a run's reasoning lives in a terminal that gets closed;
- **a timeout and bounded retries**, retrying only a failure the role never survived — a transport
  error or a timeout — and never a role that ran and reached a conclusion, since that just spends
  tokens on the same answer;
- **resume**: a step that finished under a run id is reused rather than paid for again. A sweep is on
  the order of 300k tokens, so redoing a step that succeeded because a later one broke is the
  expensive way to fail.

## Tokens and the provider

`Executor` is the provider seam. Everything above it — roles, gates, records, budgets — is ours;
everything below belongs to whoever runs the model. A second vendor is a third executor class and a
change nowhere else, provided it answers with an `Outcome` and maps what it reports into `Usage`.

`tokens.py` is why that works. `Usage` counts input, output and the two cache classes, because
dollars are a provider's opinion and tokens are what still compares after a model or a vendor
changes. Cache reads are in the total and out of `billable`: they are cheap, not free, and leaving
them out of the total is how a loop that looks affordable per turn stops being affordable per sweep.

```bash
python -m src.agents tokens --by role          # or --by day, --by backend
python -m src.agents run discovery-sweep --max-tokens 400000
```

A `Budget` is checked **before** a step, not after — a ceiling you discover you have crossed is a
report, not a ceiling — and the step that would have broken it is named as where the run stopped.

## The pipelines

`pipelines.py` is the fan-out shape, in code rather than decided per run — the same every time and
reviewable as a diff. Section 1.3 puts judgement in the agents and control flow in a script, and a
manager agent deciding the shape instead would add a way to get it wrong with no upside.

| Pipeline | Steps |
|---|---|
| `discovery-sweep` | explorer → challenger → reviewer |
| `upgrade` | updater → reviewer |
| `audit` | cleaner |

Two properties are worth naming. **A step sees artifacts, not reports**: it builds its task from a
mapping of role name to the file that role left behind, and there is no route from there to a
report. That is section 1.3's requirement that the challenger form its own view, made a property
rather than something the caller has to remember. And **a refused gate stops the run**, because
spending the next agent on an artifact already known to be unsound is worse than stopping.

## What is still missing

Two roles are absent on purpose: drafting an adapter, and independently authoring its golden sample.
Both wait on the golden sample framework, and section 1.8's rule is verification before the
producer.
