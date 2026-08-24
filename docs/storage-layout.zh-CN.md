# 存储布局

**简体中文** · [English](storage-layout.md)

Git 仓库与大体积数据有意分开存放。下面的路径是参考部署；换任何卷都可以，用 `MV_DATA_ROOT`
指定（见 README）。这里**故意不写记录数**——[`README.md`](../README.zh-CN.md) 说明了为什么这个项目
写死过的每个数字都过期过，运行中的实例用 `GET /api/stats` 回答。

```text
/home/zhilong/workspace/materia-viva/             Git 工作区
└── data -> /home/zhilong/SSD/workspace_data/materia-viva/data

/home/zhilong/SSD/workspace_data/materia-viva/data/
├── sources/
│   ├── experimental/                        实测结构，每个数据集一份导出
│   └── candidate/                           计算结构，每个数据集一份导出
├── index/                                   SQLite + 压缩 CIF blob
├── manifests/                               Crystal Record v1 校验报告
└── raw/                                     重建与 provenance 输入
    └── legacy-material-data -> /home/zhilong/SSD/material_data
```

兼容链接让既有流程继续可用：

| 旧路径 | 目标 |
|---|---|
| `CSAgent/materials_web` | MateriaViva 仓库 |
| `CSAgent/data/synthesizable_structs` | `data/sources/experimental` |
| `matgenbench/data/unique_structs_lemat_merged` | `data/sources/candidate` |
| `CSAgent/data/external_structs` | `data/raw/external_structs` |
| `CSAgent/data/icsd_extracted` | `data/raw/icsd_extracted` |
| `CSAgent/data/ICSD_data.zip` | `data/raw/ICSD_data.zip` |
| `data/raw/legacy-material-data` | `/home/zhilong/SSD/material_data`（245 GiB 既有数据，链接而非复制） |

不要把仓库中的 `data` 链接替换成普通目录：系统 NVMe 的可用空间远小于第二块 SSD。Git 同时
忽略 `data` 和兼容入口 `runtime -> data/index`。既有数据盘点与语义去重规则见
[`legacy-ssd-data-inventory.zh-CN.md`](legacy-ssd-data-inventory.zh-CN.md)。
