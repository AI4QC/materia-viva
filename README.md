<p align="center">
  <img src="frontend/public/logo.svg" alt="Materia Viva" width="760">
</p>

# MateriaViva

**English** · [简体中文](README.zh-CN.md)

[![CI](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml/badge.svg)](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml)
[![Dataset](https://img.shields.io/badge/Hugging%20Face-AI4QC%2Fmateria-viva-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AI4QC/materia-viva)

> **Materials discovery should not begin with calling one database API after another and juggling
> a separate account for each.** MateriaViva delivers a unified, deduplicated, licence-reviewed
> snapshot behind a single Hugging Face download.
>
> **MateriaViva is also not meant to stay a one-off collection.** The next stage builds an
> auditable self-evolving loop that keeps discovering new databases and new versions of existing
> ones, then runs admission checks, field mapping and structural deduplication. Automatic
> discovery and integration are still under development and not yet live.

## About MateriaViva

### The problem: there is plenty of materials data, and materials are still hard to find

Crystal structures are not scarce. What is missing is a materials space you can search, compare
and trace back to its source directly.

The same crystal often appears in several databases under different IDs, fields, units and file
formats. Researchers end up requesting accounts one by one, calling bulk APIs, downloading
archives, cleaning data, and then working out which records are merely duplicate structures,
intermediate relaxation frames or molecular-dynamics trajectories. Even after all that, property
fields may be disconnected from the structures, and licence boundaries still have to be checked
again.

The result: the data already exists, but a large share of the time goes into acquiring and
tidying it before any candidate screening begins.

### How we address it

MateriaViva first replaces scattered bulk APIs and per-source account logins with a versioned
Hugging Face snapshot, then organises crystal data into one searchable, traceable entry point.
Researchers start from the periodic table to pick a chemical space, narrow results with
Materials Project style property conditions, and finally inspect structures in the browser in 3D
or through OVITO/Tachyon.

| The old obstacle | How MateriaViva handles it |
|---|---|
| Every database has its own API, account and download flow | Redistributable data is published as one versioned Hugging Face snapshot |
| CIF, JSON, SQL, LMDB and property tables cannot be mixed directly | Structures enter a unified schema; source properties keep their original values, units and provenance |
| The same structure repeats across databases, and trajectory frames inflate material counts | Only unique periodic structure endpoints are accepted, deduplicated by structural fingerprint |
| Experimental structures and computational candidates get mixed together | The two record classes stay separately labelled, filtered and counted |
| The boundary between commercial and open data is unclear | Licence review precedes publication; restricted data never enters the public package |
| After downloading, there is still no convenient way to inspect anything | Periodic-table search, combined filters, interactive 3D and high-quality offline rendering in one interface |

The unified index currently contains:

| Experimental structures | Computational candidates | Unified search records |
|---:|---:|---:|
| 99,162 | 8,125,976 | 8,225,138 |

### Integrated databases

The unified structure pool is assembled from the databases below, all merged after structural
fingerprint (BAWL / entalpic fingerprint) deduplication:

| Database | Notes |
|---|---|
| [LeMat-BulkUnique](https://huggingface.co/datasets/LeMaterial/LeMat-BulkUnique) | 4,273,800 records, each keeping its `immutable_id` and fingerprint |
| [ELEMENTA / ELEMENTA Spin](https://huggingface.co/datasets/kairosmaterial/ELEMENTA) | 2,005,836 records, taking only the final relaxed structure of each optimization trajectory |
| [Materials Project](https://next-gen.materialsproject.org/) | PBE/PBEsol computed structures and properties |
| [OQMD](https://oqmd.org/) | Open Quantum Materials Database |
| [JARVIS-DFT](https://jarvis.nist.gov/) | NIST JARVIS computed structures and descriptors |
| [AFLOW](https://aflow.org/) | High-throughput automatic framework structures |
| [Alexandria](https://alexandria.icams.rub.de/) | PBE / PBEsol 3D, 2D and 1D structures |
| [NOMAD](https://nomad-lab.eu/) | Computed structures from the federated archive |
| [OMat24](https://huggingface.co/datasets/facebook/OMAT24) | Unique structure endpoints extracted from it; intermediate trajectory frames are not ingested |
| Carolina Materials Database | 214,435 existing structures |
| [COD](https://www.crystallography.net/cod/) | Crystallography Open Database, CC0 |
| [ICSD](https://icsd.products.fiz-karlsruhe.de/) | Requires a FIZ Karlsruhe licence; restricted fields never enter the public snapshot |

Deduplication and source-priority rules are in section 7 of
[`docs/dataset-acquisition.md`](docs/dataset-acquisition.md). Licence-restricted sources such as
ICSD follow the copyright and redistribution boundary below: usable locally for unified search,
while protected original files and fields are not published with the snapshot.

[![Play the MateriaViva 2K60 demo video](demo/MateriaViva_demo_preview.gif)](demo/MateriaViva_demo_2K60.mp4)

<p align="center"><a href="demo/MateriaViva_demo_2K60.mp4">Play the full 2560×1440 · 60 FPS demo video</a></p>

## MateriaViva is more than putting files side by side

- Experimentally synthesizable structures and computational candidates carry separate labels, so
  candidate counts never stand in for experimental coverage.
- Only static periodic structure endpoints enter the structure pool. Relaxation, rattled,
  molecular-dynamics and reaction-path intermediate frames do not count as new materials.
- Deduplication does not mean discarding data. After structures are merged, every source keeps
  its original ID, version, properties, units, licence and provenance.
- Raw archives exist for auditing and rebuilding; the site only reads the validated unified index
  rather than mixing source files directly.
- Data without explicit open redistribution permission never appears in the public Hugging Face
  release.

## A self-evolving materials integration database

The long-term goal is not to maintain a one-off static collection, but to keep discovering new
materials databases and new versions of existing sources, then publish a new unified snapshot
after licence judgement, format mapping, structural deduplication and quality checks.

> [!IMPORTANT]
> Automatic discovery and integration are not implemented yet. All 101 current sources are still
> found and reviewed manually, then ingested by resumable acquisition scripts. This README keeps
> planned capabilities separate from what is implemented today.

The intended loop is:

```text
discover a new source or version
        ↓
check licence, access mode, static structure scope and trajectory contamination
        ↓
generate or recommend an acquisition and field-mapping adapter
        ↓
unify format, units and provenance
        ↓
deduplicate by structural fingerprint and merge cross-database properties
        ↓
integrity and outlier checks + human approval
        ↓
publish a new Hugging Face snapshot and change report
```

Failure records and manual corrections feed the next round of source identification, field
mapping and deduplication strategy. The process never bypasses accounts, paid licences or
redistribution limits; data whose authorization cannot be confirmed stays unpublished by default.

## One download instead of scraping a hundred databases

At the publication layer, MateriaViva removes the pattern where every user separately calls
traditional bulk APIs or logs into source accounts. All data that clearly permits open
redistribution and passes review is organised into a snapshot with versions, hashes, a source
manifest and a licence manifest, published directly at:

### [Hugging Face Dataset · AI4QC/materia-viva](https://huggingface.co/datasets/AI4QC/materia-viva)

The GitHub repository holds only code, data schemas, the source catalog, documentation, tests and
demo assets. It contains no database files, unified index, render cache or partial downloads.

### Copyright and redistribution boundary

MateriaViva is released under [CC BY-NC 4.0](LICENSE) and permits non-commercial use only.

- Data that clearly permits redistribution — CC0, CC BY, CC BY-SA, CC BY-NC — may enter the public
  snapshot while keeping its original authors, versions, licences and citation requirements.
- Commercial licences, paid subscriptions, institutional licences, account-term restrictions and
  databases without explicit redistribution permission are not open-sourced.
- For restricted sources only the database name, official link, public metadata, source ID and
  licence status are published, never the protected structures, property fields or raw files.
- A unified format does not change who owns the rights to the original data. Any future automatic
  discovery flow must clear the same licence gate first.
- The snapshot includes CC BY-NC 4.0 sources such as ELEMENTA, so the integrated result must not
  be used commercially. ShareAlike sources require a separate compatibility check against the NC
  terms before they can enter the public snapshot.

## Current coverage

The machine-readable catalog currently registers 101 crystal structure or property sources.
"Registered" is not the same as "publicly downloaded":

- 58 are acquired or reuse data already present on this machine;
- 18 are registered only, or still waiting for a suitable official bulk acquisition route;
- 22 need an account, provider authorization or a paid licence, and keep catalog information only;
- 3 trajectory sources are excluded by project scope;
- there are no unfinished background downloads.

ELEMENTA is a trajectory dataset, but it is ingested under the "one endpoint per relaxation" rule,
so intermediate frames never enter the structure pool.

Full sources, licences, download status and required manual steps are in
[`docs/dataset-acquisition.md`](docs/dataset-acquisition.md). Existing SSD data and its duplicate
relationships are in [`docs/legacy-ssd-data-inventory.md`](docs/legacy-ssd-data-inventory.md).

## Getting the code and data

```bash
git clone https://github.com/AI4QC/materia-viva.git
cd materia-viva

# after downloading the data from Hugging Face, link the local data root into the repository
export MV_DATA_ROOT=/path/on/ssd/materia-viva-data
ln -s "$MV_DATA_ROOT" data
```

Neither `data` nor its compatibility entry `runtime` is under Git. Raw archives, the SQLite/blob
index, `.part` files, receipts, render caches and local keys stay out of commits too. The expected
layout is:

```text
data/
├── sources/
│   ├── experimental/        99,162 experimental structures
│   └── candidate/           8,125,976 candidate structures
├── index/                   SQLite search database and compressed CIF blob
├── manifests/               Crystal Record v1 validation reports
└── raw/                     source archives and provenance
```

Local SSD migration and legacy path compatibility are described in
[`docs/storage-layout.md`](docs/storage-layout.md).

## Unified data format

Structure master records entering MateriaViva use `Crystal Record v1`:

```text
index,material_id,cif,pbes_gap
```

A streaming validator checks field order, data types, non-empty constraints and split counts.
Source-specific properties are kept as sidecars, then mapped into unified SQLite property columns
or JSON extension fields. Original values, units and sources are never overwritten.

- Format description: [`docs/data-format.md`](docs/data-format.md)
- JSON Schema: [`schemas/crystal-record-v1.schema.json`](schemas/crystal-record-v1.schema.json)
- Serving index: `data/index/materials.sqlite` + `data/index/structures.blob`

SQLite stores search fields and compressed block offsets; the blob stores zlib-compressed CIFs in
order. The indexer streams the source CSVs and never needs to load everything at once.

## Install and run

Requires Python 3.10+ and Node.js 20+:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

cd frontend
npm ci
cd ..
```

OVITO is best kept in its own Python environment:

```bash
export MATERIALS_OVITO_PYTHON=/path/to/ovito-enabled/python
```

Without OVITO configured, interactive 3D still works in the browser, but server-side Tachyon image
rendering is unavailable.

Validate all 8,225,138 published records and build the index:

```bash
make validate-data
python scripts/build_index.py
```

A small sample can be built during development. Only skip the source scan when the source data has
already passed full validation separately:

```bash
python scripts/build_index.py \
  --limit-per-dataset 1000 \
  --skip-source-validation \
  --output /tmp/cmu-sample-index
```

Start the site once the build finishes:

```bash
make build

MATERIALS_OVITO_PYTHON=/path/to/ovito-enabled/python \
  python scripts/serve.py --host 0.0.0.0 --port 8000
```

- Site: `http://127.0.0.1:8000`
- API docs: `http://127.0.0.1:8000/api/docs`
- Health check: `http://127.0.0.1:8000/api/health`

The index is written to `.building` temporary files first and swapped atomically on completion, so
an interruption never damages the index currently being served.

## Interface language

The site renders in English by default and switches to Chinese from the header control next to the
theme toggle. The choice is stored in `localStorage` under `mv-lang` and reflected on the document
`lang` attribute. All copy lives in `frontend/src/i18n`, where the English and Chinese dictionaries
share one `TranslationKey` union, so a missing translation is a type error rather than a silent
fallback.

## Testing

```bash
make test
make build
```

Run individually:

```bash
PYTHONPATH=backend:. python -m pytest backend/tests -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

With a real index and OVITO connected, browser acceptance can be run:

```bash
python scripts/browser_smoke.py
```

## Repository layout

```text
materia-viva/
├── backend/                 FastAPI, SQLite queries, structure parsing and OVITO rendering
├── frontend/                React, TypeScript, Vite and the interactive crystal workbench
├── scripts/                 validation, indexing, acquisition, serving and demo recording tools
├── schemas/                 Crystal Record v1 JSON Schema
├── docs/                    data, migration, acquisition and design documentation
├── demo/                    2K60 demo video, animated preview and cover
└── data/                    local data link, not under Git
```

## Demo video

- [Animated preview](demo/MateriaViva_demo_preview.gif): 800×450, click to play the full video.
- [2K60 MP4](demo/MateriaViva_demo_2K60.mp4): 2560×1440, 60 FPS, H.264 High.
- [2K cover](demo/MateriaViva_demo_2K60_cover.png).
- `demo/MateriaViva_demo_2K_source.webm`: the raw browser screen recording.

To re-record and transcode:

```bash
python scripts/record_demo.py
ffmpeg -y -i demo/MateriaViva_demo_2K_source.webm \
  -vf "minterpolate=fps=60:mi_mode=blend" \
  -c:v libx264 -profile:v high -level:v 5.1 -preset slow -crf 13 \
  -pix_fmt yuv420p -movflags +faststart -an \
  demo/MateriaViva_demo_2K60.mp4

# generate the animated preview for the GitHub README
ffmpeg -y -ss 1 -i demo/MateriaViva_demo_2K60.mp4 \
  -filter_complex "fps=5,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=72:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
  -loop 0 demo/MateriaViva_demo_preview.gif
```

## Licence, contributing and citation

MateriaViva is released under [CC BY-NC 4.0](LICENSE) and permits non-commercial use only.
External databases keep their own licences and citation requirements. Do not redistribute raw
fields from restricted sources such as ICSD or CSD just because a structure has been normalised or
matches an open source.

- Development and source submissions: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- Citing the project: [`CITATION.cff`](CITATION.cff)
