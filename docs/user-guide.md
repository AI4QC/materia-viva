# Using MateriaViva

**English** · [简体中文](user-guide.zh-CN.md)

Updated: 2026-08-24

This is a guide to the web interface: how to find a structure, and how to read what comes back. For
installing or serving it see [`../README.md`](../README.md); for how the data was assembled see
[`dataset-acquisition.md`](dataset-acquisition.md) and
[`property-integration.md`](property-integration.md).

> Screenshots are not in this guide yet. The interface is being reworked visually, and a screenshot
> taken now would be wrong by the time you read it.

## What one record is

Every row in MateriaViva is **one unique periodic crystal structure**, not one database entry. The
same structure described by eleven different databases is one record here, carrying all eleven
descriptions. That is the whole point of the project, and it is also the thing most likely to
surprise you the first time — see [Why one property has many values](#why-one-property-has-many-values).

Records are labelled **experimental** or **candidate** and the two are never mixed silently:

| Label | What it means |
|---|---|
| Experimental | the structure has been measured — it appears in a crystallographic database of real samples |
| Candidate | the structure is computational; it has been predicted or relaxed, and may or may not be synthesisable |

## Finding a structure

### The periodic table

Each element cycles through three states as you click it:

1. **neutral** — no constraint
2. **include** (green) — must be present
3. **exclude** (red) — must be absent

Below the table, three buttons decide how the included elements are read:

| Mode | Meaning | Example: Li, Fe, O selected |
|---|---|---|
| **Contains all** | every selected element must be present; others may be too | matches `LiFePO4`, and also `Li2FeO3S` |
| **Contains any** | at least one must be present | matches `Fe2O3`, `Li2O`, `LiFePO4` |
| **Exact system** | the structure contains these elements and nothing else | matches `LiFeO2`, not `LiFePO4` — P is not in the set |

"Contains all" is the default and is usually what you want. Reach for **Exact system** when you are
studying a specific chemical system and binaries of it are noise.

### The formula box

`Formula, chemical system or material ID` accepts all three:

- a formula — `LiFePO4`
- a chemical system — `Fe-O`
- a MateriaViva material ID — `exp-train-10343`

It works alongside the periodic table rather than replacing it.

Formulas are held with every count spelled out — cadmium sulfide is stored as `Cd1S1` — but you can
type it either way and both find it. Counts other than 1 are part of the identity: `Ag2I2` is a cell
of two formula units and is a **different record** from `AgI`, so searching one does not return the
other.

### Advanced filters

Numeric filters are ranges; leave either end blank for open-ended. The ones worth explaining:

| Filter | What to know |
|---|---|
| **PBEsol band gap** | a **calculated** gap from the PBEsol functional, in eV. DFT band gaps are systematically underestimated: a gap of 0 here does not prove the material is a metal, and a small gap may be a wider one in reality. Use **Metallicity** if that is the question you are asking. |
| **Energy above hull** | 0 eV/atom means on the convex hull — thermodynamically stable against decomposition at 0 K. Larger means metastable or unstable. |
| **Formation energy / atom** | negative means favourable to form from the elements. It is not the same question as energy above hull. |
| **Space group number** | comma-separated, e.g. `62, 225`. |
| **Property availability** | tick-boxes over band gap, density, space group, formation energy, energy above hull, magnetism and elasticity. These filter on whether the property was **recorded at all**, not on its value — "show me things that have elastic data" rather than "show me stiff things". |
| **Data source** | Experimental only / Candidates only. Leave both off to see everything. |

Filters combine with AND. If a search returns nothing, the usual cause is one numeric range that is
narrower than you meant, or too many included elements.

**A numeric range also excludes records that have no value for it.** Four structures in the
development slice carry no density, so any density range — even one wide enough to admit everything
— returns 996 rather than 1000. A range cannot be satisfied by an unknown, so asking for one is also
asking for the property to be present.

## Reading a material

### Basic properties

The top block is a **representative** value per property — one number chosen so the page has
something to show. Where the sources disagree, this is one of their answers, not a consensus or an
average. The full picture is below it.

### Why one property has many values

**Cross-database properties** lists every value every source database recorded, and it does not
reconcile them. For silicon carbide (`exp-train-10343`), the page carries **21 density values**:

| Value | Source |
|---|---|
| 3.17137 g/cm³ | aflow |
| 3.24 g/cm³ | amcsd |
| 3.218 g/cm³ | amcsd |
| … | … |

This is not a bug, and the design is deliberate: **a value keeps the units, the method and the
provenance it arrived with, and nothing is silently averaged into a single number.** Two values can
differ because they were computed with different functionals, measured at different temperatures, or
measured on different samples — and one source can legitimately report several, because it holds
several records for the same structure.

Every row carries its **Method** and **Source**, so you can decide which one answers *your* question.
If you need a single number, choose it on the method — do not assume the top one is best.

#### What the ×N badge means

A source can also hold **several records for one crystal** — AFLOW keeps a dozen calculation entries
for some structures — and fingerprint deduplication matches them all to one MateriaViva material.
When those records agree exactly, printing each one gives you the same line over and over, which
reads as a bug rather than as data.

Rows that match on **property, value, unit, method and source** are therefore shown once with a
`×N` badge; hover it for the upstream ids it stands for. Anything that differs is never folded:
cadmium sulfide shows `band gap 1.1886 eV ×3` and `band gap 1.1883 eV ×3` as two separate rows,
three thousandths of an eV apart.

### Where the structure came from

**Source databases** lists the contributing databases and how each was matched to this record:

| Marker | What it means |
|---|---|
| **fingerprint match** | the structure was matched by its structural fingerprint — the databases describe the same crystal without sharing an identifier |
| **ID match** | matched through an identifier the source itself cites, e.g. an ICSD number |
| **contributed structure** | this source is where the structure entered MateriaViva |

Silicon carbide has 11 contributing databases: 24 refs matched by fingerprint, 8 by ICSD id, and 1
that contributed the structure. Each carries its own licence, shown next to it.

**Download CIF** gives the unified structure record.

## The two 3D views

The viewer has two tabs, and they are different engines with different strengths:

| | OVITO render | Interactive 3D |
|---|---|---|
| What it is | ray-traced still image, produced on the server | live WebGL scene in your browser |
| Best for | figures, publication-quality stills | inspecting, rotating, looking inside |
| Needs | an OVITO installation on the server | WebGL in your browser |

If the **OVITO render** tab is greyed out, the server it is talking to has no OVITO renderer
configured; Interactive 3D works regardless and opens by default in that case.

Controls under the viewer:

- **View** — `I` isometric, `F` front, `T` top. Camera presets; both engines honour them.
- **Model** — ball-and-stick, or space-filling.
- **Cell** — how many unit cells to repeat, and whether to draw cell edges.
- **Quality** — preview or high. Ray-tracing quality, so it appears on the OVITO tab only; the
  live view has no equivalent setting.

In Interactive 3D you can drag to rotate, scroll to zoom, and right-drag to pan.

## What you will not find

Some databases MateriaViva catalogues cannot be redistributed. For those, the record carries the
source's name, link, licence and identifier, but not its data — a licence that was not confirmed
means the data stays unpublished. [`dataset-acquisition.md`](dataset-acquisition.md) records the
position for each source.
