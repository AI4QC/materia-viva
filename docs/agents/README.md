# Agent definitions

The self-evolving loop's agent roles, in the harness's own format so that a run can be reproduced
rather than reconstructed from someone's memory of a chat.

They live here rather than in `.claude/agents/` because `.gitignore` classifies `.claude/` as local
agent configuration and session state, and definitions that are not shared cannot be reproduced —
which was the whole reason for writing them down. Point the harness at them once, per checkout:

```bash
ln -s ../docs/agents .claude/agents
```

One file, one source of truth: the link is local and ignored, the definitions are versioned.

| Definition | Role | Section |
|---|---|---|
| `explorer.md` | find databases the catalog does not have | 1.4, output one |
| `challenger.md` | try to reject what discovery proposed | 1.3 |
| `updater.md` | work out what to pull when an upstream moved | 1.4, output two |
| `reviewer.md` | assemble and advise at a human gate | 1.6 |

`reviewer` is the one that has not run yet. It is defined anyway because its output is advice
rather than a catalog change, so the rule it has to satisfy is different: not "a gate can refuse it"
but "every claim in it is separable from every fact". Its anchor is that a cited precedent must
resolve to a real catalog entry, which it checks itself.

The other three were written from a run that actually happened, not from imagination, and each carries what that
run taught — the premise a pull plan had to correct, the sections of a refuter's report that produced
its only decisive finding, the claim-marking discipline without which a discovery proposal cannot be
trusted.

**Two roles are deliberately absent.** Drafting an adapter, and independently authoring its golden
sample, both wait on the golden sample framework, which does not exist. Section 1.8's rule is
verification before the producer: defining those two now would be defining producers whose output
nothing can check.

## Three things these definitions rely on

**The gate.** Every definition ends by running
`scripts/datasets/verify_catalog_change.py` against its own proposal. That is what makes the
containment rule mechanical rather than advisory: a proposal that touches anything beyond what it
adds is refused whether or not the agent meant well.

**Narrow tools.** None of them has `Edit` or `Write`. They read, search, run shell commands and
fetch. This makes "do not modify tracked files" partly structural rather than purely instructed —
partly, because a shell can still write, which is why the gate compares against `HEAD` regardless.

**One HTTP client.** They are told to import `PolitePoller` instead of making their own requests, so
they inherit one request per host per second, a full stop on 429 or 503, and a run-wide cap. This one
is still a requirement rather than a mechanism: nothing prevents an agent from using `curl`. It is
the largest remaining hole in the loop's outward behaviour and is recorded as such in section 4.
