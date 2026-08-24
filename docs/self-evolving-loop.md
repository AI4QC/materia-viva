# A self-evolving materials integration database: the loop design

**English** · [简体中文](self-evolving-loop.zh-CN.md)

Updated: 2026-08-24

This file describes how MateriaViva is meant to move from "found by hand, reviewed by hand,
ingested by resumable acquisition scripts" to an auditable self-evolving loop. It is a design
document, not a description of the present.

> [!IMPORTANT]
> **This is a design, not a description of the present.** Two things actually exist in the
> repository:
>
> | Landed | What it is |
> |---|---|
> | [`scripts/datasets/probe_upstream.py`](../scripts/datasets/probe_upstream.py) | read-only upstream change detection, covering 38 of the 106 sources |
> | [`scripts/datasets/verify_catalog_change.py`](../scripts/datasets/verify_catalog_change.py) | the gate an agent's output passes through (candidate or pull plan) |
>
> Everything else is planned, including upgrade-plan derivation, the golden sample framework, the
> admission overlap measurement, snapshot metadata and the change report, and the catalog's `state` /
> `reason` fields. **Automatic discovery and automatic integration are not implemented**, and all 106
> sources were found and reviewed by a person.
>
> Some numbers and conclusions below come from experiments that were run — a full probe sweep, a
> catalog backfill, a unit audit, two real agent runs. Those **findings** are real and are kept here,
> but **their implementations were reverted**; this document does not claim something is implemented
> when it is not. See "Findings verified but not landed" at the end.
>
> Values marked **(undecided)** are proposals made by this document, not settled decisions.

## 0. What this document adds

The loop in the README is a seven-step flowchart. What was missing was never the sequence but the
judgements between the steps: on what grounds a change counts as having happened, where a failure
goes, what makes a generated adapter acceptable, and what a snapshot promises. Those four are
sections 2 to 6.

The stance throughout: **every new field, state and gate has to point at a real problem in a real
source.** Nothing derivable is stored, and no failure is modelled before it has occurred.

## 1. The loop

The README's straight line, redrawn with its failure exits. `✋` marks a human gate.

```text
[0] discover a candidate source (a database not in the catalog)
        │ output: a candidate entry plus evidence links, entering state=registered
        │ no script can do this — it cannot find a database that is not catalogued
        ↓
[1] probe upstream → compare against the token last seen (catalogued sources only)
        │ different → continue; same → update checked_at and stop
        ↓
[2] ✋ licence, access mode, static-structure scope, trajectory contamination
        │ authorisation unclear → rejected(licence-unclear) (unpublished by default, section 6.4)
        ↓
[2.5] produce a pull plan (a diff to downloads[]) or draft an acquisition script
        │ HEAD each URL for existence and content-length; check the capacity reserve
        │ a source already past the gate → hand it straight to acquire.py
        │ a brand-new candidate → stop at the plan and wait for [2]
        ↓
[2.9] acquire.py performs the download (reserve guard / resumable / receipt)
        │ fingerprint the structures only, intersect with the pool → "N new of M candidates"
        ↓
[2.95] ✋ admission: the expert decides on the measurement
        │ overlap too high / parse failures too high → rejected (section 1.10)
        ↓
[3] generate or recommend an acquisition and field-mapping adapter (draft)
        │ gates not met → stays acquired, and the draft stays out of adapters/
        ↓
[4] ✋ review the adapter and register it
        ↓
[5] unify format, units, provenance → fingerprint deduplication → merge cross-database properties
        ↓
[6] integrity and outlier checks
        │ not passed → quarantined(integrity-failed)
        ↓
[7] ✋ publication approval → new snapshot and change report
```

The difference that matters is that there are four human gates ([2] [2.95] [4] [7]) rather than the
single one at the end of the README's diagram. The licence decision and the adapter review both sit
before data enters the index — approving afterwards cannot undo a mapping that has already polluted
it.

### 1.1 Who runs which step

Three kinds of actor, and confusing them is the easiest mistake this design invites.

| Step | Actor | Why |
|---|---|---|
| [0] discover a candidate | **agent** | needs to read papers and pages and judge "is this a crystal structure database"; a script cannot see outside the catalog |
| [1] probe upstream versions | script | a deterministic comparison, **landed** (`probe_upstream.py`, 38/106) |
| [2] licence decision | **human** | a legal judgement, and irreversible when wrong (published data cannot be recalled) |
| [2.5] produce a pull plan | **agent** | reads upstream docs to decide which files to pull and where they land; this is the largest historical bottleneck — about 22 of the 24 acquisition scripts were written for one source each |
| [3] draft an acquisition and mapping adapter | **agent** | read upstream docs and samples, write mapping code; squarely what it is good at |
| [2.95] admission | **human** | decides on the deduplication measurement, section 1.10 |
| [4] adapter review and registration | **human** | looks only at the three things no automatic check can settle, section 5 |
| [5] [6] unify, deduplicate, verify | script | a deterministic pipeline |
| [7] publication approval | **human** | a promise made to the outside |

### 1.2 The containment rule: an agent may propose anything, and nothing enters on its word

This is not a statement of principle. It is the rule this repository already runs on, with three
existing precedents:

- **`integrated` is not a claim.** It is defined as "a module exists under
  `scripts/properties/adapters/`", and a test pins the two sets equal. An agent saying a source is
  integrated does not make it so; the file existing does.
- **A figshare article id is not accepted on a search result.** All nine mappings in step 4 were
  proved by the article's own metadata listing the file id the catalog already held. A search gives
  candidates; only the file id matching admits one. The four that could not be proved that way are
  still blank.
- **An adapter is not passed by someone reading the code.** The hardest of the four gates in
  section 5 is a zero-diff golden sample — whoever wrote the draft, a field that does not match is
  a failure.

From which the agent's boundary follows, and **these lines matter far more than how the agent is
built**:

- an agent may produce candidates in state `registered` and adapter drafts in a draft directory;
- an agent **may not** write the index, alter a published snapshot, advance any source's `state`
  (scripts advance it on verifiable facts, or a human does at a gate), or make a licence decision;
- every claim an agent makes must reduce to **a check that does not depend on the agent**: a file
  exists, an id matches, a diff is empty. A claim that cannot be reduced that way queues for a
  human gate; it does not pass automatically.

Steps 1 to 4 of this document were done in exactly that pattern — agent drafting, human gates,
machine-verifiable facts — including this section.

**This section deliberately does not design the agent.** Model choice, prompting, degree of
autonomy and scheduling have nothing behind them yet, and writing them down would be guessing.
What has to exist first is the boundary above, because it fixes the ceiling on the damage a wrong
agent can do.

