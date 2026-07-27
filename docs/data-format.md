# Crystal Record v1

Crystal Record v1 is the only accepted source format for MateriaViva indexing. Each
dataset provides UTF-8 `train.csv` and `val.csv` files with this exact header:

```text
index,material_id,cif,pbes_gap
```

| Field | Logical type | Required | Meaning |
|---|---:|---:|---|
| `index` | non-negative integer | yes | Stable identifier inside the source dataset |
| `material_id` | non-empty string | yes | Composition identifier used to normalize formula and elements |
| `cif` | non-empty UTF-8 string | yes | Complete CIF document; embedded newlines are CSV-quoted |
| `pbes_gap` | float or empty | yes | PBEsol band gap in eV when available |

The machine-readable logical schema is
[`schemas/crystal-record-v1.schema.json`](../schemas/crystal-record-v1.schema.json).
Run `make validate-data` before rebuilding the index. Validation streams every
record, verifies both split headers and values, enforces the released row counts,
and atomically writes `data/manifests/{experimental,candidate}.json`.

## Canonical serving database

Source CSV files are normalized into two coordinated files:

- `data/index/materials.sqlite` stores searchable metadata, provenance, normalized
  formulas and chemical systems, structure properties, and CIF blob offsets.
- `data/index/structures.blob` stores zlib-compressed CIF payloads for random access.

The SQLite/blob pair is one logical database and must be moved, backed up, and
restored together. `build-report.json` records the source paths, counts, skipped
records, and build duration. New fields belong in the SQLite schema; source-specific
metadata should remain in provenance sidecars rather than changing the four-column
Crystal Record contract.
