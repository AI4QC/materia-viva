# Cross-database property integration

**English** · [简体中文](property-integration.zh-CN.md)

Updated: 2026-08-19

MateriaViva attaches properties from dozens of acquired source databases to the unified
structure pool, with every value carrying its source database, native record id and
calculation / measurement method. Structures the pool does not contain yet are admitted
through the same fingerprint deduplication as the original merge.

## 1. Data model (index schema v3)

Five tables extend `data/index/materials.sqlite`:

| Table | Contents |
|---|---|
| `source_defs` | one row per source database: key, display name, licence, official URL (seeded from `scripts/datasets/sources.json`) |
| `property_defs` | one row per property: canonical snake_case name, unit, kind (`num` / `text` / `bool`) |
| `material_properties` | one row per value: `material_pk`, property, source, `native_id` (source's own record id), `value_num` / `value_text`, `method` (functional or measurement conditions) |
| `material_source_refs` | which databases contain each material: `(material_pk, source, native_id, match_via)` with `match_via` ∈ `id:<db>` / `hash` / `origin` |
| `material_curves` | one row per non-scalar spectrum: `curve_type` (band structure, DOS, phonon DOS, XRD, Raman, IR, XAS, optical absorption, κ spectra), `fmt` (`xy` / `peaks` / `svg`), source, `native_id`, `method`, and an offset into `data/index/curves.blob` |

The original scalar filter columns on `materials` (band gap, formation energy, energy above
hull, stability, metallicity, magnetic ordering, magnetization, moduli, Poisson ratio) are
backfilled from `material_properties` following the source priority in
`scripts/properties/registry.py` (`SCALAR_BACKFILL_PRIORITY`); existing values are never
overwritten, and the full multi-source record always remains in `material_properties`.

Space-group coverage is completed for the whole pool by parsing the space-group token that
the BAWL fingerprint itself carries (`<md5>_<spacegroup>_<formula>`).

`materials.material_family` labels non-conventional crystal classes — `mof`, `cof`, `hof`,
`zeolite`, `zeotype`, `molecular-crystal`, `2d-material`, `1d-material`,
`carbon-allotrope` — assigned per source (`SOURCE_FAMILY`) or inferred from the
`dimensionality` property; `NULL` means an ordinary bulk crystal. The API filters on it via
`material_families=` (the pseudo-value `bulk` selects unlabelled rows) and the frontend
shows it as a badge next to the experimental/candidate tag.

## 2. Integrated sources

Numbers (property rows, materials touched, new structures per source, plus pool and
property-count totals) are generated from the live index by
`scripts/properties/summarize.py` and recorded in the summary table at the end of this
document; the groups below describe what each source contributes and how it matches.

### Large general-purpose DFT databases

| Source | Contributes | Match route |
|---|---|---|
| Materials Project (summary 2026.04.13 + 8 property endpoints 2026-08-19) | PBE(+U) gaps, formation / hull energies, stability, magnetism, VRH moduli, dielectric / piezoelectric constants, refractive index, work function, surface energy, experimental-observation flag; plus insertion-electrode voltages / capacities / energy densities, Voigt-Reuss bounds, Debye temperature, sound velocities, Clarke-Cahill minimum thermal conductivity, EOS bulk modulus, per-facet surface extremes, grain-boundary energies, mean oxidation states, coordination environments | ICSD ids + fingerprint |
| Alexandria (PBE / PBEsol / SCAN; 3D / 2D / 1D) | formation / hull energies, indirect & direct gaps, magnetization, total energies per functional | `agm` ids (≈54%) + fingerprint |
| OQMD v1.8 (SQL dump) | formation energy, hull distance, gap, magnetization — one converged final calculation per entry | pool `oqmd-…` structure ids + ICSD ids + fingerprint |
| AFLOW (AFLUX, 2.98M) | formation enthalpy, gap, total energy, prototype label, space group, density | ICSD ids (ICSD_WEB subset) + fingerprint |
| JARVIS-DFT 3D | OptB88vdW / TBmBJ / HSE06 gaps, VRH moduli, Seebeck / power factor, dielectric, DFPT piezo, SLME, spillage, exfoliation energy, EPC T_c | legacy mp ids + ICSD ids + fingerprint |
| GNoME | formation / decomposition energies, gaps; r2SCAN re-computed subset | fingerprint |
| WBM via matbench-discovery | MP2020-corrected formation / hull energies, PBE gaps; its MP-2023 snapshot also bridges legacy numeric mp ids into the match map | fingerprint (+ mp bridge) |
| ODBX misc (CAMD) | formation energy, hull distance | OQMD / ICSD ids + fingerprint |
| ELEMENTA | per-endpoint total energies (spin runs add magnetization) | endpoint ids, properties-only |
| JARVIS-QETB (829,576 records) | tight-binding formation / total energies and gaps over a fitting set full of deliberately non-equilibrium geometries; every row carries `method` "QETB (tight-binding)" so the fidelity gap to the DFT sources stays visible | fingerprint |
| Carolina Materials Database (MatSciML redistribution) | ML-generated hypothetical crystals: formation energy, space group | fingerprint |
| Materials Cloud MC3D (PBEsol-v2) | PBEsol-relaxed 3D crystals with their experimental parents | ICSD / COD ids + fingerprint |

### Experimental structure catalogues

| Source | Contributes | Match route |
|---|---|---|
| COD (full-catalog parquet, rev 282068) | as-published experimental CIFs plus chemical / mineral names and the temperature and pressure the measurement was made at; theoretical, retracted and redirected rows are dropped, organics are admitted (the C/H block the original tier build excluded) | `cod` ids + fingerprint |
| ICSD (FIZ detail records) | chemical and mineral names, calculated density | `icsd` ids + fingerprint, properties-only |

ICSD is licensed from FIZ Karlsruhe: its adapter is `properties_only` and must stay
that way, so no FIZ structure ever enters the pool, and neither its structures nor
the values staged from it may appear in a published MateriaViva snapshot.
`scripts/properties/icsd_bridge.py` recovers the collection codes that reached the
pool as MP / COD / OQMD / Alexandria structures rather than through the local ICSD
half of the merge — 38,223 further collection codes, 49,579 code→material pairs —
so the ICSD-keyed sources below
(webmineral, AMDB, OBELiX, SPSE, 3DSC, SNUMAT, MC3D, …) stop silently dropping
their rows for them.

### Specialised property libraries

SNUMAT (GGA / HSE06 electronic + optical gaps, magnetic ordering; ICSD),
Materiae (SOC / NSOC topological classes, symmetry indicators, DOS gaps; mp + ICSD),
phonix (lattice thermal conductivity, phonon frequency range, imaginary-mode flag; mp),
PhononDB (NIMS MDR: PBEsol DFPT dielectric constants and Born effective charges, plus the
harmonic phonon DOS itself; mp ids read out of the MDR record titles + fingerprint),
NOVOMAG (magnetic polarization / moments / anisotropy, Curie temperatures; mp),
AMDB (an altermagnetism screen over MAGNDATA: spin-splitting metrics and the screening
gap; ICSD, properties-only), SuperBand + 3DSC + JARVIS supercon 2D/3D (superconducting
T_c; 3DSC is properties-only),
SPSE (BVSE migration barriers, experimental ionic conductivities; ICSD, properties-only),
OBELiX (experimental room-temperature ionic conductivity; ICSD, properties-only),
CSLLM negatives (a `predicted_synthesizable=false` label for pool materials whose
fingerprint matches a PU-screened non-synthesizable structure; properties-only — a
missing row is not a prediction of synthesizability),
C2DB / 2DMatPedia / MC2D / BiDB / OpenMX 2D-AB2 (2D gaps, exfoliation / interlayer binding
energies, work functions, AB2 monolayer prototypes), OMDB-organic (omdb.mathub.io — organic molecular-crystal gaps; COD ids), CMR collections (GLLB-SC gaps +
derivative discontinuities, perovskite heats of formation, OQMD-linked energetics,
low-dimensionality labels), Materials Cloud archives (SHG coefficients, refractive index /
birefringence, HSE / LDA gaps, TQC topology classes, electride ELF), HADB (hard-coating
elastic moduli, DFT + MLIP at temperature), SACADA (carbon allotropes: density, hardness,
moduli, relative energies), TCOD (DFT gaps in theoretical CIFs), HEX high-pressure
elements (0–300 GPa), AMCSD + RRUFF (experimental mineral structures, mineral names,
measured densities / chemistry), webmineral (species-level mineral compilations from the
*Handbook of Mineralogy* — density, Mohs hardness, refractive index; ICSD,
properties-only, and the values describe the species rather than the matched specimen),
AFLOW prototype encyclopedia (prototype + Strukturbericht
labels; properties-only), open-framework aluminophosphates (AlPO frameworks, IZA codes).

### Porous and framework materials

hMOF (hypothetical MOFs: CO₂ uptake, zeo++ geometry), Boyd–Woo `mof-carbon-capture`
(GCMC CO₂ capture: uptakes, selectivities, working capacities, heats of adsorption),
MOFX-DB (CoREMOF / IZA / Tobacco subsets: geometry + single-gas uptakes near 298 K, 1 bar),
CoRE MOF 2019 (curated experimentally reported MOFs: Zeo++ porosity — largest cavity and
pore-limiting diameters, largest free path, density, gravimetric and volumetric surface
area, void fraction, pore volume — from the tables published beside the archives in Zenodo
record [10.5281/zenodo.3677685](https://doi.org/10.5281/zenodo.3677685), CC BY 4.0; the
all-solvent-removed and free-solvent-removed variants are kept apart by the method string,
because on the 2,574 pairs that differ the FSR cell is the tighter one),
QMOF (DFT-relaxed MOFs: multi-functional gaps and direct/indirect flag, total energy,
magnetization, density, LCD / PLD; CSD refcodes for the 16,040 CSD-derived rows),
FAIR-MOFs (experimental CSD-derived MOFs: porosity, RCSR topology, bond-dissociation
energies), EC-MOF (conductive 2D MOFs: gaps, formation / binding energies), CURATED-COFs
(synthesized covalent organic frameworks with their framework names), IZA-SC (the 268
approved zeolite framework types as DLS76-idealized pure-silica geometries — not
experimental), Deem SLC zeolites and pcod (hypothetical frameworks, below). All carry
`material_family` labels except pcod, whose chemistry is mixed — silicates, phosphates,
borates, vanadates, aluminates — and which is emphatically not all zeolites.

Two of these ship their entire property payload inside the CIF itself:

- **Deem SLC zeolites.** Every one of the 331,172 CIFs ends with the SLC-forcefield GULP
  run that produced it, written as CIF comments so no parser ever sees it. Parsing that
  trailer yields bulk and shear moduli in Reuss / Voigt / Hill, Young's modulus per stress
  axis, six directional Poisson ratios (not averaged — the arithmetic mean of six
  directional ratios is not the isotropic ratio of anything, and averaging would discard
  exactly the anisotropy a hypothetical-zeolite screen is looking for), Hill sound
  velocities, density, framework density, both dielectric constants as the trace/3 of the
  printed tensors, and the energy per T atom: ~2.98M rows. A plausibility window per
  property name drops the 0.42% of values where GULP's own averaging diverged on a
  near-singular compliance matrix. The `<id>.txt` file shipped next to each CIF carries
  the framework's simulated diffraction pattern, giving 136,008 XRD stick patterns
  converted from d-spacing to Cu Kα 2θ so they overlay the on-demand simulation.
- **pcod** (GRINSP snapshot, 2008-04-01) contributes `structure_prediction_r_factor` and
  `framework_density`, both read out of the free-text and commented trailers. Its
  commented space-group suggestions are deliberately *not* mapped onto
  `spacegroup_number`: the depositor disabled them and the deposited coordinates are the
  P1 expansion regardless.

> **Enumerated frameworks and the limits of the fingerprint.** hMOF, the Deem zeolites and
> pcod are all *enumerated* libraries — one framework topology decorated with a menu of
> functional groups, or an idealized silica / aluminophosphate net where every Si is
> 4-coordinated and every O 2-coordinated. Sibling entries therefore share a bonding graph
> and a primitive composition, which is everything the BAWL fingerprint looks at, so the
> hash cannot separate them: 59% of the 331k Deem set collides within the source, and
> 46,891 of hMOF's 135,818 hashable records collided with an earlier record. All three are
> admitted under a composite key — (fingerprint, volume per atom) — which is cell-choice
> invariant and separates frameworks the graph hash cannot.
>
> - Deem (`scripts/properties/deem_zeolite_admit.py`): 136,008 frameworks admitted, 8,262
>   pool duplicates confirmed by both fingerprint and density, 180,386 composite duplicates
>   dropped.
> - hMOF (`scripts/properties/hmof_composite_admit.py`): 38,571 frameworks admitted on top
>   of the 88,927 the first load reached, worth 358,924 new property rows, and 28,914
>   ambiguous fingerprints purged from the match map so that no later source can resolve
>   through them.
>
> Colliding fingerprints are deliberately never registered in the match map, so a future
> SiO₂ or MOF record can never be mis-attached to an ambiguous framework by fingerprint
> alone. `load.FINGERPRINT_UNRELIABLE` enforces the same rule at load time for
> `deem-zeolites` and `pcod`: for those two a `hash` row in `matched.tsv.gz` is not evidence
> of identity, because the hash path collapsed 126,578 distinct Deem frameworks onto 281
> pool materials — one of them absorbing 27,007 — and loading through those refs stapled one
> framework's elastic moduli onto a material that is a different framework. Those rows are
> now rejected; the `origin` refs from the composite-key admission, 1:1 with a pool
> material, are what properties attach through. Clearing what the earlier runs had already
> written deleted 190,655 Deem and 4,916 pcod hash refs and removed 4,190,215 wrongly
> attributed property rows.

### Deliberately excluded sources

| Source | Reason |
|---|---|
| MOSAEC-DB | ships no structures (CSD refcodes only) — nothing to match against |
| TopoMat | the local mirror carries band data but no topology labels |
| MatterGen snapshots | training-set copies; their DFT values originate from MP / Alexandria, both already ingested |
| alexandria-jarvis-snapshot | older (2024.10.1) mirror of the loaded Alexandria source; sampled ids and hull entries verified identical — duplicate provenance |
| catalysis-hub | the crawl omitted `reactionSystems`, the field that joins a reaction to its slab and thence to a bulk id, so 144,386 of 158,304 reaction energies (91.2%) have no authoritative route; the remaining 8.8% (one publication that encodes `…-mp-<n>-<term>` in `surfaceComposition`) covered only 60 materials and was dropped with the rest rather than shipping a token subset. Reviving it means re-crawling the GraphQL API with `reactionSystems` plus the full `systems` table (the local `systems/` crawl aborted at 32 of 305,169 rows). |
| ShiftML2 / MAD | no per-record ids; rattled and MD frames are excluded by project scope |
| SIMPOD / opXRD | both original reasons have lapsed — the curve store now holds non-scalar patterns and COD is ingested — but neither source has been re-evaluated or given an adapter |
| ARC-MOF | overlaps hMOF / Tobacco / CoREMOF pools heavily; deferred |
| HOFSyn | CIFs carry CCDC redistribution restrictions; deferred |
| B-IncStrDB | incommensurate structures reduce to misleading average cells |
| CCP-NC magres / 2D alloys / Materials Cloud specialized | site-resolved tensors, raw uncorrected totals or no properties at all; deferred |
| OMat24 / MPtrj / MC Li-ion | trajectory datasets, excluded by scope |

## 3. Matching rules

Matching never relies on formula equality. Two paths, in order:

1. **Authoritative id match.** When a record explicitly *is* an entry of a database the
   pool already tracks (LeMat immutable ids `mp-…`/`oqmd-…`/`agm…`, experimental
   `icsd-…`/`cod-…`, ELEMENTA endpoint ids), the adapter declares `match_ids` and the
   record resolves without touching the structure. Ids that point at a *related* entry
   (e.g. a monolayer's 3D bulk parent) are deliberately **not** used.
2. **Fingerprint match.** The record's structure is parsed, capped (≤500 sites, ≤300 after
   primitive reduction, ordered occupancies only) and hashed with the same
   primitive-reduced BAWL protocol as the original merge; the hash is looked up against the
   full-pool hash map. A hash may legitimately resolve to both an experimental and a
   candidate material; properties attach to every match.

Sources whose structures may not be redistributed (ICSD-derived mirrors such as SPSE or
3DSC-ICSD) run in `properties_only` mode: they may only annotate existing materials and
never contribute new structures.

Legacy numeric Materials Project ids (still used by JARVIS, phonix, NOVOMAG, 3DSC, Materiae
and others) are bridged through the matbench-discovery MP-2023 snapshot: its structures are
fingerprint-matched into the pool once, and the resulting `mp-#### → material` pairs are
registered in the match map (`scripts/properties/mp_bridge.py`).

**What the fingerprint cannot reach.** BAWL needs an ordered, size-capped cell, so two
classes of record can never be deduplicated and are left unmatched rather than guessed at:
partial-occupancy (disordered) structures, and structures still over the site caps after
primitive reduction. This is where the large experimental catalogues lose records — COD
leaves 120,997 DISORDERED and 119,368 too-large entries unmatched, ICSD leaves 84,971
DISORDERED. It is a boundary of the deduplication approach rather than a defect in it: a
disordered cell has no single set of atomic positions to hash, and admitting one under a
guessed ordering would put a structure in the pool that nobody deposited.

## 4. New-structure admission

A record whose fingerprint misses the pool becomes a new master record, subject to the
standard admission rules (static endpoint, ordered, size caps). The loader appends the CIF
to the blob, inserts the `materials` row (space group from the fingerprint token,
`material_family` from the source), appends a Crystal Record v1 row to the source CSV and a
fingerprint row to the merge metadata (`added_meta.tsv` / `synth_meta.tsv`), and registers
the fingerprint back into the match map — so every later source deduplicates against
freshly admitted structures automatically. Experimental databases (e.g. AMCSD minerals)
enter the experimental pool; computed and hypothetical databases enter the candidate pool.

## 5. Pipeline

```text
scripts/properties/
├── registry.py     canonical property vocabulary, source→family map, scalar priority
├── base.py         adapter protocol (SourceRecord / PropertyValue / flags)
├── adapters/       one adapter per source database
├── match_map.py    build data/props_work/match_map.sqlite from the pool merge metadata
├── pipeline.py     per-source stages: adapt → hash → match (resumable artifacts)
├── hashing.py      parallel BAWL fingerprints (28 workers, ~600 structures/s)
├── load.py         migrate / load / backfill / verify against the live index
├── curves.py       load non-scalar spectra into curves.blob / material_curves
├── curve_sources/  one curve extractor per source database
├── mp_bridge.py    legacy mp-id bridge
├── verify_complete.py  three-way completeness audit of the whole property layer
└── run_all.py      production driver (bridge → main → huge → backfill)
```

Per-source artifacts live in `data/props_work/<source>/` (`staging_props.tsv.gz`,
`id_matches.tsv.gz`, `hashes.tsv.gz`, `matched.tsv.gz`, `new_structs.jsonl.gz`,
`report.json`, `load_report.json`); the driver's state is `data/props_work/run_status.json`.
A full rebuild of the property layer is: `match_map.py` → `run_all.py` against a freshly
built base index. Loading is idempotent — a source with a recorded load refuses to
double-load.

`verify_complete.py` audits the result independently of the loader's own bookkeeping, with
three checks per source, each able to fail on its own:

1. **Load integrity** — the row count the loader's receipt reports must equal the count the
   index actually holds for that source. A mismatch means a load was interrupted, ran
   twice, or had its rows cleared and never re-inserted; the summary table can never show
   that, because it only reports what is in the database.
2. **Staging yield** — `staged - landed - unmatched` must be zero. Every row the adapter
   staged is either in the index or accounted for as `props_unmatched` (a `native_id` no
   pool material corresponds to); anything else is silently dropped data.
3. **Field coverage** — every distinct property *name* in `staging_props.tsv.gz` must be
   present in the index for that source. Names staged only for records that are unmatched
   anyway are excluded, since a field whose every carrier had nowhere to land is not a
   defect; that exclusion is what separates a loader bug from an empty match.

Sources staged on disk but absent from `source_defs` are reported as NEVER LOADED, and
sources in the registry with no work directory as NOT STAGED, so nothing can go missing
merely by not being mentioned. Several scripts write `material_properties` without going
through the loader (`hmof_composite_admit`, `alexandria_recover_functional_runs`,
`aflow_ael_attach`, `phonondb_attach`) and none of them refresh `load_report.json`, so rows
above the receipt are surfaced as out-of-band information rather than as a defect — only
the index falling *below* the receipt is an error. It currently audits **54** sources and
reports **0** problems.

## 6. Method and unit conventions

Units are converted to the canonical unit of `property_defs` inside the adapter (e.g.
cm⁻¹ → THz for phonon frequencies, kcal/mol → kJ/mol for heats of adsorption, meV/atom →
eV/atom for hull distances); the `method` string records the level of theory or measurement
conditions verbatim (`PBE`, `HSE06`, `GLLB-SC indirect`, `GCMC 298K ~1bar TraPPE`,
`experiment 300K`, …). One property may therefore carry several rows per material — one per
(source, method) — and the UI presents them all rather than averaging.

A canonical name is refused when the quantity behind it differs in kind, even where the
numbers would look plausible in the same column and a method string could in principle
disambiguate them:

- `structure_prediction_r_factor` is deliberately not `r_factor`. GRINSP's R is the cost
  function of a geometric restraint search — the disagreement between a predicted
  framework's realised distances and angles and the ideal targets fed to the optimiser —
  while `r_factor` is the crystallographic refinement residual R1 that
  open-framework-aluminophosphate stages from published refinements. Nothing in pcod was
  ever measured, so nothing there was refined against an observation. Both are
  dimensionless, both improve downwards, and their ranges interleave (0.0001–0.0500 against
  0.022–0.078), so no numeric filter could separate them afterwards; pcod would also
  outnumber the refined values ~17.2k to ≤312, leaving the column's dominant population
  contradicting its own definition.
- `energy_per_t_atom` (kJ/mol) is deliberately not `total_energy_per_atom` (eV/atom). The
  Deem trailer reports a forcefield lattice energy per *tetrahedral* site, not a DFT total
  energy per atom, and filing it in the shared column would corrupt it. The T-atom
  convention is the one the registry already uses for `framework_density`, so any other
  framework source reporting the same quantity can reuse the name.

## 7. API and frontend

- `GET /api/materials/{id}` now returns `properties` (per-source rows joined with
  `property_defs` / `source_defs`), `source_refs` and `curves` (one entry per stored
  spectrum, with its type, method and source).
- `GET /api/materials/{id}/curves/{curve_id}` serves one stored payload — JSON for `xy` /
  `peaks`, `image/svg+xml` for `svg` — immutably cached; `GET /api/materials/{id}/xrd`
  simulates a Cu Kα powder pattern from the CIF on demand for every structure in the pool.
- `GET /api/materials` accepts `material_families=` (CSV; `bulk` = unlabelled).
- The detail page shows a material-class badge, a "Representative properties" section
  (backfilled scalar columns), the full cross-database property list with per-value source
  tags, a spectra panel that draws stored and simulated diffraction on one 2θ axis, and a
  source-database section linking every native record id.


## 8. Summary table (generated 2026-08-19)

Regenerate with `scripts/properties/summarize.py` after any load.

| Source | Property rows | Materials touched | New structures | Licence |
|---|---:|---:|---:|---|
| Alexandria Materials Database (`alexandria`) | 60,588,138 | 5,894,222 | 1,514,488 | Alexandria dataset terms |
| AFLOW (`aflow`) | 18,464,119 | 2,275,947 | 1,650,288 | AFLOW academic non-commercial terms |
| ELEMENTA and ELEMENTA Spin (`elementa`) | 8,023,344 | 2,005,836 | 0 | CC BY-NC 4.0 |
| Open Quantum Materials Database (`oqmd`) | 6,086,500 | 1,229,047 | 255,085 | CC BY 4.0 |
| Hypothetical MOFs for wet flue-gas carbon capture (`mof-carbon-capture`) | 5,454,666 | 287,610 | 287,610 | CC BY 4.0 |
| GNoME materials discovery dataset (`gnome`) | 4,897,901 | 554,056 | 547,603 | CC BY-NC 4.0 |
| Materials Project (`materials-project`) | 4,291,860 | 211,854 | 3,157 | Materials Project terms |
| Michael Deem PCOD hypothetical zeolite structures v2.1 (`deem-zeolites`) | 2,977,166 | 136,008 | 136,008 | CC BY 4.0 |
| NIST JARVIS-QETB tight-binding dataset (`jarvis-qetb`) | 2,524,250 | 191,606 | 124,598 | NIST/JARVIS dataset terms |
| Matbench Discovery / WBM (`matbench-discovery`) | 1,734,187 | 401,437 | 136,041 | CC BY 4.0 |
| NIST JARVIS-DFT 3D (`jarvis-dft`) | 1,569,924 | 120,277 | 14,986 | NIST/JARVIS dataset terms |
| Hypothetical MOF database (`hmof`) | 892,486 | 127,498 | 127,498 | Figshare record licence |
| Materiae - Material Sciences Database (catalogue of topological electronic materials) (`materiae`) | 589,993 | 67,688 | 4,769 | Materiae site terms; cite Zhang et al., Nature 566, 475-479 (2019) |
| Carolina Materials Database (`carolina`) | 428,272 | 210,000 | 43,801 | CC BY 4.0 |
| Crystallography Open Database (`cod`) | 354,350 | 265,903 | 238,839 | CC0 |
| Quantum MOF Database (`qmof`) | 339,443 | 26,615 | 17,142 | CC BY 4.0 |
| DTU Computational Materials Repository static periodic datasets (`cmr-static`) | 305,346 | 192,185 | 33,044 | CC BY-SA 4.0 |
| Open Databases Integration for Materials Design (`odbx`) | 287,006 | 142,987 | 103,138 | ODBX provider terms and source-dataset provenance |
| FAIR-MOFs experimental and optimized structures (`fair-mofs`) | 277,454 | 33,030 | 32,847 | CC BY 4.0 |
| Inorganic Crystal Structure Database (`icsd`) | 257,558 | 77,041 | 73,823 | FIZ Karlsruhe ICSD licence |
| SNUMAT hybrid-functional database (`snumat`) | 170,893 | 21,115 | 3,273 | Figshare record licence |
| CoRE MOF 2019 (`core-mof`) | 155,488 | 11,784 | 1,606 | CC BY 4.0 |
| Phonix anharmonic phonon and thermal-conductivity database (`phonix`) | 155,192 | 22,733 | 2,171 | CC BY 4.0 |
| Materials Cloud Archive static optical, topological, and electride datasets (`materials-cloud-archive-static`) | 143,153 | 68,547 | 2,811 | record-specific open licences, predominantly CC BY 4.0 |
| CSLLM non-synthesizable screening set (`csllm-negatives`) | 98,303 | 94,797 | 0 | CC BY 4.0 |
| MOFX-DB adsorption structures and isotherms (`mofx-db`) | 87,845 | 10,665 | 10,377 | MOFX-DB dataset terms |
| NIMS MDR harmonic phonon calculation database (`phonondb`) | 86,616 | 15,245 | 1,700 | CC BY 4.0 |
| Materials Cloud MC3D (`mc3d`) | 70,508 | 68,487 | 6,733 | Materials Cloud record licence |
| NovoMag magnetic materials database (`novomag`) | 38,884 | 5,309 | 1,573 | CC BY 4.0 |
| 3DSC superconductors with crystal structures (`3dsc`) | 36,531 | 3,123 | 0 | 3DSC repository licence and upstream MP/ICSD terms |
| 2DMatPedia (`2dmatpedia`) | 30,583 | 6,491 | 4,275 | 2DMatPedia terms |
| High-Throughput Screening Platform for Solid Electrolytes (`spse`) | 29,953 | 3,599 | 0 | CC BY 4.0 record; underlying ICSD-derived structures retain ICSD terms |
| NIST JARVIS specialized crystal endpoint and property datasets (`jarvis-specialized-structures`) | 26,154 | 3,443 | 574 | NIST/JARVIS dataset terms |
| American Mineralogist Crystal Structure Database (`amcsd`) | 24,639 | 7,790 | 1,203 | AMCSD terms |
| Predicted Crystallography Open Database (`pcod`) | 24,416 | 12,418 | 12,418 | public domain |
| Computational 2D Materials Database (`c2db`) | 14,120 | 3,493 | 2,253 | CC BY-SA 4.0 |
| Materials Cloud MC2D (`mc2d`) | 13,202 | 3,164 | 1,873 | Materials Cloud record licence |
| Organic Materials Database (OMDB, omdb.mathub.io) (`omdb-organic`) | 12,013 | 11,975 | 11,888 | OMDB terms |
| Samara Carbon Allotrope Database (`sacada`) | 10,349 | 1,532 | 1,508 | SACADA site terms and source-publication provenance |
| 2DHub van der Waals Bilayer Database (`bidb`) | 9,405 | 1,023 | 17 | 2DHub dataset terms |
| SuperBand electronic-band and Fermi-surface database of superconductors (`superband`) | 8,985 | 3,147 | 7 | CC BY 4.0 data; MIT software |
| EC-MOF Phase-I electrically conductive MOFs (`ec-mof`) | 7,848 | 1,067 | 1,067 | EC-MOF site terms and source-publication provenance |
| AFLOW Encyclopedia of Crystallographic Prototypes (`aflow-prototypes`) | 6,251 | 1,788 | 0 | Apache-2.0 |
| Webmineral mineralogy database (`webmineral`) | 4,698 | 1,320 | 0 | Webmineral site and cited-source terms |
| OpenMX AB2 two-dimensional structure map (`openmx-2d-ab2`) | 4,305 | 2,151 | 1,797 | OpenMX database and source-publication terms |
| HEX high-pressure elemental crystal structures (`hex-high-pressure`) | 1,456 | 241 | 37 | CC0 |
| RRUFF mineral chemistry, diffraction, Raman, and infrared database (`rruff`) | 1,302 | 829 | 123 | RRUFF terms and source-citation provenance |
| Open-framework aluminophosphate structure database (`open-framework-aluminophosphate`) | 925 | 186 | 139 | CC BY 4.0 |
| Curated COF structures (`curated-cof`) | 684 | 757 | 757 | repository licence |
| Anyterial Altermagnets Database (`amdb`) | 622 | 103 | 0 | AMDB terms and source-publication provenance |
| IZA Database of Zeolite Structures (`iza-zeolite`) | 529 | 213 | 24 | IZA Structure Commission terms |
| Hard-coating Alloys Database (`hadb`) | 492 | 123 | 105 | HADB terms and source-publication provenance |
| Theoretical Crystallography Open Database (`tcod`) | 357 | 2,803 | 2,227 | CC0 |
| OBELiX solid-state electrolyte structures and ionic conductivity (`obelix`) | 112 | 60 | 0 | CC BY 4.0 |

Totals: **121,620,776** property rows over **166** distinct properties, **12,812,918**
materials carrying at least one cross-database property; pool now 357,127 experimental +
13,186,150 candidate structures (13,543,277 total), 1,190,447 of them contributed by two or
more sources.

The "New structures" column counts `match_via = 'origin'` refs. For `icsd` that is
provenance rather than admission: the source is `properties_only`, its
`new_structs.jsonl.gz` is empty, and all 73,823 refs point at experimental-pool materials
that predate this pipeline. No FIZ Karlsruhe structure is admitted or published.

Non-scalar store: **1,198,897** curves — 586,626 X-ray absorption spectra (Materials
Project), 231,162 band-structure plots (122,526 Materials Project, 108,636 Materiae),
164,381 electronic DOS (102,049 Materials Project, 59,162 Materiae, 3,170 SuperBand),
150,460 powder-XRD peak sets (136,008 simulated, shipped with the Deem archives; 13,512
calculated, AMCSD; 940 measured, RRUFF), 46,421 phonon DOS (28,214 phonix, 13,545 PhononDB,
4,662 Materials Project), 7,836 spectral and 7,836 cumulative thermal-conductivity curves
(phonix), 2,084 Raman and 167 infrared spectra (RRUFF), 1,924 optical-absorption curves
(Materials Project) — plus on-demand simulated XRD for every structure via
`/api/materials/{id}/xrd`.

Pool-wide backfill results: space groups **13,542,712 / 13,543,277** materials (99.996%,
parsed from the BAWL fingerprint token), formation energy 9,531,809, energy above hull
7,307,427, band gap 8,566,028, magnetism 8,046,563, elasticity 59,155.
