# The agents

Five roles, each a Python object rather than a document. The markdown the harness reads is rendered
from them, so the definition and what runs cannot drift.

**Why it is built this way** — the eight decisions, what each costs, and what would overturn them —
is [`docs/agent-framework.md`](../../docs/agent-framework.md). The loop these roles serve is
designed in [`docs/self-evolving-loop.md`](../../docs/self-evolving-loop.md). This file is the
reference: what the modules are, and how to run them.

| Module | Role | Section |
|---|---|---|
| `explorer.py` | find databases the catalog does not have | 1.4, output one |
| `challenger.py` | try to reject what the explorer proposed | 1.3 |
| `updater.py` | work out what to pull when an upstream moved | 1.4, output two |
| `reviewer.py` | assemble and advise at a human gate | 1.6 |
| `cleaner.py` | find redundancy and error in what we already hold | 1.6, 6.3 |

Supporting modules: `base.py` (what a role is; a role breaking a constraint fails to construct),
`harness.py` (run one role: workspace, gate, record), `pipelines.py` (which roles, in what order),
`detectors.py` (the deterministic half of the cleaner's work), `tokens.py` (what a run cost),
`memory.py` (what a sweep already turned down), `schedule.py` (how often each job runs).

## Commands

```bash
python -m src.agents render          # write .claude/agents/*.md for the harness
python -m src.agents list            # the pipelines and the roles each runs
python -m src.agents plan <name>     # what would run, and what each step is told
python -m src.agents run <name>      # run it, gating and recording each step
python -m src.agents tokens          # what has been spent, by role, backend or day
python -m src.agents due             # which scheduled jobs have come round (--run, --cron)
python -m src.agents rejected        # what a sweep already turned down
```

## Running a pipeline

```bash
pip install claude-agent-sdk          # optional; without it the CLI backend is used
python -m src.agents run discovery-sweep
python -m src.agents run upgrade --about mc2d          # what the run is about, given to every step
python -m src.agents run discovery-sweep --run-id 20260824T090000Z --resume
python -m src.agents run discovery-sweep --backend cli # override which backend runs it
python -m src.agents run discovery-sweep --max-tokens 400000
```

| Pipeline | Steps |
|---|---|
| `discovery-sweep` | explorer → challenger → reviewer |
| `upgrade` | updater → reviewer |
| `audit` | cleaner |

Anything short of a passed gate stops the run — `refused`, `no-proposal`, or `did-not-run`. A step
is given the artifact the previous role left, never its report.

## Memory and cadence

```bash
python -m src.agents remember camd https://camd.example --why "already ingested inside odbx"
python -m src.agents rejected
```

Refusals live in `scripts/datasets/rejected.json`, and `pipelines.py` reads them into the explorer's
task. **No agent writes it**: a person runs `remember` after reading the outcome, and a refusal
without a reason is refused.

| Job | Cadence |
|---|---|
| `probe` | weekly — cheap, deterministic, 38 requests through the polite poller |
| `audit` | monthly — one agent over what we already hold |
| `discovery-sweep` | **manual** — nothing puts a ~300k-token job on a timer before one has run unattended and been read |
| `upgrade` | **manual** — it has to be told which source moved |

A job that fails is not marked as done, so it stays due instead of being skipped until next week.

```bash
python -m src.agents due          # what has come round
python -m src.agents due --cron   # the crontab line, printed rather than installed
```
