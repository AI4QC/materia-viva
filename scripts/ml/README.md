# `scripts/ml` — 分性质提取 GNN 训练集

把 MateriaViva 索引（13.54M 结构 / 121.6M 性质行 / 54 个数据库）拆成
**按性质分开的、可直接训练的数据集**，用来补全缺失性质（含矩阵/张量性质）。

所有脚本都是只读的，不改动 `data/index/`。

## 环境

```bash
PY=/path/to/user/anaconda3/envs/matgenbench-py310/bin/python   # pymatgen + pyarrow + numpy
```

服务器上如果没有索引，先拉：

```bash
$PY scripts/fetch_index.py --variant index --out data/index      # ~47 GB
$PY scripts/fetch_index.py --variant slice --out data/slice      # ~9 MB，先跑通流程用这个
```

## 流水线

| 步骤 | 脚本 | 输入 | 输出 | 耗时 / 磁盘 |
|---|---|---|---|---|
| 1 | `property_census.py` | `materials.sqlite` | `census_*.json` | ~23 min，62 MB |
| 2 | `export_targets.py` | `materials.sqlite` | `materials.parquet` + `targets/*.parquet` | ~25 min，~3 GB |
| 3 | `extract_tensors.py` | `data/raw/acquired/` | `tensors/*.parquet` | ~1 min，~50 MB |
| 4 | `make_training_sets.py` | 第 2 步产物 | `datasets/*.parquet` | ~10 min，~1 GB |
| 5 | `export_structures.py` | blob + sqlite | `structures/shard-*.npz` | 30 核约 1.5 h，~6 GB |
| 6 | `prediction_sets.py` | 第 2、4 步产物 | `predict/PREDICTION_SETS.*.json` | ~2 min，~1 MB |

```bash
$PY scripts/ml/property_census.py      --out data/ml/census
$PY scripts/ml/export_targets.py       --out data/ml/export
$PY scripts/ml/extract_tensors.py jarvis   --out data/ml/export/tensors
$PY scripts/ml/extract_tensors.py phonondb --out data/ml/export/tensors --workers 16
$PY scripts/ml/make_training_sets.py   --export data/ml/export --out data/ml/datasets
$PY scripts/ml/export_structures.py    --out data/ml/export/structures --workers 30
$PY scripts/ml/prediction_sets.py      --export data/ml/export --datasets data/ml/datasets \
                                       --out data/ml/predict
```

### 只做一个性质（省磁盘）

```bash
$PY scripts/ml/make_training_sets.py --export data/ml/export --out /scratch/bg \
    --property band_gap --theory-policy split
$PY scripts/ml/export_structures.py  --out /scratch/bg/structures \
    --pks-from /scratch/bg/band_gap__gga.parquet --workers 16
```

结构**不按性质复制**。`materials.parquet` 和每个 target 表都带
`blob_offset` / `blob_length`，训练时直接从那一份 9.1 GB 的
`structures.blob` 里 seek 出 CIF 即可，不需要每个性质存一份结构。

## 四个必须处理的坑

脚本已经全部处理，这里说明为什么，改参数前先读：

1. **泛函/理论层级**（`method_groups.theory_level`）。`method` 是 54 个 adapter
   各写各的自由文本，普查扫出 190,428 个不同的 (性质, 来源, method) 组合。
   band_gap 里 PBE / HSE06 / mBJ / 实验混在一起，方法带来的系统偏差约 1 eV，
   模型只会学"这条数据来自哪个库"。默认按理论层级分组，只留最大的一组。

2. **条件依赖的性质**（`method_groups.CONDITION_SPLIT_PROPERTIES`）。有些性质
   一个材料有 3–8 个都对的值，区别只写在 `method` 里：`co2_uptake` 有 4 个
   GCMC (P, T) 条件，`decomposition_energy` 有 4 个参考凸包，
   `migration_barrier` 有 BVSE/BVEL × 1D/2D/3D × 工作离子，
   deem-zeolites 的 `poisson_ratio` 是 6 个方向分量、`youngs_modulus` 是 3 个
   应力轴。对这些取中位数得到的不是物理量 —— 每个条件是一个独立任务。

