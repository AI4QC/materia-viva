# 2dmatpedia golden sample

`raw/twodmatpd.json.zip` is hand-built; the same minimal jarvis `atoms` dict is
reused except where a broken one is the point.

| row | what it pins |
|---|---|
| `2dm-1` | the two things that would otherwise regress silently: `exfoliation_energy_per_atom` 0.089 eV/atom becoming 89.0 meV/atom, and the magnetisation normalisation living in the method (`… per cell`) rather than in a unit the database discards |
| `2dm-2` | with no numeric field at all, only `dimensionality` remains |
| `2dm-3` | an unusable `atoms` dict empties the structure without losing the properties |
| (no id) | the native id falls back to `2dm-x<index>` |

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
