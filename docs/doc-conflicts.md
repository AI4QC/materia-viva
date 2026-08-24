# Documentation conflicts: a review list

**English** · [简体中文](doc-conflicts.zh-CN.md)

Updated: 2026-08-24

One quantity should have one value. This file lists **where that is still not true**, what has
already been settled (so it is not redone), and the one decision that needs the machine holding the
data.

Whoever wrote this list could not verify the structure pool's real size: **none** of the 106
catalogued `data_path` directories exist in this checkout, and `data/` is not in Git. So everything
below that would require observing the truth is **reported, never guessed**.

---

## 1. Open: the size of the structure pool

### What is not the problem

**The application is right.** `/api/stats`
([`backend/materials_api/app.py:59`](../backend/materials_api/app.py)) reads
`experimental_count` / `candidate_count` from the SQLite `metadata` table, and those keys are
written when the index is built. They are live. The figure on the landing page therefore follows the
index and needs no maintenance.

**What is wrong are the constants scattered through the scripts** — hand-kept copies of the same
fact, stopped in the 8.2M era (99,162 experimental + 8,125,976 candidate = 8,225,138).

### The conflicts

| Site | What it says | Severity | Consequence |
|---|---|---|---|
| [`scripts/validate_data.py:20`](../scripts/validate_data.py) | `EXPECTED_COUNTS = {"experimental": 99_162, "candidate": 8_125_976}` | **blocking** | `make validate-data` is a `SystemExit` gate, it fails outright on a mismatch, and the Makefile does not pass `--no-count-check` |
| [`scripts/browser_smoke.py:37`](../scripts/browser_smoke.py) | asserts the literal `8,225,138` is visible on the page | **false failure** | the page is live, so the smoke test fails against any index whose counts are not 8,225,138 |
| [`scripts/record_demo.py:165`](../scripts/record_demo.py) | narration: "unified and deduplicated into 8,225,138 searchable structures" | **outward-facing** | the recorded demo states a stale number |
| [`scripts/analysis/plot_dataset_stats.py`](../scripts/analysis/plot_dataset_stats.py) | `6.12M` in 12 places: 1 docstring (which also says `99k`) and 11 plot titles and legends | **outward-facing** | generated figures carry stale numbers in their titles |
| [`backend/materials_api/indexer.py:1`](../backend/materials_api/indexer.py) | docstring: "the experimental and 6.12M structure datasets" | comment only | no behaviour depends on it |
| [`scripts/datasets/elementa_hash.py:8`](../scripts/datasets/elementa_hash.py), [`elementa_merge.py:6`](../scripts/datasets/elementa_merge.py) | docstrings mentioning "the existing 6.12M pool" | comment only | the argument they make is about primitive reduction and does not rest on the number |

### What zhilong has to decide

1. **The authoritative counts for the released snapshot** — how many `experimental` and how many
   `candidate`. What the documents currently rely on is the measurement of 2026-08-19
   (357,127 / 13,186,150 / 13,543,277 total, reported in
   [`property-integration.md`](property-integration.md)). Is that the number `validate_data.py`
   should be guarding? Or does validation guard the **released snapshot** while that table counts
   the **online index**, making them two different quantities? **That distinction decides whether
   the fix is to the constants or to the wording.**

2. **Whether this gate should hold a literal at all.** The suggestion is that it should not:
   [`validate_data.py:51`](../scripts/validate_data.py) writes the real count into
   `data/manifests/<role>.json` on every run. The fact already has an authoritative copy, and the
   constant is a second, hand-transcribed one. Comparing against the previous manifest instead would
   make the gate guard "did the data change unexpectedly since the last validated state" — which is
   what a count gate is for — and updating it would become a reviewable manifest diff rather than an
   edit to a constant.

   This is a proposal, not something that has been done.

---

## 2. Settled: the documents (do not redo)

Before 2026-08-24 (commit `02eeaef`) one quantity had four values across the documents:

- README's table and `property-integration`: 357,127 / 13,186,150 / 13,543,277
- `storage-layout`, describing those same two directories: 99,162 / 8,125,976
- README's own build command: 13,077,781, agreeing with neither
- `migration-report`: 99,162 / 6,120,140, with no clause saying these were history

The rule applied was one README already stated, directly below its own table:

> Counts are not written into prose, because every hardcoded figure in this project has gone stale
> at least once; ask the running instance instead.

After applying it: the `storage-layout` tree says what the directories hold rather than how many;
the build command names `validate_data.py` instead of restating a number; README's table is
attributed to the 2026-08-19 measurement with `GET /api/stats` named as the live figure; and
`migration-report`'s counts are marked as of 2026-07-26.

**Tests hold this in place**: `test_no_document_reports_a_pool_size_that_belongs_to_an_earlier_era`
bars `13,077,781` / `8,225,138` / `8,125,976` from prose, exempting `migration-report` as a dated
historical record, and `test_the_acquisition_notes_state_the_number_of_sources_the_catalog_holds`
re-derives the source total from the catalog.

---

## 3. Not conflicts, but worth knowing

**The Chinese `dataset-acquisition` is incomplete.** English is 535 lines, Chinese 337, with the
same heading count (33/33) and every source identifier present in both. What is missing is several
summary rows from the English tables — for instance ELEMENTA's "43,521,713 frames across 2,235,193
relaxations". **There is no numeric disagreement**; it is a completeness gap, and closing it is
translation work rather than correction.

**No Chinese/English pair disagrees numerically.** Every thousands-separated figure was compared
pair by pair. The only differences are the one above and `7,836` in `property-integration`, which
Chinese writes once as "各 7,836" ("7,836 each") where English writes it twice.

---

## 4. How to re-check

```bash
# whether a retired pool size is back in prose, and whether the source total matches the catalog
PYTHONPATH=backend:. python -m pytest backend/tests/test_dataset_acquisition.py -q

# whether every relative link resolves
for f in $(git ls-files "*.md"); do d=$(dirname "$f"); \
  grep -oE '\]\([^)]+\)' "$f" | sed -E 's/^\]\(|\)$//g' | grep -v '^http' | grep -v '^#' | \
  while read -r p; do t="${p%%#*}"; [ -z "$t" ] || [ -e "$d/$t" ] || echo "$f -> $p"; done; done

# which era-8.2M constants are left in the code
grep -rn "99_162\|8_125_976\|8,225,138\|6\.12M" $(git ls-files "*.py")
```

The live figures come from a running instance:

```bash
curl -s http://127.0.0.1:8000/api/stats
```
