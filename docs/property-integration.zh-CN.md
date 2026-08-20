# 跨数据库性质整合

[English](property-integration.md) · **简体中文**

更新：2026-08-19

MateriaViva 将已获取的数十个来源数据库的性质数据挂接到统一结构池上，每个数值都保留其
来源数据库、原始记录号和计算 / 测量方法。结构池中尚不存在的晶体，经与初始合并完全相同
的结构指纹去重后收录。

## 1. 数据模型（索引 schema v3）

`data/index/materials.sqlite` 新增五张表：

| 表 | 内容 |
|---|---|
| `source_defs` | 每个来源数据库一行：键名、显示名、许可、官方链接（来自 `scripts/datasets/sources.json`） |
| `property_defs` | 每个性质一行：规范 snake_case 名称、单位、类型（`num` / `text` / `bool`） |
| `material_properties` | 每个数值一行：`material_pk`、性质、来源、`native_id`（来源自身的记录号）、`value_num` / `value_text`、`method`（泛函或测量条件） |
| `material_source_refs` | 每个材料出现在哪些数据库：`(material_pk, source, native_id, match_via)`，`match_via` ∈ `id:<db>` / `hash` / `origin` |
| `material_curves` | 每条非标量谱一行：`curve_type`（能带、DOS、声子 DOS、XRD、拉曼、红外、XAS、光吸收、κ 谱）、`fmt`（`xy` / `peaks` / `svg`）、来源、`native_id`、`method`，以及在 `data/index/curves.blob` 中的偏移量 |

`materials` 表原有的标量筛选列（带隙、形成能、凸包能、稳定性、金属性、磁序、磁矩、模
量、泊松比）按 `scripts/properties/registry.py` 中的来源优先级（`SCALAR_BACKFILL_PRIORITY`）
从 `material_properties` 回填；已有数值绝不覆盖，完整的多来源记录始终保留在
`material_properties` 中。

全池空间群覆盖通过解析 BAWL 指纹自带的空间群段（`<md5>_<空间群号>_<化学式>`）补全。

`materials.material_family` 标注非常规晶体类别 —— `mof`、`cof`（共价有机框架）、`hof`、`zeolite`（沸石）、
`zeotype`（类沸石）、`molecular-crystal`（分子晶体）、`2d-material`、`1d-material`、
`carbon-allotrope`（碳同素异形体）——按来源映射（`SOURCE_FAMILY`）或由 `dimensionality`
性质推断；`NULL` 表示常规块体晶体。API 通过 `material_families=` 筛选（伪值 `bulk` 选中
未标注行），前端在实验 / 候选徽章旁显示类别徽章。

## 2. 已整合的数据库

数字（每个来源的性质行数、覆盖材料数、贡献新结构数，以及结构池与性质种类总数）由
`scripts/properties/summarize.py` 从线上索引直接生成，记录在本文末尾的汇总表；下面按类别
说明每个来源贡献什么、走哪条匹配路径。

### 大型综合 DFT 数据库

| 来源 | 贡献内容 | 匹配路径 |
|---|---|---|
| Materials Project（summary 2026.04.13 + 8 个性质端点 2026-08-19） | PBE(+U) 带隙、形成能 / 凸包能、稳定性、磁性、VRH 模量、介电 / 压电常数、折射率、功函数、表面能、实验观测标记；另有嵌入式电极电压 / 容量 / 能量密度、Voigt-Reuss 上下界、德拜温度、声速、Clarke-Cahill 最小热导率、状态方程体模量、逐晶面表面性质极值、晶界能、平均氧化态、配位环境 | ICSD id + 指纹 |
| Alexandria（PBE / PBEsol / SCAN；3D / 2D / 1D） | 各泛函的形成能 / 凸包能、间接与直接带隙、磁化强度、总能 | `agm` id（约 54%）+ 指纹 |
| OQMD v1.8（SQL dump） | 形成能、凸包距离、带隙、磁化——每条目只取一个收敛终态计算 | 池内 `oqmd-…` 结构 id + ICSD id + 指纹 |
| AFLOW（AFLUX，298 万） | 形成焓、带隙、总能、原型标签、空间群、密度 | ICSD id（ICSD_WEB 子集）+ 指纹 |
| JARVIS-DFT 3D | OptB88vdW / TBmBJ / HSE06 带隙、VRH 模量、Seebeck / 功率因子、介电、DFPT 压电、SLME、spillage、剥离能、EPC 超导 T_c | 旧版 mp id + ICSD id + 指纹 |
| GNoME | 形成能 / 分解能、带隙；含 r2SCAN 复算子集 | 指纹 |
| WBM（经 matbench-discovery） | MP2020 修正形成能 / 凸包能、PBE 带隙；其 MP-2023 快照同时把旧版数字 mp id 桥接进匹配映射 | 指纹（+ mp 桥接） |
| ODBX misc（CAMD） | 形成能、凸包距离 | OQMD / ICSD id + 指纹 |
| ELEMENTA | 每端点总能（自旋弛豫附带磁化） | 端点 id，仅性质 |
| JARVIS-QETB（829,576 条） | 紧束缚形成能 / 总能与带隙；该数据集是拟合集，充满刻意构造的非平衡构型，因此每一行都带 `method` "QETB (tight-binding)"，与 DFT 来源的精度差距始终可见 | 指纹 |
| Carolina Materials Database（MatSciML 再分发版） | 机器学习生成的假设晶体：形成能、空间群 | 指纹 |
| Materials Cloud MC3D（PBEsol-v2） | PBEsol 弛豫的三维晶体及其实验母体 | ICSD / COD id + 指纹 |

