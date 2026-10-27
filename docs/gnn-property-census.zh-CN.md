# GNN 性质预测：索引普查与分性质数据提取报告

> **2026-09-11 更新**：NOMAD 并入后（55 个来源、14,590,485 个结构、131,824,881 条性质）重跑了 `property_census.py` / `task_census.py` / `make_training_sets.py` / `prediction_sets.py`。汇总数字（513 个任务、176 个训练集、适用域统计）已按本次运行更新；下文各节的**逐任务明细表**仍是上一次运行的输出，行数会略有出入，以 `data/ml/` 下的 JSON 为准。

**日期** 2026-08-30 · **索引** `data/index/materials.sqlite`（schema v3）·
**普查方式** 全表扫描 ·
**配套脚本** [`scripts/ml/`](../scripts/ml/README.md)（数据提取）· [`scripts/train/`](../scripts/train/README.md)（批量训练）

目标：用已有数据规模化训练 GNN 模型，补全所有结构缺失的性质（含矩阵性质）。
本文汇总性质任务的数据规模、适用域和提取方法。

---

## 01 结论

**"几十个模型"这个量级偏保守。** 把 `method` 字段按理论层级和测量条件正确拆开之后：

| 门槛 | 回归任务 | 覆盖性质 | 分类任务 | 覆盖性质 |
|---|--:|--:|--:|--:|
| ≥ 1,000,000 材料 | 13 | 13 | 1 | 1 |
| ≥ 100,000 | 97 | 47 | 15 | 11 |
| ≥ 10,000 | **161** | **77** | 31 | 19 |
| ≥ 2,000 | 210 | 97 | 37 | 24 |
| ≥ 300 | 249 | 110 | 40 | 26 |

另有 7 组本地就能取出的张量目标，和 6 类已在索引里的曲线目标。

**流水线已跑通并验证过一遍**，不是纸面方案。默认参数下产出 **176 个训练集**、
覆盖 **116 个性质**、共 **93,864,594 条标签**，全部带 train/val/test 划分，磁盘 1.9 GB。

**每个材料都有结构。** `materials` 表里 `blob_offset` / `blob_length` 非空是硬约束，
不存在"有标签没结构"的行。候选结构平均 15.1 个原子、上限 500 个，
对消息传递网络是很舒服的尺寸。

**真正的风险在标签口径，不在数据量。** 普查扫出 **190,428** 个不同的
(性质, 来源, method) 组合 —— 这个字段是 55 个 adapter 各写各的自由文本。
不做归一化直接按性质名训练，有几个任务学到的会是"这条数据来自哪个库"而不是物理。
第 09 节的四个坑已在脚本里处理；第 10 节是我自己在构建过程中踩的两个边界错误；
第 11 节是索引自带的一个既有缺陷。

**"补全所有结构"这句话本身需要限定。** 很多性质只对特定材料有意义 ——
`co2_uptake` 是多孔骨架的 GCMC 吸附量，对致密金属间化合物没有定义。
176 个任务里 **63 个**的训练集 >90% 属于同一个 `material_family`。
第 06 节给每个任务标了适用域，并算出它到底允许对哪些结构打分：
**109 / 176 个任务的可预测范围不到池的一半**，
总预测量 1,105,593,143 而不是 176 × 14,590,485 = 2,567,925,360，相差 2.32 倍。

---

## 02 数据全景

| 维度 | 实验 | 候选 | 合计 |
|---|--:|--:|--:|
| 结构数 | 357,127 | 14,233,358 | **14,590,485** |
| 平均原子数 | 136.6 | 14.6 | — |
| ≤ 50 原子 | 81,908 | 13,531,672 | 13,613,580 |
| ≤ 200 原子 | 270,424 | 14,170,637 | 14,441,061 |
| CIF 压缩后 | 0.75 GB | 8.36 GB | 9.11 GB |

- 性质行数 **131,824,881**，分布在 **151** 个有数据的性质上（共定义了 166 个）
- 数据库 **55** 个，其中 **3,233,769** 个结构由 ≥2 个库贡献
- 曲线 1,198,897 条，17 GB

### 许可分布 —— 如果模型或权重要公开，先看这一栏

索引**不是**按许可过滤过的快照。按性质行数统计：

| 许可类别 | 性质行数 | 占比 |
|---|--:|--:|
| 站点条款 / 其他 | 71,256,259 | 54.1% |
| 学术 / 非商用 | 18,464,119 | 14.0% |
| CC BY | 18,021,550 | 13.7% |
| CC BY-NC（禁商用） | 12,921,245 | 9.8% |
| 逐上传件许可（NOMAD） | 10,204,105 | 7.7% |
| CC0 / 公共领域 | 380,579 | 0.3% |
| CC BY-SA | 319,466 | 0.2% |
| ICSD 许可（受限） | 257,558 | 0.2% |

**受限来源合计 41,847,027 行，占 31.7%。** 用全量数据训出来的模型在分发时会继承这些限制。
想要一个可自由发布的子集，需要在 `make_training_sets.py` 之前按 `source_defs.license`
先筛 `targets/*.parquet`。这一步**还没做**。

---

## 03 数据量分层

按拆分后每个任务的可训练材料数分层（普查口径，所有理论层级都算）：

| 层 | 门槛 | 任务数 | 性质数 | 典型内容 | 建议 |
|---|---|--:|--:|---|---|
| T1 | ≥ 1M | 13 | 13 | 基础能量与电子结构 | 可上大模型，做多任务骨干 |
| T2 | ≥ 100k | 97 | 47 | 孔道、吸附、弹性 | 常规训练，接领域头 |
| T3 | ≥ 10k | 161 | 77 | 光学、声子、热电 | 主力区间，冻结骨干微调 |
| T4 | ≥ 2k | 210 | 97 | 超导、压电、表面 | 必须迁移学习 |
| T5 | ≥ 300 | 249 | 110 | 晶界、高压、反铁磁 | 只能当下游小样本，谨慎报指标 |

---

## 04 普查全表（≥10,000 材料的回归任务，共 161 个）

`⚠` 标记的是**条件依赖**性质：同一个材料有多个都正确的值，
每个条件是独立任务，不能取中位数合并（见第 09 节坑 2）。

完整数据（含 ≥300 的全部 513 个任务、分类任务、每个来源的行数）在
`data/ml/census/task_census.json`。