### 1.3 How the agents are organised: split where objectives conflict, not by step

Self-evolution is meant to be built out of agents, possibly several, but **the criterion is not
"more agents". It is: split into two only where the objectives conflict. Where they do not, a
second agent is only a second chance to hallucinate.**

That criterion has one observed measurement behind it. Step 2 and the audit of step 1 were done by
two parallel subagents. One spent roughly 85k tokens, overturned this document's own section 3.2
(concluding that the catalog should gain no field at all) and found three factual errors in it. The
other spent roughly 69k tokens and found two real bugs — a failed probe erasing the baseline, and
`--catalog` crashing after the probe loop — along with one wrong judgement. What made the pair work
is specific: **the second agent's task was to attack the first one's premises.** And the wrong
judgement is the standing reminder that **the benefit arrives together with a verification cost**;
unchecked, several agents only produce more confident wrong answers faster.

#### The three pairs that genuinely conflict

| Split | Why it has to be split |
|---|---|
| drafting an adapter ↔ authoring its golden sample | when one agent writes both the mapping and the expected output, **a zero diff means nothing** — it will have written the expectation to match its own bug. A reads the upstream documentation and writes the adapter; B reads the same documentation and writes the expectation, without seeing A's code. This is section 1.2 one level up: the checker separated from the checked |
| finding sources ↔ refuting candidates | the finder's objective is to find something, which biases it toward output. The refuter asks: is this really a crystal structure database, is the licence really open, is it already covered by a source we have. `open-materials-db` (redundant, its primary source COD is already integrated) is exactly that shape — searching again does not surface it; someone has to be trying to reject it |
| mapping semantics ↔ units and dimensions | the "right unit, wrong meaning" case section 5 leaves to human review can be split off to a role that only checks dimensions. Weaker than the first two, and can wait |

#### Where MAS is deliberately not used

- **Steps [1] [5] [6]** (probing, unifying, deduplicating) are deterministic scripts and already
  run. Putting an agent in charge of them only adds a new way to fail — the agent running the wrong
  script — with no upside.
- **No manager agent orchestrating the pipeline.** The fan-out shape belongs in a **script**: which
  step fans out, into how many, how the results are merged. That is reviewable code and it is the
  same every run. **Judgement to the agents, control flow to code.**
- **The licence decision does not split.** Two agents do not make a legal call safer; it needs a
  human (step [2]).

#### How it runs

- **The harness is Claude Code subagents**, not a framework of our own. The repository already
  carries `.claude/CLAUDE.md` and `.mcp.json`, so an agent inherits this project's conventions for
  free, and the web search discovery needs comes with the harness. Building an API loop instead
  means rebuilding tool use, retries and sandboxing for a research dataset maintained by two people.
- **The unit of output is a branch, a commit and a report**, not a database write. The reason is
  observed: every human gate in steps 1 to 4 was, in substance, a person reading a diff. It also
  turns section 1.2's damage ceiling into something concrete — an unmerged branch, undone with
  `git revert`.
- **Triggered manually for now**, on the machine holding the data. Building a schedule before an
  agent has run once is the wrong order, and the probe baseline is machine-local anyway
  (section 3.2), so CI cannot run that half.

#### How a discovery agent's output is machine-verified

Section 1.2 requires every claim to reduce to a check that does not depend on the agent. For a
candidate database, what is checkable is:

| Check | Machine-checkable |
|---|---|
| `official_url` resolves and returns 200 | ✅ |
| not a duplicate of a catalogued entry (host plus name) | ✅ |
| a licence statement exists at a resolvable URL | ⚠️ conditional — the catalog has **no such field**, and `license` is free text (`Materials Project terms`). The verifier checks an optional `licence_url` a candidate may volunteer and reports "not supplied" otherwise. What it anchors is that the licence claim has a page a reviewer can open; judging the content is still step [2] |
| `validate_catalog` passes | ✅ |
| whether `plan_probe` can probe it | ✅ free, and it answers directly whether the source can enter the loop |
| the record count it claims, whether it really is a crystal structure database | ❌ a claim only, and it must be marked as a claim and queued for a human |

Implemented:
[`scripts/datasets/verify_catalog_change.py`](../scripts/datasets/verify_catalog_change.py). Both
agent roles that touch the catalog produce the same kind of artifact — a branch whose diff either
adds a source (a candidate) or changes `downloads[]` (a pull plan) — so it is one gate reading one
diff. The candidate side adds three checks: whether `official_url` resolves, whether it duplicates an
existing `official_url`, and whether it duplicates a name.

**The host check needs qualifying, or what it rejects is legitimate candidates.** 46 of the catalog's
106 sources sit on 13 shared hosts, `figshare.com` alone carrying 8 — and figshare, zenodo and github
are exactly where new materials datasets tend to live. So the rule comes from the catalog itself: **a
host is evidence of duplication only when exactly one existing source uses it**, meaning it is that
source's own domain; two or more sharing it makes it a platform, which carries no signal.

**There is no memory of rejections at all, and that is the discovery agent's most immediate defect.**
The intended mechanism was that the catalog's `rejected` entries are the memory, so an agent
deduplicating against the whole of `sources.json` would not re-propose a source already declined.
That has two holes:

1. `state` / `reason` have not landed, so **no** catalog entry carries `rejected` and the mechanism's
   precondition is absent today;
2. even once it lands it is not enough — **a candidate rejected at the gate never enters the
   catalog**, so it leaves no trace. This has already happened: one discovery run produced five
   candidates, four were declined, and the next run will propose them again unchanged.

For a memory to exist, the rejected candidate itself has to be recorded, which needs somewhere other
than the catalog — or candidates have to land as `registered` before being rejected. That decision
has not been made.

### 1.4 The three MAS outputs, and who actually pulls the data

What the MAS is actually for: **search for new sources and upgrades → produce a pull plan → hand it
to an expert.** Three outputs of increasing risk, with different gates.

#### Output one: a candidate source

A catalog entry in state `registered` plus evidence links. Machine checks are the table at the end
of section 1.2.

#### Output two: a pull plan (the most valuable of the three)

Note that this one is mainly for **new** sources. A version upgrade of a source already acquired
does not go through the MAS by default; it routes on file-name overlap, section 1.9.

**The format needs no inventing — it is already in the catalog**: `downloads: [{filename, url,
bytes}]` plus `data_path`. So a pull plan is a diff to that array, and it can be verified without
trusting a word the agent said:

