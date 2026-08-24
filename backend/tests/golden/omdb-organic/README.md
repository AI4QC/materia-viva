# omdb-organic golden sample

`raw/omdbv1.json.zip` is hand-built; every record uses the same minimal jarvis
`atoms` dict except where the point is that it is broken.

| row | what it pins |
|---|---|
| 0 | gap plus a COD id match |
| 1 | a null gap leaves the record with no properties, and it is still emitted |
| 2 | no `cod_id`: the native id falls back to the row index and there is no match |
| 3 | an unusable `atoms` dict leaves `structure` empty without losing the property |

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