### 实验结构总库

| 来源 | 贡献内容 | 匹配路径 |
|---|---|---|
| COD（全库 parquet 快照，rev 282068） | 原样发表的实验 CIF，以及化学名 / 矿物名和测量时的温度与压力；理论、撤稿和重定向条目被剔除，有机物这次予以收录（旧分层构建排除的 C/H 部分） | `cod` id + 指纹 |
| ICSD（FIZ 详情记录） | 化学名与矿物名、计算密度 | `icsd` id + 指纹，仅性质 |

ICSD 由 FIZ Karlsruhe 授权：其适配器为 `properties_only` 且必须保持如此，因此没有任何
FIZ 结构会进入结构池，其结构与由它暂存的数值也都不得出现在对外发布的 MateriaViva 快照
中。`scripts/properties/icsd_bridge.py` 找回那些以 MP / COD / OQMD / Alexandria 结构身份
入池、而非经本地 ICSD 那半边合并入池的收录号——新增 38,223 个收录号、49,579 对
收录号→材料映射——使下面这些以 ICSD 为键的来源（webmineral、AMDB、OBELiX、SPSE、3DSC、
SNUMAT、MC3D 等）不再对它们静默丢行。

### 专题性质库

SNUMAT（GGA / HSE06 电子与光学带隙、磁序；ICSD）、Materiae（SOC / NSOC 拓扑分类、对称性
指标、DOS 带隙；mp + ICSD）、phonix（晶格热导率、声子频率范围、虚频标记；mp）、PhononDB
（NIMS MDR：PBEsol DFPT 介电常数与 Born 有效电荷，以及谐振声子 DOS 本身；mp id 取自 MDR
记录标题 + 指纹）、NOVOMAG
（磁极化 / 磁矩 / 磁各向异性、居里温度；mp）、AMDB（对 MAGNDATA 做的交替磁性筛查：自旋劈裂
指标与筛查计算的带隙；ICSD，仅性质）、SuperBand + 3DSC + JARVIS supercon 2D/3D
（超导 T_c；3DSC 仅性质）、SPSE（BVSE 迁移势垒、实验离子电导率；ICSD，仅性质）、OBELiX
（实验室温离子电导率；ICSD，仅性质）、CSLLM negatives（对指纹命中 PU 筛查所判“不可合成”
结构的池内材料打上 `predicted_synthesizable=false`；仅性质——没有这一行并不等于预测其可
合成）、C2DB / 2DMatPedia / MC2D / BiDB / OpenMX 2D-AB2（二维带隙、剥离 /
层间结合能、功函数、AB2 单层原型）、OMDB-organic（omdb.mathub.io，有机分子晶体带隙；COD id）、CMR 合集（GLLB-SC 带隙 + 导数不连续、
钙钛矿形成热、OQMD 关联能量、低维标签）、Materials Cloud 归档（SHG 系数、折射率 / 双折射、
HSE / LDA 带隙、TQC 拓扑类、电子化物 ELF）、HADB（硬质涂层弹性模量，DFT + MLIP 含温度）、
SACADA（碳同素异形体：密度、硬度、模量、相对能量）、TCOD（理论 CIF 中的 DFT 带隙）、HEX
高压单质（0–300 GPa）、AMCSD + RRUFF（实验矿物结构、矿物名、实测密度 / 化学组成）、
webmineral（取自《Handbook of Mineralogy》的矿物种级汇编——密度、莫氏硬度、折射率；ICSD，
仅性质，且数值描述的是矿物种整体而非所匹配的那件标本）、AFLOW
原型百科（原型 + Strukturbericht 标签；仅性质）、开放骨架磷酸铝（AlPO 骨架、IZA 代码）。