| Check | By what |
|---|---|
| URL is https, filename is a safe relative path, bytes is a non-negative integer | `validate_catalog` already does it |
| each URL really exists, and content-length matches the `bytes` claimed | one HEAD each |
| the download will not eat the SSD safety reserve | `acquire.py`'s `ensure_capacity` (50 GiB) already does it |
| `data_path` does not collide with an existing source | compared within the catalog |
| no free-text field still names an upstream id the plan replaced | ids taken from the removed URLs, searched for in the prose |

Which is to say output two needs almost no new code — what it needs is an agent filling that array,
followed by the existing validation and a round of HEADs. Implemented:
[`scripts/datasets/verify_catalog_change.py`](../scripts/datasets/verify_catalog_change.py). It
compares the working tree's catalog against HEAD and verifies only what this diff adds or alters,
because the agent's output is a diff (section 1.3).

The last of those checks came out of running the agent for real the first time: the agent itself
noted in its report that once the plan is accepted, the old record id left in `status` and `notes`
becomes a lie that no machine check would catch. It is machine-checkable, so it is now checked by
machine.

#### Output three: an acquisition script

About 22 sources have no static file list — paginated APIs, GraphQL, login required, one endpoint
per record — so a pull plan cannot express them and a script has to be drafted. Highest risk, and
gated at the same level as an adapter (section 5): a short slice of a real response as a golden
sample, with **another** agent writing the expectation independently.

### 1.5 Who actually pulls: `acquire.py`, not the agent

`scripts/datasets/acquire.py` already provides three things an agent running curl directly would
throw away: the 50 GiB SSD safety reserve (`ensure_capacity`), resumable transfers
(`run_curl_resumable`) and download receipts (`write_receipt`). So the agent does not fetch data. It
produces a plan and `acquire.py` executes it.

**When a pull may go ahead without waiting** depends on whether the licence gate has been passed,
and `state` answers that:

- a source already past the gate (`state` is `acquired` or `integrated`) whose upstream published a
  new version → **it may be pulled straight away**, because the licence decision has not changed and
  what is being pulled is a new version of the same source;
- a brand-new candidate (`state=registered`) → **it stops at the plan** and waits for step [2]. Once
  data is downloaded and in the index, a wrong licence call cannot be taken back.

### 1.6 What the expert is handed

Not a transcript. **A diff and a fixed checklist.** The checklist was not invented; every line of it
corresponds to a real entry in the catalog, and all five are things an expert catches and an agent
does not:

| To check | Real precedent |
|---|---|
| whether what is pulled is static structure endpoints or trajectory frames | `elementa` (one endpoint per relaxation: 2.2M taken from 43.5M frames), `mptrj` / `omat24` (excluded outright as `scope-trajectory`) |
| whether the join keys are complete enough for the data to attach | `catalysis-hub` (the crawl omitted `reactionSystems`, leaving 91% of reactions unattachable; downloaded and still rejected) |
| which fields to exclude | `spse` (`excluded_structure_fields`: migration-path arrays) |
| the licence and redistribution boundary | `icsd` / `elementa` / `gnome` / `aflow` (restricted, kept out of the public snapshot) |
| whether it is redundant with a source we have | `open-materials-db` (its primary source is COD, already integrated) |

### 1.7 What the MAS searches: the 66 the probe cannot reach

The probe already covers 40 sources deterministically, one HTTP request each. **Do not send an agent
to redo those 40** — slower, dearer, less reliable. What the MAS searches is:

- **the 66 sources the probe cannot reach** (browse-only interfaces, per-record downloads,
  registration required, federated queries, and the 5 unresolved figshare entries) — deciding
  whether they published a new version is itself a task of reading pages and papers;
- **databases not in the catalog at all** — which a script cannot do in principle.

### 1.8 How to leave room for the MAS: build the verifier, not the scaffold

Finishing the rest of the loop and leaving room for the MAS, then planning the automation
afterwards, follows directly from the rule above. But "leaving room" has one specific method and one
specific trap.

**The method: build each agent role's verifier first and leave the producer empty.** The reason is
an asymmetry — a producer's shape is what we know least about (which split, what prompting, how many
rounds), while a verifier's shape follows from what must be true, and that is already settled:

| Data contract | Its verifier | Useful to a person today |
|---|---|---|
| `downloads[]` plus `data_path` | `validate_catalog` + a HEAD per URL + `ensure_capacity` | yes: a hand-written pull plan goes through the same gate (**landed**) |
| a candidate source entry | `official_url` resolves + host and name deduplication + `validate_catalog` + probeability | yes: adding a source by hand should pass the same ones (**landed**) |
| an adapter plus its golden sample | a zero-diff regression | **yes, and overdue**: the adapters had no test coverage at all |

Once the verifier exists, plugging an agent in is only swapping the producer; the contract and the
gate do not change by a line. That is what the room actually consists of.

**The trap: do not build an `agents/` directory, prompt templates, model configuration or an
orchestration framework.** Those are all guesses about the producer, and the producer is the one
part with no evidence behind it. Guesses written down become constraints in a later reader's mind.
An empty directory and a stub are not room; they are a decision made early and wrong.

### 1.9 Upgrades: let file-name overlap decide whether judgement is needed

**A catalogued, already-acquired source publishing a new version does not go through the MAS by
default.** But the criterion is not "have we pulled it before". It is a harder fact, and one API
call computes it: **do the new version's file names still match the ones the catalog records.** That
number is computed first, and only then is judgement invoked.

The three lagging zenodo sources land on the three possible answers:

| Source | Recorded names surviving in the new version | Route |
|---|---|---|
| `carolina` | 1 of 1 | **mechanical**: substitute the record id and HEAD each URL. No agent |
| `arc-mof` | 23 of 24; `ARCMOF_20220610.tar.gz` gone, 25 files upstream | **mechanical plus a delta**: the expert answers only "what about the one that vanished and the ones that arrived". No agent |
| `core-mof` | **0 of 2** — neither v1.1.3 csv exists in v2.0.1, which ships 9 different files | **upstream restructured**: someone has to decide which of the nine correspond to what we ingested. This is where a MAS or an expert is worth spending |

**Not implemented.** What it needs is settled: fetch the latest version's file list per probe kind,
compute the overlap, produce a plan that can be pasted straight into `downloads[]`, and HEAD each URL
for existence and content-length. It must not write the catalog — the output is a proposal awaiting
review.

So upgrades route on overlap:

- **all names present** → the plan is a substitution. The source is already past the licence gate
  (section 1.5), so it can go straight to `acquire.py`; the expert gets a one-line notice.
- **some present** → derive the mechanical part and list what vanished and what arrived. The
  expert's question narrows to that delta instead of the whole source.
- **none present** → upstream changed its structure. Only now is judgement needed, and only now is
  a MAS worth spending.

