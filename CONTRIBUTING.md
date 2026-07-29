# Contributing to MateriaViva

**English** · [简体中文](CONTRIBUTING.zh-CN.md)

Thanks for contributing code, documentation or data source information to MateriaViva. Please
observe the boundaries below before submitting.

## Development workflow

1. Create a short-lived branch from `main`.
2. Keep Python code compatible with Python 3.10+; the frontend uses Node.js 20+.
3. Run `make test` and `make build`.
4. Describe behaviour changes, verification commands and any data schema impact in the commit.

## Data boundaries

- Never commit `data/`, `runtime/`, raw databases, the SQLite/blob index, render caches, `.part`
  files, receipts, API tokens or licence-restricted data to Git.
- New sources must be registered in `scripts/datasets/sources.json` with their official URL, access
  mode, licence, target path, current status and provenance notes.
- MateriaViva currently accepts only unique periodic structure endpoints; molecular dynamics,
  relaxation processes, rattled configurations and reaction-path intermediate frames must not be
  imported as independent structures.
- Original source formats may be retained, but everything must convert to `Crystal Record v1` before
  entering the serving index, preserving source ID, source record ID, version, units and licence
  information.
- Do not delete a suspected duplicate source before the unified structural fingerprint comparison is
  complete; deduplication must preserve all properties and provenance.

## Verification

```bash
PYTHONPATH=backend:. python -m pytest backend/tests -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

Changes to the data schema or the indexer also require `make validate-data`, or a minimal synthetic
fixture covering the change when the full dataset is unavailable. The complete data is published to
the [Hugging Face Dataset](https://huggingface.co/datasets/AI4QC/materia-viva) rather than
transferred through Git PRs.