| # | 性质 | 分组（泛函 / 条件） | 单位 | 材料数 | 该性质的主要来源 |
|--:|---|---|---|--:|---|
| 1 | `total_energy_per_atom` | gga | eV/atom | 10,117,201 | alexandria, aflow |
| 2 | `formation_energy_per_atom` | gga | eV/atom | 8,491,348 | alexandria, aflow |
| 3 | `total_magnetization` | gga | μB | 7,229,974 | alexandria, elementa |
| 4 | `spacegroup_number` | gga | — | 7,194,366 | alexandria, aflow |
| 5 | `energy_above_hull` | gga | eV/atom | 6,530,937 | alexandria, oqmd |
| 6 | `band_gap` | gga | eV | 6,321,787 | alexandria, oqmd |
| 7 | `dos_at_fermi` | gga | states/eV | 5,220,234 | alexandria, materiae |
| 8 | `phase_separation_energy` | gga | eV/atom | 5,171,389 | alexandria |
| 9 | `band_gap_direct` | gga | eV | 5,170,364 | alexandria, materials-cloud-archive-static |
| 10 | `volume_per_atom` | gga | Å³/atom | 2,275,023 | aflow |
| 11 | `density` | gga | g/cm³ | 2,254,603 | aflow, deem-zeolites |
| 12 | `max_residual_stress` | — | eV/Å³ | 2,005,836 | elementa |
| 13 | `max_residual_force` | — | eV/Å | 2,005,836 | elementa |
| 14 | `magnetization_per_atom` | — | μB/atom | 938,459 | oqmd |
| 15 | `band_gap` | tight-binding | eV | 632,143 | alexandria, oqmd |
| 16 | `total_energy_per_atom` | tight-binding | eV/atom | 630,096 | alexandria, aflow |
| 17 | `formation_energy_per_atom` | tight-binding | eV/atom | 606,176 | alexandria, aflow |
| 18 | `decomposition_energy` ⚠ | PBE GNoME vs MP+OQMD hull | eV/atom | 554,056 | gnome, materials-project |
| 19 | `decomposition_energy` ⚠ | PBE GNoME vs MP hull | eV/atom | 554,056 | gnome, materials-project |
| 20 | `decomposition_energy` ⚠ | PBE GNoME vs GNoME hull | eV/atom | 554,056 | gnome, materials-project |
| 21 | `decomposition_energy` ⚠ | PBE GNoME | eV/atom | 554,056 | gnome, materials-project |
| 22 | `largest_cavity_diameter` | geometric | Å | 473,324 | mof-carbon-capture, hmof |
| 23 | `pore_limiting_diameter` | — | Å | 473,282 | mof-carbon-capture, hmof |
| 24 | `void_fraction` | geometric | — | 454,309 | mof-carbon-capture, hmof |
| 25 | `surface_area_gravimetric` | geometric | m²/g | 429,815 | mof-carbon-capture, hmof |
| 26 | `spacegroup_number` | pbesol | — | 386,638 | alexandria, aflow |
| 27 | `total_magnetization` | pbesol | μB | 365,920 | alexandria, elementa |
| 28 | `total_magnetization` | scan | μB | 364,392 | alexandria, elementa |
| 29 | `phase_separation_energy` | pbesol | eV/atom | 362,171 | alexandria |
| 30 | `band_gap_direct` | pbesol | eV | 361,971 | alexandria, materials-cloud-archive-static |
| 31 | `phase_separation_energy` | scan | eV/atom | 360,659 | alexandria |
| 32 | `band_gap_direct` | scan | eV | 360,460 | alexandria, materials-cloud-archive-static |
| 33 | `dos_at_fermi` | pbesol | states/eV | 357,942 | alexandria, materiae |
| 34 | `dos_at_fermi` | scan | states/eV | 356,447 | alexandria, materiae |
| 35 | `energy_above_hull` | pbesol | eV/atom | 335,467 | alexandria, oqmd |
| 36 | `energy_above_hull` | scan | eV/atom | 334,066 | alexandria, oqmd |
| 37 | `spacegroup_number` | scan | — | 318,550 | alexandria, aflow |
| 38 | `band_gap` | pbesol | eV | 311,206 | alexandria, oqmd |
| 39 | `total_energy_per_atom` | pbesol | eV/atom | 308,983 | alexandria, aflow |
| 40 | `band_gap` | scan | eV | 308,692 | alexandria, oqmd |
| 41 | `total_energy_per_atom` | scan | eV/atom | 307,693 | alexandria, aflow |
| 42 | `pore_volume` | — | cm³/g | 299,394 | mof-carbon-capture, core-mof |
| 43 | `formation_energy_per_atom` | pbesol | eV/atom | 297,279 | alexandria, aflow |
| 44 | `formation_energy_per_atom` | scan | eV/atom | 296,037 | alexandria, aflow |
| 45 | `working_capacity_vacuum_swing` ⚠ | — | mol/kg | 287,610 | mof-carbon-capture |
| 46 | `working_capacity_temperature_swing` ⚠ | — | mol/kg | 287,610 | mof-carbon-capture |
| 47 | `n2_uptake` ⚠ | GCMC binary CO2/N2 0.85bar 298K | mol/kg | 287,610 | mof-carbon-capture, mofx-db |
| 48 | `co2_uptake` ⚠ | GCMC binary CO2/N2 0.15bar 298K | mol/kg | 287,610 | mof-carbon-capture, hmof |
| 49 | `co2_uptake` ⚠ | GCMC 0.15bar 298K | mol/kg | 287,610 | mof-carbon-capture, hmof |
| 50 | `co2_uptake` ⚠ | GCMC 0.10bar 363K | mol/kg | 287,610 | mof-carbon-capture, hmof |
| 51 | `co2_n2_selectivity` | — | — | 287,610 | mof-carbon-capture |
| 52 | `co2_uptake` ⚠ | GCMC 0.70bar 413K | mol/kg | 287,564 | mof-carbon-capture, hmof |
| 53 | `n2_heat_of_adsorption` ⚠ | — | kJ/mol | 285,827 | mof-carbon-capture |
| 54 | `co2_heat_of_adsorption` ⚠ | GCMC 0.70bar 413K | kJ/mol | 285,765 | mof-carbon-capture |
| 55 | `co2_heat_of_adsorption` ⚠ | GCMC 0.15bar 298K | kJ/mol | 285,663 | mof-carbon-capture |
| 56 | `co2_heat_of_adsorption` ⚠ | GCMC 0.10bar 363K | kJ/mol | 285,649 | mof-carbon-capture |
| 57 | `co2_heat_of_adsorption` ⚠ | GCMC binary CO2/N2 0.15bar 298K | kJ/mol | 285,268 | mof-carbon-capture |
| 58 | `measurement_temperature` | — | K | 238,161 | cod |
| 59 | `fermi_energy` | — | eV | 215,053 | materials-project, c2db |
| 60 | `magnetization_per_volume` | — | μB/Å³ | 211,854 | materials-project |
| 61 | `surface_area_volumetric` | geometric | m²/cm³ | 167,087 | hmof, fair-mofs |
| 62 | `energy_per_t_atom` | — | kJ/mol | 136,008 | deem-zeolites |
| 63 | `framework_density` | forcefield | T/1000 Å³ | 136,006 | deem-zeolites, pcod |
| 64 | `poisson_ratio` ⚠ | GULP SLC forcefield (ν_zy) | — | 135,980 | deem-zeolites, jarvis-dft |
| 65 | `poisson_ratio` ⚠ | GULP SLC forcefield (ν_zx) | — | 135,976 | deem-zeolites, jarvis-dft |
| 66 | `poisson_ratio` ⚠ | GULP SLC forcefield (ν_yz) | — | 135,975 | deem-zeolites, jarvis-dft |
| 67 | `poisson_ratio` ⚠ | GULP SLC forcefield (ν_xz) | — | 135,970 | deem-zeolites, jarvis-dft |
| 68 | `poisson_ratio` ⚠ | GULP SLC forcefield (ν_yx) | — | 135,941 | deem-zeolites, jarvis-dft |
| 69 | `poisson_ratio` ⚠ | GULP SLC forcefield (ν_xy) | — | 135,940 | deem-zeolites, jarvis-dft |
| 70 | `bulk_modulus_voigt` | forcefield | GPa | 135,909 | deem-zeolites, materials-project |
| 71 | `youngs_modulus` ⚠ | GULP SLC forcefield (stress axis z) | GPa | 135,887 | deem-zeolites, hadb |
| 72 | `bulk_modulus_reuss` | forcefield | GPa | 135,849 | deem-zeolites, materials-project |
| 73 | `sound_velocity_longitudinal` | forcefield | m/s | 135,834 | deem-zeolites, materials-project |
| 74 | `youngs_modulus` ⚠ | GULP SLC forcefield (stress axis y) | GPa | 135,504 | deem-zeolites, hadb |
| 75 | `youngs_modulus` ⚠ | GULP SLC forcefield (stress axis x) | GPa | 135,485 | deem-zeolites, hadb |
| 76 | `shear_modulus_voigt` | forcefield | GPa | 134,250 | deem-zeolites, materials-project |
| 77 | `sound_velocity_transverse` | forcefield | m/s | 132,952 | deem-zeolites, materials-project |
| 78 | `dielectric_constant_total` | forcefield | — | 131,026 | deem-zeolites, materials-project |
| 79 | `shear_modulus_reuss` | forcefield | GPa | 130,939 | deem-zeolites, materials-project |
| 80 | `co2_uptake` ⚠ | GCMC (hMOF) max over pressures | mol/kg | 127,498 | mof-carbon-capture, hmof |
| 81 | `co2_uptake` ⚠ | GCMC (hMOF) 0.01 bar | mol/kg | 127,498 | mof-carbon-capture, hmof |
| 82 | `vbm` | — | eV | 123,288 | materials-project |
| 83 | `cbm` | — | eV | 123,288 | materials-project |
| 84 | `bulk_modulus_vrh` | forcefield | GPa | 121,704 | deem-zeolites, jarvis-dft |
| 85 | `shear_modulus_vrh` | forcefield | GPa | 118,793 | deem-zeolites, jarvis-dft |
| 86 | `decomposition_energy` ⚠ | r2SCAN GNoME vs MP+OQMD hull | eV/atom | 117,045 | gnome, materials-project |
| 87 | `decomposition_energy` ⚠ | r2SCAN GNoME vs MP hull | eV/atom | 117,045 | gnome, materials-project |
| 88 | `decomposition_energy` ⚠ | r2SCAN GNoME vs GNoME hull | eV/atom | 117,045 | gnome, materials-project |
| 89 | `decomposition_energy` ⚠ | r2SCAN GNoME | eV/atom | 117,045 | gnome, materials-project |
| 90 | `total_magnetization` | gga-vdw | μB | 111,181 | alexandria, elementa |
| 91 | `energy_above_hull` | gga-vdw | eV/atom | 108,999 | alexandria, oqmd |
| 92 | `dielectric_constant_electronic` | forcefield | — | 107,200 | deem-zeolites, jarvis-dft |
| 93 | `density` | experiment | g/cm³ | 103,819 | aflow, deem-zeolites |
| 94 | `spacegroup_number` | gga-vdw | — | 102,963 | alexandria, aflow |
| 95 | `band_gap` | gga-vdw | eV | 100,720 | alexandria, oqmd |
| 96 | `density` | forcefield | g/cm³ | 100,490 | aflow, deem-zeolites |
| 97 | `total_energy_per_atom` | gga-vdw | eV/atom | 100,394 | alexandria, aflow |
| 98 | `formation_energy_per_atom` | gga-vdw | eV/atom | 96,719 | alexandria, aflow |
| 99 | `total_energy_per_atom` | r2scan | eV/atom | 87,646 | alexandria, aflow |
| 100 | `formation_energy_per_atom` | r2scan | eV/atom | 84,326 | alexandria, aflow |
| 101 | `dielectric_constant_electronic` | gga-vdw | — | 68,771 | deem-zeolites, jarvis-dft |
| 102 | `decomposition_energy` ⚠ | PBE(+U) MP2026 equilibrium reaction energy | eV/atom | 59,007 | gnome, materials-project |
| 103 | `band_gap` | hse06 | eV | 56,631 | alexandria, oqmd |
| 104 | `poisson_ratio` ⚠ | OptB88vdW ElaStic | — | 46,665 | deem-zeolites, jarvis-dft |
| 105 | `band_gap` | gllbsc | eV | 45,918 | alexandria, oqmd |
| 106 | `bulk_modulus_vrh` | gga-vdw | GPa | 42,019 | deem-zeolites, jarvis-dft |
| 107 | `shear_modulus_vrh` | gga-vdw | GPa | 41,923 | deem-zeolites, jarvis-dft |
| 108 | `seebeck_coefficient` ⚠ | BoltzTraP p-type | μV/K | 40,378 | jarvis-dft, jarvis-specialized-structures |
| 109 | `seebeck_coefficient` ⚠ | BoltzTraP n-type | μV/K | 40,378 | jarvis-dft, jarvis-specialized-structures |
| 110 | `power_factor` ⚠ | BoltzTraP p-type | μW/cm·K² | 40,375 | jarvis-dft, jarvis-specialized-structures |
| 111 | `power_factor` ⚠ | BoltzTraP n-type | μW/cm·K² | 40,375 | jarvis-dft, jarvis-specialized-structures |
| 112 | `largest_free_path_diameter` | — | Å | 36,602 | fair-mofs, core-mof |
| 113 | `density` | geometric | g/cm³ | 34,061 | aflow, deem-zeolites |
| 114 | `bulk_modulus_vrh` | gga | GPa | 31,517 | deem-zeolites, jarvis-dft |
| 115 | `shear_modulus_vrh` | gga | GPa | 31,445 | deem-zeolites, jarvis-dft |
| 116 | `pore_channel_count` | — | — | 27,089 | fair-mofs |
| 117 | `lattice_thermal_conductivity` | — | W/m·K | 26,507 | materials-project, phonix |
| 118 | `debye_temperature` | — | K | 25,997 | materials-project, aflow |
| 119 | `band_gap` | mbj | eV | 25,331 | alexandria, oqmd |
| 120 | `dielectric_constant_electronic` | mbj | — | 24,809 | deem-zeolites, jarvis-dft |
| 121 | `poisson_ratio` ⚠ | PBE(+U) MP2026 | — | 24,518 | deem-zeolites, jarvis-dft |
| 122 | `elastic_anisotropy` | — | — | 24,430 | materials-project |
| 123 | `total_energy_per_atom` | hse06 | eV/atom | 22,483 | alexandria, aflow |
| 124 | `sound_velocity_transverse` | gga | m/s | 20,810 | deem-zeolites, materials-project |
| 125 | `sound_velocity_longitudinal` | gga | m/s | 20,810 | deem-zeolites, materials-project |
| 126 | `shear_modulus_voigt` | gga | GPa | 20,810 | deem-zeolites, materials-project |
| 127 | `shear_modulus_reuss` | gga | GPa | 20,810 | deem-zeolites, materials-project |
| 128 | `bulk_modulus_voigt` | gga | GPa | 20,810 | deem-zeolites, materials-project |
| 129 | `bulk_modulus_reuss` | gga | GPa | 20,810 | deem-zeolites, materials-project |
| 130 | `framework_bond_dissociation_energy` | — | eV/atom | 20,194 | fair-mofs |
| 131 | `nmr_efg_max` | — | V/m² | 19,740 | jarvis-dft |
| 132 | `phonon_max_frequency` | gga | THz | 19,394 | phonix, jarvis-dft |
| 133 | `phonon_min_frequency` | gga | THz | 19,392 | phonix, jarvis-dft |
| 134 | `num_voltage_steps` | — | — | 19,280 | materials-project |
| 135 | `max_voltage_step` | — | V | 19,280 | materials-project |
| 136 | `energy_density_volumetric` | — | Wh/L | 19,280 | materials-project |
| 137 | `energy_density_gravimetric` | — | Wh/kg | 19,280 | materials-project |
| 138 | `electrode_volume_change` | — | fraction | 19,280 | materials-project |
| 139 | `electrode_stability_discharged` | — | eV/atom | 19,280 | materials-project |
| 140 | `electrode_stability_charged` | — | eV/atom | 19,280 | materials-project |
| 141 | `capacity_volumetric` | — | mAh/cm³ | 19,280 | materials-project |
| 142 | `capacity_gravimetric` | — | mAh/g | 19,280 | materials-project |
| 143 | `average_voltage` | — | V | 19,280 | materials-project |
| 144 | `spillage` | — | — | 19,113 | jarvis-dft, jarvis-specialized-structures |
| 145 | `heat_of_formation` | gllbsc | eV/atom | 18,683 | cmr-static |
| 146 | `slme` | — | % | 16,815 | jarvis-dft, jarvis-specialized-structures |
| 147 | `phonon_min_frequency` | dfpt-phonon | THz | 16,169 | phonix, jarvis-dft |
| 148 | `phonon_max_frequency` | dfpt-phonon | THz | 16,142 | phonix, jarvis-dft |
| 149 | `refractive_index` | gga | — | 15,136 | materials-project, materials-cloud-archive-static |
| 150 | `spacegroup_number` | other | — | 14,521 | alexandria, aflow |
| 151 | `dielectric_constant_total` | gga | — | 13,710 | deem-zeolites, materials-project |
| 152 | `band_gap` | other | eV | 13,599 | alexandria, oqmd |
| 153 | `heat_capacity` | pbesol | J/mol·K | 13,059 | phonondb, aflow |
| 154 | `structure_prediction_r_factor` | — | — | 12,415 | pcod |
| 155 | `framework_density` | other | T/1000 Å³ | 12,188 | deem-zeolites, pcod |
| 156 | `dielectric_constant_ionic` | gga | — | 11,191 | materials-project, jarvis-dft |
| 157 | `dielectric_constant_electronic` | gga | — | 11,177 | deem-zeolites, jarvis-dft |
| 158 | `poisson_ratio` ⚠ | PBE AEL (AFLOW) | — | 10,690 | deem-zeolites, jarvis-dft |
| 159 | `thermal_conductivity` | — | W/m·K | 10,565 | aflow |
| 160 | `thermal_expansion` | — | 1/K | 10,563 | aflow |
| 161 | `heat_capacity` | gga | J/mol·K | 10,075 | phonondb, aflow |

---

## 05 已产出的 176 个训练集

默认参数：`--theory-policy majority --resolve median --split chemsys --min-materials 300`。
产物在 `data/ml/datasets/`，1.9 GB。

| 指标 | 值 | 说明 |
|---|--:|---|
| 训练集数 | 176 | 覆盖 116 个性质 |
| 标签总数 | 93,864,594 | 去重、消解冲突之后 |
| 多源标注的材料 | 5,856,861 | ≥2 个数据库给过值 |
| 源间分歧 | 522,739 | 极差 > 0.25 σ，已标注未丢弃 |
| 越界丢弃 | 6,502 | 修正边界后（修正前 2,238,299，见第 10 节） |
| 空折叠的任务 | 0 | 级联降级修复了 23 个 |
| 划分方式 | 153 / 23 | chemsys / 降级到 formula |
| 含实验标签的任务 | 129 | 可做实验-计算校准 |
| 分层 | T1 13 · T2 60 · T3 52 · T4 32 · T5 19 | |

**多源** = 被 ≥2 个数据库标注过的材料数；**分歧** = 其中源间极差超过 0.25 个标准差的部分。
这些行的 `value_spread` 都写在输出里，可以拿来给标签加权。
`⚠` = 划分从 chemsys 降级到 formula（见第 09 节坑 4）。