3. **跨库冲突**。1,190,447 个结构由 ≥2 个数据库贡献，数值真的会不一样。
   `--resolve median|priority|drop-conflicts`，每个材料的
   `value_spread` 一律写进输出，可以用来给标签加权。

4. **划分泄漏**。同一化合物常以不同 id 出现多次，随机划分会把它同时放进
   train 和 test。默认 `--split chemsys` 按化学体系整体留出；
   `--split random` 只用来复现有泄漏的基线。

### 索引自带的一个已知缺陷：`materials.n_atoms` 有 61,717 行是半个胞

普查时发现的，不是本套脚本引入的。部分上游 CIF 存的是<b>非对称单胞 + 对称操作</b>，
建索引时没有展开，于是 `materials` 表里的 `n_atoms` / `formula` / `density`
都只有真实值的一半。用来源自己发布的 density 对拍可以精确定位：

```sql
SELECT sd.key, COUNT(*) n,
       SUM(ABS(m.density*2 - p.value_num) < 0.02*p.value_num) half_cell
FROM material_properties p
JOIN source_defs sd ON sd.id = p.source_id
JOIN materials   m  ON m.pk  = p.material_pk
WHERE p.property_id = (SELECT id FROM property_defs WHERE name='density')
  AND p.value_num > 0 AND m.density IS NOT NULL
GROUP BY sd.key;
```

结果：deem-zeolites 61,642 / 136,008（45%），另有 aflow 43、icsd 23、amcsd 8，合计 61,717。
实例 `pool-train-12848566`：索引记 `Si12O24` / 36 原子 / 1.362 g/cm³，
而 CIF 头声明 `Z=24`、空间群 Ima2（8 个对称操作），Deem 自己发布的
`framework_density` 27.31 T/1000Å³ 与 `density` 2.724 g/cm³ 都对应 **72 个原子**。

**影响范围**：`export_structures.py` 走 `CifParser`，展开对称操作，**结构本身是对的**
（该例解析出 72 个原子）。错的只有元数据列。所以：

- 原子数请用 `np.diff(atom_ptr)`，**不要**用 `datasets/*.parquet` 里的 `n_atoms`；
- 任何 per-atom 归一化在这 61,717 行上会差 2 倍；
- 受影响的正好是 23 个 `*__forcefield` / `*__GULP_SLC_forcefield__*` 沸石训练集。

另外：实验结构里约 12% 的 CIF 带部分占据（无序），无法直接编码成图。
`export_structures.py --disorder skip`（默认）丢掉它们，
`--disorder majority` 取占据最高的元素并在 `disordered` 掩码里标出来。

## 适用域：不是每个性质都对每个结构有意义

**这是"补全所有结构缺失的性质"里最容易出错的一步。** `co2_uptake` 是 GCMC 吸附量，
对多孔骨架有意义，对致密金属间化合物没有 —— 它的训练集 100% 是 MOF（287,466 个，
密度中位数 0.73 g/cm³，每一个都含碳），而池子是 1354 万个结构、密度中位数约 7 g/cm³。
拿它全池打分会产出约 1300 万个看起来像数据的数字。

162 个任务里，**63 个**的训练集 >90% 属于同一个 `material_family`；
`bulk_modulus_vrh__forcefield` 只覆盖 **2 个化学体系**。

`applicability.py` 用两个独立来源描述每个任务的域：

- **声明域**（`DECLARED`，手写）—— 这个性质物理上需要结构"是什么"。
  九类：`porous` / `framework` / `layered` / `ion-conducting` / `magnetic` /
  `gapped` / `surface-derived` / `synthesized-only` / `pool-wide`，
  外加 `pool-wide-biased-labels`（性质本身无限制，只是标签恰好来自一个族 ——
  几何孔道描述符属于这类：zeo++ 对任何周期结构都能算）。
- **经验域**（`profile()`，实测）—— 训练集实际覆盖了什么：族分布、
  化学体系数、`always_elements`（**每一个**训练结构都含的元素，最硬的约束）、
  密度与原子数的 p99。

两者不一致本身就有信息：声明为 pool-wide 但标签集中在一个族，
说明是**标签有偏**而不是性质受限。两者都写进 `DATASETS.json`。

### 算出每个模型允许打分的结构