### 多孔 / 框架材料

hMOF（假设 MOF：CO₂ 吸附量、zeo++ 几何描述符）、Boyd–Woo `mof-carbon-capture`（GCMC 碳捕集：
吸附量、选择性、工作容量、吸附热）、MOFX-DB（CoREMOF / IZA / Tobacco 子集：几何 + 298 K、
1 bar 附近单气体吸附量）、CoRE MOF 2019（经整理的实验报道 MOF：Zeo++ 孔隙学——最大空腔直径
与孔径限制直径、最大自由通路、密度、质量比与体积比表面积、空隙率、孔体积——取自与结构压缩包
一同发布在 Zenodo 记录
[10.5281/zenodo.3677685](https://doi.org/10.5281/zenodo.3677685) 的两张表，CC BY 4.0；
去除全部溶剂（ASR）与只去除游离溶剂（FSR）两种处理由 method 字符串区分，因为在 2,574 对
存在差异的骨架上 FSR 的晶胞更紧）、QMOF（DFT 弛豫的 MOF：多泛函带隙与直接 / 间接标记、总能、
磁化、密度、LCD / PLD；其中 16,040 条源自 CSD 的记录带 CSD refcode）、
FAIR-MOFs（实验 CSD 衍生 MOF：孔隙率、RCSR 拓扑、键解离能）、
EC-MOF（导电二维 MOF：带隙、形成 / 结合能）、CURATED-COFs（文献中已合成的共价有机框架及其
骨架名）、IZA-SC（268 种官方认可的沸石骨架类型，为 DLS76 理想化的纯硅几何——并非实验结构）、
Deem SLC 沸石与 pcod（假设骨架，见下）。除 pcod 外全部带
`material_family` 类别标签；pcod 的化学组成混杂——硅酸盐、磷酸盐、硼酸盐、钒酸盐、铝酸盐——
绝不能一概称作沸石。

其中两个来源的全部性质载荷都写在 CIF 文件自身之内：

- **Deem SLC 沸石。** 331,172 个 CIF 每一个的末尾都附着生成它的 SLC 力场 GULP 输出，以 CIF
  注释形式写入，任何解析器都看不到。解析该尾块可得 Reuss / Voigt / Hill 三种平均下的体模量与
  剪切模量、逐应力轴的杨氏模量、六个方向的泊松比（不做平均——六个方向泊松比的算术均值不是任何
  量的各向同性泊松比，取平均恰好会丢掉假设沸石筛选真正关心的各向异性）、Hill 声速、密度、骨架
  密度、两种介电常数（取所印张量的 trace/3），以及每 T 原子能量：约 298 万行。逐性质的合理性
  窗口剔除了 0.42% 的数值——那些是源自近奇异柔度矩阵、GULP 自身平均发散所致的数值假象。每个
  CIF 旁附带的 `<id>.txt` 存有该骨架的模拟衍射图谱，由此得到 136,008 条 XRD 棒图，并已由 d 值
  换算为 Cu Kα 的 2θ，以便与按需模拟的图谱叠加。
- **pcod**（GRINSP 快照，2008-04-01）贡献 `structure_prediction_r_factor` 与
  `framework_density`，二者分别读自自由文本与注释尾块。其被注释掉的空间群推测**刻意不**映射到
  `spacegroup_number`：那是存放者主动禁用的建议，而所存坐标本就是 P1 展开。

> **枚举型骨架与指纹的边界。** hMOF、Deem 沸石与 pcod 都是*枚举型*库——同一骨架拓扑配上一份
> 官能团菜单，或者 Si 全为四配位、O 全为二配位的理想化硅 / 磷酸铝网。同源条目因此共享同一套
> 键合图与原胞化组成，而这正是 BAWL 指纹所看的全部，于是哈希无法把它们分开：33.1 万条 Deem
> 集中有 59% 在源内碰撞，hMOF 的 135,818 条可哈希记录中有 46,891 条与更早的记录碰撞。三者一律
> 按复合判据收录——（指纹，每原子体积），后者对晶胞选择不变，能区分图哈希分不开的骨架。
>
> - Deem（`scripts/properties/deem_zeolite_admit.py`）：收录 136,008 个骨架，8,262 个经指纹 +
>   密度双重确认的池内真重复，舍弃 180,386 个复合重复。
> - hMOF（`scripts/properties/hmof_composite_admit.py`）：在首次装载已覆盖的 88,927 个之外
>   再收录 38,571 个骨架，带来 358,924 条新性质行，并从匹配映射中清除 28,914 个歧义指纹，使
>   后续来源无法再经由它们归位。
>
> 碰撞指纹刻意从不注册进匹配映射，未来的 SiO₂ 或 MOF 记录不会仅凭指纹被误挂到歧义骨架上。
> `load.FINGERPRINT_UNRELIABLE` 在装载环节对 `deem-zeolites` 与 `pcod` 施加同一条规则：对这两
> 个来源而言，`matched.tsv.gz` 中的 `hash` 行不构成同一性证据——哈希路径把 126,578 个不同的
> Deem 骨架压到了 281 个池内材料上，其中一个吸收了 27,007 个，经这些引用装载性质会把某个骨架的
> 弹性模量钉到另一个骨架的材料上。这些行现已被拒收；性质实际经由复合判据收录所产生、与池内材料
> 一一对应的 `origin` 引用挂接。清理早先各次运行已经写下的内容，删除了 190,655 条 Deem 与
> 4,916 条 pcod 哈希引用，并移除 4,190,215 条被错误归属的性质行。

### 明确排除的来源

| 来源 | 原因 |
|---|---|
| MOSAEC-DB | 不含结构（仅 CSD refcode）——无从匹配 |
| TopoMat | 本地镜像只有能带数据，没有拓扑分类标签 |
| MatterGen 快照 | 训练集副本；其 DFT 数值源自已整合的 MP / Alexandria |
| alexandria-jarvis-snapshot | 已装载 Alexandria 源的旧版（2024.10.1）镜像；抽验 id 与凸包条目完全一致——重复来源 |
| catalysis-hub | 抓取时漏掉了 `reactionSystems`——反应连接到表面板、再连到块体 ID 的关键字段，导致 158,304 条反应能中 144,386 条（91.2%）没有权威匹配路径；余下 8.8%（某个发表集把 `…-mp-<n>-<终止面>` 写进了 `surfaceComposition`）只覆盖 60 个材料，与其发布这点零头不如整体排除。恢复需要重新抓取 GraphQL 并请求 `reactionSystems`，同时补全 `systems` 表（本地那次抓取在 305,169 条中只完成 32 条） |
| ShiftML2 / MAD | 无逐记录 id；扰动帧与 MD 帧按项目范围排除 |
| SIMPOD / opXRD | 原先的两条理由都已失效——曲线存储现已能容纳非标量图谱，COD 也已整合——但这两个来源尚未重新评估，也还没有适配器 |
| ARC-MOF | 与 hMOF / Tobacco / CoREMOF 高度重叠；暂缓 |
| HOFSyn | CIF 带 CCDC 再分发限制；暂缓 |
| B-IncStrDB | 非公度调制结构的平均晶胞有误导性 |
| CCP-NC magres / 2D 合金 / Materials Cloud specialized | 位点级张量 / 未修正裸总能 / 无性质；暂缓 |
| OMat24 / MPtrj / MC Li-ion | 轨迹数据集，项目范围排除 |

## 3. 匹配规则

匹配从不依赖化学式相等。两条路径，按顺序：

1. **权威 ID 直配。** 当一条记录明确*就是*结构池已登记数据库的某条目（LeMat immutable id
   `mp-…`/`oqmd-…`/`agm…`、实验池 `icsd-…`/`cod-…`、ELEMENTA 端点 id）时，适配器声明
   `match_ids`，记录无需解析结构即可归位。指向*相关*条目的 id（例如单层材料的 3D 母体）
   被刻意**排除**。
2. **指纹匹配。** 解析记录结构，施加准入约束（≤500 位点、原胞化后 ≤300、仅有序占位），
   用与初始合并完全相同的原胞化 BAWL 协议计算指纹，再查全池哈希映射。同一指纹可能同时
   命中实验池和候选池的材料；性质挂接到每一个命中项。

结构不可再分发的来源（如 SPSE、3DSC-ICSD 这类 ICSD 衍生镜像）以 `properties_only` 模式
运行：只能为现有材料添加性质注记，绝不贡献新结构。

旧版数字型 Materials Project id（JARVIS、phonix、NOVOMAG、3DSC、Materiae 等仍在使用）
通过 matbench-discovery 的 MP-2023 快照桥接：其结构一次性指纹匹配入池，得到的
`mp-#### → material` 对注册进匹配映射（`scripts/properties/mp_bridge.py`）。

**指纹够不到的地方。** BAWL 需要一个有序且尺寸在上限之内的晶胞，因此有两类记录永远无法去重，
只能留作未匹配而不是猜测：部分占位（无序）结构，以及原胞化之后仍超出位点上限的结构。大型实验
总库的记录正是在这里流失——COD 有 120,997 条无序、119,368 条过大的条目未能匹配，ICSD 有
84,971 条无序未能匹配。这是去重方法本身的边界，而非其缺陷：无序晶胞没有唯一一套原子位置可供
哈希，若按猜测的某种有序化收录，等于往池里放入一个谁都没有存放过的结构。

## 4. 新结构收录

指纹未命中池的记录成为新的主记录，同样服从标准准入规则（静态端点、有序、规模上限）。
装载器把 CIF 追加进 blob，插入 `materials` 行（空间群取自指纹段，`material_family` 取自
来源），向源 CSV 追加 Crystal Record v1 行、向合并元数据（`added_meta.tsv` /
`synth_meta.tsv`）追加指纹行，并把指纹回写进匹配映射——后续来源自动与新收录结构去重。
实验数据库（如 AMCSD 矿物）进入实验池；计算与假设数据库进入候选池。

## 5. 流水线

```text
scripts/properties/
├── registry.py     规范性质词表、来源→类别映射、标量优先级
├── base.py         适配器协议（SourceRecord / PropertyValue / 旗标）
├── adapters/       每个来源数据库一个适配器
├── match_map.py    从池合并元数据构建 data/props_work/match_map.sqlite
├── pipeline.py     每源三阶段：adapt → hash → match（产物可断点续跑）
├── hashing.py      并行 BAWL 指纹（28 进程，约 600 结构/秒）
├── load.py         migrate / load / backfill / verify 直连线上索引
├── curves.py       把非标量谱装入 curves.blob / material_curves
├── curve_sources/  每个来源数据库一个曲线提取器
├── mp_bridge.py    旧版 mp-id 桥接
├── verify_complete.py  对整个性质层做三重完整性审计
└── run_all.py      生产调度器（bridge → main → huge → backfill）
```

每源产物位于 `data/props_work/<source>/`；调度器状态在
`data/props_work/run_status.json`。性质层的完整重建流程为：基础索引重建后依次运行
`match_map.py` 与 `run_all.py`。装载幂等——已记录装载的来源拒绝重复装载。

`verify_complete.py` 不依赖装载器自身的记账，独立审计结果，每个来源三项检查，各自都可能单独
失败：

1. **装载完整性**——装载器回执报告的行数必须等于索引中该来源实际持有的行数。不相等意味着某次
   装载被中断、跑了两遍，或行被清空后没有重新插入；汇总表永远看不出这一点，因为它只报告数据库
   里现有的东西。
2. **暂存产出**——`staged - landed - unmatched` 必须为零。适配器暂存的每一行要么在索引里，要么
   被记为 `props_unmatched`（没有池内材料与之对应的 `native_id`）；除此之外的差额就是被静默丢弃
   的数据。
3. **字段覆盖**——`staging_props.tsv.gz` 中出现的每一个不同的性质*名称*，都必须在索引中该来源
   之下存在。只为未匹配记录暂存的名称予以排除，因为一个字段的全部载体本就无处可落并不算缺陷；
   正是这条排除把装载器的 bug 和“匹配为空”区分开来。

已在磁盘上暂存却不见于 `source_defs` 的来源报为 NEVER LOADED，登记在册却没有工作目录的来源报为
NOT STAGED，任何东西都不会因为没被提及而蒙混过去。有几个脚本绕过装载器直接写
`material_properties`（`hmof_composite_admit`、`alexandria_recover_functional_runs`、
`aflow_ael_attach`、`phonondb_attach`），它们都不刷新 `load_report.json`，因此高于回执的行数
作为旁路信息呈现而不判为缺陷——只有索引*低于*回执才是错误。当前审计 **54** 个来源，报告
**0** 个问题。

## 6. 方法与单位约定

单位在适配器内换算为 `property_defs` 的规范单位（如声子频率 cm⁻¹ → THz、吸附热
kcal/mol → kJ/mol、凸包距离 meV/atom → eV/atom）；`method` 字符串原样记录理论层级或测量
条件（`PBE`、`HSE06`、`GLLB-SC indirect`、`GCMC 298K ~1bar TraPPE`、`experiment 300K`
等）。因此同一性质在同一材料上可能存在多行——每个（来源，方法）一行——界面全部呈现而
非取平均。

当名称背后的物理量在种类上就不同时，即便数字落在同一列里看着合理、即便 method 字符串原则上
能区分，也拒绝复用规范名称：

- `structure_prediction_r_factor` 刻意不叫 `r_factor`。GRINSP 的 R 是几何约束搜索的代价函数
  ——预测骨架实际实现的键长键角与喂给优化器的理想目标值之间的偏差——而 `r_factor` 在 registry
  中的定义是晶体学精修残差 R1，开放骨架磷酸铝暂存的正是后者。pcod 中没有任何条目被测量过，
  因此也没有任何东西是对着观测精修出来的。两者都无量纲、都是越小越好，取值范围还相互交叠
  （此处 0.0001–0.0500，对应 AlPO 精修的 0.022–0.078），事后没有任何数值筛选能把它们分开；
  而且 pcod 会贡献约 1.72 万行，压过那边不到 312 行，使该列的主导人群与其自身定义相矛盾。
- `energy_per_t_atom`（kJ/mol）刻意不叫 `total_energy_per_atom`（eV/atom）。Deem 的尾块报告
  的是每个*四面体*位点的力场晶格能，而不是每原子 DFT 总能，归入共用列会污染该列。T 原子约定
  正是 registry 在 `framework_density` 上已经采用的约定，任何报告同一物理量的其他骨架来源都
  可以复用这个名称。

## 7. API 与前端

- `GET /api/materials/{id}` 现在返回 `properties`（与 `property_defs` / `source_defs`
  连接后的逐来源行）、`source_refs` 和 `curves`（每条已存谱一项，带类型、方法与来源）。
- `GET /api/materials/{id}/curves/{curve_id}` 提供单条已存载荷——`xy` / `peaks` 返回 JSON，
  `svg` 返回 `image/svg+xml`——并按不可变缓存；`GET /api/materials/{id}/xrd` 则为池中任意结构
  按需从 CIF 模拟 Cu Kα 粉末衍射图谱。
- `GET /api/materials` 接受 `material_families=`（CSV；`bulk` = 未标注）。
- 详情页显示材料类别徽章、“代表性质”区（回填的标量列）、带逐值来源标记的完整跨库性质
  列表、把已存谱与模拟衍射画在同一条 2θ 轴上的谱图面板，以及链接每个原始记录号的来源数据库区。


## 8. 汇总表（2026-08-19 生成）

任何装载之后用 `scripts/properties/summarize.py` 重新生成。

| 来源 | 性质行数 | 覆盖材料数 | 新增结构 | 许可 |
|---|---:|---:|---:|---|
| Alexandria Materials Database (`alexandria`) | 60,588,138 | 5,894,222 | 1,514,488 | Alexandria dataset terms |
| AFLOW (`aflow`) | 18,464,119 | 2,275,947 | 1,650,288 | AFLOW academic non-commercial terms |
| ELEMENTA and ELEMENTA Spin (`elementa`) | 8,023,344 | 2,005,836 | 0 | CC BY-NC 4.0 |
| Open Quantum Materials Database (`oqmd`) | 6,086,500 | 1,229,047 | 255,085 | CC BY 4.0 |
| Hypothetical MOFs for wet flue-gas carbon capture (`mof-carbon-capture`) | 5,454,666 | 287,610 | 287,610 | CC BY 4.0 |
| GNoME materials discovery dataset (`gnome`) | 4,897,901 | 554,056 | 547,603 | CC BY-NC 4.0 |
| Materials Project (`materials-project`) | 4,291,860 | 211,854 | 3,157 | Materials Project terms |
| Michael Deem PCOD hypothetical zeolite structures v2.1 (`deem-zeolites`) | 2,977,166 | 136,008 | 136,008 | CC BY 4.0 |
| NIST JARVIS-QETB tight-binding dataset (`jarvis-qetb`) | 2,524,250 | 191,606 | 124,598 | NIST/JARVIS dataset terms |
| Matbench Discovery / WBM (`matbench-discovery`) | 1,734,187 | 401,437 | 136,041 | CC BY 4.0 |
| NIST JARVIS-DFT 3D (`jarvis-dft`) | 1,569,924 | 120,277 | 14,986 | NIST/JARVIS dataset terms |
| Hypothetical MOF database (`hmof`) | 892,486 | 127,498 | 127,498 | Figshare record licence |
| Materiae - Material Sciences Database (catalogue of topological electronic materials) (`materiae`) | 589,993 | 67,688 | 4,769 | Materiae site terms; cite Zhang et al., Nature 566, 475-479 (2019) |
| Carolina Materials Database (`carolina`) | 428,272 | 210,000 | 43,801 | CC BY 4.0 |
| Crystallography Open Database (`cod`) | 354,350 | 265,903 | 238,839 | CC0 |
| Quantum MOF Database (`qmof`) | 339,443 | 26,615 | 17,142 | CC BY 4.0 |
| DTU Computational Materials Repository static periodic datasets (`cmr-static`) | 305,346 | 192,185 | 33,044 | CC BY-SA 4.0 |
| Open Databases Integration for Materials Design (`odbx`) | 287,006 | 142,987 | 103,138 | ODBX provider terms and source-dataset provenance |
| FAIR-MOFs experimental and optimized structures (`fair-mofs`) | 277,454 | 33,030 | 32,847 | CC BY 4.0 |
| Inorganic Crystal Structure Database (`icsd`) | 257,558 | 77,041 | 73,823 | FIZ Karlsruhe ICSD licence |
| SNUMAT hybrid-functional database (`snumat`) | 170,893 | 21,115 | 3,273 | Figshare record licence |
| CoRE MOF 2019 (`core-mof`) | 155,488 | 11,784 | 1,606 | CC BY 4.0 |
| Phonix anharmonic phonon and thermal-conductivity database (`phonix`) | 155,192 | 22,733 | 2,171 | CC BY 4.0 |
| Materials Cloud Archive static optical, topological, and electride datasets (`materials-cloud-archive-static`) | 143,153 | 68,547 | 2,811 | record-specific open licences, predominantly CC BY 4.0 |
| CSLLM non-synthesizable screening set (`csllm-negatives`) | 98,303 | 94,797 | 0 | CC BY 4.0 |
| MOFX-DB adsorption structures and isotherms (`mofx-db`) | 87,845 | 10,665 | 10,377 | MOFX-DB dataset terms |
| NIMS MDR harmonic phonon calculation database (`phonondb`) | 86,616 | 15,245 | 1,700 | CC BY 4.0 |
| Materials Cloud MC3D (`mc3d`) | 70,508 | 68,487 | 6,733 | Materials Cloud record licence |
| NovoMag magnetic materials database (`novomag`) | 38,884 | 5,309 | 1,573 | CC BY 4.0 |
| 3DSC superconductors with crystal structures (`3dsc`) | 36,531 | 3,123 | 0 | 3DSC repository licence and upstream MP/ICSD terms |
| 2DMatPedia (`2dmatpedia`) | 30,583 | 6,491 | 4,275 | 2DMatPedia terms |
| High-Throughput Screening Platform for Solid Electrolytes (`spse`) | 29,953 | 3,599 | 0 | CC BY 4.0 record; underlying ICSD-derived structures retain ICSD terms |
| NIST JARVIS specialized crystal endpoint and property datasets (`jarvis-specialized-structures`) | 26,154 | 3,443 | 574 | NIST/JARVIS dataset terms |
| American Mineralogist Crystal Structure Database (`amcsd`) | 24,639 | 7,790 | 1,203 | AMCSD terms |
| Predicted Crystallography Open Database (`pcod`) | 24,416 | 12,418 | 12,418 | public domain |
| Computational 2D Materials Database (`c2db`) | 14,120 | 3,493 | 2,253 | CC BY-SA 4.0 |
| Materials Cloud MC2D (`mc2d`) | 13,202 | 3,164 | 1,873 | Materials Cloud record licence |
| Organic Materials Database (OMDB, omdb.mathub.io) (`omdb-organic`) | 12,013 | 11,975 | 11,888 | OMDB terms |
| Samara Carbon Allotrope Database (`sacada`) | 10,349 | 1,532 | 1,508 | SACADA site terms and source-publication provenance |
| 2DHub van der Waals Bilayer Database (`bidb`) | 9,405 | 1,023 | 17 | 2DHub dataset terms |
| SuperBand electronic-band and Fermi-surface database of superconductors (`superband`) | 8,985 | 3,147 | 7 | CC BY 4.0 data; MIT software |
| EC-MOF Phase-I electrically conductive MOFs (`ec-mof`) | 7,848 | 1,067 | 1,067 | EC-MOF site terms and source-publication provenance |
| AFLOW Encyclopedia of Crystallographic Prototypes (`aflow-prototypes`) | 6,251 | 1,788 | 0 | Apache-2.0 |
| Webmineral mineralogy database (`webmineral`) | 4,698 | 1,320 | 0 | Webmineral site and cited-source terms |
| OpenMX AB2 two-dimensional structure map (`openmx-2d-ab2`) | 4,305 | 2,151 | 1,797 | OpenMX database and source-publication terms |
| HEX high-pressure elemental crystal structures (`hex-high-pressure`) | 1,456 | 241 | 37 | CC0 |
| RRUFF mineral chemistry, diffraction, Raman, and infrared database (`rruff`) | 1,302 | 829 | 123 | RRUFF terms and source-citation provenance |
| Open-framework aluminophosphate structure database (`open-framework-aluminophosphate`) | 925 | 186 | 139 | CC BY 4.0 |
| Curated COF structures (`curated-cof`) | 684 | 757 | 757 | repository licence |
| Anyterial Altermagnets Database (`amdb`) | 622 | 103 | 0 | AMDB terms and source-publication provenance |
| IZA Database of Zeolite Structures (`iza-zeolite`) | 529 | 213 | 24 | IZA Structure Commission terms |
| Hard-coating Alloys Database (`hadb`) | 492 | 123 | 105 | HADB terms and source-publication provenance |
| Theoretical Crystallography Open Database (`tcod`) | 357 | 2,803 | 2,227 | CC0 |
| OBELiX solid-state electrolyte structures and ionic conductivity (`obelix`) | 112 | 60 | 0 | CC BY 4.0 |

总计：**121,620,776** 条性质行，覆盖 **166** 种性质，**12,812,918** 个材料至少携带一条跨库
性质；结构池现为 **357,127** 实验结构 + **13,186,150** 候选结构（共 **13,543,277**），其中
**1,190,447** 个由两个及以上来源共同贡献。

“新增结构”一列统计的是 `match_via = 'origin'` 引用。对 `icsd` 而言这是溯源而非收录：该来源为
`properties_only`，其 `new_structs.jsonl.gz` 为空，全部 73,823 条引用指向的都是早于本流水线就
已在池中的实验结构。没有任何 FIZ Karlsruhe 结构被收录或发布。

非标量存储：**1,198,897** 条曲线——X 射线吸收谱 586,626（Materials Project）、能带图 231,162
（Materials Project 122,526、Materiae 108,636）、电子 DOS 164,381（Materials Project 102,049、
Materiae 59,162、SuperBand 3,170）、粉末 XRD 峰表 150,460（Deem 压缩包自带的模拟图谱 136,008、
AMCSD 计算 13,512、RRUFF 实测 940）、声子 DOS 46,421（phonix 28,214、PhononDB 13,545、
Materials Project 4,662）、热导谱与累积热导曲线各 7,836（phonix）、拉曼 2,084 与红外 167
（RRUFF）、光吸收曲线 1,924（Materials Project）——另有全池按需模拟 XRD
（`/api/materials/{id}/xrd`）。

全池回填结果：空间群 **13,542,712 / 13,543,277**（99.996%，解析自 BAWL 指纹段），形成能
9,531,809、凸包能 7,307,427、带隙 8,566,028、磁性 8,046,563、弹性 59,155。