One implementation trap worth recording: **the comparison has to be scoped to the host being
probed.** `carolina` takes one archive from zenodo and two parquet files from a Hugging Face
dataset; comparing all three against zenodo's list reports the Hugging Face pair as vanished and
turns a `mechanical` upgrade into a `delta`, sending an expert after a problem that does not exist.
Files belonging to other hosts are counted in the report but kept out of the comparison.

**The one risk genuinely new to upgrades is the licence changing.** A dataset switching licence
between versions does happen, and both invenio and figshare return a licence field, so this can be
compared by machine — but only after normalising: all three sources return `cc-by-4.0` upstream
against a catalogued `CC BY 4.0`, and a plain string comparison cries wolf. A difference that
survives normalising goes back to the human licence decision in step [2]; passing that gate once
does not grant a pass forever.

**The 66 unprobeable sources are a separate matter**: deciding whether they published a new version
means reading pages and papers, and that step needs an agent (section 1.7). But once the answer is
yes, the shape of their acquisition is still known — **the MAS is used on "did it change", not on
"how do we pull it".**

### 1.10 Admission: measure the overlap, then ask the expert

New datasets keep appearing, so the loop needs a standing lane: discover, pull, deduplicate,
approve. Three decisions about that lane.

#### The two periodic activities are different things

| Activity | Period | Actor | Coverage |
|---|---|---|---|
| whether a catalogued source has a new version | per source, weeks to a month | script, deterministic | 38 (landed) |
| searching for datasets not in the catalog | one sweep weekly or monthly | **agent** | the whole internet |
| deciding whether the 66 unprobeable sources moved | with the sweep above | **agent** | 66 (section 1.7) |

Conflating them costs twice: sending an agent to redo those 40 deterministic probes is slow and
dear, and sending a script to search for new datasets cannot work at all.

#### Redundancy stops being an opinion and becomes a measurement

`open-materials-db` was declined by reading its documentation and judging that COD, which we already
integrate, covers it — an opinion. With a deduplication lane it becomes a number: after pulling,
fingerprint the structures only, intersect with the pool's fingerprint set, and report **"N new
unique structures of M candidates"**.

That is precisely the kind of check section 1.2 asks for — **a number an agent cannot invent**. So
admission rests on the measurement, not on the narrative.

**Not implemented.** Its shape is settled: read the fingerprint output
`scripts/properties/hashing.py` already produces (`native_id / n_sites / formula / bawl_hash`,
failures written as `FAIL:<reason>`), so it **does not re-implement the fingerprint protocol**; the
pool side is `hash_map` in `data/props_work/match_map.sqlite`, opened read-only. Its output is the
four measurements below, for example:

```text
340 rows read, 15 parse failures (0.0441)
  FAIL:TOO_LARGE × 12
  FAIL:DISORDERED × 3
320 unique fingerprints, 300 already in the pool, 20 new (0.0625)
  overlaps cod on 300 materials
  overlaps icsd on 100 materials
```

`id_map` carries an index on `(source, native_id)` and none on `material_id`, so the per-source
breakdown costs one scan of it — that is the price of naming which existing sources hold the
overlap, and it is a single pass.

#### The consequence that saves the most work: admission needs structures, not properties

Measuring the overlap means parsing structures out of what was pulled — but **structures only**. The
property adapter of section 5, with its golden sample, is the expensive part and it **does not have
to exist** before the admission decision. The pieces are already there: CIF to BAWL fingerprint in
`scripts/properties/hashing.py`, extxyz to BAWL in `scripts/datasets/elementa_hash.py`, and loading
the pool's reference fingerprint set is established practice in
`scripts/datasets/elementa_merge.py`.

So the order is:

```
✋ licence → pull → fingerprint structures only → measure overlap → ✋ admission → then write the adapter
```

**Which means a full adapter is never written for a dataset that ends up rejected.** That is where
this lane saves the most.

#### What the expert sees at the admission gate

The checklist of section 1.6, plus four measurements:

| Measurement | Why it can decide admission |
|---|---|
| N new unique structures of M candidates | direct evidence of redundancy |
| which existing sources it overlaps, and by how much | separates "a duplicate in bulk" from "it fills in one chemical space" |
| the parse failure fraction | a high rate is itself a rejection signal (malformed format, missing fields) |
| the share of trajectory or intermediate frames | the `elementa` line of section 1.6, the static-endpoint rule |

#### A reason code to add once the measurement exists, and not before

`open-materials-db` is currently recorded as `scope-unbounded`, but its real reason is redundancy.
Once this measurement exists, `redundant-with-pool` will have a checkable definition (overlap above
a threshold) and can join the vocabulary in section 2.2. Added now it would be a label nobody can
verify — which is the rule "a new code only when a new failure mode actually occurs" broken.

## 2. Source states and failure exits

### 2.1 States

```
registered → acquired → integrated
```

Any step can leave for one of two states carrying a reason code:

- `rejected(reason)` — judged not to be ingested; a human may reconsider, nothing retries
  automatically;
- `quarantined(reason)` — failed this round, re-entered next round.

There is no `acquiring` (the acquisition scripts are resumable, so an in-flight state need not be
persisted), no `licence-cleared` (the licence decision's result is a boolean on the licence field,
not a source state) and no `superseded` (whether upstream is ahead is answered by comparing `seen`).

There is also **no `adapter-pending`**: backfilling all 106 entries showed that nothing lands in
`acquired` without also landing in `adapter-pending` — files in hand with no adapter yet is the
whole meaning of `acquired`. Whether an adapter is missing is answered by whether a module exists
under `scripts/properties/adapters/`, which needs no second state. By the same logic `integrated` is
not a claim: it is *defined* as "an adapter module exists", and a test pins it
(`test_integrated_state_matches_the_sources_that_have_an_adapter`).

**Publication visibility is not stored in the catalog.** It is derived from the licence decision: a
restricted source's `source_id` goes on a publication deny-list and the public snapshot filters on
`source_id`. Storing a `visibility` field would give the licence a second source of truth, and the
two would drift.

ICSD is the canonical shape of "integrated and unpublishable": `state` is `integrated`, `access` is
`licensed`, and it does not appear in the public snapshot. That is not a failure state.

### 2.2 Reason codes

Every code corresponds to a situation already present in `sources.json`:

Instances are written as catalog ids and pinned by a test
(`test_every_documented_reason_code_example_really_carries_it`) — the whole point of this table is
that every code points at a real entry, and two of its rows had drifted.

