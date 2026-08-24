# amcsd golden sample

`raw/cif.zip` is hand-built. CIF text is passed through verbatim by the adapter,
so these files only need the fields its regexes read.

| entry | what it pins |
|---|---|
| `0000001.cif` | quoted mineral name is unquoted; density is kept |
| `0000002.cif` | a density of exactly 0 fails the `> 0` guard, and the record is still emitted with no properties |
| `0000003.cif` | no `_database_code_amcsd` — skipped |
| `__original__/0000004.cif` | the as-published duplicate path is skipped |
| `notes.txt` | a non-`.cif` member is skipped |
| `0000005.cif` | an unquoted mineral name with trailing spaces is trimmed |

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
