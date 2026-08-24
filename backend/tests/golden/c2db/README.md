# c2db golden sample

`raw/c2db_atoms.json.zip` is hand-built.

| row | what it pins |
|---|---|
| `MoS2-…` | all three scalars — gap, work function, Fermi level — under one method |
| `WS2-…` | gap only |
| (no id) | the native id falls back to `c2db-<index>`, and a gap of exactly 0 is kept (it is a real metal, not a missing value) |
| `BN-…` | an unusable `atoms` dict leaves only `dimensionality` |

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