| Reason code | Meaning | Existing instances (catalog ids) |
|---|---|---|
| `licence-unclear` | redistribution authorisation cannot be confirmed | none: the licence gate's default-deny exit, produced at runtime |
| `licence-restricted` | explicitly restricted, and the licence is a harder bound than the interface | `topological-materials` |
| `account-required` | needs manual registration or login, cannot be automated | 21 entries, among them `csd` `mpds` `matcloud` `matcraft` `pearsons-crystal-data` `nist-crystal-data` |
| `no-bulk-interface` | no official bulk interface, and crawling is prohibited | `magndata` `qpod` `hetdb` `x2db` `mpod` `matterverse` `nlr-matdb` |
| `scope-trajectory` | a trajectory or intermediate-frame dataset, outside the static-structure scope | `mptrj` `omat24` `materials-cloud-li-ion-trajectories` |
| `scope-unbounded` | has a bulk interface, but we deliberately do not mirror it whole | `nomad` `perovskite-database` `open-materials-db` |
| `join-key-missing` | the crawl lacks the join key, so the data cannot attach | `catalysis-hub` |
| `integrity-failed` | a checksum, count or outlier check did not pass | none: written by the integrity check when quarantining, produced at runtime |

Note that `icsd` is **not** in this table: it is `state=integrated` and unpublishable, the
"integrated and unpublishable" shape of section 2.1 rather than a rejection. Citing it as an example
of `licence-restricted` is a mistake this table used to make.

A new code is added only when a new failure mode actually occurs; the vocabulary is not laid out in
advance. After the backfill, `licence-unclear` and `integrity-failed` still have zero instances,
because they are **runtime outcomes rather than catalog categories**: the first is the licence gate's
default-deny exit, the second is written by the integrity check when quarantining. Zero instances in
the catalog is the expected state.

`scope-unbounded` is the code the data forced out during the backfill. `nomad`'s status is
`too-large-for-full-mirror` — it *has* a bulk interface, and not mirroring it whole is our choice,
so recording it as `no-bulk-interface` would be false. Two more belong to the same class:
`perovskite-database` (reached through a NOMAD query, catalogued only) and `open-materials-db`
(redundant, its primary source COD already integrated). They are exactly the class described in
section 4 of [`docs/dataset-acquisition.md`](dataset-acquisition.md), "probed but not mirrored
without bounds".

Two others were settled in the same pass: `optimade` is recorded as `acquired` (the registry was
fetched and verified; only the federated provider data goes unmirrored), and
`topological-materials` as `rejected(licence-restricted)` — it is both browse-only and
non-redistributable, and the licence is the harder bound.

### 2.3 The relationship to the `status` text

The state is, today, written into the free-text `status` field of `sources.json`, for example:

```
downloaded-158304-reactions-2026-08-18-excluded-from-ingestion-crawl-omitted-reactionSystems-join-key-so-91-percent-unattachable
```

That string encodes state, date, counts and the failure reason at once. It is useful to a person and
should stay. **`status` is the human-readable narrative and the new fields are the machine-readable
state**; both exist, and neither replaces the other (the hard reason they cannot is section 3.4).

### 2.4 Catalysis-Hub, walked through

```
registered → acquired(158304 reactions, 2026-08-18) → rejected(join-key-missing)
```

The crawl omitted the `reactionSystems` join key, so 91% of the reactions cannot attach to a
structure. The failure happened before [4], and the index was never polluted — which is the reason
the adapter gate sits before ingestion. The path to reconsidering is re-crawling with the join key,
not fixing the adapter.

## 3. The catalog fields change detection needs

### 3.1 Where it started

The 106 entries of `scripts/datasets/sources.json` (`schema_version: 1`) carried only
`id / name / access / official_url / license / data_path / status / downloads`, with a few also
carrying `notes / estimated_documents / paper_url / revision`. Exactly one entry had `revision` —
ELEMENTA, whose value is the Hugging Face commit SHA
`9de9010715da4f563326f99bf3f7ee829cf4486a`.

So "upstream version" existed in the catalog as a single special case, with everything else
compressed into the `status` text and no comparable baseline, leaving nothing to decide "there is a
new version" against. Meanwhile section 7 of [`docs/dataset-acquisition.md`](dataset-acquisition.md)
already promised to "retain `source`, `source_version`, `source_id`, `license`, `retrieved_at`" —
the intent was written down long ago; it had just never landed in the catalog schema.

### 3.2 The catalog does not store upstream state (the conclusion after step 1)

This section originally designed an `upstream` block (`probe` / `probe_kind` / `seen` /
`checked_at`) to be written into `sources.json`. After step 1's probe had run over everything, that
design was refuted by its own output. The criterion: **is this value human knowledge, or a result
recomputable on every run?**

- `seen` is entirely derived. All 29 non-null tokens in `data/probe/seen.json` are machine-read
  validators: HTTP ETags, `Last-Modified`, git SHAs, Hugging Face repo shas, Invenio record ids. Not
  one needed a person.
- `probe` and `probe_kind` are derived too. `plan_probe()` is a pure function of `downloads[].url`
  and assigns a kind and an endpoint to all 106 entries with no human input. The earlier claim that
  "`probe_kind` decides how to probe and cannot be derived" was simply wrong.
- **The catalog already holds its version pointer**: it is inside the download URL. The four
  "upstream is ahead" findings — `arc-mof`, `carolina`, `core-mof`, `topomat` — come from comparing
  the record id in that URL against upstream's latest. Storing `upstream.seen` as well is the same
  pointer twice, which is exactly why section 2.1 refuses `visibility`, and those four URLs are
  already drifting.
- Change detection needs no catalog field. `diff_against()` compares against the previous side file,
  and step 1's acceptance criterion was always "run twice, the second run reports unchanged". Writing
  the state into the catalog would turn a read-only probe into a catalog mutator writing a
  106-entry diff into version control every round.
- ELEMENTA's top-level `revision` demonstrates redundancy rather than precedent: the probe derived
  the identical sha independently. It also has no reader (nothing in `scripts/` or `backend/` greps
  for it), and it is left untouched.

**So: probe state lives permanently in the side file `<data root>/probe/seen.json`, outside version
control; the catalog gains no `upstream` block; and the probe offers no `--sync` to write results
back into the catalog — that would be the same design under another name.**

The cost of that choice has to be stated: the side file lives under `data/`, which is not in version
control, so **the baseline is machine-local**. A fresh clone, CI or a second machine has no baseline;
every source reports `first-seen` on the first run, and the probe has to have run twice on that
machine before "did it change" can be answered. Lose the SSD and the baseline goes with it. Two
people cannot share probe results either.

