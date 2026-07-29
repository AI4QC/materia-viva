# 既有 SSD 材料数据盘点与去重策略

**简体中文** · [English](legacy-ssd-data-inventory.md)

更新时间：2026-07-26

## 1. 接入方式

既有目录保持原位，不复制、不改名、不删除：

```text
/home/zhilong/SSD/material_data
```

MateriaViva 数据根目录中增加只占一个目录项的兼容链接：

```text
data/raw/legacy-material-data -> /home/zhilong/SSD/material_data
```

两条路径都落在 `/dev/nvme1n1p2`。这样统一采集流程可以发现既有数据，同时不会再占用一份 SSD 空间。

## 2. 实际规模与格式

| 分组 | 实测规模 | 内容 |
|---|---:|---|
| 全部既有目录 | 262,116,742,634 bytes（`du` 约 245 GiB） | 49 个顶层文件及 OMat24 子树 |
| OMat24 | 201,196,941,908 bytes（约 188 GiB） | 18 个训练/验证/sAlex `tar.gz`，以及已展开的 500 个 ASE LMDB 分片和 500 个 lock 文件 |
| 其余顶层数据 | 约 60.9 GB | 38 个 LMDB、5 个 NPY、5 个 JSON/NDJSON 和 1 个 ZIP |

顶层结构库实测条目数：

| 文件 | 条目数 | 记录形式 | 重合判断 |
|---|---:|---|---|
| `mp_structs.lmdb` | 154,519 | pickled pymatgen `Structure` | 与当前 MP 全量 summary 高度重合，但版本和条目数不同 |
| `oqmd_structs.lmdb` | 1,022,595 | pickled pymatgen `Structure` | 是当前 OQMD v1.8 整库的旧结构子集 |
| `icsd_structs.lmdb` | 200,455 | pickled pymatgen `Structure` | 与本机 203,830 个授权 ICSD CIF 高度重合 |
| `carolina_matdb_structs.lmdb` | 214,435 | pickled pymatgen `Structure` | 独立来源信息不足，先隔离为 `legacy/carolina`，待从生成脚本或论文恢复 provenance |
| `MP_PBE_new.json` | 74,991 行 | NDJSON，结构加 PBE 性质 | 与 MP 结构重合，性质和历史版本仍有保留价值 |
| `OQMD_PBE_new.json` | 635,518 行 | NDJSON，结构加 PBE 性质 | 与 OQMD 主库重合，作为旧版性质快照保留 |

此外还有 JARVIS `cfid_3d-8-18-2021`、84k CFID 描述符、JQE tight-binding、结构说明与训练测试数组。38 个 LMDB 中既有完整结构表，也有经过图转换的性质训练集；后者的值是 `torch_geometric.data.Data`，不能当作独立晶体来源重复计数。

## 3. 已确认的重复关系

### 文件级完全重复

`cfid_3d-8-18-2021.json` 与同名 ZIP 中的唯一成员完全一致：

```text
uncompressed bytes: 1,297,356,464
SHA-256: 3c778b77556ab273eb25150fa322b78f57133f7c9103684ea427b88530d2070b
```

当前仍保留压缩和未压缩两份；未经用户确认不删除。若以后只保留 ZIP，可回收约 1.30 GB，且 JSON 可从 ZIP 无损恢复。

### 内容级高度重合但不是同一文件

- 旧 MP、OQMD、ICSD、JARVIS 结构库与当前采集版本存在大范围结构重合，但字段、版本和计算方法不同，不能按文件名或材料 ID 直接覆盖。
- 旧 OMat24 已包含完整训练、验证和 sAlex 归档，但它属于轨迹/扰动构型数据，不纳入 MateriaViva 独特结构库。本轮重复的 `omat24_1M_251210.tar.gz.part` 已于 2026-07-26 删除；旧全量原文件未改动，仅保留 provenance 登记。
- `sample_*`、`train_*`、同一泛函的多个 split 以及图神经网络 LMDB 是训练划分，不是新的材料数据库；接入时只作为 property/ML-artifact sidecar。

## 4. 不能丢失的独有性质

既有目录包含主结构库没有完整覆盖的性质，因此不能简单按“来源重复”删除：

- 磁矩：`magmom_outcar.lmdb` 74,261 条。
- 弹性：`bulk_modulus_kv.lmdb` 和 `shear_modulus_gv.lmdb` 各 23,824 条。
- 热电：n/p 型 Seebeck 与 power factor 各约 23.2k 条。
- 带隙与稳定性：PBE、PBEsol、SCAN、mBJ、GLLB-SC、OptB88 等多个方法及 mBJ hull 数据。
- 描述符与可解释性：CFID 描述符、`explanations.npy`、`wml_test_data.npy`。
- OMat24 轨迹：AIMD、rattled、rattled-relax、validation 和 sAlex 不进入统一结构库，也不参与当前结构/性质采集。

## 5. 统一格式和去重顺序

1. 先登记文件级 provenance：原路径、尺寸、修改时间、来源推断、许可和 SHA-256；未知来源标为 `provenance_pending`。
2. 对 JSON、NDJSON、pymatgen LMDB、ASE LMDB、PyG LMDB 和 NPY 分别使用只读适配器；原文件永不原地改写。OMat tar 只登记 provenance，不开发入库适配器。
3. 结构转换到 `Crystal Record v1` 的扩展标准层，保留 `source_id/source_version/source_record_id/structure_role`。
4. 对标准化晶格、元素、占位和分数坐标先做完全哈希，再做带容差结构匹配；缺陷、表面、二维堆垛和体相结构分开匹配，轨迹帧不采集。
5. 重复结构只合并检索实体。不同泛函、温度、压力、磁态、计算代码和实验条件下的性质全部作为多值记录保留。
6. ICSD/CSD 派生项继承许可限制；即使与开放结构匹配，也不能借开放来源反向再分发受限原始字段。

在结构指纹和 provenance 完成前，任何 `legacy-material-data` 文件都不进入删除队列。
