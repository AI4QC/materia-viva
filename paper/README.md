# Manuscript: a self-evolving materials database

Draft of the MateriaViva integration paper. Three main figures are complete;
Section 2.8 and Figure 4 are reserved for the GNN property-completion stage and
are marked in the PDF with a visible orange placeholder block rather than left
silently empty.

## Layout

```
paper/
  tex/
    main.tex          front_meta (title + abstract), front_body (introduction),
                      body (results + figures), discussion, methods, refs.bib
    si.tex            si_body (Notes S1-S8) + si_tables (Tables S1-S4, generated)
    build.sh          SI first, export its labels, then two main-text passes
  data/               every CSV a figure or a sentence in the text reads
  figure_scripts/     extraction from the database, then the figures and SI tables
  figs/               fig1_architecture, fig2_redundancy, fig3_landscape,
                      fig4_completion
```

Results is four sections: what the corpus contains and how it recognises its own
additions; how much is duplicated and whether the duplicates agree; what is
missing and why; and what can be learned from it. The fourth is the one still in
progress -- the census, the training sets and the applicability domains are done
and reported; the trained models are not, and their absence is marked by a
visible `\PENDINGGNN` block that becomes the closing passage of that section.

The main text is a research paper: the object of study is the public
materials-data corpus and the unification pipeline is the instrument. Everything
a reader might want in order to reproduce or dispute the instrument lives in the
SI, which is cross-referenced from the main text through `gen-si-xr.py` (it reads
`si.aux` and writes `si-xr.tex`, because Tectonic cannot resolve `\externaldocument`
across separate compilations). Run `build.sh`, never `tectonic main.tex` alone,
or the Supplementary references will not resolve.

## Reproducing every number

No figure and no number in the text was transcribed by hand. The chain is:

```
data/index/materials.sqlite            (the published database, read-only)
        |
        |  python paper/figure_scripts/generate_all.py --extract
        v
paper/data/*.csv                       (the source data for the paper)
        |
        |  python paper/figure_scripts/generate_all.py
        v
paper/figs/*.pdf                       (the figures)
```

| Script | Produces | Cost |
|---|---|---|
| `extract_stats.py` | `sources.csv`, `properties.csv`, `property_source_matrix.csv`, `source_degree.csv`, `source_overlap.csv`, `curves.csv`, `pool_*.csv`, `summary.json` | one grouped scan, ~9 min |
| `extract_evolution.py` | `evolution_sources.csv`, `evolution.json` | ~1 min |
| `extract_substrate.py` | `substrate_growth.csv`, `substrate_growth.json` | ~1 min |
| `extract_substrate_growth.py` | `substrate_curve.csv`, `substrate_curve.json` | ~1 min; attributes every admitted structure to the source that admitted it |
| `extract_agreement.py` | `material_property_count.csv`, `agreement_*.csv`, `completeness.json` | one full table scan, ~30 min |
| `cost_tiers.py` | `cost_tiers.csv`, `cost_tiers.json` | instant, reads `properties.csv` |
| `extract_crossfill.py` | `crossfill.json`, `crossfill_sources.csv`, `crossfill_properties.csv` | one full table scan, ~10 min; what each structure gained from databases other than its own contributor |
| `extract_cell_sources.py` | `cell_sources.json`, `cell_sources.csv` | one full table scan plus a sort, ~5 min; how many databases stand behind each filled cell |
| `extract_gnn_census.py` | `gnn_tasks.csv`, `gnn_theory_levels.csv`, `gnn_prediction_sets.csv`, `gnn_census.json` | instant, reads `data/ml/census` and `data/ml/predict` |
| `make_si_tables.py` | `tex/si_tables.tex` (Tables S1-S4) | instant, reads `paper/data` |

Figure 4 reads the outputs of `scripts/ml/` (`property_census.py`,
`prediction_sets.py`) rather than recomputing them, so the figure and
`docs/gnn-property-census.zh-CN.md` cannot drift apart. Every tier count in the
figure reproduces that document exactly.

`curves_by_type.csv` is one SQL query (distinct materials per curve type; the
per-source counts in `curves.csv` must not be summed, because a material with a
band structure from two databases would be counted twice).

Two independent paths give the same occupancy figure: summing `n_materials` over
`properties.csv` and popcounting the per-material bitmap in `extract_agreement.py`
both give 95,128,921 filled cells.

## Building the PDF

```
cd paper/tex && ./build.sh          # or: tectonic --keep-intermediates main.tex
```

The Springer Nature class files (`sn-jnl.cls`, `sn-nature.bst`) and
`layout_tune.tex` are carried over from the group's existing manuscript setup.

## Before submission

- **Run every entry in `refs_extra.bib` through `nature-ref-verifier`.** Those 24
  entries were written from working knowledge, not copied from a verified
  record, and volume/page/year are exactly where that fails. The 31 entries in
  `refs_borrowed.bib` came from an already-verified bibliography.
- The cost-tier assignment in `cost_tiers.py` is a hand judgement and is meant to
  be disputed line by line; it is in the repository for that purpose.
- Author list and affiliations are inherited from the group template and need
  confirming.