```bash
$PY scripts/ml/prediction_sets.py --export data/ml/export \
    --datasets data/ml/datasets --out data/ml/predict --gate strict
# 落地某个任务的 pk 列表
$PY scripts/ml/prediction_sets.py ... --materialize co2_uptake__GCMC_0.15bar_298K
```

两档门控：

- `strict`（默认）—— 只凭索引里已有的证据放行：族属于声明域允许的集合、
  含全部 `always_elements`、不超过训练集 n_atoms 的 p99。
  **声明为 pool-wide 但标签 >90% 集中于一族的，也限制在该族内。**
  高精度，会漏放（一个来自 MP 的多孔骨架没有族标签，会被拒）。
- `wide` —— 额外放行密度落在训练带内的无族标结构。**这是代理，且有已知错误**：
  金属锂密度 0.53 g/cm³，会通过多孔性密度门但根本没有孔。只能用来做候选筛选清单。

严格的多孔性门控是跑一遍 zeo++（孔径限制直径 vs 吸附质动力学直径 ——
CO₂ 3.3 Å、H₂ 2.9 Å），本脚本**没有**做；`--gate wide` 的存在就是为了在那之前
先出候选清单，每份输出都记录了是哪档门控产生的。

实测结果（strict）：`co2_uptake` 可预测 **190,084** 个结构（池的 1.4%），
不是 1354 万；`exfoliation_energy` 149,409（1.1%）；
`bulk_modulus_vrh__forcefield` 只剩 **474** —— 池里 136,305 个沸石里
135,817 个已经有标签了。

有些受限的域索引里没有列可以收窄（`migration_barrier__*_Na`：BVSE 算的是
**假想**插入离子的势垒，所以不含 Na 的骨架也是合法训练行，`always_elements` 为空）。
这类任务会带 `warning` 标记，其"可预测数"是**上界**而不是可信范围。

## 矩阵性质

索引本身是标量存储（`value_num` 一个 float），入库时张量都被压成了标量
（6×6 弹性张量 → `bulk_modulus_vrh`，3×3 介电张量 → trace/3，
Born 电荷 → 最大分量）。张量要回原始档案取。

**本地已有**（`extract_tensors.py` 直接产出，已跑通）：

| 张量 | 形状 | 来源 | 已匹配到 pool 的条数 |
|---|---|---|---|
| 弹性刚度 | 6×6 | jarvis-dft | 34,437 |
| 介电（仅对角） | 3 | jarvis-dft OptB88vdW | 60,183 |
| 介电（仅对角） | 3 | jarvis-dft TBmBJ | 19,797 |
| 电场梯度 | 每个 Wyckoff 位点 3×3 | jarvis-dft | 13,825 |
| Γ 点声子频率 | 变长 | jarvis-dft | 13,896 |
| 高频介电张量 | 3×3 | phonondb PBEsol DFPT | 4,908 |
| Born 有效电荷 | N×3×3 | phonondb PBEsol DFPT | 4,908 |

**需要重新拉取**（当初只请求了标量字段，张量根本没下载）——
`extract_tensors.py plan` 会打印具体的 endpoint 和字段：
MP elasticity (13,283)、MP dielectric (~7,500)、MP piezoelectric (3,322)、
AFLOW `ael_stiffness_tensor`。都是小请求，几十分钟量级。

**曲线类**（已经在索引里，`material_curves` + `curves.blob`，17 GB）：
band_structure 122,511、dos 118,984、xrd 142,589、xas 91,181、
phonon_dos 27,591、kappa 谱 7,103。这些是序列目标，可以直接训。

## 输出格式

`targets/<property>.parquet` — 长表，一行一个 (材料, 来源, method) 观测：
`material_pk, source, native_id, method, theory_level, value_num, value_text`

`datasets/<property>[__<group>].parquet` — 模型可直接用：
`material_pk, target, n_observations, value_spread, split, formula,
chemical_system, is_experimental, n_atoms, blob_offset, blob_length`

`structures/shard-*.npz` — 变长数组按 `atom_ptr` 拼接：
`lattice (S,3,3) · atom_ptr (S+1,) · frac_coords (A,3) · atomic_numbers (A,)
· material_pk (S,) · disordered (S,)`

`tensors/*.parquet` — `material_pk, native_id, n_units, tensor`（行主序展平），
形状写在 Parquet 的 key-value metadata 里（`tensor_shape`）。
