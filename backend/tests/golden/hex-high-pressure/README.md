# hex-high-pressure golden sample

`raw/HEX.zip` is hand-built. The member path carries the search pressure and the
category, so the fixture is mostly about which paths are accepted.

| member | what it pins |
|---|---|
| `DB_GS/DB_GS_000/Fe_0_GS.cif` | pressure from the filename and a valid FINDSYM space group |
| `DB_EA/DB_EA_100/Li_100_EA.cif` | a space group outside 1-230 is rejected, leaving pressure alone |
| `DB_MISS/DB_MISS_300/Na_300_MISS.cif` | no FINDSYM line at all |
| `__MACOSX/...` | archive noise is skipped |
| `DB_GS/DB_EA_100/Cu_100_GS.cif` | the directory must repeat its own category — this one does not, so the backreference in the member pattern rejects it |

Records come out in archive-name order, so `DB_EA` precedes `DB_GS`.

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
