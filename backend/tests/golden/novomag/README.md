# novomag golden sample

`raw/magdb-v1.json` is hand-built JSONL: one pymatgen `ComputedStructureEntry`
per line, eight lines in, three records out.

| line | what it pins |
|---|---|
| `NM-1` | everything at once — the magnetisation normalisation in the method (`… per cell`), the anisotropy constant picking the direction of largest magnitude (`100`, −1.7 over 0.9 and 0.4), meV→eV on both hull and decomposition energies, and a rydberg-per-cell total energy becoming −68.0285 eV/atom over two sites |
| `NM-2` | a moment reported `per: atom` is dropped, because only per-cell is trusted; a hull energy already in eV is not divided |
| `NM-3` | a space group of 999 and a Curie temperature of 1e6 are both outside their windows, leaving no properties and no structure |
| stats line | a row carrying `stats_id` is skipped |
| `@class: ComputedEntry` | anything that is not a `ComputedStructureEntry` is skipped |
| blank `entry_id` | skipped |
| `{ not json` | a malformed line is skipped rather than aborting the file |
| empty line | skipped |

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
