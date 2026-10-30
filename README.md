<p align="center">
  <img src="frontend/public/logo.svg" alt="MateriaViva" width="760">
</p>

# MateriaViva

**English** · [简体中文](README.zh-CN.md)

[![CI](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml/badge.svg)](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml)
[![Open dataset](https://img.shields.io/badge/Hugging%20Face-MateriaViva--Open-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AI4QC/MateriaViva-Open)

MateriaViva brings crystal structures and properties from multiple materials databases into a unified, searchable resource. It links records across sources while retaining their identifiers, property values, methods and provenance.

The same crystal may appear in several databases under different identifiers and with different properties. MateriaViva connects these records so researchers can search a chemical space, inspect structures and compare the available evidence in one place.

## Introduction and walkthrough videos

Explore MateriaViva from searching and filtering materials to inspecting structures with OVITO, comparing properties and spectra, tracing sources, downloading CIF files and using the personal workspace.

[![Preview of the English MateriaViva introduction and walkthrough](demo/MateriaViva_demo_preview.gif)](https://github.com/AI4QC/materia-viva/releases/download/tutorials-2026.10.30/MateriaViva-EN.mp4)

The GIF above is a short preview from the English edition. Click it to open the full video, or choose a language below.

| Edition | Narration and captions | Duration | Full video |
|---|---|---|---|
| English | English narration and English captions | 9:11 | [Watch / download MP4](https://github.com/AI4QC/materia-viva/releases/download/tutorials-2026.10.30/MateriaViva-EN.mp4) |
| 简体中文 | Chinese narration and Chinese captions | 9:06 | [观看／下载 MP4](https://github.com/AI4QC/materia-viva/releases/download/tutorials-2026.10.30/MateriaViva-ZH.mp4) |

Both videos are 1080p at 30 fps and cover 25 scenes, with real OVITO crystal animations, chapter transitions and close-ups of key controls. They use the original web interface and public catalog in a local demonstration environment with OVITO/Tachyon enabled; availability on the live site may differ.

[Subtitles, chapter lists and checksums](https://github.com/AI4QC/materia-viva/releases/tag/tutorials-2026.10.30) · [Video details](demo/README.md)

## What MateriaViva offers

- **Integrated records.** Structure records are matched across databases using identifiers and structural fingerprints; properties retain their source, native identifier and calculation or measurement method.
- **Experimental and candidate structures.** The interface labels the two categories separately and supports filtering by composition, structure and properties.
- **Structure and property inspection.** Browse structures in interactive 3D, compare values from different sources and inspect available curves and spectra.
- **Data for reuse.** Download the public structures, properties, curves and predictions as Parquet files, with source and licence information.

## Data coverage

The figures below describe the project's recorded snapshot. The full pool and public release are different datasets; numbers can change in later releases. The [public data card](https://huggingface.co/datasets/AI4QC/MateriaViva-Open) describes the open release.

| | Full pool | Public release |
|---|---:|---:|
| Structures | 14,590,485 | 10,903,588 |
| Property values | 131,824,881 | 113,459,302 |
| Curves | 1,198,897 | 850,417 |

The full pool integrates **55 source databases**. These include general materials datasets such as Materials Project, Alexandria, NOMAD and OQMD; experimental catalogues such as COD; and specialised collections such as QMOF, hMOF and Deem zeolites. See the [source catalogue](scripts/datasets/sources.json) and [property integration notes](docs/property-integration.md).

The public release also contains predictions for 95 property tasks in this snapshot. **Predictions are model outputs, not measurements**; consult each task's metadata for the applicability domain and reported evaluation. See the [public dataset card](https://huggingface.co/datasets/AI4QC/MateriaViva-Open) for coverage and caveats.

## Data access and licences

| Dataset | Access | Contents |
|---|---|---|
| [MateriaViva-Open](https://huggingface.co/datasets/AI4QC/MateriaViva-Open) | Public | Structures, properties, curves and predictions in Parquet |
| [MateriaViva](https://huggingface.co/datasets/AI4QC/MateriaViva) | Private; access required | Full runtime index and a development slice |

A structure is included in the public release when an open-licence database holds it. **Property values and curves keep their own source licences**, which can differ from the structure licence. Check `licence` and `licence_class` before reuse. For some records, the stored CIF was supplied by a non-open source even though an open database holds the same structure; use `origin_open` when the origin of the coordinates matters. The [dataset card](https://huggingface.co/datasets/AI4QC/MateriaViva-Open) describes these fields and their limitations.

The full index contains restricted data, including ICSD records, and requires the appropriate access and licences. See the [data acquisition notes](docs/dataset-acquisition.md) and [source licence assessment](DATA_LICENCES_2026-10-19.zh-CN.md).

### Download public data

The public release can be downloaded without access to the private runtime index:

```bash
python -m pip install huggingface_hub
hf download AI4QC/MateriaViva-Open --repo-type dataset --local-dir data/open
```

To download only selected files, pass `--include`, for example `--include "properties/bulk_modulus_vrh.parquet"`. Public data is in Parquet format; it is not the runtime index used by the web application.

## Run the web application

Requires Python 3.10+, Node.js 20+ and pnpm. The example uses the development slice of the **private** dataset, so your Hugging Face account needs access.

```bash
git clone https://github.com/AI4QC/materia-viva.git
cd materia-viva
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt

pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build

hf auth login
python scripts/fetch_index.py slice
python scripts/serve.py --runtime data/slice
```

Open <http://127.0.0.1:8000>; API documentation is at <http://127.0.0.1:8000/api/docs>. To use the full index, run `python scripts/fetch_index.py full` and serve `data/index` instead. Both downloads require access to the private dataset.

Interactive 3D works in the browser. Server-side OVITO rendering is optional and can be configured with `MATERIALS_OVITO_PYTHON` pointing to an OVITO-enabled interpreter.

## Documentation and development

- [User guide](docs/user-guide.md) · [Data format](docs/data-format.md) · [Property integration](docs/property-integration.md)
- [Data sources and acquisition](docs/dataset-acquisition.md) · [Source licence assessment](DATA_LICENCES_2026-10-19.zh-CN.md)
- [Contributing](CONTRIBUTING.md) · [Citation](CITATION.cff)

The repository contains the FastAPI backend in `backend/`, the React frontend in `frontend/`, data-processing scripts in `scripts/`, and schemas and documentation in `schemas/` and `docs/`. The data files and runtime index are kept outside Git.

## Licence

MateriaViva code is released under [CC BY-NC 4.0](LICENSE). Data from external sources remains subject to its original licence and citation requirements.
