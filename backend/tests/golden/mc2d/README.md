# mc2d golden sample

`raw/structure_2d.json` holds four rows copied verbatim from Materials Cloud
record [17gf6-84915](https://archive.materialscloud.org/api/records/17gf6-84915)
(CC BY 4.0), chosen one per branch. The two zips carry placeholder CIF text under
the real uuids: the adapter passes CIF through as a string, so the fixture only
needs the member names to line up.

| row | what it pins |
|---|---|
| `Na4HgP2` | both van-der-Waals functionals, so two `interlayer_binding_energy` rows differing only by method |
| `ZnIn2Se4O12` | DF2-C09 only |
| `Ni3GeTe2` | no binding energy at all — dimensionality, gap and space group remain |
| `LaBr` | no optimized uuid, so the structure comes from the as-extracted archive instead |

The reason this sample matters most: upstream ships binding energies in eV/Å²
while the canonical unit is meV/Å², and the ×1000 conversion was missing. The
static unit audit cannot catch that returning — the label would stay meV/Å² while
the numbers silently shrank — so the four values here (32.47, 14.98, 11.67,
17.51) are what holds the fix in place.

`authored_by: recorded-from-adapter` — a regression baseline, not proof the
mapping is right.