| 训练集 | 声明域 | 材料数 | train | val | test | 多源 | 分歧 | 实验 | 目标 mean ± std | 划分 |
|---|---|--:|--:|--:|--:|--:|--:|--:|---|---|
| `total_energy_per_atom__gga` | pool-wide | 11,375,665 | 9,100,576 | 1,137,586 | 1,137,503 | 1,240,463 | 42,969 | 78,769 | -5.448 ± 2.027 | chemsys |
| `formation_energy_per_atom__gga` | pool-wide | 9,672,505 | 7,738,011 | 967,345 | 967,149 | 1,229,497 | 75,435 | 70,842 | -0.321 ± 0.948 | chemsys |
| `total_magnetization__gga` | pool-wide | 7,972,636 | 6,378,113 | 797,277 | 797,246 | 153,309 | 27,667 | 73,453 | 1.515 ± 4.412 | chemsys |
| `spacegroup_number__gga` | pool-wide | 7,919,120 | 6,335,296 | 791,912 | 791,912 | 833,480 | 90,234 | 55,088 | 110.777 ± 73.101 | chemsys |
| `band_gap__gga` | pool-wide | 7,569,867 | 6,056,020 | 756,863 | 756,984 | 476,165 | 63,442 | 80,670 | 0.244 ± 0.802 | chemsys |
| `energy_above_hull__gga` | pool-wide | 7,218,674 | 5,774,991 | 721,825 | 721,858 | 489,803 | 62,836 | 70,443 | 0.344 ± 0.484 | chemsys |
| `dos_at_fermi__gga` | pool-wide | 5,869,827 | 4,695,864 | 586,989 | 586,974 | 111,867 | 15,276 | 40,503 | 6.705 ± 7.627 | chemsys |
| `band_gap_direct__gga` | gapped | 5,828,018 | 4,662,419 | 582,804 | 582,795 | 52,722 | 5,272 | 10,877 | 0.22 ± 0.737 | chemsys |
| `phase_separation_energy__gga` | pool-wide | 5,824,704 | 4,659,769 | 582,479 | 582,456 | 51,952 | 18,988 | 10,868 | 0.336 ± 0.497 | chemsys |
| `density__gga` | pool-wide | 2,274,200 | 1,819,374 | 227,463 | 227,363 | 434,865 | 14,218 | 39,565 | 8.255 ± 3.508 | chemsys |
| `volume_per_atom__gga` | pool-wide | 2,273,671 | 1,818,956 | 227,384 | 227,331 | 434,937 | 31,599 | 39,483 | 20.342 ± 6.454 | chemsys |
| `max_residual_stress__gga` | pool-wide | 2,003,831 | 1,603,107 | 200,362 | 200,362 | 0 | 0 | 0 | 0.001 ± 0.001 | chemsys |
| `max_residual_force__gga` | pool-wide | 2,003,830 | 1,603,114 | 200,380 | 200,336 | 0 | 0 | 0 | 0.039 ± 0.01 | chemsys |
| `magnetization_per_atom__gga` | pool-wide | 937,519 | 750,016 | 93,760 | 93,743 | 34,050 | 13,659 | 27,653 | 0.268 ± 0.457 | chemsys |
| `decomposition_energy__PBE_GNoME_vs_GNoME_hull` | pool-wide | 554,056 | 443,245 | 55,410 | 55,401 | 0 | 0 | 8 | 0.0 ± 0.0 | chemsys |
| `decomposition_energy__PBE_GNoME_vs_MP_OQMD_hull` | pool-wide | 553,778 | 443,024 | 55,381 | 55,373 | 0 | 0 | 8 | -0.025 ± 0.042 | chemsys |
| `decomposition_energy__PBE_GNoME_vs_MP_hull` | pool-wide | 553,680 | 442,945 | 55,369 | 55,366 | 0 | 0 | 8 | -0.036 ± 0.066 | chemsys |
| `decomposition_energy__PBE_GNoME` | pool-wide | 553,500 | 442,800 | 55,350 | 55,350 | 0 | 0 | 8 | -0.039 ± 0.067 | chemsys |
| `pore_limiting_diameter__geometric` | pool-wide-biased-labels | 472,809 | 378,629 | 47,489 | 46,691 | 26,372 | 6,027 | 37,919 | 6.802 ± 3.737 | chemsys |
| `largest_cavity_diameter__geometric` | pool-wide-biased-labels | 472,808 | 378,612 | 47,496 | 46,700 | 26,372 | 5,609 | 37,930 | 9.167 ± 4.415 | chemsys |
| `void_fraction__geometric` | pool-wide-biased-labels | 454,589 | 391,051 | 18,727 | 44,811 | 22,937 | 7,840 | 36,864 | 0.45 ± 0.242 | chemsys |
| `surface_area_gravimetric__geometric` | pool-wide-biased-labels | 429,536 | 370,516 | 17,419 | 41,601 | 8,650 | 1,176 | 12,058 | 2654.79 ± 1685.338 | chemsys |
| `pore_volume__geometric` | pool-wide-biased-labels | 299,244 | 242,128 | 27,193 | 29,923 | 6,062 | 272 | 11,764 | 0.737 ± 0.679 | chemsys |
| `co2_n2_selectivity__gcmc` | porous | 287,466 | 233,443 | 25,365 | 28,658 | 0 | 0 | 0 | 14.434 ± 16.925 | chemsys |
| `co2_uptake__GCMC_0.10bar_363K` | porous | 287,466 | 233,426 | 25,374 | 28,666 | 0 | 0 | 0 | 0.1 ± 0.077 | chemsys |
| `co2_uptake__GCMC_0.15bar_298K` | porous | 287,466 | 233,426 | 25,372 | 28,668 | 0 | 0 | 0 | 0.535 ± 0.534 | chemsys |
| `co2_uptake__GCMC_binary_CO2_N2_0.15bar_298K` | porous | 287,466 | 233,430 | 25,369 | 28,667 | 0 | 0 | 0 | 0.508 ± 0.489 | chemsys |
| `n2_uptake__GCMC_binary_CO2_N2_0.85bar_298K` | porous | 287,466 | 233,434 | 25,370 | 28,662 | 0 | 0 | 0 | 0.2 ± 0.072 | chemsys |
| `co2_uptake__GCMC_0.70bar_413K` | porous | 287,420 | 233,389 | 25,365 | 28,666 | 0 | 0 | 0 | 0.234 ± 0.127 | chemsys |
| `working_capacity_temperature_swing__GCMC_TSA_0.15bar_298K_-__0.70bar_413K` | porous | 287,322 | 233,314 | 25,350 | 28,658 | 0 | 0 | 0 | 0.301 ± 0.43 | chemsys |
| `working_capacity_vacuum_swing__GCMC_VSA` | porous | 287,322 | 233,299 | 25,368 | 28,655 | 0 | 0 | 0 | 0.435 ± 0.471 | chemsys |
| `n2_heat_of_adsorption__GCMC_binary_CO2_N2_0.85bar_298K` | porous | 285,541 | 231,799 | 25,210 | 28,532 | 0 | 0 | 0 | 11.45 ± 3.682 | chemsys |
| `co2_heat_of_adsorption__GCMC_0.70bar_413K` | porous | 285,479 | 231,765 | 25,197 | 28,517 | 0 | 0 | 0 | 18.846 ± 5.996 | chemsys |
| `co2_heat_of_adsorption__GCMC_0.15bar_298K` | porous | 285,377 | 231,681 | 25,189 | 28,507 | 0 | 0 | 0 | 20.313 ± 5.88 | chemsys |
| `co2_heat_of_adsorption__GCMC_0.10bar_363K` | porous | 285,363 | 231,669 | 25,185 | 28,509 | 0 | 0 | 0 | 19.421 ± 5.974 | chemsys |
| `co2_heat_of_adsorption__GCMC_binary_CO2_N2_0.15bar_298K` | porous | 284,982 | 231,345 | 25,160 | 28,477 | 0 | 0 | 0 | 20.086 ± 5.813 | chemsys |
| `is_gap_direct__gga` | gapped | 243,137 | 194,510 | 24,318 | 24,309 | 18,803 | 2,285 | 73,488 | 0.18 ± 0.382 | chemsys |
| `measurement_temperature__experiment` | synthesized-only | 237,965 | 190,372 | 26,158 | 21,435 | 1,627 | 986 | 224,010 | 209.39 ± 84.66 | chemsys |
| `fermi_energy__gga` | pool-wide | 214,839 | 171,877 | 21,480 | 21,482 | 3,545 | 1,230 | 63,949 | 2.993 ± 2.873 | chemsys |
| `experimentally_observed__experiment` | synthesized-only | 211,854 | 169,484 | 21,211 | 21,159 | 3,347 | 533 | 64,052 | 0.504 ± 0.499 | chemsys |
| `is_stable__gga` | pool-wide | 211,854 | 169,484 | 21,211 | 21,159 | 3,347 | 557 | 64,052 | 0.277 ± 0.447 | chemsys |
| `magnetization_per_volume__gga` | pool-wide | 211,749 | 169,402 | 21,191 | 21,156 | 3,347 | 513 | 64,012 | 0.014 ± 0.028 | chemsys |
| `is_metal__gga` | pool-wide | 211,746 | 169,397 | 21,200 | 21,149 | 3,344 | 490 | 64,009 | 0.456 ± 0.498 | chemsys |
| `surface_area_volumetric__geometric` | pool-wide-biased-labels | 166,920 | 141,896 | 9,597 | 15,427 | 22,336 | 7,570 | 36,748 | 1437.114 ± 858.152 | chemsys |
| `framework_density__forcefield` | framework | 135,877 | 120,236 | 3,819 | 11,822 | 0 | 0 | 0 | 19.922 ± 2.807 | formula ⚠ |
| `dielectric_constant_electronic__forcefield` | gapped | 135,870 | 120,224 | 3,821 | 11,825 | 0 | 0 | 0 | 1.774 ± 0.124 | formula ⚠ |
| `energy_per_t_atom__forcefield` | framework | 135,870 | 120,232 | 3,816 | 11,822 | 0 | 0 | 0 | -12394.962 ± 4.914 | formula ⚠ |
| `poisson_ratio__GULP_SLC_forcefield__ν_zy` | pool-wide | 135,844 | 120,204 | 3,825 | 11,815 | 0 | 0 | 0 | 0.289 ± 0.205 | formula ⚠ |
| `poisson_ratio__GULP_SLC_forcefield__ν_zx` | pool-wide | 135,840 | 120,199 | 3,821 | 11,820 | 0 | 0 | 0 | 0.287 ± 0.208 | formula ⚠ |
| `poisson_ratio__GULP_SLC_forcefield__ν_yz` | pool-wide | 135,839 | 120,202 | 3,823 | 11,814 | 0 | 0 | 0 | 0.271 ± 0.201 | formula ⚠ |
| `poisson_ratio__GULP_SLC_forcefield__ν_xz` | pool-wide | 135,834 | 120,201 | 3,825 | 11,808 | 0 | 0 | 0 | 0.268 ± 0.203 | formula ⚠ |
| `bulk_modulus_vrh__forcefield` | pool-wide | 135,817 | 120,188 | 3,817 | 11,812 | 0 | 0 | 0 | 53.333 ± 14.518 | formula ⚠ |
| `bulk_modulus_voigt__forcefield` | pool-wide | 135,815 | 120,182 | 3,822 | 11,811 | 0 | 0 | 0 | 58.59 ± 14.635 | formula ⚠ |
| `poisson_ratio__GULP_SLC_forcefield__ν_yx` | pool-wide | 135,805 | 120,165 | 3,822 | 11,818 | 0 | 0 | 0 | 0.289 ± 0.226 | formula ⚠ |
| `poisson_ratio__GULP_SLC_forcefield__ν_xy` | pool-wide | 135,804 | 120,165 | 3,822 | 11,817 | 0 | 0 | 0 | 0.29 ± 0.228 | formula ⚠ |
| `bulk_modulus_reuss__forcefield` | pool-wide | 135,756 | 120,129 | 3,816 | 11,811 | 0 | 0 | 0 | 48.083 ± 16.42 | formula ⚠ |
| `youngs_modulus__GULP_SLC_forcefield__stress_axis_z` | pool-wide | 135,751 | 120,120 | 3,821 | 11,810 | 0 | 0 | 0 | 76.915 ± 31.228 | formula ⚠ |
| `sound_velocity_longitudinal__forcefield` | pool-wide | 135,744 | 120,111 | 3,823 | 11,810 | 0 | 0 | 0 | 6654.46 ± 1063.096 | formula ⚠ |
| `dielectric_constant_total__forcefield` | gapped | 135,382 | 119,824 | 3,796 | 11,762 | 0 | 0 | 0 | 3.725 ± 0.7 | formula ⚠ |
| `youngs_modulus__GULP_SLC_forcefield__stress_axis_y` | pool-wide | 135,368 | 119,783 | 3,818 | 11,767 | 0 | 0 | 0 | 72.793 ± 31.659 | formula ⚠ |
| `youngs_modulus__GULP_SLC_forcefield__stress_axis_x` | pool-wide | 135,347 | 119,773 | 3,817 | 11,757 | 0 | 0 | 0 | 72.601 ± 31.4 | formula ⚠ |
| `shear_modulus_voigt__forcefield` | pool-wide | 134,123 | 118,654 | 3,780 | 11,689 | 0 | 0 | 0 | 28.947 ± 14.638 | formula ⚠ |
| `sound_velocity_transverse__forcefield` | pool-wide | 132,864 | 117,570 | 3,739 | 11,555 | 0 | 0 | 0 | 3617.826 ± 777.911 | formula ⚠ |
| `shear_modulus_vrh__forcefield` | pool-wide | 132,816 | 117,533 | 3,738 | 11,545 | 0 | 0 | 0 | 27.223 ± 17.495 | formula ⚠ |
| `shear_modulus_reuss__forcefield` | pool-wide | 130,785 | 115,730 | 3,668 | 11,387 | 0 | 0 | 0 | 25.706 ± 20.641 | formula ⚠ |
| `co2_uptake__GCMC__hMOF__0.01_bar` | porous | 127,434 | 109,413 | 7,563 | 10,458 | 0 | 0 | 0 | 0.108 ± 0.217 | chemsys |
| `co2_uptake__GCMC__hMOF__max_over_pressures` | porous | 127,434 | 109,421 | 7,563 | 10,450 | 0 | 0 | 0 | 5.053 ± 2.702 | chemsys |
| `vbm__gga` | gapped | 123,165 | 98,545 | 12,317 | 12,303 | 2,010 | 529 | 38,657 | 1.583 ± 2.329 | chemsys |
| `cbm__gga` | gapped | 123,164 | 98,551 | 12,310 | 12,303 | 2,013 | 623 | 38,653 | 3.608 ± 2.216 | chemsys |
| `decomposition_energy__r2SCAN_GNoME_vs_GNoME_hull` | pool-wide | 116,986 | 93,589 | 11,702 | 11,695 | 0 | 0 | 5 | 0.004 ± 0.015 | chemsys |
| `decomposition_energy__r2SCAN_GNoME` | pool-wide | 116,927 | 93,542 | 11,693 | 11,692 | 0 | 0 | 5 | -0.04 ± 0.059 | chemsys |
| `decomposition_energy__r2SCAN_GNoME_vs_MP_hull` | pool-wide | 116,927 | 93,542 | 11,693 | 11,692 | 0 | 0 | 5 | -0.04 ± 0.059 | chemsys |
| `decomposition_energy__r2SCAN_GNoME_vs_MP_OQMD_hull` | pool-wide | 116,927 | 93,542 | 11,693 | 11,692 | 0 | 0 | 5 | -0.03 ± 0.05 | chemsys |
| `predicted_synthesizable__other` | pool-wide | 94,797 | 75,838 | 9,480 | 9,479 | 3,181 | 0 | 376 | 0.0 ± 0.0 | chemsys |
| `dielectric_constant_electronic__gga-vdw` | gapped | 79,555 | 63,646 | 7,955 | 7,954 | 6,189 | 1,238 | 19,795 | 54.959 ± 65.238 | chemsys |
| `decomposition_energy__PBE__U__MP2026_equilibrium_reaction_energy` | pool-wide | 58,921 | 47,137 | 5,893 | 5,891 | 57 | 6 | 28,327 | -0.079 ± 0.247 | chemsys |
| `bulk_modulus_vrh__gga-vdw` | pool-wide | 42,841 | 34,273 | 4,284 | 4,284 | 3,002 | 261 | 11,792 | 89.742 ± 67.184 | chemsys |
| `poisson_ratio__OptB88vdW_ElaStic` | pool-wide | 42,792 | 34,234 | 4,279 | 4,279 | 3,000 | 289 | 11,774 | 0.332 ± 0.403 | chemsys |
| `shear_modulus_vrh__gga-vdw` | pool-wide | 40,625 | 32,504 | 4,059 | 4,062 | 2,875 | 323 | 11,629 | 42.218 ± 37.26 | chemsys |
| `power_factor__BoltzTraP_p-type` | pool-wide | 40,342 | 32,274 | 4,038 | 4,030 | 2,591 | 35 | 16,459 | 869.426 ± 923.911 | chemsys |
| `seebeck_coefficient__BoltzTraP_n-type` | pool-wide | 40,339 | 32,275 | 4,031 | 4,033 | 2,591 | 362 | 16,455 | -104.39 ± 135.116 | chemsys |
| `power_factor__BoltzTraP_n-type` | pool-wide | 40,337 | 32,270 | 4,035 | 4,032 | 2,591 | 101 | 16,460 | 902.243 ± 938.449 | chemsys |
| `seebeck_coefficient__BoltzTraP_p-type` | pool-wide | 40,336 | 32,270 | 4,034 | 4,032 | 2,587 | 329 | 16,459 | 160.263 ± 183.27 | chemsys |
| `largest_free_path_diameter__geometric` | pool-wide-biased-labels | 36,565 | 29,751 | 3,161 | 3,653 | 19,754 | 5,144 | 36,434 | 5.072 ± 3.452 | chemsys |
| `dielectric_constant_electronic__mbj` | gapped | 29,102 | 23,283 | 2,909 | 2,910 | 1,905 | 195 | 9,325 | 49.701 ± 74.076 | chemsys |
| `bulk_modulus_vrh__gga` | pool-wide | 28,988 | 23,200 | 2,891 | 2,897 | 5,651 | 393 | 14,442 | 102.793 ± 72.932 | chemsys |
| `shear_modulus_vrh__gga` | pool-wide | 28,046 | 22,437 | 2,805 | 2,804 | 5,561 | 589 | 14,099 | 50.86 ± 46.262 | chemsys |
| `pore_channel_count__geometric` | framework | 27,087 | 21,712 | 2,671 | 2,704 | 14,689 | 3,351 | 26,969 | 0.412 ± 0.698 | chemsys |
| `lattice_thermal_conductivity__gga` | pool-wide | 26,470 | 21,187 | 2,636 | 2,647 | 21,250 | 541 | 11,119 | 2.105 ± 11.554 | chemsys |
| `debye_temperature__gga` | pool-wide | 25,972 | 20,778 | 2,597 | 2,597 | 5,396 | 790 | 13,086 | 356.331 ± 203.495 | chemsys |
| `elastic_anisotropy__gga` | pool-wide | 24,405 | 19,524 | 2,443 | 2,438 | 81 | 0 | 12,017 | 3.77482049674771e+105 ± 2.5777564895128636e+107 | chemsys |
| `poisson_ratio__PBE__U__MP2026` | pool-wide | 24,381 | 19,508 | 2,438 | 2,435 | 81 | 34 | 12,014 | 0.303 ± 0.263 | chemsys |
| `has_imaginary_phonon__gga` | pool-wide | 22,699 | 18,160 | 2,273 | 2,266 | 7,073 | 1,244 | 2,926 | 0.672 ± 0.456 | chemsys |
| `phonon_min_frequency__gga` | pool-wide | 22,685 | 18,148 | 2,272 | 2,265 | 7,067 | 13 | 2,924 | -1.822 ± 8.605 | chemsys |
| `phonon_max_frequency__gga` | pool-wide | 22,675 | 18,143 | 2,266 | 2,266 | 7,066 | 9 | 2,919 | 31.119 ± 27.135 | chemsys |
| `bulk_modulus_reuss__gga` | pool-wide | 20,745 | 16,598 | 2,073 | 2,074 | 53 | 21 | 10,309 | 100.828 ± 73.833 | chemsys |
| `bulk_modulus_voigt__gga` | pool-wide | 20,744 | 16,597 | 2,073 | 2,074 | 53 | 15 | 10,308 | 104.292 ± 73.441 | chemsys |
| `shear_modulus_reuss__gga` | pool-wide | 20,744 | 16,596 | 2,075 | 2,073 | 53 | 27 | 10,307 | 47.417 ± 43.322 | chemsys |
| `shear_modulus_voigt__gga` | pool-wide | 20,744 | 16,596 | 2,075 | 2,073 | 53 | 24 | 10,308 | 54.755 ± 44.9 | chemsys |
| `sound_velocity_longitudinal__gga` | pool-wide | 20,744 | 16,596 | 2,075 | 2,073 | 53 | 26 | 10,308 | 4904.27 ± 1902.122 | chemsys |
| `sound_velocity_transverse__gga` | pool-wide | 20,743 | 16,595 | 2,075 | 2,073 | 53 | 26 | 10,309 | 2678.099 ± 1203.576 | chemsys |
| `framework_bond_dissociation_energy__other` | framework | 20,172 | 16,365 | 1,797 | 2,010 | 17 | 3 | 20,086 | -0.795 ± 1.646 | chemsys |
| `nmr_efg_max__gga-vdw` | pool-wide | 19,731 | 15,785 | 1,981 | 1,965 | 1,463 | 175 | 7,940 | 6.624126592671431e+22 ± 5.235820551084939e+22 | chemsys |
| `num_voltage_steps__gga` | ion-conducting | 19,280 | 15,424 | 1,930 | 1,926 | 2,089 | 395 | 2,630 | 1.306 ± 0.749 | chemsys |
| `max_voltage_step__gga` | ion-conducting | 19,277 | 15,424 | 1,927 | 1,926 | 2,088 | 366 | 2,630 | 0.195 ± 0.518 | chemsys |
| `electrode_stability_discharged__gga` | ion-conducting | 19,271 | 15,418 | 1,928 | 1,925 | 2,089 | 852 | 2,630 | 0.116 ± 0.207 | chemsys |
| `electrode_stability_charged__gga` | ion-conducting | 19,270 | 15,416 | 1,928 | 1,926 | 2,089 | 105 | 2,627 | 0.103 ± 0.265 | chemsys |
| `capacity_volumetric__gga` | ion-conducting | 19,263 | 15,412 | 1,929 | 1,922 | 2,089 | 899 | 2,626 | 593.491 ± 552.822 | chemsys |
| `capacity_gravimetric__gga` | ion-conducting | 19,261 | 15,409 | 1,929 | 1,923 | 2,089 | 839 | 2,625 | 156.199 ± 168.723 | chemsys |
| `energy_density_gravimetric__gga` | ion-conducting | 19,261 | 15,410 | 1,928 | 1,923 | 2,089 | 1,196 | 2,628 | 362.008 ± 336.355 | chemsys |
| `average_voltage__gga` | ion-conducting | 19,260 | 15,409 | 1,928 | 1,923 | 2,089 | 1,268 | 2,629 | 2.475 ± 1.694 | chemsys |
| `electrode_volume_change__gga` | ion-conducting | 19,260 | 15,409 | 1,928 | 1,923 | 2,089 | 77 | 2,628 | 0.276 ± 1.781 | chemsys |
| `energy_density_volumetric__gga` | ion-conducting | 19,260 | 15,408 | 1,927 | 1,925 | 2,087 | 1,224 | 2,627 | 1335.257 ± 1214.326 | chemsys |
| `spillage__gga-vdw` | pool-wide | 19,104 | 15,291 | 1,903 | 1,910 | 592 | 134 | 7,190 | 0.575 ± 0.658 | chemsys |
| `heat_of_formation__gllbsc` | pool-wide | 18,925 | 15,141 | 1,892 | 1,892 | 24 | 21 | 46 | 1.478 ± 0.737 | chemsys |
| `slme__gga-vdw` | gapped | 16,809 | 13,448 | 1,681 | 1,680 | 1,174 | 187 | 6,612 | 11.218 ± 12.18 | chemsys |
| `refractive_index__gga` | gapped | 16,652 | 13,323 | 1,666 | 1,663 | 103 | 2 | 7,266 | 2.373 ± 1.272 | chemsys |
| `dielectric_constant_ionic__gga` | gapped | 14,069 | 11,257 | 1,411 | 1,401 | 85 | 0 | 7,094 | 12.819 ± 42.52 | chemsys |
| `dielectric_constant_total__gga` | gapped | 14,052 | 11,242 | 1,409 | 1,401 | 84 | 2 | 7,085 | 20.078 ± 51.087 | chemsys |
| `dielectric_constant_electronic__gga` | gapped | 14,048 | 11,239 | 1,408 | 1,401 | 84 | 0 | 7,083 | 6.81 ± 17.553 | chemsys |
| `heat_capacity__pbesol` | pool-wide | 13,531 | 10,827 | 1,351 | 1,353 | 177 | 0 | 2,809 | 189.453 ± 134.738 | chemsys |
| `structure_prediction_r_factor__geometric` | pool-wide | 12,401 | 10,009 | 1,413 | 979 | 0 | 0 | 0 | 0.012 ± 0.004 | chemsys |
| `thermal_conductivity__gga` | pool-wide | 10,554 | 8,445 | 1,056 | 1,053 | 120 | 18 | 5,811 | 7.824 ± 14.115 | chemsys |
| `thermal_expansion__gga` | pool-wide | 10,552 | 8,443 | 1,054 | 1,055 | 120 | 9 | 5,809 | 0.0 ± 0.0 | chemsys |
| `poisson_ratio__PBE_AEL__AFLOW` | pool-wide | 10,521 | 8,417 | 1,054 | 1,050 | 120 | 28 | 5,794 | 0.29 ± 0.061 | chemsys |
| `piezoelectric_modulus__dfpt-phonon` | gapped | 8,734 | 6,988 | 874 | 872 | 495 | 37 | 3,871 | 0.192 ± 0.561 | chemsys |
| `gllbsc_derivative_discontinuity__gllbsc` | gapped | 8,226 | 6,581 | 824 | 821 | 524 | 47 | 3,274 | 0.969 ± 0.656 | chemsys |
| `eos_bulk_modulus__dfpt-phonon` | pool-wide | 8,050 | 6,440 | 805 | 805 | 181 | 25 | 1,268 | 107.95 ± 59.745 | chemsys |
| `ar_uptake__GCMC_87K__1bar_TraPPE` | porous | 7,894 | 6,386 | 720 | 788 | 82 | 8 | 7,877 | 11.246 ± 10.338 | chemsys |
| `lattice_thermal_conductivity_coherence__gga` | pool-wide | 7,686 | 6,149 | 770 | 767 | 686 | 17 | 1,386 | 0.221 ± 0.317 | chemsys |
| `lattice_thermal_conductivity_particle__gga` | pool-wide | 7,670 | 6,137 | 766 | 767 | 683 | 4 | 1,383 | 21.715 ± 388.834 | chemsys |
| `born_effective_charge_max__pbesol` | pool-wide | 7,554 | 6,046 | 753 | 755 | 112 | 2 | 1,861 | 3.981 ± 1.874 | chemsys |
| `effective_mass_electron__transport-postproc` | gapped | 6,515 | 5,212 | 653 | 650 | 249 | 20 | 2,964 | 0.899 ± 2.33 | chemsys |
| `effective_mass_hole__transport-postproc` | gapped | 6,502 | 5,204 | 649 | 649 | 250 | 33 | 2,965 | 1.504 ± 2.281 | chemsys |
| `continuous_symmetry_measure__other` | pool-wide | 6,104 | 4,884 | 610 | 610 | 65 | 6 | 3,167 | 0.964 ± 2.214 | chemsys |
| `magnetic_polarization__gga` | magnetic | 5,307 | 4,253 | 527 | 527 | 41 | 0 | 839 | 0.495 ± 0.573 | chemsys |
| `decomposition_energy__PBE__NOVOMAG` | pool-wide | 5,305 | 4,253 | 523 | 529 | 41 | 4 | 839 | -0.238 ± 0.32 | chemsys |
| `n2_uptake__GCMC_77K__1bar_TraPPE` | porous | 4,909 | 3,940 | 526 | 443 | 60 | 4 | 4,903 | 8.715 ± 7.901 | chemsys |
| `exfoliation_energy__gga` | layered | 4,667 | 3,734 | 469 | 464 | 19 | 0 | 209 | 147.804 ± 187.686 | chemsys |
| `work_function__gga` | surface-derived | 3,726 | 2,987 | 367 | 372 | 267 | 216 | 193 | 4.826 ± 1.097 | chemsys |
| `tc_superconducting__experiment` | synthesized-only | 3,119 | 2,497 | 320 | 302 | 1,926 | 350 | 1,865 | 6.935 ± 14.742 | chemsys |
| `interlayer_binding_energy__gga-vdw` | layered | 2,963 | 2,371 | 296 | 296 | 12 | 6 | 220 | 0.034 ± 0.027 | chemsys |
| `birefringence__lda` | gapped | 2,565 | 2,054 | 257 | 254 | 54 | 2 | 194 | 0.144 ± 0.237 | chemsys |
| `shg_coefficient__lda` | gapped | 2,562 | 2,050 | 257 | 255 | 54 | 3 | 194 | 14.451 ± 27.725 | chemsys |
| `h2_uptake__GCMC_130K__100bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | 2,038 | 329 | 180 | 0 | 0 | 0 | 25.144 ± 4.758 | chemsys |
| `h2_uptake__GCMC_160K__5bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | 2,042 | 324 | 181 | 0 | 0 | 0 | 1.746 ± 0.991 | chemsys |
| `h2_uptake__GCMC_200K__100bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | 2,042 | 324 | 181 | 0 | 0 | 0 | 13.436 ± 2.094 | chemsys |
| `h2_uptake__GCMC_243K__100bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | 2,042 | 324 | 181 | 0 | 0 | 0 | 10.045 ± 1.391 | chemsys |
| `h2_uptake__GCMC_77K__6bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | 2,038 | 329 | 180 | 0 | 0 | 0 | 16.238 ± 9.457 | chemsys |
| `kr_uptake__GCMC_298K__1bar_in_Xe_Kr_y_0.8_Talu_et_al.__Colloids_Surf_A_2001_187-1` | porous | 2,547 | 2,039 | 328 | 180 | 0 | 0 | 0 | 0.538 ± 0.219 | chemsys |
| `xe_uptake__GCMC_298K__1bar_in_Xe_Kr_y_0.2_Talu_et_al.__Colloids_Surf_A_2001_187-1` | porous | 2,547 | 2,039 | 327 | 181 | 0 | 0 | 0 | 0.55 ± 0.618 | chemsys |
| `n2_uptake__GCMC_77K__0.999bar_TraPPE` | porous | 2,501 | 2,039 | 212 | 250 | 23 | 0 | 2,489 | 8.963 ± 7.951 | chemsys |
| `migration_barrier__BVSE_1D_Na` | ion-conducting | 2,118 | 1,695 | 213 | 210 | 279 | 43 | 2,116 | 2.329 ± 2.347 | chemsys |
| `migration_barrier__BVSE_2D_Na` | ion-conducting | 2,112 | 1,690 | 212 | 210 | 280 | 48 | 2,110 | 3.227 ± 2.914 | chemsys |
| `migration_barrier__BVEL_1D_Na` | ion-conducting | 2,103 | 1,683 | 211 | 209 | 275 | 54 | 2,101 | 3.487 ± 3.258 | chemsys |
| `migration_barrier__BVEL_2D_Na` | ion-conducting | 2,082 | 1,666 | 208 | 208 | 275 | 56 | 2,080 | 4.675 ± 3.956 | chemsys |
| `migration_barrier__BVSE_3D_Na` | ion-conducting | 2,024 | 1,620 | 202 | 202 | 261 | 37 | 2,022 | 4.927 ± 4.428 | chemsys |
| `migration_barrier__BVEL_3D_Na` | ion-conducting | 1,857 | 1,486 | 188 | 183 | 233 | 51 | 1,855 | 6.113 ± 4.959 | chemsys |
| `migration_barrier__BVSE_1D_Li` | ion-conducting | 1,556 | 1,245 | 156 | 155 | 245 | 34 | 1,555 | 1.211 ± 1.053 | chemsys |
| `migration_barrier__BVSE_2D_Li` | ion-conducting | 1,556 | 1,245 | 156 | 155 | 245 | 28 | 1,555 | 1.658 ± 1.332 | chemsys |
| `migration_barrier__BVEL_1D_Li` | ion-conducting | 1,555 | 1,244 | 157 | 154 | 245 | 46 | 1,554 | 1.581 ± 1.215 | chemsys |
| `migration_barrier__BVEL_2D_Li` | ion-conducting | 1,555 | 1,244 | 157 | 154 | 245 | 41 | 1,554 | 2.003 ± 1.486 | chemsys |
| `migration_barrier__BVSE_3D_Li` | ion-conducting | 1,544 | 1,236 | 155 | 153 | 244 | 24 | 1,543 | 2.428 ± 2.216 | chemsys |
| `migration_barrier__BVEL_3D_Li` | ion-conducting | 1,539 | 1,233 | 153 | 153 | 244 | 36 | 1,538 | 2.846 ± 2.518 | chemsys |
| `magnetic_anisotropy_constant__gga` | magnetic | 1,487 | 1,194 | 146 | 147 | 16 | 1 | 234 | 0.144 ± 1.643 | chemsys |
| `relative_energy_to_diamond__other` | pool-wide | 1,451 | 1,161 | 176 | 114 | 3 | 0 | 13 | 0.732 ± 0.32 | formula ⚠ |
| `phonon_log_average_frequency__other` | pool-wide | 1,430 | 1,144 | 144 | 142 | 85 | 20 | 298 | 195.658 ± 143.721 | chemsys |
| `electron_phonon_coupling__other` | pool-wide | 1,429 | 1,144 | 143 | 142 | 85 | 17 | 298 | 1.005 ± 1.533 | chemsys |
| `hardness_vickers__other` | pool-wide | 1,412 | 1,131 | 171 | 110 | 3 | 1 | 11 | 48.014 ± 28.442 | formula ⚠ |
| `mohs_hardness__experiment` | synthesized-only | 1,183 | 948 | 117 | 118 | 10 | 5 | 1,130 | 3.817 ± 1.545 | chemsys |
| `measurement_pressure__experiment` | synthesized-only | 1,092 | 875 | 110 | 107 | 401 | 162 | 874 | 6.003 ± 17.116 | chemsys |
| `dynamically_stable__gga` | pool-wide | 1,023 | 819 | 102 | 102 | 26 | 0 | 59 | 1.0 ± 0.0 | chemsys |
| `layer_group_number__other` | pool-wide | 1,022 | 818 | 102 | 102 | 26 | 0 | 59 | 59.113 ± 20.416 | chemsys |
| `bulk_modulus_eos__gga` | pool-wide | 502 | 403 | 54 | 45 | 0 | 0 | 290 | 87.559 ± 77.252 | chemsys |
| `bulk_modulus_pressure_derivative__gga` | pool-wide | 501 | 401 | 50 | 50 | 0 | 0 | 289 | 3.311 ± 0.572 | chemsys |
| `d_band_center__gga` | surface-derived | 483 | 391 | 44 | 48 | 483 | 230 | 0 | -3.905 ± 2.587 | chemsys |

---

## 06 适用域：不是每个性质都对每个结构有意义

**这是"补全所有结构缺失的性质"里最容易出错的一步，也是第一版流水线完全漏掉的一步。**

`co2_uptake` 是 GCMC 吸附量：对多孔骨架有意义，对致密金属间化合物没有 ——
不是"吸附量为零"，而是这个量根本没有定义，因为 GCMC 的模拟胞里没地方插入分子。
它的训练集 100% 是 MOF（287,466 个，密度中位数 0.73 g/cm³，**每一个都含碳**），
而池子是 1354 万个结构、密度中位数约 7 g/cm³。
拿它全池打分会产出约 1300 万个看起来像数据的数字。

同样的问题以不同边界覆盖了三分之一的语料：
**176 个任务里 63 个的训练集 >90% 属于同一个 `material_family`**，
`bulk_modulus_vrh__forcefield` 只覆盖 **2 个化学体系**。

### 两个独立来源描述每个任务的域

`applicability.py`：

- **声明域**（`DECLARED`，手写）—— 这个性质物理上要求结构"是什么"。
  手写是因为它不可能从数字里推出来。

  | 域 | 含义 | 任务数 |
  |---|---|--:|
  | `pool-wide` | 任何周期晶体都适用 | 78 |
  | `porous` | 需要可及孔道（吸附量、吸附热、工作容量） | 25 |
  | `ion-conducting` | 需要可迁移工作离子（迁移势垒、电极量） | 22 |
  | `gapped` | 金属下无定义或退化（有效质量、折射率、介电、SLME） | 15 |
  | `pool-wide-biased-labels` | 性质无限制，只是标签恰好来自一个族 | 7 |
  | `synthesized-only` | 标签存在只因为有人做过样品 | 5 |
  | `framework` | 需要节点-连接体 / 四面体骨架拓扑 | 4 |
  | `magnetic` | 需要磁有序基态 | 2 |
  | `surface-derived` | 是表面/界面量，池里存的是体相胞 | 2 |
  | `layered` | 需要范德华间隙 | 2 |

  `pool-wide-biased-labels` 是个刻意区分出来的类别：几何孔道描述符
  （`void_fraction`、`pore_limiting_diameter`、`surface_area_gravimetric`…）
  **不受域限制** —— zeo++ 对任何周期结构都能算出一个良定义（通常接近 0）的答案。
  它们只是恰好只在多孔材料上被算过。这是**采样偏置，不是域限制**，两者要分开处理。

- **经验域**（`profile()`，实测）—— 训练集实际覆盖了什么：族分布、化学体系数、
  密度与原子数的 p99，以及 `always_elements` ——
  **每一个**训练结构都含的元素，这是最硬的约束。
  `co2_uptake` 从没见过不含碳的材料；`migration_barrier__*_Li` 从没见过不含 Li 的。

两者不一致本身就有信息：声明为 pool-wide 但标签集中在一个族，
说明是**标签有偏**而不是性质受限，`strict` 门控会据此把模型限制在它见过的族内。

### 门控结果

```bash
$PY scripts/ml/prediction_sets.py --export data/ml/export \
    --datasets data/ml/datasets --out data/ml/predict --gate strict
