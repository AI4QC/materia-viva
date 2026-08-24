# snumat golden sample

`raw/snumat.json.zip` is hand-built.

| row | what it pins |
|---|---|
| `SNU-1` | `SOC: "True"` puts `+SOC` in every method string, which is what keeps a spin-orbit run from colliding with its scalar sibling on the same ICSD parent |
| `SNU-2` | all four gap columns map to four `band_gap` rows differing only by method; the HSE gap character maps to `is_gap_direct` |
| (no id) | the native id falls back to `snumat-<index>`, and a gap character that is neither direct nor indirect is dropped |

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
