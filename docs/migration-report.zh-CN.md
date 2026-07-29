# 迁移报告 — 2026-07-26

**简体中文** · [English](migration-report.md)

## 结果

MateriaViva 应用代码从原先嵌套的 web 目录迁出，进入独立的
`/home/zhilong/workspace/materia-viva` Git 仓库。活动数据库文件移动到第二块 NVMe SSD 上的
`/home/zhilong/SSD/workspace_data/materia-viva/data`。仓库路径和旧路径都解析到这一份活动
数据树。

## 已迁移资产

| 资产 | 近似大小 | 新位置 | 完整性检查 |
|---|---:|---|---|
| 实验来源 | 283 MB | `data/sources/experimental` | 源/目标 SHA-256 加全量记录校验 |
| 候选来源 | 7.1 GB | `data/sources/candidate` | 同文件系统保留 inode 的移动，加全量记录校验 |
| 检索索引 | 5.6 GB | `data/index` | 源/目标 SHA-256 及无错的 SQLite/API 读取 |
| 外部 provenance 来源 | 30 GB | `data/raw/external_structs` | 全部 1,071 个文件的 SHA-256 |
| 解压后的 ICSD CIF | 1.1 GB，203,830 个文件 | `data/raw/icsd_extracted` | 每个文件的源/目标 SHA-256 |
| ICSD 原始归档 | 635 MB | `data/raw/ICSD_data.zip` | 源/目标 SHA-256 |

来源 CSV 校验在迁移当时给出的发布计数为：

- 实验：94,204 train + 4,958 validation = 99,162。
- 候选：5,814,133 train + 306,007 validation = 6,120,140。
- 合并可检索索引：6,219,302 条记录。

这些数字是 2026-07-26 迁移当时的状态。候选池此后接入 ELEMENTA，当前计数见
[`dataset-acquisition.zh-CN.md`](dataset-acquisition.zh-CN.md) 与 README。

## 兼容与恢复

旧的应用、来源数据集和原始数据路径在目标通过完整性检查后被替换为符号链接。跨文件系统的
源目录被移入桌面回收站，而不是不可逆删除，因此在清空回收站前仍可恢复。候选数据集是第二块
SSD 内保留 inode 的重命名，没有重复的活动副本。