```

| 可预测范围 | 任务数 |
|---|--:|
| ≥ 90% 池 | 45 |
| 50–90% | 22 |
| 10–50% | 40 |
| 1–10% | 39 |
| < 1% | 30 |

**109 / 176 个任务的可预测范围不到池的一半。**

总预测量 **1,105,593,143**，而不是无视适用域时的 176 × 14,590,485 = 2,567,925,360
—— **相差 2.35 倍**，差掉的那部分基本都是物理上无意义的输出。

几个代表：

| 任务 | 已有标签 | 可预测 | 占池 |
|---|--:|--:|--:|
| `co2_uptake__GCMC_0.15bar_298K` | 287,466 | **190,084** | 1.40% |
| `exfoliation_energy__gga` | 4,667 | **149,409** | 1.10% |
| `migration_barrier__BVSE_3D_Li` | 1,544 | **686,636** | 5.07% |
| `bulk_modulus_vrh__forcefield` | 135,817 | **474** | 0.00% |

最后一行值得停一下：池里只有 136,305 个沸石，其中 135,817 个已经有标签。
**这个模型在它验证过的域内几乎没有东西可补。**
它的 13,370,734 个"缺失值"全是域外的。

### 两档门控

- **`strict`（默认）** —— 只凭索引里已有的证据放行：族属于声明域允许的集合、
  含全部 `always_elements`、不超过训练集 `n_atoms` 的 p99。
  声明为 pool-wide 但标签 >90% 集中于一族的，也限制在该族内。
  高精度，会漏放 —— 一个来自 Materials Project 的多孔骨架没有族标签，会被拒。
- **`wide`** —— 额外放行密度落在训练带内的无族标结构。
  **这是代理，且有已知的错误方向**：金属锂密度 0.53 g/cm³，
  会通过多孔性密度门但根本没有孔。只能用来做候选筛选清单，不能直接发布数字。

严格的多孔性门控是跑一遍 zeo++（孔径限制直径 vs 吸附质动力学直径 ——
CO₂ 3.3 Å、H₂ 2.9 Å），本流水线**没有**做；`--gate wide` 的存在就是为了在那之前
先出候选清单。每份输出都记录了是哪档门控产生的。

### 待定门控与无法门控的

`gapped` 和 `magnetic` 不是"无法门控"：索引里有 `pbes_gap` 和 `total_magnetization`
（第二版 `export_targets.py` 才把这两列导出来），所以**已知值的部分直接筛**，
只有值未知的部分待定 —— 21 个任务、累计 95,583,739 个结构，
需要先把带隙/磁矩预测出来再筛。这是个自然的两阶段流程。

剩下 7 个任务索引里确实没有列可以收窄，它们的"可预测数"是**上界**而不是可信范围，
输出里带 `warning` 标记：

- `tc_superconducting`、`mohs_hardness`、`measurement_temperature` 等
  （`synthesized-only`）—— 标签缺失通常是"没人测过"而不是"不适用"，无结构门控。
- `magnetic_polarization`、`magnetic_anisotropy_constant` ——
  池里大部分结构的磁矩未知或非零，门控放行 55–59%。

还有一个反直觉的情况值得记下来：`migration_barrier__*_Na` 的 `always_elements` 是**空的**。
因为 BVSE 算的是**假想**插入离子的势垒，不含 Na 的骨架也是合法训练行。
所以这里退回到"含至少一种工作离子（Li/Na/K/Mg/Ca/Zn/Al…）"的门控，
而不是把整个池放行。

### 逐任务适用域（全部 176 个，按可预测数升序）

`⚠` = 声明域受限但索引里没有能收窄它的列，该数字是上界。

| 任务 | 声明域 | 已有标签 | 可预测 | 占池 | 训练集主导族 | 必含元素 |
|---|---|--:|--:|--:|---|---|
| `relative_energy_to_diamond__other` | pool-wide | 1,451 | **77** | 0.00% | carbon-allotrope 100% | C |
| `hardness_vickers__other` | pool-wide | 1,412 | **112** | 0.00% | carbon-allotrope 100% | C |
| `dielectric_constant_electronic__forcefield` | gapped | 135,870 | **314** | 0.00% | zeolite 100% | O+Si |
| `poisson_ratio__GULP_SLC_forcefield__ν_zy` | pool-wide | 135,844 | **441** | 0.00% | zeolite 100% | O+Si |
| `poisson_ratio__GULP_SLC_forcefield__ν_yz` | pool-wide | 135,839 | **444** | 0.00% | zeolite 100% | O+Si |
| `poisson_ratio__GULP_SLC_forcefield__ν_zx` | pool-wide | 135,840 | **445** | 0.00% | zeolite 100% | O+Si |
| `poisson_ratio__GULP_SLC_forcefield__ν_xz` | pool-wide | 135,834 | **451** | 0.00% | zeolite 100% | O+Si |
| `bulk_modulus_voigt__forcefield` | pool-wide | 135,815 | **470** | 0.00% | zeolite 100% | O+Si |
| `bulk_modulus_vrh__forcefield` | pool-wide | 135,817 | **474** | 0.00% | zeolite 100% | — |
| `poisson_ratio__GULP_SLC_forcefield__ν_yx` | pool-wide | 135,805 | **478** | 0.00% | zeolite 100% | O+Si |
| `poisson_ratio__GULP_SLC_forcefield__ν_xy` | pool-wide | 135,804 | **481** | 0.00% | zeolite 100% | O+Si |
| `bulk_modulus_reuss__forcefield` | pool-wide | 135,756 | **529** | 0.00% | zeolite 100% | O+Si |
| `youngs_modulus__GULP_SLC_forcefield__stress_axis_z` | pool-wide | 135,751 | **535** | 0.00% | zeolite 100% | O+Si |
| `sound_velocity_longitudinal__forcefield` | pool-wide | 135,744 | **542** | 0.00% | zeolite 100% | O+Si |
| `framework_density__forcefield` | framework | 135,877 | **773** | 0.01% | zeolite 100% | O+Si |
| `energy_per_t_atom__forcefield` | framework | 135,870 | **780** | 0.01% | zeolite 100% | O+Si |
| `dielectric_constant_total__forcefield` | gapped | 135,382 | **800** | 0.01% | zeolite 100% | O+Si |
| `youngs_modulus__GULP_SLC_forcefield__stress_axis_y` | pool-wide | 135,368 | **910** | 0.01% | zeolite 100% | O+Si |
| `youngs_modulus__GULP_SLC_forcefield__stress_axis_x` | pool-wide | 135,347 | **932** | 0.01% | zeolite 100% | O+Si |
| `shear_modulus_voigt__forcefield` | pool-wide | 134,123 | **2,159** | 0.02% | zeolite 100% | O+Si |
| `sound_velocity_transverse__forcefield` | pool-wide | 132,864 | **3,413** | 0.03% | zeolite 100% | O+Si |
| `shear_modulus_vrh__forcefield` | pool-wide | 132,816 | **3,467** | 0.03% | zeolite 100% | — |
| `shear_modulus_reuss__forcefield` | pool-wide | 130,785 | **5,491** | 0.04% | zeolite 100% | O+Si |
| `largest_cavity_diameter__geometric` | pool-wide-biased-labels | 472,808 | **5,690** | 0.04% | mof 100% | — |
| `pore_limiting_diameter__geometric` | pool-wide-biased-labels | 472,809 | **5,714** | 0.04% | mof 100% | — |
| `void_fraction__geometric` | pool-wide-biased-labels | 454,589 | **23,823** | 0.18% | mof 100% | — |
| `surface_area_gravimetric__geometric` | pool-wide-biased-labels | 429,536 | **48,234** | 0.36% | mof 100% | — |
| `dynamically_stable__gga` | pool-wide | 1,023 | **100,787** | 0.74% | 2d-material 100% | — |
| `layer_group_number__other` | pool-wide | 1,022 | **100,788** | 0.74% | 2d-material 100% | — |
| `work_function__gga` | surface-derived | 3,726 | **121,668** | 0.90% | 2d-material 94% | — |
| `exfoliation_energy__gga` | layered | 4,667 | **149,409** | 1.10% | 2d-material 100% | — |
| `interlayer_binding_energy__gga-vdw` | layered | 2,963 | **151,625** | 1.12% | 2d-material 100% | — |
| `pore_volume__geometric` | pool-wide-biased-labels | 299,244 | **178,434** | 1.32% | mof 100% | — |
| `co2_n2_selectivity__gcmc` | porous | 287,466 | **190,084** | 1.40% | mof 100% | C |
| `co2_uptake__GCMC_0.10bar_363K` | porous | 287,466 | **190,084** | 1.40% | mof 100% | C |
| `co2_uptake__GCMC_0.15bar_298K` | porous | 287,466 | **190,084** | 1.40% | mof 100% | C |
| `co2_uptake__GCMC_binary_CO2_N2_0.15bar_298K` | porous | 287,466 | **190,084** | 1.40% | mof 100% | C |
| `n2_uptake__GCMC_binary_CO2_N2_0.85bar_298K` | porous | 287,466 | **190,084** | 1.40% | mof 100% | C |
| `co2_uptake__GCMC_0.70bar_413K` | porous | 287,420 | **190,122** | 1.40% | mof 100% | C |
| `working_capacity_temperature_swing__GCMC_TSA_0.15bar_298K_-__0.70bar_413K` | porous | 287,322 | **190,215** | 1.40% | mof 100% | C |
| `working_capacity_vacuum_swing__GCMC_VSA` | porous | 287,322 | **190,227** | 1.41% | mof 100% | C |
| `n2_heat_of_adsorption__GCMC_binary_CO2_N2_0.85bar_298K` | porous | 285,541 | **192,001** | 1.42% | mof 100% | C |
| `co2_heat_of_adsorption__GCMC_0.70bar_413K` | porous | 285,479 | **192,063** | 1.42% | mof 100% | C |
| `co2_heat_of_adsorption__GCMC_0.15bar_298K` | porous | 285,377 | **192,173** | 1.42% | mof 100% | C |
| `co2_heat_of_adsorption__GCMC_0.10bar_363K` | porous | 285,363 | **192,179** | 1.42% | mof 100% | C |
| `co2_heat_of_adsorption__GCMC_binary_CO2_N2_0.15bar_298K` | porous | 284,982 | **192,568** | 1.42% | mof 100% | C |
| `surface_area_volumetric__geometric` | pool-wide-biased-labels | 166,920 | **304,598** | 2.25% | mof 100% | — |
| `co2_uptake__GCMC__hMOF__max_over_pressures` | porous | 127,434 | **305,648** | 2.26% | mof 100% | C+O |
| `co2_uptake__GCMC__hMOF__0.01_bar` | porous | 127,434 | **305,661** | 2.26% | mof 100% | C+O |
| `d_band_center__gga` | surface-derived | 483 | **426,828** | 3.15% | mof 100% | C |
| `largest_free_path_diameter__geometric` | pool-wide-biased-labels | 36,565 | **440,472** | 3.25% | mof 100% | — |
| `pore_channel_count__geometric` | framework | 27,087 | **587,058** | 4.33% | mof 100% | — |
| `framework_bond_dissociation_energy__other` | framework | 20,172 | **594,169** | 4.39% | mof 100% | — |
| `ar_uptake__GCMC_87K__1bar_TraPPE` | porous | 7,894 | **605,659** | 4.47% | mof 100% | — |
| `n2_uptake__GCMC_77K__1bar_TraPPE` | porous | 4,909 | **608,085** | 4.49% | mof 100% | — |
| `n2_uptake__GCMC_77K__0.999bar_TraPPE` | porous | 2,501 | **609,696** | 4.50% | mof 100% | — |
| `h2_uptake__GCMC_130K__100bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | **610,936** | 4.51% | mof 100% | — |
| `h2_uptake__GCMC_77K__6bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | **610,936** | 4.51% | mof 100% | — |
| `h2_uptake__GCMC_160K__5bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | **610,937** | 4.51% | mof 100% | — |
| `h2_uptake__GCMC_200K__100bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | **610,937** | 4.51% | mof 100% | — |
| `h2_uptake__GCMC_243K__100bar_Michels-Degraaff-Tenseldam_with_Darkrim-` | porous | 2,547 | **610,937** | 4.51% | mof 100% | — |
| `kr_uptake__GCMC_298K__1bar_in_Xe_Kr_y_0.8_Talu_et_al.__Colloids_Surf_A_2001_187-1` | porous | 2,547 | **610,937** | 4.51% | mof 100% | — |
| `xe_uptake__GCMC_298K__1bar_in_Xe_Kr_y_0.2_Talu_et_al.__Colloids_Surf_A_2001_187-1` | porous | 2,547 | **610,937** | 4.51% | mof 100% | — |
| `migration_barrier__BVSE_1D_Li` | ion-conducting | 1,556 | **686,624** | 5.07% | — | Li |
| `migration_barrier__BVSE_2D_Li` | ion-conducting | 1,556 | **686,624** | 5.07% | — | Li |
| `migration_barrier__BVEL_1D_Li` | ion-conducting | 1,555 | **686,625** | 5.07% | — | Li |
| `migration_barrier__BVEL_2D_Li` | ion-conducting | 1,555 | **686,625** | 5.07% | — | Li |
| `migration_barrier__BVSE_3D_Li` | ion-conducting | 1,544 | **686,636** | 5.07% | — | Li |
| `migration_barrier__BVEL_3D_Li` | ion-conducting | 1,539 | **686,641** | 5.07% | — | Li |
| `total_energy_per_atom__gga` | pool-wide | 11,375,665 | **1,439,238** | 10.63% | — | — |
| `formation_energy_per_atom__gga` | pool-wide | 9,672,505 | **3,122,521** | 23.06% | — | — |
| `piezoelectric_modulus__dfpt-phonon` | gapped | 8,734 | **4,514,212** | 33.33% | — | — |
| `dielectric_constant_electronic__mbj` | gapped | 29,102 | **4,611,638** | 34.05% | — | — |
| `band_gap_direct__gga` | gapped | 5,828,018 | **4,667,096** | 34.46% | — | — |
| `dielectric_constant_electronic__gga-vdw` | gapped | 79,555 | **4,740,095** | 35.00% | — | — |
| `slme__gga-vdw` | gapped | 16,809 | **4,742,934** | 35.02% | — | — |
| `effective_mass_electron__transport-postproc` | gapped | 6,515 | **4,744,185** | 35.03% | — | — |
| `effective_mass_hole__transport-postproc` | gapped | 6,502 | **4,744,194** | 35.03% | — | — |
| `heat_of_formation__gllbsc` | pool-wide | 18,925 | **4,768,745** | 35.21% | — | — |
| `spacegroup_number__gga` | pool-wide | 7,919,120 | **4,779,301** | 35.29% | — | — |
| `gllbsc_derivative_discontinuity__gllbsc` | gapped | 8,226 | **4,813,991** | 35.55% | — | — |
| `total_magnetization__gga` | pool-wide | 7,972,636 | **4,855,604** | 35.85% | — | — |
| `dielectric_constant_ionic__gga` | gapped | 14,069 | **4,899,290** | 36.18% | — | — |
| `dielectric_constant_total__gga` | gapped | 14,052 | **4,899,291** | 36.18% | — | — |
| `dielectric_constant_electronic__gga` | gapped | 14,048 | **4,899,293** | 36.18% | — | — |
| `num_voltage_steps__gga` | ion-conducting | 19,280 | **4,943,290** | 36.50% | — | — |
| `max_voltage_step__gga` | ion-conducting | 19,277 | **4,943,293** | 36.50% | — | — |
| `electrode_stability_discharged__gga` | ion-conducting | 19,271 | **4,943,296** | 36.50% | — | — |
| `electrode_stability_charged__gga` | ion-conducting | 19,270 | **4,943,297** | 36.50% | — | — |
| `capacity_gravimetric__gga` | ion-conducting | 19,261 | **4,943,299** | 36.50% | — | — |
| `capacity_volumetric__gga` | ion-conducting | 19,263 | **4,943,300** | 36.50% | — | — |
| `electrode_volume_change__gga` | ion-conducting | 19,260 | **4,943,301** | 36.50% | — | — |
| `average_voltage__gga` | ion-conducting | 19,260 | **4,943,306** | 36.50% | — | — |
| `energy_density_volumetric__gga` | ion-conducting | 19,260 | **4,943,306** | 36.50% | — | — |
| `energy_density_gravimetric__gga` | ion-conducting | 19,261 | **4,943,308** | 36.50% | — | — |
| `birefringence__lda` | gapped | 2,565 | **4,970,119** | 36.70% | — | — |
| `shg_coefficient__lda` | gapped | 2,562 | **4,970,120** | 36.70% | — | — |
| `refractive_index__gga` | gapped | 16,652 | **5,026,198** | 37.11% | — | — |
| `migration_barrier__BVSE_1D_Na` | ion-conducting | 2,118 | **5,051,085** | 37.30% | — | — |
| `migration_barrier__BVSE_2D_Na` | ion-conducting | 2,112 | **5,051,091** | 37.30% | — | — |
| `migration_barrier__BVEL_1D_Na` | ion-conducting | 2,103 | **5,051,100** | 37.30% | — | — |
| `migration_barrier__BVEL_2D_Na` | ion-conducting | 2,082 | **5,051,121** | 37.30% | — | — |
| `migration_barrier__BVSE_3D_Na` | ion-conducting | 2,024 | **5,051,178** | 37.30% | — | — |
| `migration_barrier__BVEL_3D_Na` | ion-conducting | 1,857 | **5,051,345** | 37.30% | — | — |
| `band_gap__gga` | pool-wide | 7,569,867 | **5,353,202** | 39.53% | — | — |
| `energy_above_hull__gga` | pool-wide | 7,218,674 | **5,575,402** | 41.17% | — | — |
| `cbm__gga` | gapped | 123,164 | **5,584,302** | 41.23% | — | — |
| `vbm__gga` | gapped | 123,165 | **5,584,302** | 41.23% | — | — |
| `is_gap_direct__gga` | gapped | 243,137 | **5,584,800** | 41.24% | — | — |
| `dos_at_fermi__gga` | pool-wide | 5,869,827 | **6,849,518** | 50.58% | — | — |
| `phase_separation_energy__gga` | pool-wide | 5,824,704 | **6,863,556** | 50.68% | — | — |
| `magnetic_anisotropy_constant__gga` | magnetic ⚠ | 1,487 | **7,508,685** | 55.44% | — | — |
| `magnetic_polarization__gga` | magnetic ⚠ | 5,307 | **8,056,149** | 59.48% | — | — |
| `phonon_log_average_frequency__other` | pool-wide | 1,430 | **9,085,321** | 67.08% | — | — |
| `electron_phonon_coupling__other` | pool-wide | 1,429 | **9,085,322** | 67.08% | — | — |
| `max_residual_force__gga` | pool-wide | 2,003,830 | **9,757,851** | 72.05% | — | — |
| `max_residual_stress__gga` | pool-wide | 2,003,831 | **9,757,895** | 72.05% | — | — |
| `density__gga` | pool-wide | 2,274,200 | **9,831,445** | 72.59% | — | — |
| `volume_per_atom__gga` | pool-wide | 2,273,671 | **9,831,768** | 72.59% | — | — |
| `nmr_efg_max__gga-vdw` | pool-wide | 19,731 | **11,722,166** | 86.55% | — | — |
| `magnetization_per_atom__gga` | pool-wide | 937,519 | **11,786,868** | 87.03% | — | — |
| `decomposition_energy__PBE_GNoME_vs_GNoME_hull` | pool-wide | 554,056 | **11,888,327** | 87.78% | — | — |
| `decomposition_energy__PBE_GNoME_vs_MP_OQMD_hull` | pool-wide | 553,778 | **11,888,603** | 87.78% | — | — |
| `decomposition_energy__PBE_GNoME_vs_MP_hull` | pool-wide | 553,680 | **11,888,692** | 87.78% | — | — |
| `decomposition_energy__PBE_GNoME` | pool-wide | 553,500 | **11,888,874** | 87.78% | — | — |
| `bulk_modulus_vrh__gga-vdw` | pool-wide | 42,841 | **12,018,322** | 88.74% | — | — |
| `poisson_ratio__OptB88vdW_ElaStic` | pool-wide | 42,792 | **12,018,369** | 88.74% | — | — |
| `shear_modulus_vrh__gga-vdw` | pool-wide | 40,625 | **12,020,532** | 88.76% | — | — |
| `spillage__gga-vdw` | pool-wide | 19,104 | **12,041,772** | 88.91% | — | — |
| `bulk_modulus_eos__gga` | pool-wide | 502 | **12,083,509** | 89.22% | — | — |
| `bulk_modulus_pressure_derivative__gga` | pool-wide | 501 | **12,083,510** | 89.22% | — | — |
| `born_effective_charge_max__pbesol` | pool-wide | 7,554 | **12,118,703** | 89.48% | — | — |
| `predicted_synthesizable__other` | pool-wide | 94,797 | **12,144,160** | 89.67% | — | — |
| `decomposition_energy__r2SCAN_GNoME_vs_GNoME_hull` | pool-wide | 116,986 | **12,316,022** | 90.94% | — | — |
| `decomposition_energy__r2SCAN_GNoME` | pool-wide | 116,927 | **12,316,081** | 90.94% | — | — |
| `decomposition_energy__r2SCAN_GNoME_vs_MP_hull` | pool-wide | 116,927 | **12,316,081** | 90.94% | — | — |
| `decomposition_energy__r2SCAN_GNoME_vs_MP_OQMD_hull` | pool-wide | 116,927 | **12,316,081** | 90.94% | — | — |
| `power_factor__BoltzTraP_p-type` | pool-wide | 40,342 | **12,453,353** | 91.95% | — | — |
| `seebeck_coefficient__BoltzTraP_n-type` | pool-wide | 40,339 | **12,453,356** | 91.95% | — | — |
| `power_factor__BoltzTraP_n-type` | pool-wide | 40,337 | **12,453,358** | 91.95% | — | — |
| `seebeck_coefficient__BoltzTraP_p-type` | pool-wide | 40,336 | **12,453,359** | 91.95% | — | — |
| `thermal_conductivity__gga` | pool-wide | 10,554 | **12,465,976** | 92.05% | — | — |
| `thermal_expansion__gga` | pool-wide | 10,552 | **12,465,978** | 92.05% | — | — |
| `poisson_ratio__PBE_AEL__AFLOW` | pool-wide | 10,521 | **12,466,009** | 92.05% | — | — |
| `bulk_modulus_reuss__gga` | pool-wide | 20,745 | **12,472,760** | 92.10% | — | — |
| `bulk_modulus_voigt__gga` | pool-wide | 20,744 | **12,472,761** | 92.10% | — | — |
| `shear_modulus_reuss__gga` | pool-wide | 20,744 | **12,472,761** | 92.10% | — | — |
| `shear_modulus_voigt__gga` | pool-wide | 20,744 | **12,472,761** | 92.10% | — | — |
| `sound_velocity_longitudinal__gga` | pool-wide | 20,744 | **12,472,761** | 92.10% | — | — |
| `sound_velocity_transverse__gga` | pool-wide | 20,743 | **12,472,762** | 92.10% | — | — |
| `debye_temperature__gga` | pool-wide | 25,972 | **12,488,255** | 92.21% | — | — |
| `bulk_modulus_vrh__gga` | pool-wide | 28,988 | **12,530,661** | 92.52% | — | — |
| `shear_modulus_vrh__gga` | pool-wide | 28,046 | **12,533,542** | 92.54% | — | — |
| `elastic_anisotropy__gga` | pool-wide | 24,405 | **12,564,468** | 92.77% | — | — |
| `poisson_ratio__PBE__U__MP2026` | pool-wide | 24,381 | **12,564,493** | 92.77% | — | — |
| `tc_superconducting__experiment` | synthesized-only ⚠ | 3,119 | **12,757,326** | 94.20% | — | — |
| `lattice_thermal_conductivity__gga` | pool-wide | 26,470 | **12,844,095** | 94.84% | — | — |
| `continuous_symmetry_measure__other` | pool-wide | 6,104 | **12,991,641** | 95.93% | — | — |
| `lattice_thermal_conductivity_coherence__gga` | pool-wide | 7,686 | **13,034,288** | 96.24% | — | — |
| `lattice_thermal_conductivity_particle__gga` | pool-wide | 7,670 | **13,034,305** | 96.24% | — | — |
| `eos_bulk_modulus__dfpt-phonon` | pool-wide | 8,050 | **13,059,140** | 96.43% | — | — |
| `decomposition_energy__PBE__NOVOMAG` | pool-wide | 5,305 | **13,097,368** | 96.71% | — | — |
| `fermi_energy__gga` | pool-wide | 214,839 | **13,100,882** | 96.73% | — | — |
| `decomposition_energy__PBE__U__MP2026_equilibrium_reaction_energy` | pool-wide | 58,921 | **13,101,757** | 96.74% | — | — |
| `experimentally_observed__experiment` | synthesized-only ⚠ | 211,854 | **13,103,898** | 96.76% | — | — |
| `is_stable__gga` | pool-wide | 211,854 | **13,103,898** | 96.76% | — | — |
| `is_metal__gga` | pool-wide | 211,746 | **13,103,975** | 96.76% | — | — |
| `magnetization_per_volume__gga` | pool-wide | 211,749 | **13,104,003** | 96.76% | — | — |
| `heat_capacity__pbesol` | pool-wide | 13,531 | **13,137,157** | 97.00% | — | — |
| `has_imaginary_phonon__gga` | pool-wide | 22,699 | **13,170,345** | 97.25% | — | — |
| `phonon_min_frequency__gga` | pool-wide | 22,685 | **13,170,359** | 97.25% | — | — |
| `phonon_max_frequency__gga` | pool-wide | 22,675 | **13,170,369** | 97.25% | — | — |
| `measurement_temperature__experiment` | synthesized-only ⚠ | 237,965 | **13,302,190** | 98.22% | — | — |
| `mohs_hardness__experiment` | synthesized-only ⚠ | 1,183 | **13,361,341** | 98.66% | — | — |
| `structure_prediction_r_factor__geometric` | pool-wide | 12,401 | **13,484,794** | 99.57% | — | — |
| `measurement_pressure__experiment` | synthesized-only ⚠ | 1,092 | **13,533,489** | 99.93% | — | — |

---

## 08 矩阵性质

索引本身是标量存储 —— `value_num` 只有一个 float。入库时张量全被压成了标量：
6×6 弹性张量变成 `bulk_modulus_vrh`，3×3 介电张量变成 trace/3，
Born 电荷变成最大分量。**张量要回原始档案取。**

### 本地已跑通，直接可用

`scripts/ml/extract_tensors.py jarvis` / `phonondb`，产物在 `tensors/*.parquet`：

| 张量 | 形状 | 来源 / 方法 | 已匹配到 pool 的条数 |
|---|---|---|--:|
| 弹性刚度 C_ij | 6 × 6 | jarvis-dft · OptB88vdW | **34,437** |
| 介电张量（仅对角） | 3 | jarvis-dft · OptB88vdW | 60,183 |
| 介电张量（仅对角） | 3 | jarvis-dft · TBmBJ | 19,797 |
| 电场梯度 EFG | 每 Wyckoff 位点 3 × 3 | jarvis-dft · OptB88vdW | 13,825 |
| Γ 点声子频率 | 变长 | jarvis-dft · DFPT | 13,896 |
| 高频介电张量 ε∞ | 3 × 3 | phonondb · PBEsol DFPT | 4,908 |
| Born 有效电荷 Z* | N × 3 × 3 | phonondb · PBEsol DFPT | 4,908 |

**物理校验已做**：抽样的 C_ij 严格对称（|C − Cᵀ| = 0），
Born 电荷满足声学求和规则（Σ tr(Z\*)/3 = 0.000）。

EFG 那一栏值得单独说一句：JARVIS 每行是 `[元素, Wyckoff字母, 9 个张量分量]`，
是**每个对称独立位点**一个 3×3，不是每个原子一个。元素和 Wyckoff 标签一起存进了
`labels` 列 —— 丢掉它这块数据就没法映射回结构。

### 张量来源及覆盖范围

| 端点 | 张量 | 条数 | 说明 |
|---|---|--:|---|
| MP `/materials/elasticity/` | 6 × 6 刚度 | 13,283 | manifest 字段表里只有 VRH 标量 |
| MP `/materials/dielectric/` | 3 × 3 total/ionic/electronic | ~7,500 | 本地完全没有这个 harvest |
| MP `/materials/piezoelectric/` | 3 × 6 | 3,322 | 只下了 `e_ij_max` |
| AFLOW AFLUX | 6 × 6 刚度 | 5,664+ | `ael_stiffness_tensor` 未请求 |


### 曲线类目标（已在索引里，17 GB `curves.blob`）

| 曲线 | 材料数 | 曲线数 | 主要来源 |
|---|--:|--:|---|
| xrd | 142,640 | 150,460 | amcsd, rruff, deem-zeolites |
| band_structure | 130,183 | 231,162 | materiae, materials-project |
| dos | 118,984 | 164,381 | materiae, superband, materials-project |
| xas | 91,181 | 586,626 | materials-project |
| phonon_dos | 27,591 | 46,421 | phonix, phonondb, materials-project |
| kappa_spectral / cumulative | 7,103 | 15,672 | phonix |

这些是序列目标，需要另写一套重采样到固定网格的导出，**还没做**。

---

## 09 四个必须处理的坑

都是普查过程中在真实数据里撞到的，不是理论担忧。脚本已全部处理，改参数前先读这一节。

### 坑 1 · 泛函混杂：同一个性质名下混着不同理论层级

`band_gap` 的 7.82M 个材料里，81% 是 GGA、8% 是紧束缚、各 4% 是 PBEsol 和 SCAN，
另外还有 HSE06、mBJ、GLLBSC 和实验值 —— 一共 13 个层级。
方法带来的系统偏差在 1 eV 量级，模型无法从结构推断，只会去学"这条数据来自哪个库"。

> **处理**：`method_groups.theory_level()` 把自由文本收敛到理论层级，
> 默认只保留最大的一组；`--theory-policy split` 可以每个层级各训一个模型。

### 坑 2 · 条件依赖：一个材料有多个都正确的值

**这一条最容易翻车。**

| 性质 | 每个材料的多个值来自 |
|---|---|
| `co2_uptake` | 4 个 GCMC 条件：0.10 bar/363 K、0.15 bar/298 K、0.70 bar/413 K、CO₂/N₂ 二元混合 |
| `h2_uptake` | 5 个 (T, P) 组合：77 K/6 bar、130 K/100 bar、160 K/5 bar… |
| `decomposition_energy` | 同一个 PBE 能量对 4 个不同参考凸包（GNoME / MP / MP+OQMD / 自身） |
| `migration_barrier` | BVSE / BVEL × 1D / 2D / 3D × 工作离子 |
| `poisson_ratio` | deem-zeolites 存的是 6 个方向分量 ν_xy … ν_zy |
| `youngs_modulus` | deem-zeolites 存的是 3 个应力轴 |
| `topology_class` | 有 SOC / 无 SOC |

对这些取中位数，得到的不是任何物理量。

> **处理**：`CONDITION_SPLIT_PROPERTIES` 列出这些性质，每个条件拆成独立任务；
> `condition_key()` 先剥掉 3dsc 写进 method 的掺杂组分
> —— `tc_superconducting` 因此有 7,151 个不同的 method 值，不剥掉的话每条记录自成一组。

### 坑 3 · 跨库分歧：3,233,769 个结构由 ≥2 个库贡献，数值真的不一样

不是重复记录，是同一个结构在不同数据库里算出了不同的值。
实际产出的 176 个训练集里，**5,831,192** 个材料被多源标注过，
其中 **519,599** 个的源间极差超过 0.25 个标准差。

> **处理**：`--resolve median | priority | drop-conflicts`。默认取中位数，
> 但极差一律写进 `value_spread` 列，可以用来给标签加权；
> `n_observations` 记录有几个源给过值。

### 坑 4 · 划分泄漏：随机划分会把同一化合物同时放进 train 和 test

池子里同一化合物常以不同 id 出现多次。随机划分下测试集指标会被显著高估，
而且这个高估在"补全缺失性质"这个用途上是致命的 ——
真正要预测的恰恰是训练集里没见过的化学体系。

但按化学体系整体留出对**单一化学的枚举库**会退化：13.6 万个 Deem 沸石全是 SiO₂、
SACADA 全是碳，整个任务只有一个化学体系，留出之后 val 和 test 直接是空的 ——
首轮构建里 176 个任务有 **23 个**撞上这个（train 135,887 / val 0 / test 0）。

> **处理**：级联降级 `chemsys → formula → random`，取仍能产出三个非空折叠的最强划分，
> 并把实际用的那一级写进 `split_mode` / `split_fallback`，**绝不静默**。
> 划分按**材料数**切而不是按分组数切 —— 直接哈希分组会把 29% 的沸石丢进 val（目标 10%）。
> 修正后：139 个任务用 chemsys，23 个降级到 formula，空折叠 0 个。

### 另外一条：无序结构

实验结构里有一部分 CIF 带部分占据，位点没有唯一原子序数，无法直接编码成图节点。
`export_structures.py --disorder skip`（默认）丢掉它们；
`--disorder majority` 取占据最高的元素，并在分片的 `disordered` 掩码里标出来。

---

## 10 我自己踩的两个错

写在这里是因为它们是可复现的教训，也因为它们改变了 200 万条标签的去留。
两个都是我给的"物理边界"写错了，而不是数据有问题 —— 是**丢弃计数**暴露出来的。

### 错误 1 · `total_magnetization` 的边界写成了非负 → 恢复 1,982,000 条标签

我给的边界是 `(0, 1000)`，结果丢掉了 **25.4%** 的数据。查了分布才发现：

```
total_magnetization (n=9,101,588)
  分位数 .1/1/5/25/50/75/95/99/99.9%:
    [-13.93, -0.51, -0.00, -0.00, 0.00, 0.91, 8.46, 22.39, 48.08]
  负值占比 25.9%   min -340.30   max 383.37
```

**25.9% 的总磁矩本来就是负的** —— 那是自旋约定（多数自旋向下），不是错误值，
分布关于 0 大致对称。改成对称边界后，该任务从 5,990,935 涨到 **7,972,636** 个材料。

> **现在**：边界 `(−1000, 1000)`；想要磁矩大小的话由训练侧显式 `abs()`，
> 而不是在这里静默扔掉四分之一的语料。

### 错误 2 · ν ∈ [−1, 0.5] 是**各向同性**极限，用错了对象

我按热力学稳定性给 `poisson_ratio` 卡了 `(−1, 0.5)`，丢掉 10–13%。
但这里 **11.2%** 的行是**方向分量**（deem-zeolites 把 ν_xy … ν_zy 分开存），
各向异性晶体的单方向泊松比合法地可以超过 0.5。教科书边界只对各向同性平均值成立。

> **现在**：只保留一个宽松的合理性边界 `(−10, 10)`，真正的长尾交给分位数裁剪 ——
> 顺带把裁剪逻辑也改了：原来"有硬边界就不做分位数裁剪"，
> 现在两者都做，硬边界只当合理性过滤。
> **全局越界丢弃从 2,238,299 降到 1,577。**

**可以带走的一条规则**：任何一个丢掉大批数据的边界，都要先去看被丢掉的那批长什么样。
这两次都是分布看一眼就明白了。`make_training_sets.py` 现在把
`n_out_of_bounds_dropped` 逐任务写进 `DATASETS.json`，就是为了让这种错误下次也能被一眼看见。

---

## 11 索引自带的一个缺陷：61,717 行是半个胞

这个是普查过程中撞出来的**既有**问题，不是本套脚本引入的，
但它直接影响 23 个已产出的沸石训练集。

部分上游 CIF 存的是**非对称单胞 + 对称操作**。建索引时没有展开，
于是 `materials` 表里的 `n_atoms` / `formula` / `density` 都只有真实值的一半。

以 `pool-train-12848566` 为例：

| | 索引记录 | CIF 与来源自己发布的值 |
|---|---|---|
| formula | `Si12O24` | `_chemical_formula_sum "Si O2"`，`_cell_formula_units_Z 24` |
| 原子数 | 36 | **72**（Si24O48） |
| 空间群 | 46 | Ima2，**8 个对称操作** |
| density | 1.362 g/cm³ | Deem 发布值 **2.724** g/cm³ |
| framework_density | — | Deem 发布值 **27.31** T/1000 Å³ = 24 个 T 原子 / 878.9 Å³ |

来源自己的两个值都精确对应 72 个原子。索引的值正好是一半。

### 用来源自己的 density 对拍，可以精确定位

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

| 来源 | 有两方 density 的行 | 一致 | 正好差 2 倍 | 占比 |
|---|--:|--:|--:|--:|
| deem-zeolites | 136,008 | 69,701 | **61,642** | 45.3% |
| aflow | 3,051,728 | 2,695,836 | 43 | <0.01% |
| icsd | 123,324 | 103,535 | 23 | 0.02% |
| amcsd | 14,661 | 9,261 | 8 | 0.05% |
| 其余 6 个来源 | 21,441 | 20,288 | 1 | <0.01% |
| **合计** | | | **61,717** | |

### 影响范围 —— 结构是对的，只有元数据列错

`export_structures.py` 对这类 CIF 走 `CifParser`，会正确展开对称操作
（该例解析出 72 个原子）。**导出的图结构本身没有问题。**
错的只是 `materials` 表那几列，以及它们透传到 `materials.parquet`
和 `datasets/*.parquet` 的副本。

- 原子数请用 npz 分片里的 `np.diff(atom_ptr)`，**不要**用 `datasets/*.parquet` 的 `n_atoms` 列
- 任何 per-atom 归一化在这 61,717 行上会差 2 倍
- 受影响的正好是 23 个 `*__forcefield` / `*__GULP_SLC_forcefield__*` 沸石训练集
  —— 也正是第 09 节里划分降级的那 23 个
- 性质值本身不受影响：`material_properties` 里 deem-zeolites 发布的 density 是对的（2.724），
  错的是 `materials.density`（1.362）

修不修是另一回事 —— 重建这 61,717 行的元数据要重跑一遍索引器的结构解析。
在那之前，上面三条足够绕开它。

---

## 12 提取流水线

五个脚本在 `scripts/ml/`，全部只读，不动 `data/index/`。

| 步骤 | 脚本 | 产出 |
|--:|---|---|
| 1 | `property_census.py` | `census_groups / census_property.json` |
| 2 | `export_targets.py` | `materials.parquet` + `targets/*.parquet` ×151 |
| 3 | `extract_tensors.py` | `tensors/*.parquet` ×7 |
| 4 | `make_training_sets.py` | `datasets/*.parquet` ×176 |
| 5 | `export_structures.py` | `structures/shard-*.npz` |

```bash
# 环境：pymatgen + pyarrow + numpy
PY=python

# 服务器上如果没有索引，先拉（~47 GB；先用 slice 跑通流程只要 9 MB）
$PY scripts/fetch_index.py --variant index --out data/index

$PY scripts/ml/property_census.py      --out data/ml/census
$PY scripts/ml/export_targets.py       --out data/ml/export
$PY scripts/ml/extract_tensors.py jarvis   --out data/ml/export/tensors
$PY scripts/ml/extract_tensors.py phonondb --out data/ml/export/tensors --workers 16
$PY scripts/ml/make_training_sets.py   --export data/ml/export --out data/ml/datasets
$PY scripts/ml/export_structures.py    --out data/ml/export/structures --workers 30
```

### 只做一个性质（省磁盘）

```bash
$PY scripts/ml/make_training_sets.py --export data/ml/export --out /scratch/bg \
    --property band_gap --theory-policy split
$PY scripts/ml/export_structures.py  --out /scratch/bg/structures \
    --pks-from /scratch/bg/band_gap__gga.parquet --workers 16
```

### 为什么第 2 步是一次顺序扫描

直觉写法是按性质循环 `WHERE property_id = ?` 再 join `materials`，
那会在一个 21 GB 的库上产生上千万次随机 rowid 寻道，要跑几个小时。
改成两次纯顺序扫描：先把 `materials` 导成一张共享索引表，
再把 `material_properties` 从头扫一遍、边扫边扇出到 151 个 Parquet writer。
实测 0.28–0.39M 行/秒，121.6M 行一次过。

### 结构不按性质复制

每个 target 表都带 `blob_offset` / `blob_length`，训练时直接从那一份 9.1 GB 的
`structures.blob` 里 seek 出 CIF 就行，不需要给每个性质各存一份结构。
第 5 步的 npz 分片是可选的加速项（把 CIF 预解析成数组）。

### CIF 解析

候选结构（13.19M，占 97%）是 pymatgen 写出的 P1、定长列，
用手写解析器比 `CifParser` 快约两个数量级，已逐结构对拍验证过：
晶格与原子间距离一致到 1e-8 Å。唯一的系统差异是 `CifParser` 会把
0.6667133 这类循环小数吸附回 2/3，差值 <1e-4（分数坐标），两边都不算更对。

实验结构（357K）是上游原始 CIF —— 真实对称操作、ASE 写的 `data_image0`、
部分占据 —— 一律走 `CifParser`。

**这里有个容易写错的地方**：判断"是不是 P1"不能看 `'x, y, z'` 在不在文件里 ——
列了 4 个对称操作的 CIF 同样含这个串，那样会把非对称单胞当成完整晶胞，
静默丢掉四分之三的原子。解析器现在真正数对称操作的条数，>1 就退回 `CifParser`。

抽样 3,000 个结构验证（`--disorder majority`）：

| | 结构数 | 快路径 | CifParser | 失败 | 原子数与库不符 |
|---|--:|--:|--:|--:|--:|
| candidate | 1,500 | 1,442 | 58 | 0 | 12 † |
| experimental | 1,500 | 220 | 1,280 | 0 | 0 |

† 这 12 个正是第 11 节的半胞问题 —— 解析器是对的，库里的 `n_atoms` 是错的。

---

## 13 输出格式

四类产物，都是 zstd 压缩的 Parquet / npz，join 键统一是 `material_pk`。

### `targets/<property>.parquet` —— 长表，一行一个观测

| 列 | 类型 | 说明 |
|---|---|---|
| `material_pk` | int64 | join 键，等于 sqlite rowid |
| `source` | string | `source_defs.key` |
| `native_id` | string | 上游库里的原始 id |
| `method` | string | 原始自由文本，一字未改 |
| `theory_level` | string | 归一化后的理论层级 |
| `value_num` / `value_text` | float64 / string | 数值或文本值 |

**冲突不在这里消解** —— 跨库分歧保持可见，由 `make_training_sets.py` 按策略处理。

### `datasets/<property>[__<group>].parquet` —— 模型可直接用

| 列 | 类型 | 说明 |
|---|---|---|
| `material_pk` | int64 | 一行一个材料 |
| `target` | float64 | 消解冲突后的值 |
| `n_observations` | int32 | 有几个源给过值 |
| `value_spread` | float32 | 源间极差，可用作标签权重 |
| `split` | string | `train` / `val` / `test` |
| `formula`, `chemical_system` | string | 划分键，也便于分层评估 |
| `is_experimental`, `n_atoms` | int8, int16 | 筛选与分桶（`n_atoms` 见第 11 节警告） |
| `blob_offset`, `blob_length` | int64, int32 | 直接去 `structures.blob` 取 CIF |

### `structures/shard-*.npz` —— 变长数组按 `atom_ptr` 拼接

```
lattice        (S, 3, 3)  float32   行向量，Å
atom_ptr       (S+1,)     int64     每个结构的位点切片边界
frac_coords    (A, 3)     float32
atomic_numbers (A,)       int16
material_pk    (S,)       int64     join 回 targets / datasets
disordered     (S,)       bool      部分占据取了多数元素的标记
```

### `tensors/*.parquet`

`material_pk, native_id, n_units, tensor`（行主序展平），per-site 的还有 `labels`。
形状写在 Parquet 的 key-value metadata 里（`tensor_shape`，`-1` 表示变长轴），
所以固定 6×6 和每位点 3×3 用同一个读取器。

---

## 数据限制

- **降级划分的 val 比例偏低。** 23 个降级到 formula 的任务实际落在
   val 2.8% / test 8.7%（目标各 10%）—— 沸石的 formula 分组极度不均衡，
   按材料数切也只能做到这样。真正对的划分键应该是**骨架拓扑**，索引里没有。
   在这些任务上报泛化指标时要说明这一点。

- **没做许可过滤的子集。** 31.7% 的行来自受限来源，要发布权重的话需要先切一份干净的。

- **多孔性没有真正的门控。** 第 06 节的 `porous` 域现在靠 `material_family`
   标签（strict）或密度代理（wide）来筛，两者都不是孔隙率。
   正解是对全池跑一遍 zeo++ 拿 PLD，然后按吸附质动力学直径卡。
   顺带这也会把 `pool-wide-biased-labels` 那 7 个几何描述符任务的标签偏置问题解决掉。

- **61,717 行的半胞元数据没修。** 见第 11 节。绕开的办法有了，
   但要真正修好需要重跑索引器对这批 CIF 的结构解析，
   顺带重算 `n_atoms` / `formula` / `density` / `volume`。

---

## 附：数据文件位置

| 路径 | 内容 |
|---|---|
| `data/ml/census/census_groups.json` | 190,428 个 (性质, 来源, method) 组的原始统计 |
| `data/ml/census/census_property.json` | 每个性质的汇总、去重材料数、分层判定 |
| `data/ml/census/task_census.json` | 拆分后 513 个任务的清单（本文第 04 节的完整版） |
| `data/ml/export/materials.parquet` | 14,590,485 行共享结构索引 |
| `data/ml/export/targets/*.parquet` | 151 个性质的长表 |
| `data/ml/export/tensors/*.parquet` | 7 组张量 |
| `data/ml/datasets/*.parquet` | 176 个模型可直接用的训练集 |
| `data/ml/datasets/DATASETS.json` | 每个训练集的完整统计（含丢弃计数、划分降级记录） |
| `data/ml/datasets/task_summary.json` | 本文第 05 节表格的数据源 |
| `data/ml/predict/PREDICTION_SETS.strict.json` | 每个任务允许打分的结构数、门控理由、警告 |
| `data/ml/predict/<task>.pk.parquet` | `--materialize` 落地的实际 pk 列表 |
