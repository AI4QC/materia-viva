# Storage layout

**English** · [简体中文](storage-layout.zh-CN.md)

The Git repository and large data are intentionally separated. The paths below are the reference
deployment; any volume works, and `MV_DATA_ROOT` is how a different one is named (see the README).
Record counts are deliberately absent — [`README.md`](../README.md) explains why every figure this
project hardcoded went stale, and `GET /api/stats` on a running instance answers instead.

```text
/home/zhilong/workspace/materia-viva/             Git working tree
└── data -> /home/zhilong/SSD/workspace_data/materia-viva/data

/home/zhilong/SSD/workspace_data/materia-viva/data/
├── sources/
│   ├── experimental/                        measured structures, one export per dataset
│   └── candidate/                           computed structures, one export per dataset
├── index/                                   SQLite + compressed CIF blob
├── manifests/                               Crystal Record v1 reports
└── raw/                                     rebuild and provenance inputs
    └── legacy-material-data -> /home/zhilong/SSD/material_data
```

Compatibility links keep earlier workflows operational:

| Legacy path | Target |
|---|---|
| `CSAgent/materials_web` | the MateriaViva repository |
| `CSAgent/data/synthesizable_structs` | `data/sources/experimental` |
| `matgenbench/data/unique_structs_lemat_merged` | `data/sources/candidate` |
| `CSAgent/data/external_structs` | `data/raw/external_structs` |
| `CSAgent/data/icsd_extracted` | `data/raw/icsd_extracted` |
| `CSAgent/data/ICSD_data.zip` | `data/raw/ICSD_data.zip` |
| `data/raw/legacy-material-data` | `/home/zhilong/SSD/material_data` (245 GiB of existing data, linked rather than copied) |

Do not replace the repository `data` link with a normal directory: the system NVMe
has substantially less free space than the secondary SSD. Git ignores both `data`
and the compatibility `runtime -> data/index` link.
The legacy inventory and semantic deduplication rules are documented in
[`legacy-ssd-data-inventory.md`](legacy-ssd-data-inventory.md).
