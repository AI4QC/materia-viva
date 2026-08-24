# Proposal: the agent framework

**English** · [简体中文](agent-framework.zh-CN.md)

Updated: 2026-08-24

This proposes the framework that runs MateriaViva's agents. The loop those agents serve is designed
in [`self-evolving-loop.md`](self-evolving-loop.md); this is only about the machinery — what the
layers are, what each decides, what it costs, and what has not been shown to work.

It is written to be accepted or rejected. Every claim of evidence points at a run that happened.

## What it is

Five roles, each a Python object. A harness that runs one and checks what came back. A script that
says which roles run in what order. Two things they lean on: a gate that reads a proposed catalog
change, and one HTTP client that all outward traffic goes through.

```
src/agents/
  base.py        what a role is; a role breaking a constraint fails to construct
  explorer.py challenger.py updater.py reviewer.py cleaner.py
  harness.py     run one role: workspace, gate, record
  pipelines.py   which roles, in what order
  detectors.py   the deterministic half of the cleaner's work
  tokens.py      what a run cost, counted so it survives a change of provider
  __main__.py    render | list | plan | run | tokens
```

## The six decisions, and what each costs

**1. A role is code, not a document.** `base.Role` refuses at construction to build a role holding a
tool that can edit a file, able to fetch without being told to use the shared client, or proposing a
catalog change without running the gate on itself. The markdown the harness reads is rendered from
the object, so the definition and what runs cannot drift.

*Cost*: the prompts are now inside Python string literals, which is a worse place to write prose
than a markdown file. *What would overturn it*: if the constraints turn out to be better expressed
as a linter over markdown, the objects buy nothing.

**2. Split roles only where objectives conflict.** Discovery and refutation are split because a
finder is biased toward output; assembling a packet is not split, because an assembler has no
opposing objective.

*Evidence*: the pair found something a second search could not. CAMD passed every machine check —
different host, different name — and was refused because the challenger read `odbx.py` and found the
dataset already ingested there. *Cost*: two runs instead of one, and one of the two agents in an
earlier pair produced a wrong judgement that had to be caught by hand.

**3. Nothing enters on an agent's word.** Every claim reduces to a check that does not depend on the
agent, and the gate reads the diff rather than the reasoning.

*Evidence*: the gate refuses a diff touching anything beyond what it adds — before that check
existed, a diff moving a source from `rejected` to `integrated` passed with zero problems reported.
*Cost*: an agent cannot do anything a check cannot verify, which is why two roles are absent.

**4. The harness runs the gate, not the agent.** A role is told to check itself; the harness checks
anyway, gives each run a workspace outside the repository, records role, task, backend, cost and
verdict, retries only a failure the role never survived, and resumes a run rather than repeating
steps that already succeeded. Two backends — `claude_agent_sdk` in process when importable, the
`claude` CLI otherwise — because the SDK is a 93 MB platform-specific wheel and does not belong in
the repository's requirements.

*Evidence*: the three runs below wrote their proposals outside the tree and the repository stayed
clean — though they were driven by hand, before this harness existed, so they are evidence for the
workspace rule and not for the harness that now enforces it.

*Cost*: a layer between the operator and the gate is a layer the gate can fail behind. It did: the
harness invoked the gate without `PYTHONPATH`, so it exited on `ImportError`, and because the gate
also exits 1 for a refusal, a gate that never ran was indistinguishable from one that said no. Fixed
by giving refusal its own exit code and recording which of five things happened, but the class of
failure is inherent to the decision.

**5. Control flow is a script, judgement is an agent.** No manager agent. `pipelines.py` fixes the
shape, and a step sees only the artifact the previous role left, never its report.

*Evidence*: section 1.3 requires the challenger to form its own view; before this, that rested on
whoever launched it remembering to withhold the report. *Cost*: a fixed shape cannot adapt to a run
that needs a different one.

**6. The provider is a seam, not an assumption.** `Executor` is the only place that knows who runs
the model. Roles, gates, records and budgets are counted in tokens, which still compare after a
vendor changes; a provider's dollars and its per-model report are mapped at the seam into `Usage`.

*Cost*: the neutral shape loses whatever a provider reports that does not fit it. *What would
overturn it*: if a second provider is never added, the indirection bought nothing.

## What has actually run

| Run | Cost | What it produced |
|---|---|---|
| updater on core-mof's restructure | 63k tokens, 20 tool uses | a plan that passed the gate, and a correction to the premise it was given — two files it was told were new had been present in the previous version with identical md5 |
| explorer | 122k tokens, 64 tool uses | 5 candidates, 12 checked-and-excluded, every claim marked unverified |
| challenger | 114k tokens, 41 tool uses | 3 rejected on evidence, 2 queued; found CAMD already inside `odbx` |

Roughly 300k tokens for one discovery sweep and one upgrade. That is the number to plan against, and
it is the strongest argument for the deterministic parts staying deterministic: the probe answers
"did 38 sources change" in 38 HTTP requests.

## What is not built, and why

**Two roles.** Drafting an adapter, and independently authoring its golden sample. Both wait on the
golden sample framework: verification before the producer, so a producer whose output nothing can
check is not defined.

**A memory of rejections.** A candidate refused at the gate never enters the catalog and leaves no
trace, so the next sweep will propose the same four again. This is the framework's most immediate
hole.

**A schedule.** Everything is triggered by hand. Nothing should change that until a sweep has run
unattended once and been read.

## What running it for real would need

- **A home for reports.** The harness records each run in its workspace; nothing collects them.
- **Someone to read the traces.** `python -m src.agents tokens` groups what has been spent by role,
  by backend or by day, and `--max-tokens` stops a run before the step that would exceed it. What is
  missing is a decision about what the ceiling should be: ~300k tokens for a sweep plus an upgrade is
  affordable monthly and not weekly, and nobody has said which.

## What would falsify this framework

If a sweep produces candidates the challenger cannot meaningfully attack, the pair is theatre and
should collapse to one role. If the gate never refuses anything across several sweeps, it is
checking the wrong things. If reviewer packets go unread, the role is cost without benefit. None of
these has had enough runs to tell.
