# obelix golden sample

`raw/all.csv` is hand-built, not a copy of the real 599-entry file: each row
exercises one branch of `scripts/properties/adapters/obelix.py`.

| row | what it pins |
|---|---|
| `A1` | all three properties, and an `ICSD ID` that is a whole number |
| `A2` | the `<digits>-ICSD` provenance pattern, with a trailing comment |
| `A3` | the `ICSD-<digits>` pattern in the second reference column |
| `A4` | no property at all — the record is dropped even though it has an ICSD id |
| (blank id) | a row with no `ID` is dropped |
| `A6` | conductivity of exactly 0 fails the `> 0` guard, leaving no property |
| `A7` | a non-integer `ICSD ID` yields no match id |
| `A8` | space group alone is enough to keep the record |

`expected.json` was recorded from the adapter, so it proves the behaviour has
not changed — not that the mapping is right. See `authored_by` in that file and
the note at the top of `scripts/properties/golden.py`.