The mitigating half: **the most valuable signal needs no baseline.**
`catalog_points_at_older_record` compares the record id in the download URL against upstream's
latest, which is why `arc-mof`, `carolina`, `core-mof` and `topomat` surfaced on a first-ever run
where everything was `first-seen`. Losing the baseline weakens only the `changed` verdict for
`http-head`, `hf-revision` and `git-commit`; it does not make the probe blind. If sharing a baseline
across machines ever becomes necessary, putting `seen.json` under version control can be discussed
then — that is a separate decision, not this one.

The catalog should hold only **human knowledge that cannot be derived from the URL**, and there are
two such items:

- `state` / `reason` (sections 2.1 and 2.2) — step 3, where 21 entries needed human judgement;
- figshare article ids (section 3.3) — step 4, recorded by hand.

The `schema_version` bump does not belong to step 2 but travels with whichever commit actually adds
a field. The catalog is still at **1** and `state` / `reason` have not landed; when they do, the new
fields must be optional so version 1 files keep loading (an entry without `state` reads as
`registered`).

Fields not added, with the reasons, all since borne out by the data:

- `check_interval_days` — one global default interval to begin with (**undecided**), and `manual`
  means do not probe. A per-source period waits until some source is observed to need one;
- `probe_failures` and a backoff counter — the right handling of a failed probe is "nothing was
  learned this time", and the next round retries naturally;
- `visibility` — derived, section 2.1;
- `etag` / `last_modified` / `content_hash` / `upstream_version` as four parallel fields — four
  encodings of one question; one opaque token instead.

### 3.3 The ceiling on automatic probing

Only **45 of the 106 sources carry a `downloads[].url`**. The other 61 (browse-only interfaces,
per-record downloads, registration required, federated queries) have no fixed endpoint to probe and
their `probe_kind` is permanently `manual`. **Automatic change detection covers at most 42% of the
catalog**, with the rest falling to a human review when due. That ceiling is a property of the
sources themselves rather than a shortfall in the implementation, and neither this document nor any
outward description should imply that all 106 are automatic.

> The table below is about **upstream inputs** — where those 106 integrated databases host their own
> bulk files. It has nothing to do with the Hugging Face repository MateriaViva publishes its own
> snapshots to (`AI4QC/MateriaViva`, the output). The `huggingface.co` row means other people's HF
> datasets (`kairosmaterial/ELEMENTA`, `phonix-db/phonix-summary`,
> `colabfit/Carolina_Materials`), not ours.

The 45 probeable sources by download host, and whether the upstream identity can be taken from the
URL already recorded:

| Host | Sources | Upstream identity in the existing URL |
|---|---:|---|
| `ndownloader.figshare.com` | 14 | ⚠️ the file id does not move with the version; 9 article ids resolved, 5 unresolved |
| `zenodo.org` | 8 | ✅ `api/records/<record_id>/...` |
| `archive.materialscloud.org` | 5 | ✅ `api/records/<record_id>/...` |
| `huggingface.co` | 3 | ✅ `datasets/<repo>/resolve/main/...` |
| github (raw / media / codeload / archive) | 5 | ✅ `<org>/<repo>/<branch>/...` |
| other single-source hosts | 10 | case by case; most can only be `http-head` |

`http-head` probes only the first download URL, following the politeness rule of one request per
probe. `cmr-static` has 27 download URLs, `rruff` 16 and `mofx-db` 6, so for them this is **partial
cover** — such probes report `head-covers-1-of-N-files` in their note, so partial cover cannot be
read as full cover.

Two direct conclusions:

- **38 sources are probeable** (invenio-latest 13, http-head 12, figshare-article 7, git-commit 4,
  hf-revision 2), every upstream identity coming out of the existing URL. Landed:
  [`scripts/datasets/probe_upstream.py`](../scripts/datasets/probe_upstream.py), writing
  `<data root>/probe/seen.json`;
- **7 of the 14 figshare sources already carry the article id in `official_url`** and by the rule of
  section 3.2 stay out of the catalog, extracted by `plan_probe`. Two more (`jarvis-dft`,
  `hex-high-pressure`) were shown to be resolvable, but that was catalog data and went back with the
  rest of the data changes, so they count as unresolved again — the mechanism is in the code and the
  `figshare_article` field currently has no user.

### 3.4 The hard constraint: the change has to be purely additive

`backend/tests/test_dataset_acquisition.py` asserts against **substrings** of `status`, for example
`"user-action-required" in sources["matcloud"]["status"]`,
`sources["mptrj"]["status"] == "excluded-by-scope-trajectory-dataset"` and
`"912-full-and-1267-partial" in sources["opxrd"]["status"]`.

Therefore:

- the existing text semantics of `status` **cannot be rewritten**; new state can only sit alongside;
- every new field must be optional, absent reading as `state: "registered"`, so that 106 entries need
  not be backfilled at once;
- `schema_version` goes to 2, and the loader accepts both 1 and 2.

Existing consumers to check when the fields change:

- [`scripts/datasets/acquire.py:278`](../scripts/datasets/acquire.py:278) — the `--catalog` default;
- [`scripts/properties/registry.py:20`](../scripts/properties/registry.py:20) — the `SOURCES_JSON`
  constant, and the "source is not registered in scripts/datasets/sources.json" error;
- [`scripts/properties/base.py:115`](../scripts/properties/base.py:115) — an adapter's source id
  doubles as its provenance tag.

## 4. Politeness while probing

This is the only part of the loop with an outward side effect, so the rules are strict:

- one request per probe (a `HEAD` or a minimal metadata query), and **never re-download an archive to
  determine a version**;
- prefer conditional requests, `If-None-Match` / `If-Modified-Since`; a `304` settles it as unchanged;
- one concurrent request per host, at least a second apart; a `429` or `5xx` is given up on for this
  round, not retried;
- a User-Agent naming the project and a contact; `robots.txt` and each source's terms respected;
- **no bypassing accounts, paid licences or redistribution limits.** A source whose version
  information requires a login is `probe_kind: "manual"`, with `seen` updated by a person at review
  time.

Frequency: one global interval to begin with (**undecided**, on the order of weeks to a month),
probing when due. Sources with `probe_kind: "manual"` are not probed; when they come due, a person
is reminded to review them.
**One technique that moves a great deal of knowledge to before the pull: a zip's central directory
can be fetched on its own.** A zip keeps every path name in a central directory at the end of the
file, and a Range request can take just that. Measured on `opxrd`'s 1.4 GB archive: read the last
64 KB for the EOCD to get the central directory's offset and size (10.27 MB, **0.73%** of the
archive), then read those 10 MB to get all 92,565 entry names and the 7 contributor directories.
**That is not "download and look" — it is an input to the admission decision.** It answers what an
archive holds, how it is organised, and which existing source it shares provenance with; questions
that otherwise wait for the pull or rest on believing the documentation.

