<p align="center">
  <img src="frontend/public/logo.svg" alt="Materia Viva" width="760">
</p>

# MateriaViva

**简体中文** · [English](README.md)

[![CI](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml/badge.svg)](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml)
[![Dataset](https://img.shields.io/badge/Hugging%20Face-AI4QC%2FMateriaViva-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AI4QC/MateriaViva)
[![Open dataset](https://img.shields.io/badge/Hugging%20Face-AI4QC%2FMateriaViva--Open-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AI4QC/MateriaViva-Open)

> **材料发现不该从逐个调用数据库 API 和维护多套账户开始。** MateriaViva 用一个 Hugging Face
> 下载入口交付经过统一、去重和许可审查的数据快照。
>
> **MateriaViva 也不会停在一次性数据合集。** 下一阶段将建立可审计的自我进化闭环，持续发现
> 新数据库和新版本并完成准入检查、格式映射与结构去重。自动发现与整合目前正在开发，
> 尚未上线。

## About MateriaViva

### 问题：材料数据很多，但材料仍然难找

晶体结构并不稀缺。真正缺少的是一个可以直接搜索、比较并追溯来源的材料空间。

同一种晶体可能同时出现在多个数据库中，却使用不同的 ID、字段、单位和文件格式。研究者
常常要分别申请账户、调用批量 API、下载归档、清洗数据，再判断哪些记录只是重复结构、
弛豫中间帧或分子动力学轨迹。即使完成这些工作，性质字段也可能和结构脱节，许可边界还要
重新核对。

结果是：数据已经存在，但在真正开始筛选候选材料之前，大量时间先消耗在数据获取和整理上。

### 为什么重要：探测正向筛选的极限，并支撑逆向设计

材料发现有两条路线。**正向筛选**是在已知材料中找出已经具备目标性质的那一个；
**逆向设计**是直接生成满足要求的结构。公开数据的现状把这两条路线隔开了，
MateriaViva 想同时服务于两者。

正向筛选通常被认为受限于"已知材料有多少"。并非如此，它真正受限于
"其中有多少被算过"。统一池中有 1354 万个不同结构，而**任何需要单独做一次计算的性质，
覆盖率都不到五十分之一** —— 弹性模量 1.45%，晶格热导率 0.20%。
因此今天在公开数据上做筛选，排出来的是"有人算过的材料"，而不是"存在的材料"，
它看起来的边界其实是算力投向的产物。

把所有来源整合起来，再**对整个池子预测缺失的性质**，就把这个产物换成更接近真实的边界，
同时回答一个此前无法提出的问题：*已知材料里，有多少是因为没人算过、而不是因为不够好，
才被漏掉的？* 两种答案都重要。产出很多，说明正向筛选一直在自己的射程之内运行，
还有大量本可合成的材料等待被发现；产出很少，说明已知集合接近穷尽，
后续进展必须来自设计结构而不是寻找结构。

第二条路线需要的恰恰是这个数据库所提供的。生成模型判断"新颖性"时，
要对照的是全部已发表结构而不是某一个库，这需要跨 55 个来源去重后的结构；
它被条件化的目标必须是一个有定义的物理量而不是一个列名，这需要带方法标注的性质标签。
这种规模上的结构与性质标准化，正是让两条路线可比、而不是各自成篇的前提。

### 我们如何解决

MateriaViva先用 Hugging Face 版本快照替代分散的批量 API 与账户
登录，再把晶体数据整理成一个可检索、可追溯的统一入口。研究者从元素周期表开始选择
化学空间，使用 Materials Project 风格的性质条件缩小结果，最后通过浏览器 3D 或
OVITO/Tachyon 检查结构。

| 原来的障碍 | MateriaViva 的处理方式 |
|---|---|
| 每个数据库都有自己的 API、账户和下载流程 | 允许再分发的数据统一发布为 Hugging Face 版本快照 |
| CIF、JSON、SQL、LMDB 和属性表无法直接混用 | 结构进入统一模式，来源性质保留原值、单位和 provenance |
| 同一结构跨库重复，轨迹帧又会放大材料数量 | 只接收独特周期结构端点，统一做结构指纹去重 |
| 实验结构和计算候选容易混在一起 | 两类记录始终分开标注、筛选和统计 |
| 商业数据与开放数据的边界不清楚 | 许可审查先于发布；公开版只收录开源库持有的结构，每个数值都标注来源许可 |
| 下载后仍缺少直观检查工具 | 周期表检索、组合筛选、交互式 3D 和高质量离线渲染在同一界面完成 |

当前统一索引包含：

| 实验晶体结构 | 计算候选结构 | 统一检索记录 |
|---:|---:|---:|
| 357,127 | 14,233,358 | 14,590,485 |

结构池之上另有跨数据库性质层：来自 **55 个已整合来源库**、覆盖 **166 种性质**的
**131,824,881 条性质行**，每个数值都保留来源数据库、原始记录号和计算 / 测量方法；
13,792,960 个材料至少携带一条跨库性质，其中 **3,233,769 个结构由两个及以上来源库共同
贡献**——这个重叠正是去重换来的东西。其中 3,153,748 个结构的性质记录来自不止一个数据库，
也就是说已标注池中接近四分之一的内容，任何单一提供方都拿不全。非标量数据——**1,198,897 条已存谱线**（能带、
声子 / 电子 DOS、粉末 XRD、XAS、拉曼、红外、热导）以及全池按需模拟 XRD——存放于并行
曲线存储。空间群覆盖全池 99.996%。MOF、COF、沸石、分子晶体、二维材料、碳同素异形体等
非常规晶体类别均有标注并可筛选。
详见 [`docs/property-integration.zh-CN.md`](docs/property-integration.zh-CN.md)。

以上为快照数字；运行中实例的 `curl -s http://127.0.0.1:8000/api/stats` 才是准数。

### 已整合的数据库

统一索引由以下数据库汇聚而成：其中提供结构的来源，经结构指纹（BAWL / entalpic fingerprint）
去重后并入结构池；仅提供性质的来源（ICSD 即在其中）只为池内已有材料补充数值，自身不贡献任何
结构。池内结构来自去重后的基础合并——其中包括
[LeMat-BulkUnique](https://huggingface.co/datasets/LeMaterial/LeMat-BulkUnique) 与 ELEMENTA 的
弛豫终态端点，每条记录都保留自己的 `immutable_id` 与指纹——下列每个数据库再按权威记录 id 或
指纹挂接上去，指纹未命中的部分作为新结构入池。**3,233,769 个结构由两个及以上来源库共同贡献**
——它们在这里各自只占一行，同时带着每个来源的数值和 provenance，而不是留下一堆需要人工核对的
近重复条目。

**55 个来源库，131,824,881 条性质行：**

| 类别 | 数据库数 | 性质行数 | 主要成员 |
|---|---:|---:|---|
| 大型综合 DFT 数据库 | 13 | 119,170,114 | Alexandria、AFLOW、NOMAD、ELEMENTA、OQMD、GNoME、Materials Project |
| 实验结构总库 | 2 | 611,908 | COD、ICSD |
| 专题性质库 | 28 | 1,823,909 | Materiae、CMR、SNUMAT、phonix、Materials Cloud 归档 |
| 多孔 / 框架材料 | 12 | 10,218,950 | Boyd–Woo 碳捕集 MOF、Deem 沸石、hMOF、QMOF |

> ⚠️ **每个来源的许可都按提供方自己的条款核对过（2026-10-19；证据逐条记在
> [`scripts/source_licences.json`](scripts/source_licences.json)）。** 55 个来源里 37 个是开放许可。
> **只有 ICSD 需要购买**，而且买了也不允许再分发。ELEMENTA 和 GNoME 是 CC BY-NC 4.0（非商业）；
> ICSD、RRUFF、IZA 沸石库和 AMDB 不允许再分发；AFLOW 和另外 11 个小来源没有可依赖的许可（大多
> 根本没写，等于没有授予任何权利）。NOMAD 以前按“逐上传件许可”扣下，实际是 CC BY 4.0：它的条款要求每个上传者
> 授予这一许可。
>
> **ICSD 结构在私有完整版里，不在公开版里。** 原始实验结构池本来就有 73,823 个 ICSD CIF，
> ICSD 还为池内材料补充化学名、矿物名和计算密度。公开版只在某个开源库持有同一结构时才保留
> ICSD 来源的结构（共 14,629 个，标记为 `origin_open = false`）。公开版结构对应的 ICSD 名称和
> 密度随结构一起发布（91,995 个值，`licence_class = restricted`）。

<details>
<summary><b>全部 55 个数据库明细</b>——各自贡献什么、性质行数与许可</summary>

<br>

#### 大型综合 DFT 数据库——13 个来源，119,170,114 条性质行

| 数据库 | 贡献内容 | 性质行数 | 许可 |
|---|---|---:|---|
| [Alexandria](https://alexandria.icams.rub.de/datasets.html) | PBE / PBEsol / SCAN 的三维、二维、一维晶体：形成能与凸包能、间接与直接带隙、磁化强度 | 60,588,138 | Alexandria dataset terms |
| [AFLOW](https://aflow.org/documentation/) ⚠️ | 高通量形成焓、带隙、总能、原型标签、密度 | 18,464,119 | 未声明许可 |
| [ELEMENTA / ELEMENTA Spin](https://huggingface.co/datasets/kairosmaterial/ELEMENTA) ⚠️ | 它带入基础合并的 2,005,836 个弛豫终态端点上的逐端点总能，自旋弛豫另附磁化强度 | 8,023,344 | CC BY-NC 4.0 |
| [NOMAD](https://nomad-lab.eu/prod/v1/gui/search/entries) | 1,940 万条作者上传的计算，归约为每个 (材料, 性质, 方法) 一个值：按交换关联泛函族与自旋通道分列的带隙、残余力、VRH / Voigt / Reuss 模量、每格点体积；另贡献了 1,047,208 个其他来源都没有的结构 | 10,204,105 | CC BY 4.0（NOMAD 条款） |
| [OQMD](https://oqmd.org/download/) | 每条目一个收敛终态计算：形成能、凸包距离、带隙、磁化 | 6,086,500 | CC BY 4.0 |
| [GNoME](https://github.com/google-deepmind/materials_discovery/blob/main/DATASET.md) ⚠️ | 形成能与分解能、带隙，另含 r2SCAN 复算子集 | 4,897,901 | CC BY-NC 4.0 |
| [Materials Project](https://docs.materialsproject.org/downloading-data/how-do-i-download-the-materials-project-database) | PBE(+U) 带隙、能量与稳定性、VRH 模量、介电 / 压电常数、嵌入式电极电压与容量、表面能与晶界能、氧化态 | 4,291,860 | Materials Project terms |
| [JARVIS-QETB](https://jarvis.nist.gov/) | 紧束缚能量与带隙，数据来自充满刻意构造非平衡构型的拟合集；每一行都保留 "QETB (tight-binding)" 的 method 字符串 | 2,524,250 | NIST/JARVIS dataset terms |
| [Matbench Discovery / WBM](https://figshare.com/articles/dataset/Matbench_Discovery_v1_0_0/22715158) | MP2020 修正形成能与凸包能、PBE 带隙；其 MP-2023 快照还把旧版数字 `mp-` id 桥接进匹配映射 | 1,734,187 | CC BY 4.0 |
| [JARVIS-DFT 3D](https://pages.nist.gov/jarvis/databases/) | OptB88vdW / TBmBJ / HSE06 带隙、VRH 模量、Seebeck 与功率因子、DFPT 压电、SLME、spillage、剥离能 | 1,569,924 | NIST/JARVIS dataset terms |
| [Carolina Materials Database](https://www.carolinamatdb.org/) | 机器学习生成的假设晶体：形成能、空间群 | 428,272 | CC BY 4.0 |
| [ODBX](https://odbx.science/) | CAMD 形成能与凸包距离 | 287,006 | ODBX provider terms and source-dataset provenance |
| [Materials Cloud MC3D](https://mc3d.materialscloud.org/) | PBEsol 弛豫的三维晶体及其实验母体关联 | 70,508 | Materials Cloud record licence |

#### 实验结构总库——2 个来源，611,908 条性质行

| 数据库 | 贡献内容 | 性质行数 | 许可 |
|---|---|---:|---|
| [COD](https://wiki.crystallography.net/howtoobtaincod) | 原样发表的实验 CIF，附化学名 / 矿物名以及测量时的温度与压力 | 354,350 | CC0 |
| [ICSD](https://icsd.products.fiz-karlsruhe.de/) ⚠️ | 原始实验结构池中的 73,823 个结构；为池内材料补充化学名与矿物名、计算密度 | 257,558 | FIZ Karlsruhe ICSD licence |

#### 专题性质库——28 个来源，1,823,909 条性质行

电子结构、光学与拓扑（5 个来源，1,221,398 行）：

| 数据库 | 贡献内容 | 性质行数 | 许可 |
|---|---|---:|---|
| [Materiae](https://cmpdc.iphy.ac.cn/materiae/) | SOC / NSOC 拓扑分类、对称性指标、DOS 带隙、能带 | 589,993 | Materiae site terms; cite Zhang et al., Nature 566, 475-479 (2019) |
| [CMR 静态合集](https://cmr.fysik.dtu.dk/) | GLLB-SC 带隙与导数不连续、钙钛矿形成热、OQMD 关联能量、低维标签 | 305,346 | CC BY-SA 4.0 |
| [SNUMAT](https://figshare.com/articles/dataset/21713885) | GGA 与 HSE06 的电子和光学带隙、磁序 | 170,893 | Figshare record licence |
| [Materials Cloud 归档静态数据集](https://archive.materialscloud.org/) | SHG 系数、折射率与双折射、HSE / LDA 带隙、TQC 拓扑类、电子化物 ELF | 143,153 | record-specific open licences, predominantly CC BY 4.0 |
| [OMDB-organic](https://omdb.mathub.io/dataset/) | 有机分子晶体带隙 | 12,013 | OMDB terms |

声子、热输运与力学（3 个来源，242,300 行）：

| 数据库 | 贡献内容 | 性质行数 | 许可 |
|---|---|---:|---|
| [phonix](https://phonix-db.org/) | 晶格热导率、声子频率范围、虚频标记，以及谱分辨与累积 κ 曲线 | 155,192 | CC BY 4.0 |
| [PhononDB（NIMS MDR）](https://mdr.nims.go.jp/collections/8g84ms862?locale=en) | PBEsol DFPT 介电常数、Born 有效电荷、谐振声子 DOS | 86,616 | CC BY 4.0 |
| [HADB](https://hadb.funmat-ii.se/) | 硬质涂层合金：DFT 与 MLIP 的含温弹性模量 | 492 | HADB terms and source-publication provenance |

磁性、超导与离子输运（6 个来源，115,087 行）：

| 数据库 | 贡献内容 | 性质行数 | 许可 |
|---|---|---:|---|
| [NovoMag](https://www.novomag.physics.iastate.edu/structure-database) | 磁极化、磁矩、磁各向异性、居里温度 | 38,884 | CC BY 4.0 |
| [3DSC](https://github.com/aimat-lab/3DSC) | 与晶体结构对应的超导临界温度；仅性质 | 36,531 | 3DSC repository licence and upstream MP/ICSD terms |
| [SPSE](https://figshare.com/articles/dataset/High-Throughput_Screening_Platform_for_Solid_Electrolytes_Combining_Hierarchical_Ion-Transport_Prediction_Algorithms_/12011412) | BVSE 迁移势垒、实验离子电导率；仅性质 | 29,953 | CC BY 4.0 record; underlying ICSD-derived structures retain ICSD terms |
| [SuperBand](https://github.com/ljcj007/SuperBand) | 超导体的能带、DOS 与费米面 | 8,985 | CC BY 4.0 data; MIT software |
| [AMDB](https://altermagnets.anyterial.se/) | 对 MAGNDATA 做的交替磁性筛查：自旋劈裂指标与筛查带隙；仅性质 | 622 | AMDB terms and source-publication provenance |
| [OBELiX](https://github.com/NRC-Mila/OBELiX) | 实测室温离子电导率；仅性质 | 112 | CC BY 4.0 |

二维与层状材料（5 个来源，71,615 行）：

| 数据库 | 贡献内容 | 性质行数 | 许可 |
|---|---|---:|---|
| [2DMatPedia](https://www.2dmatpedia.org/download) | 由体相母体剥离得到的单层：带隙、剥离能 | 30,583 | 2DMatPedia terms |
| [C2DB](https://2dhub.org/) | 计算二维材料：带隙、功函数、稳定性 | 14,120 | CC BY-SA 4.0 |
| [Materials Cloud MC2D](https://mc2d.materialscloud.org/) | 可剥离单层及其层间结合能 | 13,202 | Materials Cloud record licence |
| [BiDB](https://www.2dhub.org/bidb/bidb.html) | 范德华双层：按堆垛方式区分的结合能与带隙 | 9,405 | 2DHub dataset terms |
| [OpenMX 2D AB2](https://www.openmx-square.org/2d-ab2/) | AB2 单层原型及其电子结构 | 4,305 | OpenMX database and source-publication terms |

矿物、原型与其他专题集（9 个来源，173,509 行）：

| 数据库 | 贡献内容 | 性质行数 | 许可 |
|---|---|---:|---|
| [CSLLM negatives](https://doi.org/10.6084/m9.figshare.29086931) | PU 筛查给出的 `predicted_synthesizable=false` 标签；仅性质，且没有这一行并不等于预测其可合成 | 98,303 | CC BY 4.0 |
| [JARVIS 专题数据集](https://pages.nist.gov/jarvis/databases/) | NIST JARVIS 的专题晶体端点与性质集 | 26,154 | NIST/JARVIS dataset terms |
| [AMCSD](https://www.rruff.net/about/download-data/) | 实验矿物结构，附矿物名、实测密度与计算衍射谱 | 24,639 | AMCSD terms |
| [SACADA](https://www.sacada.info/) | 碳同素异形体：密度、硬度、模量、相对能量 | 10,349 | SACADA site terms and source-publication provenance |
| [AFLOW 原型百科](https://aflowlib.duke.edu/p/index.html) | 原型与 Strukturbericht 标签；仅性质 | 6,251 | Apache-2.0 |
| [Webmineral](https://webmineral.com/) | 矿物种级汇编——密度、莫氏硬度、折射率；仅性质，且数值描述的是矿物种整体而非所匹配的那件标本 | 4,698 | Webmineral site and cited-source terms |
| [HEX 高压单质](https://springernature.figshare.com/collections/HEX_a_complete_Database_of_High-Pressure_Elemental_Crystal_Structures/7119778/1) | 0–300 GPa 的单质晶体结构 | 1,456 | CC0 |
| [RRUFF](https://www.rruff.net/about/download-data/) | 实测矿物化学组成，以及拉曼、红外与衍射谱 | 1,302 | RRUFF terms and source-citation provenance |
| [TCOD](https://www.crystallography.net/tcod/) | 理论 CIF 中的 DFT 带隙 | 357 | CC0 |

#### 多孔 / 框架材料——12 个来源，10,218,950 条性质行

| 数据库 | 贡献内容 | 性质行数 | 许可 |
|---|---|---:|---|
| [Boyd–Woo 碳捕集 MOF](https://archive.materialscloud.org/record/2018.0016/v3) | 湿烟气 GCMC 碳捕集：吸附量、选择性、工作容量、吸附热 | 5,454,666 | CC BY 4.0 |
| [Deem SLC 沸石](https://mwdeem.org/PCOD/index.html) | 假设沸石，性质取自 CIF 尾部的 SLC 力场计算：模量、方向性泊松比、声速、骨架密度，另附模拟 XRD 谱 | 2,977,166 | CC BY 4.0 |
| [hMOF](https://figshare.com/articles/dataset/15127758) | 假设 MOF：CO₂ 吸附量与 zeo++ 孔隙几何 | 892,486 | Figshare record licence |
| [QMOF](https://github.com/Andrew-S-Rosen/QMOF) | DFT 弛豫的 MOF：多泛函带隙、总能、磁化、LCD / PLD | 339,443 | CC BY 4.0 |
| [FAIR-MOFs](https://zenodo.org/records/13254307) | 源自 CSD 的实验 MOF：孔隙学、RCSR 拓扑、键解离能 | 277,454 | CC BY 4.0 |
| [CoRE MOF 2019](https://zenodo.org/records/3677685) | 经整理的实验报道 MOF：Zeo++ 孔隙学、比表面积、空隙率、孔体积 | 155,488 | CC BY 4.0 |
| [MOFX-DB](https://mof.tech.northwestern.edu/databases) | CoRE MOF / IZA / ToBaCCo 子集：孔隙几何与 298 K、1 bar 附近的单气体吸附量 | 87,845 | MOFX-DB dataset terms |
| [PCOD](https://www.crystallography.net/pcod/) | GRINSP 预测骨架——硅酸盐、磷酸盐、硼酸盐等：预测 R 因子与骨架密度 | 24,416 | public domain |
| [EC-MOF](https://ec-mof.njit.edu/) | 导电二维 MOF：带隙、形成能与结合能 | 7,848 | EC-MOF site terms and source-publication provenance |
| [开放骨架磷酸铝](https://figshare.com/articles/dataset/Database_of_Open-Framework_Aluminophosphate_Structures/7822574) | AlPO 骨架，附 IZA 代码与已发表的精修残差 | 925 | CC BY 4.0 |
| [CURATED-COFs](https://github.com/lipelopesoliveira/curatedCOFs) | 已合成的共价有机骨架及其骨架名称 | 684 | repository licence |
| [IZA-SC](https://www.iza-structure.org/databases/) | 官方认定的沸石骨架类型，为 DLS76 理想化纯硅几何，并非实验晶胞 | 529 | IZA Structure Commission terms |

</details>

去重与来源优先级规则见
[`docs/dataset-acquisition.zh-CN.md`](docs/dataset-acquisition.zh-CN.md) 第 7 节；每个来源贡献
什么、如何挂接到结构池见
[`docs/property-integration.zh-CN.md`](docs/property-integration.zh-CN.md) 第 2 节。ICSD 等受
许可限制的来源按“版权和再分发边界”处理：它们的结构只留在私有完整版里，公开版只收录有开源库
持有的结构。

[![播放 MateriaViva 2K60 演示视频](demo/MateriaViva_demo_preview.gif)](demo/MateriaViva_demo_2K60.mp4)

<p align="center"><a href="demo/MateriaViva_demo_2K60.mp4">播放完整 2560×1440 · 60 FPS 演示视频</a></p>

## MateriaViva 不只是把文件放在一起

- 实验可合成结构和计算候选结构拥有独立标签，不用候选数量冒充实验覆盖。
- 只把材料的静态周期结构端点纳入结构库。弛豫、扰动、分子动力学和反应路径中间帧不计为
  新材料。
- 去重不等于丢数据。结构合并后仍保留每个来源的原始 ID、版本、性质、单位、许可和
  provenance。
- 原始归档用于审计和重建，网站只读取经过校验的统一索引，不直接混读来源文件。
- Hugging Face 公开版只收录有开放许可数据库持有的结构；随结构一起发布的每条性质值和曲线都
  注明来源数据库及其许可。

## 自我进化的材料整合数据库

MateriaViva 的长期目标不是维护一次性的静态合集，而是持续发现新的材料数据库和已有来源的新版本，
完成许可判断、格式映射、结构去重和质量检查后，再发布新的统一快照。

> [!IMPORTANT]
> 自动发现和自动整合功能尚未实现。当前 106 个目录来源仍由人工发现和审核，再由可恢复的采集
> 脚本接入。README 将待开发能力与当前实现分开描述。

计划中的闭环是：

```text
发现新来源或版本
        ↓
检查许可、访问方式、静态结构范围和轨迹污染
        ↓
生成或推荐采集与字段映射适配器
        ↓
统一格式、单位和 provenance
        ↓
结构指纹去重并合并跨库性质
        ↓
完整性与异常值检查 + 人工批准
        ↓
发布新的 Hugging Face 快照和变更报告
```

失败记录和人工修正会用于改进下一轮来源识别、字段映射和去重策略。这个过程不会绕过账户、
付费许可或再分发限制；无法确认授权的数据默认不公开。

## 一次下载，而不是重复抓取一百个数据库

在发布层，MateriaViva 取消“由每个用户分别调用传统数据库批量 API 或登录来源账户”的使用
方式。索引整理为带版本、哈希、来源清单和许可清单的数据集，发布在：

### Hugging Face 上的两个版本

| | [AI4QC/MateriaViva](https://huggingface.co/datasets/AI4QC/MateriaViva) · 完整版 | [AI4QC/MateriaViva-Open](https://huggingface.co/datasets/AI4QC/MateriaViva-Open) · 开源版 |
|---|---|---|
| 访问 | 私有，按人授权 | 公开 |
| 结构 | 全部 14,590,485 个 | 10,903,588 个（74.7%）：有开放许可数据库持有的结构 |
| 性质值 | 全部 131,824,881 条 | 113,459,302 条——这些结构在索引里的全部性质值 |
| 曲线（谱、态密度、能带） | 全部 1,198,897 条 | 850,417 条——同上 |
| 补全预测 | 729,661,476 个值，95 个性质 | 521,365,770 个值，同样 95 个性质 |
| 格式 | 网站直接使用的运行时索引（`materials.sqlite` + blob） | Parquet：`data/`、`properties/`、`curves/`、`predictions/` |
| 体积 | 约 54 GB | 约 14 GB |

**完整版是私有的，因为它含 ICSD。** 它就是网站使用的完整工作索引，含 73,823 个 ICSD 结构，
以及不允许再分发或只允许非商业使用的来源。只能给自己持有 ICSD 授权的人。

**开源版 = 完整版去掉闭源结构。** 只有受限、非商业或无许可数据库持有的结构不收录，它们的
性质值和曲线也随之不收录；开源库和闭源库都持有的结构保留。每个结构行标注持有它的开源库中
最宽松的许可。**性质值和曲线的许可是它所来自的数据库的许可，不一定开放**：每一行都写明
`source`、`licence` 和 `licence_class`，筛选 `licence_class == "open"` 即得开放许可的部分。
由 [`scripts/export_open_structures.py`](scripts/export_open_structures.py) 构建；许可审计见
[`DATA_LICENCES_2026-10-19.zh-CN.md`](DATA_LICENCES_2026-10-19.zh-CN.md)。

### 性质补全预测

需要单独计算的性质，没有一个覆盖到池中五十分之一的结构（见上文）。补全运行为每个性质训练一个
CGTNet 模型，用的是索引自己的数值，再对该性质适用域门控内的每个结构做预测。**本轮 140 个性质中
已完成 95 个，两个版本都已发布**：`predictions/<task>.parquet`（完整版按 `material_pk`，开源版
按 `material_id` 对应），旁边是 `<task>.json`；其余 45 个仍在训练或排队，完成后追加。

- **这些是模型预测，不是测量值。** 每个 `<task>.json` 记录 checkpoint 如何选出（在化学体系不相交的
  holdout 上选，所以报告的精度是上界）、门控收录了哪些结构及原因，以及随数值一起的警告。
- `has_imaginary_phonon__gga` 是 0/1 指示量，但按回归拟合：数值是打分不是概率，7.7% 落在 [0, 1]
  之外。排序是可用的（holdout AUC 0.85）。
- 续跑推理曾把部分结构写了两遍；打包时保留第一份（两份只差浮点噪声），条数记在 `packaging` 里。

**代码在 GitHub，数据在 Hugging Face。** GitHub 仓库只保存代码、数据模式、来源目录、文档、
测试和演示资产，不包含数据库文件、统一索引、渲染缓存或未完成下载。完整版含两个索引变体：

| 变体 | 体积 | 用途 |
|---|---:|---|
| `index/` | 约 50 GB | 完整索引，线上服务使用 |
| `slice/` | 约 112 MB | 不下载完整数据也能开发网页前端 |

切片**在两个意义上都不是随机抽样**。先跑贪心集合覆盖，保证每个数据源、每个性质名、每种曲线
类型、每个结构族和每种元素都至少出现一次——从一千三百万条里随机取一千条，几乎必然漏掉所有
稀有性质，而那恰恰是最可能坏掉的前端面板。剩余名额则留给**最富的**材料而非有代表性的铺开，
因为全池只有 2.2% 的材料带任何谱线：按代表性抽样，你会整天点开只有三个数字、没有曲线的材料。
最终是 1,000 个材料承载 186,893 条性质行与 18,290 条曲线，其中 **921 个带 ≥7 种曲线类型**。

**放大切片只会让它变稀而不是变富**——全池只有 1,049 个材料带 ≥7 种曲线类型；而且任何体积都
达不到"每个材料都有全部性质"：恰好只有 3 个材料集齐 10 种曲线类型。
见 [`scripts/export_slice.py`](scripts/export_slice.py)。

### 版权和再分发边界

MateriaViva 自身的代码按 [CC BY-NC 4.0](LICENSE) 发布，只允许非商业使用。整合进来的数据
沿用各自来源的条款，且更严格。

- 结构只有在某个开放许可数据库（公有领域、CC0、CC BY、CC BY-SA 等）持有时才进入公开版。每个
  结构行保留它应署名的数据库和原始 ID（`open_sources`、`open_source_ids`）。
- 只有订阅制、非商业（CC BY-NC）或无许可数据库持有的结构不公开，只留在私有完整版里。
- 已公开结构的性质值和曲线不论来源都随结构一起发布，每条都标注来源库的许可。来自非开放来源的
  值仍受其来源条款约束；只需要开放许可的值时，筛选 `licence_class == "open"`。
- 统一格式不会改变原数据的权利归属。未来的自动发现流程同样必须先通过许可门禁。
- 完整版包含 CC BY-NC 4.0 的来源（如 ELEMENTA、GNoME），因此不得用于商业用途。公开版中
  CC BY-SA 的行在衍生数据集中必须保持 CC BY-SA。

## 当前覆盖范围

机器可读目录登记 **106** 个晶体结构或性质来源，其中 **55 个已整合**进索引、贡献上文统计的
性质行。“登记”不等于“已采集”，“已采集”也不等于“已整合”：一个来源可能已经下载但还在等适配器，
也可能是评估后被主动排除——Catalysis-Hub 就留在目录里，其 `status` 字段记录了爬取时漏掉
`reactionSystems` 连接键、导致 91% 的反应无法挂接。

逐来源状态见 [`scripts/datasets/sources.json`](scripts/datasets/sources.json)，每条记录的
`status` 字段写明它当前处在哪个阶段——来源会在这些阶段之间移动，只有那里的信息会一直正确。

其中 ELEMENTA 是轨迹数据集，但按“每条弛豫只取终点”的规则接入，中间帧不计入结构库。

完整来源、许可、下载状态和人工操作说明见
[`docs/dataset-acquisition.zh-CN.md`](docs/dataset-acquisition.zh-CN.md)。既有 SSD 数据及重复关系见
[`docs/legacy-ssd-data-inventory.zh-CN.md`](docs/legacy-ssd-data-inventory.zh-CN.md)。

## 获取代码和数据

```bash
git clone https://github.com/AI4QC/materia-viva.git
cd materia-viva
pip install -r backend/requirements.txt

# 小切片——开发前端够用
python scripts/fetch_index.py slice
python scripts/serve.py --runtime data/slice

# 或完整索引（约 50 GB；下载期间需要约两倍空闲空间，
# 因为文件链接到位之前 hub 缓存里还有一份）
python scripts/fetch_index.py full
python scripts/serve.py --runtime data/index
```

切片和完整索引都来自私有的完整版，需要有访问权限。开源版不需要权限；它是普通 Parquet，
不是给网站用的运行时索引：

```bash
hf download AI4QC/MateriaViva-Open --repo-type dataset --local-dir data/open
# 或只取一部分，例如一个性质和它的预测
hf download AI4QC/MateriaViva-Open --repo-type dataset --local-dir data/open \
    --include "properties/bulk_modulus_vrh.parquet" "predictions/bulk_modulus_vrh__gga.*"
```

```python
from datasets import load_dataset
structures = load_dataset("AI4QC/MateriaViva-Open", split="train")   # data/ 下的分片
```

然后打开 <http://127.0.0.1:8000>。`--runtime` 接受任何含有 `materials.sqlite`、
`structures.blob` 和 `curves.blob` 的目录，所以在切片和完整索引之间切换只是换一个命令行参数，
不需要重新构建。

如果数据已经在别的盘上，直接链接进来而不必下载：

```bash
export MV_DATA_ROOT=/path/on/ssd/materia-viva-data
ln -s "$MV_DATA_ROOT" data
```

`data` 和兼容入口 `runtime` 均不受 Git 管理。原始归档、SQLite/blob 索引、`.part`、receipt、
渲染缓存和本机密钥也不会进入提交。预期目录为：

```text
data/
├── sources/                 各数据集的结构导出
├── index/                   完整索引：materials.sqlite + structures.blob + curves.blob
├── slice/                   开发切片，同样三个文件
├── manifests/               Crystal Record v1 校验报告
└── raw/                     来源归档与 provenance
```

这里不写具体数量——本项目里每一个写死的数字都至少过期过一次。要看当前值就问运行中的实例：

```bash
curl -s http://127.0.0.1:8000/api/stats
```

本机 SSD 迁移和旧路径兼容关系见 [`docs/storage-layout.zh-CN.md`](docs/storage-layout.zh-CN.md)。

## 统一数据格式

进入 MateriaViva 的结构主记录采用 `Crystal Record v1`：

```text
index,material_id,cif,pbes_gap
```

流式校验器检查字段顺序、数据类型、非空约束和 split 计数。来源专有性质以 sidecar 保留，
随后映射到统一 SQLite 属性列或 JSON 扩展字段。原始值、单位和来源不会被覆盖。

- 格式说明：[`docs/data-format.zh-CN.md`](docs/data-format.zh-CN.md)
- JSON Schema：[`schemas/crystal-record-v1.schema.json`](schemas/crystal-record-v1.schema.json)
- 服务索引：`data/index/materials.sqlite` + `data/index/structures.blob`

SQLite 保存检索字段和压缩块偏移，blob 顺序保存 zlib 压缩的 CIF。索引器以流式方式处理源
CSV，不需要一次加载全部数据。

## 安装与启动

需要 Python 3.10+ 和 Node.js 20+：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

cd frontend
corepack enable
pnpm install --frozen-lockfile
cd ..
```

OVITO 建议放在独立 Python 环境中：

```bash
export MATERIALS_OVITO_PYTHON=/path/to/ovito-enabled/python
```

未配置 OVITO 时，浏览器交互式 3D 仍可使用，服务端 Tachyon 图片渲染不可用。

校验全部 13,077,781 条发布记录并构建索引（性质层随后用 scripts/properties/run_all.py 重建）：

```bash
make validate-data
python scripts/build_index.py
```

开发时可以构建小样本。只有源数据已经单独通过完整校验时，才应跳过源扫描：

```bash
python scripts/build_index.py \
  --limit-per-dataset 1000 \
  --skip-source-validation \
  --output /tmp/cmu-sample-index
```

构建完成后启动网站：

```bash
make build

MATERIALS_OVITO_PYTHON=/path/to/ovito-enabled/python \
  python scripts/serve.py --host 0.0.0.0 --port 8000
```

- 网站：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/api/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

索引先写入 `.building` 临时文件，完成后原子替换；中断不会破坏当前服务索引。

## 测试

```bash
make test
make build
```

分别运行：

```bash
PYTHONPATH=backend:. python -m pytest backend/tests -q
cd frontend
pnpm test --run
pnpm typecheck
pnpm build
```

连接真实索引和 OVITO 后，可以执行浏览器验收：

```bash
python scripts/browser_smoke.py
```

## 仓库结构

```text
materia-viva/
├── backend/                 FastAPI、SQLite 查询、结构解析和 OVITO 渲染
├── frontend/                React、TypeScript、Vite 和交互式晶体工作台
├── scripts/                 校验、索引、采集、服务和演示录制工具
├── schemas/                 Crystal Record v1 JSON Schema
├── docs/                    数据、迁移、采集和设计文档
├── demo/                    2K60 演示视频、动态预览和封面
└── data/                    本地数据链接，不受 Git 管理
```

## 演示视频

- [首页动态预览](demo/MateriaViva_demo_preview.gif)：800×450，点击后播放完整视频。
- [2K60 MP4](demo/MateriaViva_demo_2K60.mp4)：2560×1440、60 FPS、H.264 High。
- [2K 封面](demo/MateriaViva_demo_2K60_cover.png)。
- `demo/MateriaViva_demo_2K_source.webm`：浏览器源录屏。

重新录制和转码：

```bash
python scripts/record_demo.py
ffmpeg -y -i demo/MateriaViva_demo_2K_source.webm \
  -vf "minterpolate=fps=60:mi_mode=blend" \
  -c:v libx264 -profile:v high -level:v 5.1 -preset slow -crf 13 \
  -pix_fmt yuv420p -movflags +faststart -an \
  demo/MateriaViva_demo_2K60.mp4

# 生成 GitHub README 动态预览
ffmpeg -y -ss 1 -i demo/MateriaViva_demo_2K60.mp4 \
  -filter_complex "fps=5,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=72:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
  -loop 0 demo/MateriaViva_demo_preview.gif
```

## 许可、贡献和引用

MateriaViva 按 [CC BY-NC 4.0](LICENSE) 发布，只允许非商业使用。外部数据库保留各自的
许可和引用要求。不要因为结构已经标准化或与开放来源匹配，就重新分发 ICSD、CSD 等受限
来源的原始字段。

- 开发与数据来源提交：[`CONTRIBUTING.zh-CN.md`](CONTRIBUTING.zh-CN.md)
- 项目引用：[`CITATION.cff`](CITATION.cff)
