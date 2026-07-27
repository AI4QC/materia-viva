# Storage layout

The Git repository and large data are intentionally separated:

```text
/home/zhilong/workspace/materia-viva/             Git working tree
└── data -> /home/zhilong/SSD/workspace_data/materia-viva/data

/home/zhilong/SSD/workspace_data/materia-viva/data/
├── sources/
│   ├── experimental/                        99,162 records
│   └── candidate/                           6,120,140 records
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
| `data/raw/legacy-material-data` | `/home/zhilong/SSD/material_data`（245 GiB 既有数据，不复制） |

Do not replace the repository `data` link with a normal directory: the system NVMe
has substantially less free space than the secondary SSD. Git ignores both `data`
and the compatibility `runtime -> data/index` link.
The legacy inventory and semantic deduplication rules are documented in
[`legacy-ssd-data-inventory.md`](legacy-ssd-data-inventory.md).
