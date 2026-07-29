# Crystal Record v1

**简体中文** · [English](data-format.md)

Crystal Record v1 是 MateriaViva 索引唯一接受的来源格式。每个数据集提供 UTF-8 编码的
`train.csv` 和 `val.csv`，表头必须完全一致：

```text
index,material_id,cif,pbes_gap
```

| 字段 | 逻辑类型 | 必填 | 含义 |
|---|---:|---:|---|
| `index` | 非负整数 | 是 | 来源数据集内部的稳定标识 |
| `material_id` | 非空字符串 | 是 | 用于归一化化学式和元素的组成标识 |
| `cif` | 非空 UTF-8 字符串 | 是 | 完整 CIF 文档；内嵌换行由 CSV 引号包裹 |
| `pbes_gap` | 浮点数或空 | 是 | 可用时为 PBEsol 带隙，单位 eV |

机器可读的逻辑模式见
[`schemas/crystal-record-v1.schema.json`](../schemas/crystal-record-v1.schema.json)。
重建索引前先运行 `make validate-data`。校验会流式读取每条记录，检查两个 split 的表头和
取值，强制核对发布行数，并原子写入 `data/manifests/{experimental,candidate}.json`。

## 规范服务数据库

来源 CSV 会归一化为两个配套文件：

- `data/index/materials.sqlite` 保存可检索元数据、provenance、归一化化学式与化学体系、
  结构性质以及 CIF blob 偏移。
- `data/index/structures.blob` 保存 zlib 压缩的 CIF 负载，支持随机访问。

SQLite 与 blob 是一个逻辑数据库，必须一起移动、备份和恢复。`build-report.json` 记录来源
路径、计数、跳过的记录和构建耗时。新增字段应加入 SQLite 模式；来源专有元数据应保留在
provenance sidecar 中，而不是改动四列的 Crystal Record 契约。