## 5. The gates an adapter has to pass

An adapter draft is written by an **agent** (section 1.1), which is why "generate or recommend an
acquisition and field-mapping adapter" has to become a set of decidable gates — the correctness of
generated code cannot be established by reading it, only by comparing its output. A draft lands in a
draft directory and enters
[`scripts/properties/adapters/`](../scripts/properties/adapters/) (55 adapters today) only after
passing the gates and a human review.

1. **A zero-diff golden sample, whose expectation was authored independently.** Each source has a
   fixed small fixture (roughly 50-200 raw records) and the expected output; every field has to
   match. The sample is committed with the adapter as a regression baseline. Wrong units, wrong
   magnitudes and misplaced fields are all caught here.
   **But only if the expectation did not come from whoever wrote the adapter** — one author will
   write the expectation to match their own bug, and then a zero diff proves only self-consistency.
   So the draft and the expectation come from two agents reading the same upstream documentation, the
   second without seeing the first's code (section 1.3).

   **Not implemented.** The design is: samples live in
   `backend/tests/golden/<source_key>/`, where `raw/` is the miniature raw input and `expected.json`
   the expected records, and `pytest` compares every sample in that directory field by field. Each
   sample must declare `authored_by`:

   | `authored_by` | What it proves | Used for |
   |---|---|---|
   | `recorded-from-adapter` | the behaviour has **not changed** | a regression baseline for the existing adapters |
   | `independent` | the mapping **is right** | the gate for a new adapter (the framework cannot verify the claim; it carries it for the reviewer) |

   Conflating those two is how a zero diff comes to mean nothing, so the field is mandatory and a
   test pins its permitted values.

   The first sample was `obelix` (8 hand-written CSV rows, one per branch, yielding 5 records). It
   was accepted by **breaking it on purpose**: changing the unit `S/cm` to `S/m` reported 4 property
   diffs and 4 unit violations; relaxing a `> 0` guard to `>= 0` reported the record count going 5 to
   6; breaking the ICSD provenance regex reported one line,
   `[2] match_ids: expected [['icsd','icsd-111757']], got []`. All three were caught.
2. **100% field coverage.** Every field in an upstream record is either mapped to a canonical name or
   **explicitly declared ignored** with a reason. An undeclared field is a failure — otherwise
   silently dropping a field is caught by no test.
3. **Provenance is mandatory.** `source_id`, `native_id` and `method` are non-empty. `method` keeps
   the original functional or measurement conditions verbatim (`PBE` / `r2SCAN` / `experiment` /
   `GCMC 298K 16bar`) and is never merged away.
4. **Use the existing registration path.** Registered through
   [`registry.py`](../scripts/properties/registry.py) (failing to register raises
   `source ... is not registered in scripts/datasets/sources.json`), canonical names taken from
   `CANONICAL_PROPERTIES`, scalar backfill following the existing `SCALAR_BACKFILL_PRIORITY`, with no
   parallel mechanism.

Human review looks only at the three things no automatic check can settle: whether the mapping
semantics are right (a field with the correct unit and the wrong meaning also diffs to zero),
whether the fields declared ignorable really are, and whether the source has the enumerated-library
property that needs a composite key (section 6.3).

**Gate 2, field coverage, is not implemented.** It requires knowing which fields of an upstream
record the adapter **consumed**, and adapters do not report that, so it needs instrumentation. Until
it exists, silently dropping a field is still caught only by human review — the one remaining gap in
this section, and the gates should not be read as complete.

## 6. What a snapshot promises

### 6.1 Versions and immutability

- A snapshot's version **is the Hugging Face revision**; no second version namespace is invented, and
  a human-readable tag can be added when one is wanted.
- **A published snapshot is immutable**: a correction is published as a new revision rather than
  overwritten in place. A version a user cites can always be fetched again.

### 6.2 Material id stability across snapshots

The one promise that cannot be taken back once made:

- The promise: **the same structure fingerprint keeps the same material id across snapshots.**
  Adding a source, adding a property or dropping a source causes no renumbering, and a dropped id is
  neither recycled nor reused.
- The only case where renumbering is allowed is a change to the fingerprint algorithm version. Then
  an `old_id → new_id` map must ship with the snapshot, and the change report must mark it as a
  renumbering event.

### 6.3 Determinism of deduplication

Deduplication uses the BAWL fingerprint (`material_hasher.hasher.bawl`): parse, cap at 500 sites,
reduce to the primitive cell, cap at 300 sites, hash. Properties attach by an authoritative
identifier first (`mp-` / `oqmd-` / `agm-` / `icsd-` / `cod-` …) and then by fingerprint;
**matching on formula alone is never used**.

A change to the algorithm changes which structures merge, so snapshot metadata must record the
`material_hasher` version, both site caps, and **two distinct exception lists** — both part of the
algorithm's definition, and losing either means a rebuild on another machine merges differently:

| List | Contents | Where it lives |
|---|---|---|
| composite-key admission | `deem-zeolites`, `hmof` | [`deem_zeolite_admit.py`](../scripts/properties/deem_zeolite_admit.py), [`hmof_composite_admit.py`](../scripts/properties/hmof_composite_admit.py) |
| fingerprint unreliable | `deem-zeolites`, `pcod` | `FINGERPRINT_UNRELIABLE` in [`load.py`](../scripts/properties/load.py) |

They are not the same thing and are easy to confuse. **Composite-key admission** is about which key
establishes uniqueness at admission: an enumerated library decorates one topology with substituents,
so sibling frameworks share a bonding graph and collide, and they are admitted on
`(fingerprint, volume per site)` rather than the fingerprint alone. **Fingerprint unreliable** is
about the loader refusing to resolve properties through those sources' `hash` refs — measured on the
Deem set, the hash path collapses 126,578 distinct frameworks onto 281 pool materials, one of which
absorbs 27,007 of them. The two lists intersect only on `deem-zeolites`.

The meaning of `match_via` ∈ `id:<db>` / `hash` / `origin` is in
[`docs/property-integration.md`](property-integration.md) and is not repeated here. A fingerprint
change affects only the `match_via = hash` attachments; `id:<db>` is unaffected — so the change
report counts the two separately.

### 6.4 The licence gate

- **Deny by default**: data whose authorisation cannot be confirmed does not enter the public
  snapshot, with state `rejected(licence-unclear)`;
- for a restricted source only the name, official link, public metadata, source id and licence status
  are published, never the protected structures, property fields or raw files;
- a unified format does not change who owns the rights to the original data, and any automatic
  discovery flow passes the same gate;
