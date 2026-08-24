# elementa golden sample

`raw/work/endpoints_{open,spin}.tsv` are hand-built, five rows over the two
archives. The adapter is properties-only, so no record carries a structure.

| row | what it pins |
|---|---|
| `open` / `Fe4` | the full set, including the magnetisation normalisation now in the method (`… per cell`), and the trailing colon the open archive's empty spin field leaves in the native id |
| `open` / `Ni2` | a moment of 100 μB over two sites exceeds 12 μB/atom and is dropped and counted |
| `open` / `Cu2` | −500 eV/atom falls outside the declared window and is dropped, while the residual force survives |
| `open` / `Al1` | a residual force of 99 eV/Å is outside its window; the stress and the energy are unaffected |
| `spin` / `Gd2` | a non-empty spin appears in both the native id and the per-endpoint method (`… spin: structure_05/fm`), which is what keeps sibling endpoints of one composition apart |

Running the adapter prints its drop tally; for this fixture it is
`{'total_magnetization': 1, 'total_energy_per_atom': 1, 'max_residual_force': 1}`,
one per guard above.

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