- a stricter licence must not be redistributed "contagiously" through a more permissive dataset
  (SPSE, 3DSC-ICSD and other ICSD-derived mirrors run in properties-only mode and contribute no
  structures);
- the current Hugging Face repository is the **private working index**, holding ICSD and the
  CC BY-NC / academic-terms sources ELEMENTA, GNoME and AFLOW. A public snapshot has to filter them
  out by `source_id` first — every property row records its `source_id`, so the filter is one `WHERE`
  clause, but it has not been applied.

Per-source licence decisions and the manual steps they require are in
[`docs/dataset-acquisition.md`](dataset-acquisition.md) and are not repeated here.

### 6.5 Snapshot metadata and the change report

**Not implemented.** The design is a `describe` producing snapshot metadata from an index, and a
`--diff` turning two of those into the change report.

Every snapshot carries: the index schema version, the fingerprint algorithm of section 6.3 (version,
both site caps, both exception lists), each source's licence, and each source's
`(source_id, seen, checked_at)`. That last item is what lets any snapshot be traced back to the exact
upstream version it came from — which is what "auditable" actually means.

The change report: sources added and dropped with their reason codes, per-source deltas in materials
and property rows, changes in the totals, licence changes (**compared after normalising**, or
`CC BY 4.0` against `cc-by-4.0` cries wolf), `state` / `reason` changes, and any change to the
fingerprint algorithm or the index schema — a fingerprint change being flagged separately as the
renumbering event of section 6.2.

**Counts, not names.** Which materials appeared or vanished, and which merge relationships changed,
both need the previous snapshot's identifier and match tables rather than its summary. The report
says how much moved and leaves "which ones" to whoever asks with those tables in hand. That is a
deliberate boundary, not an omission.

## 7. Implementation order

The principle: **let a read-only probe produce real data first and let the data decide what the
fields look like; build the verification before the thing that produces work for it.** Reversed, it
is either building the abstraction before looking at the need, or treating an agent's mistakes as
data.

### Landed

**The read-only probe** ([`probe_upstream.py`](../scripts/datasets/probe_upstream.py)). It extracts
the upstream identity from the existing `downloads[].url`, covers 38 of 106, and writes
`<data root>/probe/seen.json`. It **does not touch `sources.json` and downloads nothing**. For Zenodo
and Materials Cloud, `api/records/<id>/versions/latest` settles in one request whether the record we
recorded has been superseded.
→ Verified: `pytest backend/tests/test_upstream_probe.py`; run twice, the second run reports
everything unchanged.

**The gate an agent's output passes through**
([`verify_catalog_change.py`](../scripts/datasets/verify_catalog_change.py)). Both agent roles that
touch the catalog produce the same artifact — a branch whose diff either adds a source (a candidate)
or changes `downloads[]` (a pull plan) — so it is one gate reading one diff.
→ Verified: `pytest backend/tests/test_verify_catalog_change.py`.

### Not landed, ordered by whether the verification exists

| To build | Its verification | Prerequisite |
|---|---|---|
| upgrade-plan derivation (section 1.9) | the gate is already there | none; can be done now |
| the catalog's `state` / `reason` (sections 2.1, 2.2) | one pairing check added to `validate_catalog` | none; about 21 entries need human judgement |
| the admission overlap measurement (section 1.10) | reuses the existing fingerprint protocol and match map | needs the machine holding the data |
| the golden sample framework (section 5) | a zero-diff regression | none, and the 55 adapters have no test coverage, which makes this the most overdue for a person |
| snapshot metadata and the change report (section 6.5) | two runs over one index must diff to nothing | needs a real index |
| drafting adapters or acquisition scripts | the golden sample framework — **absent** | must wait for the row above |

### The agent roles

Same rule: **verification first, then the agent that produces work for it.**

| Agent role | Its verification | Can it be built |
|---|---|---|
| pull plan ([2.5], output two) | the gate is there | yes |
| discover candidates ([0]) | the gate is there (`official_url` resolves, host and name deduplication, `validate_catalog`, probeability) | yes |
| draft adapters or acquisition scripts ([3], output three) | the golden sample framework — absent | no |

## Appendix: findings verified but not landed

Each of these was verified while running experiments. The changes that acted on them were reverted
as data-side work rather than agent system, but **the problems are still there**; they are recorded
so the knowledge does not go with the code.

**`mc2d`'s interlayer binding energies are wrong by a factor of 1000.**
`scripts/properties/adapters/mc2d.py` passes the upstream
`binding_energy_per_substructure_per_unit_area_*` through labelled `eV/Å²`, while
`registry.CANONICAL_PROPERTIES` declares `interlayer_binding_energy` as `meV/Å²`, with no ×1000
conversion between them. The upstream data settles which way it goes: across the 2,865 values in
`structure_2d.json` the median is 0.0251, so 25 meV/Å², the expected magnitude for interlayer
binding; read as meV/Å² they would sit a hundredfold below van der Waals. **And the error is hidden
by the very mechanism that should surface it**: `property_defs` is seeded from the registry and
`material_properties` has no unit column, so the unit an adapter passes is discarded and the rows are
published as `meV/Å²` carrying eV/Å² numbers. The fix mirrors what `2dmatpedia` already does for
exfoliation energy (`* 1000.0`).

**Six magnetisation normalisations live in the unit instead of the method string.** The registry
deliberately keeps `total_magnetization`'s unit neutral (`μB`) and says in its own comment that
per-cell versus per-formula-unit belongs in the method string. `alexandria` and `materials_project`
comply; `2dmatpedia`, `novomag` and `elementa` put it only in the unit, which is discarded — leaving
per-cell values indistinguishable from per-f.u. ones under one property. The audit is static: extract
every literal unit from `PropertyValue` calls and compare against the registry; 7 of 207 canonical
calls disagreed.

**The instance column of the reason-code table in section 2.2 had drifted twice.** It cited ICSD, CSD
and MPDS as instances of `licence-restricted` (CSD and MPDS carry `account-required`, and ICSD is not
a rejection at all — it is the "integrated and unpublishable" shape of section 2.1), and NOMAD and
OPTIMADE for `no-bulk-interface` (NOMAD belongs to `scope-unbounded`). The instances in the table now
come from that reverted backfill, so **they currently cannot be checked** — whoever builds `state` /
`reason` should add a test that re-derives that table from `sources.json`.

**opxrd has seven contributors, and NREL / HTEM is not among them.** LBNL 70,017, INT 19,797, CNRS
1,053, EMPA 771, HKUST 523, USC 339, IKFT 65, across 92,565 zip entries. Obtained by the central
directory technique at the end of section 4.
